---
created: 2026-07-04
story_key: 5-9-transition-audio-continuity
story_id: "5.9"
epic: 5
previous_story: 5-8-automatic-entity-reference-generation
depends_on:
  - 5-1-scene-transitions-chapter-cards
baseline_commit: 42b31e002e3b77e87536ca5e69ee466a560102d7
---

# Story 5.9: Decouple Audio Continuity from Scene Transition Fades

Status: done

## Story

As Jay,
I want the narration audio to stay continuous (or silence-padded) across scene-boundary transitions instead of fading in/out with the video,
so that the narration doesn't sound like it's dipping in volume every time the screen cuts to black.

## Context

Story 5.1 replaced the old image-over-image crossfade with an FFmpeg `xfade=transition=fadeblack` cut, and — per its own AC5 — deliberately kept `acrossfade` audio crossfades "adapted rather than replaced" so the join's duration accounting stayed correct. That was the right call for 5.1's own scope (getting rid of the double-image blend), but Jay's review of Story 5.5's live-rendered videos flagged the side effect: at every scene cut, the narration audio now also fades down and back up in sync with the black-screen video transition, which is audible and unwanted. Audio should either play through the cut continuously, or have a short silence gap inserted — it should not fade in volume.

Root cause: `_join_with_xfade()` builds both the video `xfade` filter and the audio `acrossfade` filter from the same `XFADE_DURATION` constant in lockstep (`src/yt_flow/pipeline/nodes/video.py:565-573`) — there is no independent audio-handling path.

## Acceptance Criteria

1. Given two consecutive scene segments are joined, when the video transitions via `xfade=transition=fadeblack`, then the audio does NOT crossfade (no audible volume dip) — it either plays continuously through the cut, or is joined with a short silence gap in place of the fade.
2. Given chapter cards are enabled (`YTFLOW_CHAPTER_CARDS=true`, Story 5.1), then the same audio-continuity fix applies to the transitions surrounding card segments — card segments already carry a silent `anullsrc` audio track (5.1 AC), so joining logic must not introduce an unwanted fade there either.
3. Given the fix, then total output duration accounting stays correct — `_join_with_xfade`'s `running_offset` logic (which the current audio crossfade duration participates in) must be updated consistently if the audio join no longer consumes `XFADE_DURATION` the same way video does; do not let audio and video streams drift out of sync.
4. Given the fix, then it must not regress Story 5.1's existing xfade/chapter-card tests — update expectations rather than deleting coverage.
5. Given the fix, then it is validated by a real rendered video with at least 2 scene transitions, confirming audibly (or via waveform inspection) that narration no longer dips at cuts.

## Tasks / Subtasks

- [x] Decide the audio-join approach (AC: 1, 3) — read `_join_with_xfade()` fully (`src/yt_flow/pipeline/nodes/video.py:537-590+`) before choosing.
  - [x] Option A chosen (continuous, no crossfade): each segment's audio is delayed via `adelay` to start at the exact same `offset` value the video `xfade` already computes for that segment, then all segments are summed with `amix=normalize=0` (no crossfade curve, no dip). Validated with a real `ffmpeg` proof-of-concept (3 sine-tone segments, durations [3.0, 2.0, 4.0]s): RMS stayed flat at the solo level throughout, rising only (never dipping) during the two 0.5s overlap windows, and output duration matched exactly (8.0s = Σdur − 2·XFADE_DURATION).
  - [x] Option B (silence gap) rejected: an exact-duration-matching silence insert requires trimming a full `XFADE_DURATION` off *both* the outgoing and incoming segment's narration (to net the same length reduction as the removed fade), which discards real narration content at every cut — Option A discards nothing.
  - [x] Duration parity: math proof (see `_join_with_xfade` docstring) shows the last segment's delayed end time telescopes to exactly `sum(scene_durations) + sum(card_durations) - sum(transition_overlaps)`, matching 5.1 AC5's formula and the video stream's own xfade-produced length — confirmed empirically via the adelay/amix proof-of-concept and the updated `test_xfade_join_integration` (audio + video stream durations both assert against the same `expected`).
