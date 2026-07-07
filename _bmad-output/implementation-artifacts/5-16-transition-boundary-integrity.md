---
created: 2026-07-06
story_key: 5-16-transition-boundary-integrity
story_id: "5.16"
epic: 5
depends_on:
  - 5-1-scene-transitions-chapter-cards
  - 5-9-transition-audio-continuity
  - 7-1-sound-design
  - 7-4-transition-variety
baseline_commit: eb9e2964860cd183050607a00ffb9b260bee70af
---

# Story 5.16: Transition Boundary Integrity — Audio-Bridged Dip-to-Black, No Overlap

Status: done

## Story

As Jay,
I want scene transitions to follow standard documentary editing grammar — narration plays out fully, the soundscape bridges the visual transition, and dip-to-black marks the act break —
so that the last moments of each scene's image and narration are never consumed by the transition and boundaries never drop into dead air.

## Context

Context: Jay viewing feedback on E2E baseline 2026-07-06 (run `272b05a4`, SCP-049) — feedback #2. Report: `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md`. Design choices below follow standard editing conventions (audio bridging / J-cut discipline, dip-to-black reserved for act breaks) per Jay's direction (2026-07-06).

The current join is overlap-consuming by construction. `_join_with_xfade` ([src/yt_flow/pipeline/nodes/video.py:715-802](../../src/yt_flow/pipeline/nodes/video.py#L715)) places each `xfade` at `offset = Σ(dur_0..i) − (i+1)·XFADE_DURATION` ([video.py:760](../../src/yt_flow/pipeline/nodes/video.py#L760)), so the last `XFADE_DURATION` (0.5s) of every outgoing segment is blended away — the pre-transition image is visually cut short. Story 5.9's audio fix (`adelay` to the same offsets + `amix=normalize=0`, [video.py:773-780](../../src/yt_flow/pipeline/nodes/video.py#L773)) removed the volume dip but shares the overlap: the tail of narration *i* plays under the head of narration *i+1* during the window, which Jay hears as narration being cut off. The E2E baseline confirmed the accounting: total 230.9s ≈ Σnarration 225.6 + cards − xfade overlap.

The replacement grammar, in convention terms:
- **Narration is NEVER trimmed or overlapped** — it plays to its last sample before the visual boundary.
- **The audio bed bridges the boundary** (documentary audio-bridging pattern): boundaries must not fall to digital silence. Constraint honesty: 7-1's bed (BGM/ambient/stinger) is *baked into each scene segment* at compose time ([video.py:620-640](../../src/yt_flow/pipeline/nodes/video.py#L620), [src/yt_flow/pipeline/nodes/sound_design.py:63-82](../../src/yt_flow/pipeline/nodes/sound_design.py#L63)), so a single continuous bed across joins is not achievable at join time — instead, card/hold segments carry the upcoming mood's **ambient bed** (replacing today's pure `anullsrc` silence) and the incoming scene's baked **stinger** (which fires at scene start, [sound_design.py:75](../../src/yt_flow/pipeline/nodes/sound_design.py#L75)) lands as the sound punctuation right after the dip. Full cross-boundary bed continuity is recorded in Saved Questions.
- **Dip-to-black is reserved for act breaks** — which in this pipeline is exactly the scene boundary. Where a chapter card exists, the card IS the dip (no extra black hold); card-less scene boundaries get a short dip of `BLACK_HOLD_DURATION = 0.3`s (0.2–0.4s max per convention).
- **7-4's mood-driven xfade *types* are retired** (Jay-aligned decision): wipe-type variety is imperceptible; production value comes from the card + sound punctuation, not transition geometry.

## Acceptance Criteria

1. **No-overlap dip-to-black video grammar.** Given a run with 2+ scenes, when the final video is composed, then every scene boundary renders as: outgoing segment fades to black over its own last frames (in-place `fade=t=out`, consuming no duration), the dip (card, or a pure-black hold of `BLACK_HOLD_DURATION = 0.3` — a named module constant, NOT a config flag), then the incoming segment fades in from black (`fade=t=in`) over its own first frames. No frame ever blends two scene images, and no segment content is trimmed or consumed by the transition.
2. **Narration plays out fully; audio is strictly sequential.** Given the same join, then each scene's narration (with its baked bed) plays to the segment's last sample before the boundary, and the next narration starts only after the dip. The join uses plain audio concatenation — no `acrossfade`, no `adelay`+`amix`, no volume scaling of any kind — so Story 5.9's no-volume-dip guarantee holds by construction (there is no overlap window at all anymore).
3. **The soundscape bridges the dip — no dead air.** Given `sound_design_enabled=true`, then card segments and black-hold segments carry the upcoming scene's mood **ambient bed** at `AMBIENT_VOLUME` ([sound_design.py:28](../../src/yt_flow/pipeline/nodes/sound_design.py#L28), reuse `MOOD_ASSET_PATHS`/`validate_mood_assets`) instead of `anullsrc` silence — the boundary never drops to digital silence; the scene-baked bed ends with the scene tail and the incoming scene's baked stinger punctuates the cut-in (no code change to scene mixing). When `sound_design_enabled=false`, cards/holds keep `anullsrc` (today's behavior).
4. **7.4 retirement — explicit deletion list.** Given the new grammar, then ALL of the following are deleted: `MOOD_XFADE_MAP`, `resolve_transition`, the `MOOD_VALUES` key-set assert ([video.py:74-86](../../src/yt_flow/pipeline/nodes/video.py#L74)), the per-segment transition element in the join signature (7.4's `segments[i+1][2]` "announce own cut-in" rule), the `transition_variety_enabled` config flag ([src/yt_flow/config.py:97](../../src/yt_flow/config.py#L97), now dead — deletion over a vestigial flag, Ponytail), and the mood-transition wiring in `video_node` ([video.py:884-899](../../src/yt_flow/pipeline/nodes/video.py#L884)). Every fade uses the constant `FADE_DURATION = 0.5` (renamed from `XFADE_DURATION`); `wipeleft`/`fadewhite` appear nowhere. 7.4's tests are replaced per Task 4, not silently dropped.
5. **Card boundaries produce no double dip.** Given `chapter_cards=true` (default, [config.py:92](../../src/yt_flow/config.py#L92)), then a boundary where a chapter card is inserted gets NO extra black-hold segment — the card is the dip (it is already black and self-fades via `CARD_FADE_DURATION`, [video.py:690-698](../../src/yt_flow/pipeline/nodes/video.py#L690)). Adjacent scenes still get their own fade-out/fade-in; card self-fades are preserved. Black holds are inserted only at boundaries with no card (i.e. when `chapter_cards=false`).
6. **Duration invariant becomes plain sum.** Given N segments (scenes + cards) and G black holds, then total output duration ≈ Σ(segment durations) + G × `BLACK_HOLD_DURATION` (within codec quantization tolerance, cf. 5.9's documented ~37ms AAC rounding). The `running_offset` accumulator, the offset formula, the negative-offset assert, and the `adelay`/`amix` graph are deleted — the join reduces to concat arithmetic. Tests asserting the old `Σ − (n−1)·XFADE_DURATION` formula are updated to the new formula, not removed.
7. **Regression posture.** Given the change, then Story 5.1's chapter-card behavior (content, duration clamp, self-fades, 7.2 mood grade), 5.9's audio continuity, the single-scene path ([video.py:881-882](../../src/yt_flow/pipeline/nodes/video.py#L881)), and 7.1's in-scene mixing are not regressed; trace metadata ([video.py:454-455](../../src/yt_flow/pipeline/nodes/video.py#L454)) is updated to the new grammar (e.g. `transition: "dip-to-black"`, `fade_duration`, `black_hold_sec`).
8. **Live validation.** Given a real render with at least 2 scene boundaries (reuse existing rendered segments per 5.9's precedent), then ffprobe confirms the AC6 formula, frame sampling inside the dip shows pure black (no blended imagery), and waveform inspection shows narration running to the boundary at full level with the ambient bed (not digital silence) during the dip. Keep the joined output artifact on disk (5.9 review lesson: retain live-validation artifacts).

## Tasks / Subtasks

- [x] **Task 1 — Rebuild the join as fade + concat (AC: 1, 2, 6)**
  - [x] Read `_join_with_xfade` fully first ([video.py:715-802](../../src/yt_flow/pipeline/nodes/video.py#L715)) — its docstring documents exactly what is being deleted.
  - [x] Replace with a concat-based join (suggested `_join_with_fades`). Suggested signature: `segments: list[tuple[Path, float, float, float]]` = (path, duration, fade_in_sec, fade_out_sec), fades precomputed by `video_node` (0.0 for cards and holds, which self-fade or are already black; 0.0 fade-in for the first segment and 0.0 fade-out for the last, matching today's no-fade head/tail).
  - [x] Per-input filter: `[i:v]fade=t=in:st=0:d={fi},fade=t=out:st={dur-fo:.3f}:d={fo}[vN]` (skip zero fades; clamp fade duration to segment duration defensively); then one `concat=n={n}:v=1:a=1[vout][aout]`. Audio passes through untouched — no gain, no overlap.
  - [x] Add `BLACK_HOLD_DURATION = 0.3  # seconds — dip-to-black hold at card-less act breaks` beside the fade constants; a constant, not a `Settings` field (Ponytail: add a knob only when a run needs a different hold).
  - [x] Delete: `running_offset` accumulator + offset formula, `assert offset >= 0` ([video.py:768-772](../../src/yt_flow/pipeline/nodes/video.py#L768)), `adelay`/`amix` graph ([video.py:773-780](../../src/yt_flow/pipeline/nodes/video.py#L773)), and the `≥ 2×XFADE_DURATION` min-scene-length ponytail comment ([video.py:742-747](../../src/yt_flow/pipeline/nodes/video.py#L742)) — concat has no minimum-duration constraint.
- [x] **Task 2 — Retire 7.4's type map + rewire video_node (AC: 4, 5)**
  - [x] Apply the AC4 deletion list. Rename `XFADE_DURATION` → `FADE_DURATION = 0.5`; keep `XFADE_TRANSITION` deleted or repurpose its comment block to document the dip grammar.
  - [x] Remove `transition_variety_enabled` from `Settings` ([config.py:97](../../src/yt_flow/config.py#L97)) and from the `_settings_ns` test helper ([tests/pipeline/nodes/test_video.py:42](../../tests/pipeline/nodes/test_video.py#L42)).
  - [x] Rewire `video_node`'s `join_segments` construction ([video.py:883-901](../../src/yt_flow/pipeline/nodes/video.py#L883)): scenes get `FADE_DURATION` in/out fades (edges excepted); cards get 0.0 join-fades; insert a black-hold segment (0.0 fades) between two scenes only when no card was inserted there.
- [x] **Task 3 — Ambient bed on cards/holds (AC: 3)**
  - [x] `_compose_chapter_card` ([video.py:666-712](../../src/yt_flow/pipeline/nodes/video.py#L666)): when `sound_design_enabled`, replace the `anullsrc` input with the upcoming mood's ambient asset (`MOOD_ASSET_PATHS[resolve_mood(mood)]["ambient"]`, `-stream_loop -1`, `volume=AMBIENT_VOLUME`, `-t duration`); the `mood` parameter already exists (7.2 grading). Validate via the existing `validate_mood_assets` fail-fast path ([video.py:511-512](../../src/yt_flow/pipeline/nodes/video.py#L511)). `sound_design_enabled=false` → `anullsrc` unchanged.
  - [x] Black-hold segment: render once per run (black `color` source + the same ambient-or-anullsrc audio recipe, no drawtext, no self-fades — it sits between two faded-to-black frames); reuse the file at every card-less boundary. Use the *incoming* scene's mood for its ambient when moods differ (the hold announces the next act — same rule cards already use for their grade, [video.py:893-898](../../src/yt_flow/pipeline/nodes/video.py#L893)); note holds only exist when cards are off, and each boundary needs its own hold file only if moods differ — render per-boundary when `sound_design_enabled`, else one shared silent file (keep it simple).
- [x] **Task 4 — Tests (AC: 1-7)** — all in [tests/pipeline/nodes/test_video.py](../../tests/pipeline/nodes/test_video.py); reuse the `async _capture` monkeypatch of `video._run_ffmpeg` grabbing `-filter_complex` (pattern at test_video.py:314+).
  - [x] Replace the xfade-era join tests — `test_xfade_offset_math_3_scenes` (314), `test_xfade_video_crossfades_audio_does_not` (344), `test_xfade_audio_delay_matches_video_offset_3_scenes` (376), `test_xfade_uses_fadeblack_transition` (405), `test_xfade_offset_negative_raises` (438) — with: filtergraph has `concat=n=..:v=1:a=1`, per-input `fade=t=out`/`fade=t=in` at correct `st` values, NO `xfade=`/`acrossfade`/`adelay`/`amix` tokens.
  - [x] Delete 7.4's type-map tests — `test_resolve_transition_maps_each_mood` (463), `test_resolve_transition_unknown_falls_back_to_dread` (470), `test_join_with_xfade_per_boundary_transition` (475), `test_video_node_mood_varied_scene_transition` (1804), `test_video_node_multiple_mood_boundaries_each_independent` (1830), `test_video_node_card_adjacency_uses_mood_transition` (1857) — replaced by constant-fade assertions (AC4's "replaced per Task 4"). Also deleted `test_video_node_transition_variety_disabled_all_fadeblack` and `test_config_transition_variety_enabled_default_true` (same dead-flag family, not individually named in the draft but covering the same retired surface).
  - [x] New: black-hold insertion — cards off → exactly (n−1) hold inputs; cards on → zero hold inputs (AC5); card/hold audio input is the mood ambient asset when `sound_design_enabled` and `anullsrc` when not (AC3); cards keep their internal `fade=t=in/out` while receiving zero join-fades.
  - [x] Update the live-ffmpeg `test_xfade_join_integration` (1472) → renamed `test_join_with_fades_integration`: expected duration = Σdur + holds × `BLACK_HOLD_DURATION` (no overlap subtraction); assert `v:0`/`a:0` stream durations independently (5.9 pattern).
  - [x] Update `test_trace_receives_transition_metadata` (824) — added `test_record_trace_reports_dip_to_black_grammar` calling the real `_record_trace` (the autouse `_silent_trace` fixture stubs it in every other test) to assert `transition`/`fade_duration`/`black_hold_sec`; card tests `test_chapter_cards_enabled_creates_card_segments` (1723) / `test_chapter_cards_disabled_no_card_render` (1775) updated for concat tokens and hold insertion; the `Settings` default test for the removed flag deleted.
  - [x] Run `uv run pytest tests/pipeline/nodes/test_video.py -q`, then full `uv run pytest -q` (config-flag removal can ripple — grep `transition_variety` across the repo). Both green; `ruff check` clean.
- [x] **Task 5 — Live validation (AC: 8)**
  - [x] Reused real rendered segments from prior production run `eb522cf9` (`seg_001.mp4` 17.600s, `seg_002.mp4` 23.120s) and ran the new join + a real black-hold render (dread ambient bed, `sound_design_enabled=True`) with real ffmpeg.
  - [x] Verified: ffprobe durations — expected 41.020s, actual video 41.040s / audio 41.049s (within 5.9's documented AAC-rounding tolerance); dip frame sampled at the hold midpoint is flat `YAVG=16.0` (limited-range black, no blended imagery) with a visible monotonic fade ramp on both sides (27.6→16.0→18.9); windowed RMS (`astats`, 0.1s windows) across the boundary never drops toward digital silence (stays in the −20 to −30 dB band through the dip, consistent with the ambient bed at `AMBIENT_VOLUME`, not `-inf`). Output artifacts kept on disk at `_bmad-output/implementation-artifacts/5-16-live-validation/` (`joined.mp4`, `hold_001.mp4`, `dip_frame.png`) — not committed to git (binary media, no repo precedent for committing prior live-validation artifacts; `_bmad-output/` is not gitignored so the files remain available locally for review).

## Dev Notes

### Decision — why retire MOOD_XFADE_MAP outright (AC: 4)

Jay-aligned (2026-07-06 direction): wipe/white transition-type variety is imperceptible to viewers; boundary production value comes from the chapter card and the sound punctuation (7-1 stinger — and 5.17 will sync it to card entry). Structurally, `wipeleft`/`fadewhite` are also overlap transitions — they blend/slide two scene images, exactly the artifact this story removes, and `fadewhite` violates the black-hold grammar. An earlier draft of this story proposed keeping mood variety as fade-*duration* variation; rejected per the same direction — one fade grammar, one constant, no vestigial variety axis or flag. 7.4's *record* stays done/immutable; this story supersedes its runtime behavior the same way 5.9 superseded 5.1's `acrossfade`.

### Audio bridging under the baked-bed constraint (AC: 3) — read before designing

7-1 mixes the bed *inside each scene segment*: `build_sound_design_args`/`build_sound_design_filter` add bgm+ambient+stinger inputs to `_compose_scene`'s ffmpeg call, duck them under narration via `sidechaincompress`, and the stinger is a one-shot from t=0 `apad`-ed to scene duration ([sound_design.py:49-82](../../src/yt_flow/pipeline/nodes/sound_design.py#L49)). Consequences:
- A join-time continuous bed would double the bed over scene content (it's already baked in) — NOT an option without restructuring 7-1. That restructure (bed as a full-timeline track mixed at join, scenes rendered dry) is the "full continuity" Saved Question, not this story.
- What IS join-adjacent and cheap: the card/hold audio (currently `anullsrc`, [video.py:702](../../src/yt_flow/pipeline/nodes/video.py#L702)) becomes the mood ambient bed. Result at a card boundary: scene bed (full) → card ambient (low, same mood family) → next scene bed + stinger. The level steps down and back up, but never to silence — the honest approximation of audio bridging the grammar allows today.
- The scene-baked bed ends at the segment's last sample (`amix duration=first`); it cannot be faded at join time without also fading the narration tail (narration runs to the segment's final sample — that's the whole point of AC2). Accept the bed's hard out under the visual fade; the E2E loudness data (-23.6 LUFS integrated, card beds audible) suggests this reads fine; revisit only if Jay hears a bump.

### What the new join deletes vs. preserves

**Deleted** ([video.py:715-802](../../src/yt_flow/pipeline/nodes/video.py#L715) + 7.4 surface):
- `running_offset` + `offset = Σdur − (i+1)·XFADE_DURATION` ("the #1 source of xfade timing bugs" per its own docstring) — concat needs no offsets.
- `assert offset >= 0` and the `≥ 2×XFADE_DURATION` min-scene-duration assumption.
- 5.9's `adelay`+`amix=normalize=0` graph — it existed solely to track the video overlap without a dip; zero overlap makes plain concat strictly stronger.
- `MOOD_XFADE_MAP`, `resolve_transition`, its key-set assert, the 3-tuple transition element, `transition_variety_enabled` (config + `_settings_ns` kwarg).

**Preserved:**
- 5.9's no-volume-dip guarantee — now by construction (no gain manipulation anywhere in the join's audio path).
- Total-duration invariant tests — formula becomes `Σ + G·HOLD` (AC6).
- `_compose_chapter_card` visual internals: black bg, drawtext label, `CARD_FADE_DURATION` self-fades, 7.2 mood grade. Story 5.17 extends card *content* — do not restructure card rendering here beyond the audio input swap (shared-code-region coordination).
- `_compose_scene`, Ken Burns, overlays, 7.1 in-scene mixing, post-fx — untouched.
- Single-scene path (`segs[0].replace(output)`) and `_OUTPUT_ARGS` encode settings.

### Behavior nuance worth a code comment

The outgoing scene's fade-out overlaps the last ~0.5s of *its own* narration (the fade is in-place; narration runs to the segment's final sample). That is normal film grammar and satisfies "narration never trimmed" — nothing is cut or mixed with the next scene. Padding segments so the fade starts after narration ends was considered and rejected (reintroduces duration bookkeeping for no audible benefit).

### Architecture compliance / Ponytail

- No new node, DB, or API changes — entirely inside `video_node` (AD-1/AD-4 unaffected). Zero new dependencies: `fade`, `concat`, `color`, `volume`, `-stream_loop` are ffmpeg built-ins already used in this codebase.
- Net deletion: this story removes the offset accounting, the audio-overlap graph, a config flag, and a mapping table; it adds two constants and one audio-input swap. LOC should go down.

### Testing standards

- `pytest` + `pytest-asyncio`; join tests monkeypatch `video._run_ffmpeg` and assert the captured `-filter_complex`; live tests gated on ffmpeg/ffprobe availability.
- Worktree gotcha ([[worktree-editable-install-shadowing]]): run pytest with `PYTHONPATH=$PWD/src`.

### Project Structure Notes

- Expected modified files: `src/yt_flow/pipeline/nodes/video.py`, `src/yt_flow/config.py`, `tests/pipeline/nodes/test_video.py` (+ any test touching `transition_variety_enabled`). No new modules.
- **Parallel-session hazard:** 5.17 (card content + stinger sync) edits the adjacent card block of `video.py` and builds on this story's card-audio change — sequence 5.16 → 5.17, never concurrent on `video.py`. 5.15 is independent (scenario_chain.py) but gates mood observability.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 5.16] — draft scope.
- [Source: _bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md] — run `272b05a4` video-gate accounting, J1 score, loudness measurements.
- [Source: _bmad-output/implementation-artifacts/5-9-transition-audio-continuity.md] — the adelay/amix design superseded here; AC8's live-validation template.
- [Source: _bmad-output/implementation-artifacts/7-4-transition-variety.md] — the retired type map; its AC5 amendment history.
- [Source: _bmad-output/implementation-artifacts/5-1-scene-transitions-chapter-cards.md] — card segment contract.
- [Source: src/yt_flow/pipeline/nodes/sound_design.py#L17-L82] — bed asset paths, volumes, per-scene mix (the baked-bed constraint).
- [Source: src/yt_flow/pipeline/nodes/video.py#L69-L86, #L620-L712, #L715-L802, #L876-L901] — constants, scene/card compose, join, node wiring.

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- Test env has real `ffmpeg`/`ffprobe`/`fc-match` installed; full unmocked suite run takes ~3 minutes (704 passed, 1 skipped) — not a regression, just the live-ffmpeg integration tests running for real.
- Live validation script: `/tmp` scratch (not committed) reusing `_compose_black_hold` + `_join_with_fades` directly against `workspace/eb522cf9-.../seg_001.mp4`/`seg_002.mp4`.

### Completion Notes List

- Replaced `_join_with_xfade` (offset accounting + `adelay`/`amix`) with `_join_with_fades` (per-segment in-place `fade=t=in`/`fade=t=out` + `concat`). Net LOC went down as predicted by the story's Ponytail note.
- Retired 7.4 outright: `MOOD_XFADE_MAP`, `resolve_transition`, the mood-key-set assert, `XFADE_TRANSITION`, `transition_variety_enabled` (Settings + test helper), and the per-boundary mood-transition wiring in `video_node`. `FADE_DURATION = 0.5` replaces `XFADE_DURATION` as the (now constant, no variety axis) fade length.
- Added `_compose_black_hold` (new) for card-less boundaries and extended `_compose_chapter_card` with a `sound_design_enabled` param — both share a `_card_hold_audio_input` helper that swaps `anullsrc` for the upcoming scene's looped mood-ambient bed at `AMBIENT_VOLUME`, matching AC3.
- `video_node`'s join-segment construction now computes per-segment `(fade_in, fade_out)` (0.0 at the overall head/tail, `FADE_DURATION` at every internal scene edge, 0.0 for cards/holds) and inserts a black hold only at boundaries with no card (AC5).
- Trace metadata (`_record_trace`) now reports `transition: "dip-to-black"`, `fade_duration`, `black_hold_sec` instead of the retired xfade fields (AC7).
- Test suite: rewrote the join-math tests around `_join_with_fades` (concat tokens, per-segment fade points, zero-fade skip, defensive clamp), deleted the entire 7.4 type-map test family (6 tests) plus the now-dead `transition_variety_enabled` variety/disabled tests and its `Settings` default test, added a black-hold insertion test family (cards-off count, cards-on zero, ambient-vs-anullsrc for both card and hold, zero join-fades on card/hold), and updated the live-ffmpeg integration test to the new no-overlap duration formula. One correction during the review: `test_record_trace_reports_dip_to_black_grammar` initially failed because the file's autouse `_silent_trace` fixture stubs `_record_trace` in every test — fixed by capturing the real function object (`_REAL_RECORD_TRACE`) at import time, before the fixture patches it.
- Live validation (AC8, Task 5): see the Task 5 checklist above for the ffprobe/frame/RMS results. Duration, black-dip purity, and no-silence-through-the-dip all confirmed against real segments from run `eb522cf9`.
- `chapter_card_count` in trace metadata is unchanged in meaning; no `black_hold_count` field was added (not required by any AC — Ponytail YAGNI).

### File List

- `src/yt_flow/pipeline/nodes/video.py` — modified (join rewrite, 7.4 retirement, card/hold ambient bed, trace metadata)
- `src/yt_flow/config.py` — modified (removed `transition_variety_enabled`)
- `tests/pipeline/nodes/test_video.py` — modified (join/transition-variety test rewrite, new black-hold tests, trace metadata test)

## Change Log

- 2026-07-06: Story created from Jay's viewing feedback #2 on the E2E baseline video (run `272b05a4`): pre-transition image and narration cut off at scene boundaries. Root cause pre-confirmed in code (overlap-consuming xfade offsets shared by video and 5.9's audio graph).
- 2026-07-06: Revised per Jay's editing-conventions direction: audio bridging (bed carries the boundary via card/hold ambient), dip-to-black reserved for act breaks (hold 0.3s, card is the dip), MOOD_XFADE_MAP retired outright (earlier fade-duration-variety proposal dropped), `transition_variety_enabled` flag deleted.
- 2026-07-07: Implemented — dip-to-black fade+concat join, 7.4 retirement, card/hold ambient bed, trace metadata, full test rewrite (704 passed/1 skipped, ruff clean), live validation against real `eb522cf9` segments. Status → review.
- 2026-07-07: Reviewed (`bmad-code-review`) — 3 patch findings fixed (short-scene fade overlap clamp, explicit `-map` on card/hold ffmpeg calls, atomic write for the black-hold cache), 7 dismissed as false positives/spec-intentional. Full suite re-verified (705 passed/1 skipped, ruff clean). Status → done.

## Review Findings

Reviewed via `bmad-code-review` (2026-07-07): Blind Hunter + Edge Case Hunter + Acceptance Auditor, run in parallel against the uncommitted `video.py`/`config.py`/`test_video.py` diff. Acceptance Auditor confirmed all 8 ACs satisfied, including a repo-wide grep confirming zero remaining references to the AC4 deletion list (`MOOD_XFADE_MAP`, `resolve_transition`, `XFADE_TRANSITION`, `XFADE_DURATION`, `transition_variety_enabled`, `wipeleft`, `fadewhite`). 3 real gaps survived triage; 7 other raised findings were dismissed as false positives or spec-intentional behavior (already-covered validation, structurally-guaranteed dict sync, explicitly-deferred audio de-click, spec-mandated `AMBIENT_VOLUME` reuse, spec-intentional card/hold duration difference, a docstring misread).

- [x] [Review][Patch] Short-scene fade windows could overlap on one segment [video.py:791-798] — `fade_out` was clamped only against `dur`, not against `dur - fade_in`; a scene shorter than `FADE_DURATION×2` (1.0s) got overlapping fade-in/fade-out windows on its own frames (cosmetic over-darkening, not a cross-scene blend — AC1's actual guarantee held regardless). Fixed: clamp `fade_out = min(fade_out, dur - fade_in)`; also formatted both `d=` fade durations to `:.3f` for consistency with the existing `st=` formatting. New test: `test_join_with_fades_overlapping_windows_dont_double_up`.
- [x] [Review][Patch] Card/hold ffmpeg calls had no explicit `-map` [video.py:707-719, 749-763] — every other multi-input ffmpeg invocation in this file uses explicit `-map` after `-filter_complex`; the card/hold calls relied on default stream auto-selection, which was safe with `anullsrc` (audio-only) but risks picking up an embedded cover-art video stream from a real ambient `.mp3` (Story 5.16 AC:3's new input) instead of the intended black background. Fixed: added `-map 0:v -map 1:a` to both `_compose_chapter_card` and `_compose_black_hold`.
- [x] [Review][Patch] `_compose_black_hold`'s file-reuse cache could serve a truncated file after a crash [video.py:744-767] — the `hold_path.exists()` cache check trusted any file at that path, including one left incomplete by a killed/crashed prior render (unlike the atomic `segs[0].replace(output)` pattern already used elsewhere in this file for exactly this hazard class). Fixed: render to a `.tmp.mp4` path and `Path.replace()` it into place atomically, so the cache check only ever sees a fully-written file.

All 3 patches verified: `uv run pytest tests/pipeline/nodes/test_video.py -q` (127 passed) and full `uv run pytest -q` (705 passed, 1 skipped), `ruff check` clean.

## Saved Questions / Clarifications

- **Full cross-boundary bed continuity** (one continuous BGM/ambient track under the whole video, scenes rendered dry, bed mixed+ducked at join level): the "true" documentary pattern, but it restructures 7-1's per-scene mixing (sidechain ducking would need the full narration track at join time). Deferred as its own story if the ambient-bridge approximation still reads as a bump to Jay.
- **Bed hard-out at scene tails:** the baked bed stops at the segment's last sample (can't fade it without dipping narration). Accepted; revisit with the full-continuity story above if audible.
- **Audio de-click at concat boundaries:** TTS narration ends in natural silence and the bed masks transients; no `afade` added (would reintroduce the 5.9 dip class). Revisit only if a live render clicks.
- **Mood observability:** until Story 5.15 (mood wiring) lands, all live scenes resolve to `dread`, so card/hold ambient will be the dread bed in practice.
