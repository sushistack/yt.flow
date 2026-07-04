---
created: 2026-07-04
story_key: 5-9-transition-audio-continuity
story_id: "5.9"
epic: 5
previous_story: 5-8-automatic-entity-reference-generation
depends_on:
  - 5-1-scene-transitions-chapter-cards
---

# Story 5.9: Decouple Audio Continuity from Scene Transition Fades

Status: ready-for-dev

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

- [ ] Decide the audio-join approach (AC: 1, 3) — read `_join_with_xfade()` fully (`src/yt_flow/pipeline/nodes/video.py:537-590+`) before choosing.
  - [ ] Option A: concatenate audio streams directly (no `acrossfade`) while keeping video `xfade`, adjusting the `running_offset` math so video transition timing and audio concat timing both land on the correct combined-output positions.
  - [ ] Option B: insert a short silence (`anullsrc`, matching the pattern chapter cards already use per 5.1) exactly during the `XFADE_DURATION` window instead of an `acrossfade`.
  - [ ] Document the chosen approach's impact on total duration parity with the existing `sum(scene_durations) + sum(card_durations) - sum(transition_overlaps)` formula (5.1 AC5).
- [ ] Implement in `_join_with_xfade()` (AC: 1-3)
  - [ ] Replace or bypass the `acrossfade` filter per the chosen approach.
  - [ ] Keep the video `xfade` filter and its `running_offset`/`offset` accumulator untouched unless the chosen approach requires coordinated changes.
- [ ] Update tests (AC: 4)
  - [ ] Update/extend `tests/pipeline/nodes/test_video.py`'s xfade filter-graph assertions to reflect the new audio handling (no `acrossfade` present, or `anullsrc`-based silence gap present, per chosen approach).
  - [ ] Keep existing chapter-card and `fadeblack` video-transition assertions passing unmodified.
  - [ ] Run: `uv run pytest tests/pipeline/nodes/test_video.py -q`.
- [ ] Validate live (AC: 5)
  - [ ] Render a multi-scene video and confirm (by listening or waveform diff) that narration audio no longer dips at scene cuts.
  - [ ] Record the run ID and outcome in Dev Agent Record.

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

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

- Story context created 2026-07-04 following user (Jay) review of Story 5.5's live-rendered A/B videos; root cause (shared `XFADE_DURATION`-coupled `acrossfade`) pre-confirmed via code investigation before story creation — see `src/yt_flow/pipeline/nodes/video.py:565-573`.

### File List

## Change Log

- 2026-07-04: Story created from live-render review feedback (audio fading at scene transitions), root cause pre-confirmed via code investigation before story creation.

## Saved Questions / Clarifications

- Option A (continuous concat) vs Option B (silence gap) is not decided — Option A preserves narration continuity better but may need more careful duration-accounting rework; Option B is closer to the existing chapter-card pattern but introduces a brief silence at every cut. Dev agent or Jay should decide before implementing.