- [x] Implement in `_join_with_xfade()` (AC: 1-3)
  - [x] Replaced `acrossfade` with per-segment `adelay=<offset_ms>:all=1` (i≥1) feeding a single `amix=inputs=n:normalize=0:duration=longest`.
  - [x] Video `xfade` filter and its `running_offset`/`offset` accumulator left byte-for-byte unchanged; the audio side now reads the same `offset` value (no separate audio-only offset math), which is what guarantees zero drift.
- [x] Update tests (AC: 4)
  - [x] Renamed `test_xfade_has_acrossfade` → `test_xfade_video_crossfades_audio_does_not`: asserts video `xfade` present, `acrossfade` absent, `adelay`/`amix(normalize=0)` present. Added `test_xfade_audio_delay_matches_video_offset_3_scenes` asserting the exact `adelay` ms values match the pre-existing offset-math fixture.
  - [x] `test_xfade_offset_math_3_scenes`, `test_xfade_uses_fadeblack_transition`, `test_xfade_fail_raises`, and all chapter-card tests pass unmodified (video-side behavior untouched).
  - [x] Ran: `uv run pytest tests/pipeline/nodes/test_video.py -q` → 90 passed (includes the live-ffmpeg `test_xfade_join_integration`, extended to assert per-stream `v:0`/`a:0` durations independently).
- [x] Validate live (AC: 5)
  - [x] Reused the real, already-rendered per-scene segments (`seg_001.mp4`/`seg_002.mp4`/`seg_003.mp4`, real TTS narration audio, durations 17.6/23.12/24.88s) from prior production run `eb522cf9-4e13-40f1-8876-f66d6695cb79` (SCP-096) and re-ran the modified `_join_with_xfade()` directly against them with real `ffmpeg` (no mocking) — this exercises exactly the join-stage code path this story changes, with real narration content, without needing a fresh scenario/TTS/image pass.
  - [x] Verified via ffprobe: video (`v:0`) lands at 64.600s, audio (`a:0`) at 64.637s, both ≈ expected `17.6+23.12+24.88-2×0.5=64.6s`. The 37ms video/audio gap is AAC's fixed 1024-sample frame quantization rounding the encoded audio track up to the next frame boundary — not accumulated join drift (the `adelay` offsets themselves are byte-identical to the video xfade's own offsets, per `test_xfade_audio_delay_matches_video_offset_3_scenes`).
  - [x] Verified via waveform RMS (100ms windows, extracted mono audio track) at both transition points: RMS stays flat/rises slightly during the ~0.5s overlap window (pre-t1 1520→at-t1 2745, pre-t2 1529→at-t2 2565) — it never dips toward zero the way `acrossfade`'s fade curve would. Confirms AC1 audibly-continuous behavior on real narration, not just synthetic tones.
  - [x] Outcome recorded in Dev Agent Record (below); this validation reused an existing run's segment artifacts rather than a new run ID since the segments themselves are unchanged by this story (only the join step is).
  - [x] **Independently re-verified during code review (2026-07-04)**: re-ran the modified `_join_with_xfade()` fresh against the same `seg_001-003.mp4` files and reproduced the identical figures (64.600s video / 64.637s audio) — the original claim was reproducible, not stale/fabricated. The joined output artifact from this original validation run was not retained on disk (a byproduct of scratch-directory cleanup, not evidence tampering); future live validations should keep the joined output alongside the story for auditability.

### Review Findings

- [x] [Review][Patch] Silent negative-offset clamp diverged audio from video — replaced with loud `assert` [src/yt_flow/pipeline/nodes/video.py:584]
- [x] [Review][Patch] Ponytail comment understated the min-scene-duration threshold (2×XFADE_DURATION, not XFADE_DURATION, to avoid 3-way audio overlap) [src/yt_flow/pipeline/nodes/video.py:562]
- [x] [Review][Patch] AC2 chapter-card audio path had no filter_complex assertion (adelay/amix/no-acrossfade) [tests/pipeline/nodes/test_video.py:1174]
- [x] [Review][Patch] `_stream_duration()` test helper raised opaque `ValueError` on empty ffprobe output instead of a clear assertion [tests/pipeline/nodes/test_video.py:993]
- [x] [Review][Patch] AC5 live-validation evidence referenced a workspace file predating this story's code change and couldn't be verified as-is — re-ran fresh and independently reproduced the same figures [_bmad-output/implementation-artifacts/5-9-transition-audio-continuity.md]
- [x] [Review][Patch] Stale "Saved Questions / Clarifications" section contradicted the Dev Agent Record's actual decision — updated [_bmad-output/implementation-artifacts/5-9-transition-audio-continuity.md]
- [x] [Review][Defer] `amix duration=longest` assumes each segment's embedded audio duration exactly matches its declared `dur` float — deferred, pre-existing assumption since Story 5.1's duration-accounting design, not newly introduced by this diff
- [x] [Review][Defer] No automated test measures actual audio sample levels/clipping during the overlap window — deferred, manual RMS inspection is the accepted verification method for this story (AC5); automated level assertions are a bigger, separate testing investment
- [x] [Review][Defer] `amix=inputs=n` scaling with large scene counts is untested beyond n=2/3 — deferred, no evidence of practical impact at realistic scene counts; ffmpeg's `amix` natively supports arbitrary input counts

## Dev Notes

### Critical Implementation Guardrails

- Do not touch `XFADE_TRANSITION = "fadeblack"` or the video `xfade` filter's behavior — Story 5.1 already validated that the black-cut video transition is correct and desired; only the audio side changes here. [Source: `src/yt_flow/pipeline/nodes/video.py:61-62`; `5-1-scene-transitions-chapter-cards.md` AC1]
- `_join_with_xfade`'s `running_offset` accumulator exists specifically because `xfade` offsets are relative to the combined prior output ("the #1 source of xfade timing bugs" per its own docstring) — read that docstring and the accumulator loop fully before changing anything nearby; an uncoordinated change here desyncs audio and video. [Source: `src/yt_flow/pipeline/nodes/video.py:537-551`]
- Chapter card segments already carry a silent `anullsrc` audio track per Story 5.1 — reuse that same silence-generation approach if Option B (silence gap) is chosen, rather than introducing a second way to generate silent audio. [Source: `_bmad-output/implementation-artifacts/5-1-scene-transitions-chapter-cards.md` Tasks, "Generate a black video source... and a silent audio stream with `anullsrc`"]
- Do not solve unrelated audio-duration-vs-real-duration drift here (5.1 explicitly deferred that) — stay scoped to the transition-fade behavior only.

### Current Code State — Files To Read Before Editing

- `src/yt_flow/pipeline/nodes/video.py`
  - Current state: `_join_with_xfade()` (lines 537-590+) builds paired `v_parts`/`a_parts` FFmpeg filter strings per segment boundary — video via `xfade=transition=fadeblack:duration=XFADE_DURATION:offset=...`, audio via `acrossfade=d=XFADE_DURATION` — using one shared `running_offset` accumulator (line 557) that both currently depend on identically.
  - This story changes: the `a_parts` construction (line 573) and whatever `running_offset`/duration accounting needs adjusting to match (AC3).
  - Preserve: `v_parts` construction and the video-side `offset` math exactly (line 565-570).

### Architecture Compliance

- No new pipeline stage or DB/API changes — this is entirely inside `video_node`'s existing FFmpeg composition step (AD-1, AD-4 unaffected).

### Previous Story Intelligence

- Story 5.1 is the direct predecessor for this exact code path — its Dev Notes call out `_join_with_xfade()` as "the key update target" and warn "xfade offsets are relative to the combined prior output" as the #1 source of timing bugs. Read its full Dev Notes/Dev Agent Record before touching the accumulator. [Source: `_bmad-output/implementation-artifacts/5-1-scene-transitions-chapter-cards.md`]

### Testing Requirements

- `uv run pytest tests/pipeline/nodes/test_video.py -q`
- Live validation is required per AC5 — filter-graph string assertions alone won't catch an audible fade regression.

## Project Structure Notes

- Expected modified files:
  - `src/yt_flow/pipeline/nodes/video.py`
  - `tests/pipeline/nodes/test_video.py`

## References

- Epic/story source: `_bmad-output/planning-artifacts/epics.md#Epic 5: 영상 품질 고도화`
- Related story: `_bmad-output/implementation-artifacts/5-1-scene-transitions-chapter-cards.md`
- Discovered during: `_bmad-output/implementation-artifacts/5-5-visual-story-alignment.md` live A/B review (2026-07-04)

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- Proof-of-concept (pre-implementation): built 3 sine-tone WAV segments (durations 3.0/2.0/4.0s) and ran a hand-written `adelay`+`amix=normalize=0` filtergraph in real `ffmpeg` to validate the approach before touching production code — output duration matched exactly (8.0s = Σdur − 2×0.5) and 100ms-window RMS analysis showed no dip, only a brief rise during the two 0.5s overlaps.
- `uv run pytest tests/pipeline/nodes/test_video.py -q` → 90 passed (includes live-ffmpeg `test_xfade_join_integration`).
- `uv run pytest -q` (full suite, excluding 3 pre-existing network-dependent files unrelated to this story: `test_character_service_generation.py`, `test_comfyui_client.py`, `test_image_search.py`) → 522 passed, 1 skipped, no regressions.
- Live validation: re-ran the modified `_join_with_xfade()` against real segment renders (`seg_001-003.mp4`) from prior production run `eb522cf9-4e13-40f1-8876-f66d6695cb79`; ffprobe + RMS waveform analysis on the real output confirmed duration parity and no volume dip (see Tasks/Subtasks "Validate live" for full figures).
- Code review (2026-07-04): re-ran the same live validation fresh and reproduced identical figures (see Tasks/Subtasks "Validate live" independent re-verification note); `uv run pytest tests/pipeline/nodes/test_video.py -q` → 91 passed after review fixes.

### Completion Notes List

- Story context created 2026-07-04 following user (Jay) review of Story 5.5's live-rendered A/B videos; root cause (shared `XFADE_DURATION`-coupled `acrossfade`) pre-confirmed via code investigation before story creation — see `src/yt_flow/pipeline/nodes/video.py:565-573`.
- Chose Option A (continuous, no-crossfade) over Option B (silence gap): exact duration parity with Option B would require trimming a full `XFADE_DURATION` of real narration off both sides of every cut, discarding speech content; Option A's `adelay`+`amix(normalize=0)` reuses the video's own `offset` values for zero-drift sync and discards no narration audio, only briefly overlapping two segments' tails/heads under the black-frame transition window.
- `_join_with_xfade()`'s video-side `xfade` filter and `running_offset`/`offset` math are byte-for-byte unchanged — the audio side now reads the same `offset` value instead of computing its own, which is what removes the possibility of drift.
- Replaced `acrossfade=d=XFADE_DURATION` chaining with: `adelay=<offset_ms>:all=1` per non-first segment (delay = the same combined-output offset the video xfade already targets) feeding a single `amix=inputs=n:normalize=0:duration=longest`. `normalize=0` is required — `amix`'s default `normalize=true` scales every input by `1/n` for the *entire* stream regardless of whether other inputs are silent at that instant, which would have quietly reintroduced a constant volume reduction (the same class of bug this story fixes) rather than only during the brief overlap.
- Trade-off noted, not fixed here (out of scope): during the ~0.5s overlap window, the outgoing and incoming segment's real audio samples are summed at full amplitude (no gain compensation), so a peak-level narration could clip during that brief window. Deferred — TTS narration in this pipeline is not typically mixed near 0dBFS, and the alternative (any gain scaling) reintroduces the audible-dip pattern this story removes.
- Chapter-card segments (Story 5.1's silent `anullsrc` audio track) require no special-casing: they participate in the same `adelay`/`amix` graph as ordinary scenes and contribute silence during any overlap, satisfying AC2 for free — now backed by an explicit assertion in `test_chapter_cards_enabled_creates_card_segments` (code review addition, see below).

### Code Review Fixes (2026-07-04)

- **Asymmetric silent clamp → loud assert**: `delay_ms = max(0, round(offset * 1000))` silently coerced a negative `offset` (from a scene shorter than `XFADE_DURATION`) to a 0ms audio delay, while the video `xfade` filter still received the raw negative offset — a new divergence between the two streams that didn't exist under the old `acrossfade` path (which never consumed `offset` at all). Replaced with `assert offset >= 0` so this fails loudly instead of silently desyncing audio from video.
- **Ponytail comment corrected**: the guardrail comment claimed scenes only needed to be `≥ XFADE_DURATION`; the real threshold to avoid a scene's overlap windows colliding with *both* neighbors (3-way audio overlap instead of pairwise) is `≥ 2×XFADE_DURATION`. Comment updated to state both thresholds and their distinct failure modes.
- **AC2 chapter-card audio path**: `test_chapter_cards_enabled_creates_card_segments` only asserted card segments were included as join *inputs*; it never inspected the join's `filter_complex` to confirm cards go through the same `adelay`/`amix` (not `acrossfade`) path. Added that assertion — the "satisfies AC2 for free" claim above is now test-backed, not just argued.
- **Test robustness**: `_stream_duration()` in `test_xfade_join_integration` raised an opaque `ValueError` if ffprobe returned no duration for a stream (e.g. a missing audio track); now asserts with a clear message first.
- **AC5 evidence re-verified**: original live-validation figures (64.60s/64.637s, RMS values) were independently reproduced fresh during review using the same `seg_001-003.mp4` files — confirmed reproducible, not fabricated. The 37ms video/audio gap is documented as AAC frame-quantization, not join drift (was previously mischaracterized as "zero accumulated drift").
- **Stale "Saved Questions" section removed**: it still said Option A vs B was undecided, contradicting the Dev Agent Record's actual decision.

### File List

- `src/yt_flow/pipeline/nodes/video.py` — `_join_with_xfade()`: replaced `acrossfade` audio chain with `adelay`+`amix(normalize=0)` reusing the video xfade's own offset values; code review: negative-offset silent clamp replaced with a loud assert, ponytail comment corrected.
- `tests/pipeline/nodes/test_video.py` — renamed `test_xfade_has_acrossfade` → `test_xfade_video_crossfades_audio_does_not` (asserts no `acrossfade`, presence of `adelay`/`amix(normalize=0)`); added `test_xfade_audio_delay_matches_video_offset_3_scenes`; extended `test_xfade_join_integration` to assert per-stream (`v:0`/`a:0`) durations independently instead of only the container duration; code review: added `test_xfade_offset_negative_raises`, hardened `_stream_duration()`, added chapter-card filter_complex assertion to `test_chapter_cards_enabled_creates_card_segments`.

## Change Log

- 2026-07-04: Story created from live-render review feedback (audio fading at scene transitions), root cause pre-confirmed via code investigation before story creation.
- 2026-07-04: Implemented Option A (adelay+amix, no acrossfade) in `_join_with_xfade()`; updated/added `test_video.py` coverage; full regression suite green; live-validated against a real prior run's rendered segments (duration parity + RMS waveform, no dip). Status → review.
- 2026-07-04: Code review completed — 4 patches applied (asymmetric clamp → assert, ponytail comment corrected, AC2 test coverage added, test robustness fix), AC5 evidence independently re-verified, stale "Saved Questions" section removed. 3 items deferred (pre-existing/out-of-scope). Status → done.

## Saved Questions / Clarifications

- Resolved during implementation: Option A (continuous concat) was chosen over Option B (silence gap) — see Tasks/Subtasks "Decide the audio-join approach" and Dev Agent Record for the full rationale (Option B would discard real narration content at every cut).
