---
baseline_commit: abd936100ac7bf082e4e9321c887f40f94f17516
created: 2026-07-09
story_key: 8-11-per-shot-cut-assembly
story_id: "8.11"
epic: 8
previous_story: 8-10-cast-decision-split-call
depends_on:
  - 8-3-bg-only-generation-multicard-compositing   # _compose_scene card overlay chain being split
related:
  - 8-7-composite-harmonization                    # tint/shadow/light-wrap stages move into the per-shot clip
  - 8-8-character-micro-motion-techniques          # per-card motion filters move into the per-shot clip
  - 8-9-character-locomotion-blocking              # movement curves become per-shot after this story
  - spec-subtitle-word-segment-fallback            # word_timings degrade path this story must survive
workflow_decision: "No new LangGraph stage. video_node assembly change only — scenario/image/tts/subtitle artifacts are already shot-granular."
evidence: "Iteration 1 run d55a265b (e2e-iteration1-2026-07-09.md), Jay viewing feedback items #5/#6 (2026-07-09)."
---

# Story 8.11: Per-Shot Cut Assembly in video_node

Status: done

## Story

As Jay,
I want each scene's video segment cut into shot-level subclips timed to the narration sentences each shot was written for,
so that the 87 purpose-built shot images actually appear on screen in sync with what the narration is saying, instead of the first shot's image being frozen for the whole scene.

## Context — root cause, confirmed in code

Iteration 1 (run `d55a265b`) generated 87 shot backgrounds; the final video used **8** — one per scene. `_compose_scene` picks the *first* shot with an `image_path` and Ken-Burns it for the scene's entire audio duration:

```python
# video.py:745
shot = next((s for s in shots if s.get("image_path")), None)
bg_path = shot["image_path"]
```

`video_node` does the same for cast cards (`video.py:1262`): only `f"{scene_num}:{first_shot_id}"` is looked up in the resolver output. The visible result (Jay feedback #5/#6): scene 1's 13 sentences — door closing, the doctor appearing, the touch, death, surgery, reanimation — all play over the single "D-class at the door" composition, so mid-scene narration looks like it belongs to a different video.

Everything needed to cut correctly already exists in state:

- `ShotData.sentence_indices` — 0-based indices into the scene's narration sentences, the unit the image was generated for (AD-5).
- `SceneState.word_timings` — whisperx word timings for the scene's spoken track (persisted by tts/subtitle stages).
- `subtitle.py sentence_cues()` (line 202) — already derives per-sentence `(start, end)` windows from `word_timings` + `split_sentences(narration)`, including the degrade path when word counts mismatch (`_apportion` by character length). The shot timing logic must be THE SAME windows, factored out — not a second implementation that can drift from what the subtitles show.
- `_cast_resolver` output is **already keyed per shot** (`"{scene_num}:{shot_id}"` for every shot with cast) — composition just never read the other keys. Per-shot cards are data-ready today.
- `select_effect(shot, scene_index)` (video.py:214) already takes a shot — it was designed per-shot and is currently fed the same first shot once.

## Architecture decision — two-pass scene composition

Keep audio, subtitles, sound design, and post-fx at **scene** granularity (they are scene-unit artifacts and correct as-is). Split only the **visual** track:

1. **Pass 1 — per-shot silent clips.** For each shot in the scene: background zoompan (`select_effect(shot, i)`), its own resolved cast cards, per-card motion (8.8), parallax (7.3), harmonization tint/shadow/light-wrap (8.7). Duration = the shot's sentence window span (see AC:3). No audio, no subtitle burn, no sound design.
2. **Pass 2 — scene assembly.** Concat the shot clips (plain concat, no crossfade — hard cuts are the documentary idiom and avoid re-introducing 5-16's retired xfade problems), then apply in one pass exactly what `_compose_scene` does today after the overlay chain: subtitle burn (`subtitles=`), narration audio, mood sound-design mix, post-fx grade, stinger handling. Segment-level contract to `_join_with_fades` is unchanged: same `(seg_path, duration, spec, cards_overlaid)` shape, same seg_###.mp4 naming.

This keeps the blast radius inside `video.py`: gates, SSE, artifacts API, chapter cards, ending credit, and the join pipeline see identical interfaces.

## Acceptance Criteria

1. **Shot windows from the subtitle's own math.** Extract the sentence-window computation from `sentence_cues()` into a reusable helper (e.g. `sentence_windows(timings, spoken_text) -> list[tuple[float, float]]`) in `subtitle.py`; `sentence_cues` consumes it unchanged (subtitle regression suite stays green). Shot start = window start of its first `sentence_indices` entry; shot end = window end of its last. Gaps between consecutive windows (inter-sentence silence) attach to the **preceding** shot so cuts land on sentence starts.
2. **Full-scene coverage, no black frames.** The first shot's clip is stretched to start at 0.0; the last shot's clip is stretched to end at `audio_duration`. Sentences not claimed by any shot (defensive — AD-5 says visual_breakdown covers all) inherit the previous shot's visual.
3. **Minimum cut duration with merge.** `Settings.min_shot_clip_sec: float = Field(2.0, ge=0.0)` (env `YTFLOW_MIN_SHOT_CLIP_SEC`). A shot whose window is shorter merges into the *previous* shot's clip (first shot merges forward instead). Merging means the earlier clip simply extends over the merged window — the short shot's image is dropped for assembly (its file remains on disk). `0.0` disables merging.
4. **Per-shot cast cards.** The composition loop reads the resolver output for **each rendered shot's** own key, not just the first shot's. A scene may now show cards in some shots and background-only in others; card alpha validation (video.py:1224 block) now covers every rendered shot's cards.
5. **Per-shot Ken Burns variety.** `select_effect(shot, ...)` is called per shot with a per-shot index so adjacent clips don't repeat the same zoom/pan direction (the existing effect-cycling logic decides; this AC only requires it be *fed* per-shot).
6. **Scene-level artifacts unchanged.** Narration audio, ASS subtitle burn, sound design mix (incl. `include_stinger` chapter-card suppression), post-fx grade, and `-t duration` pinning behave exactly as today at scene level. Segment output naming and the `_join_with_fades` call contract are unchanged.
7. **Degrade path: no usable word_timings.** When `word_timings` is empty or the apportion fallback fired (spec-subtitle-word-segment-fallback environment), shot windows come from the same `_apportion`-by-character-length distribution the subtitles use — cuts and cues stay mutually consistent. If even that is impossible (no sentences), fall back to today's single-shot behavior for that scene with a WARNING (never fail the stage on timing math).
8. **Resume/idempotence.** Re-running video_node (5-14 style retry) overwrites shot clips and segments cleanly; intermediate per-shot clip files live under the run dir (e.g. `shots/scene_001_S00100.mp4`) and must not confuse `_validate_scene_assets` or the artifacts endpoint.
9. **Tests.** Unit: window derivation (normal, gap-attachment, merge-below-minimum, first/last stretch, unclaimed sentences, empty timings degrade). Integration (ffmpeg, marked like existing video tests): a 2-scene fixture where scene 1 has 3 shots with distinct solid-color backgrounds — assert the segment's frames at window midpoints show the correct color per shot, and that cut count == kept-shot count. Regression: full suite green.
10. **Live verification.** One real re-render (existing checkpointed run or new short run) confirming: cuts land on sentence boundaries (± one frame), per-shot cards appear, no A/V desync at scene end, and the log line reports `shots rendered / merged / scenes` counts.

## Tasks / Subtasks

- [x] Task 1: Extract `sentence_windows()` from `sentence_cues()` in `subtitle.py`; keep `sentence_cues` behavior byte-identical (AC:1, AC:7)
- [x] Task 2: Shot-window derivation helper in `video.py` (or a small `shot_timing.py`): sentence_indices → merged, gap-attached, min-duration-filtered clip plan per scene (AC:1,2,3)
  - [x] Unit tests for the clip plan (AC:9)
- [x] Task 3: Split `_compose_scene` into `_compose_shot_clip` (pass 1: zoompan + cards + motion/parallax/harmonization, silent) and scene assembly (pass 2: concat + audio + subtitles + sound design + post-fx) (AC:4,5,6)
  - [x] Move per-card chain construction (current lines ~770-855) into pass 1 unchanged in behavior
  - [x] Wire per-shot resolver keys + per-shot alpha validation (AC:4)
- [x] Task 4: `min_shot_clip_sec` Settings field + config wiring (AC:3)
- [x] Task 5: Degrade paths + logging (AC:7) — WARNING for single-shot fallback, INFO summary `scene N: K shots → M clips (merged J)`
- [x] Task 6: Integration test with solid-color shot fixtures (AC:9)
- [x] Task 7: Live verification + Dev Agent Record evidence (AC:10)

### Review Findings

Adversarial code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor), 2026-07-12. All `patch` findings applied; `defer` findings are pre-existing-class data-integrity assumptions, not blocking.

- [x] [Review][Patch] `_validate_scene_assets` hard-failed on shots merged out of the render plan, reintroducing the exact "don't abort over an unused shot's missing image" failure mode the pre-8.11 code guarded against [video.py:_validate_scene_assets] — fixed: now validates only the shots `shot_timing.plan_shot_clips` actually keeps.
- [x] [Review][Patch] `video_node`'s `card_counts`/`rendered_cards`/motion-style metrics summed cards from every image-bearing shot, including ones `shot_timing` merged away and never composited [video.py:video_node] — fixed: scoped to the shot IDs that survive the clip plan.
- [x] [Review][Patch] `_assemble_scene_from_clips`'s sound-design-disabled branch had no `-t <duration>` clamp (the sound-design branch had one) — accumulated per-clip frame rounding could leave the concatenated video track shorter than the narration audio [video.py:_assemble_scene_from_clips] — fixed: added the same clamp to both branches.
- [x] [Review][Patch] Multi-clip effect selection used `select_effect(clip.shot, scene_index * 100 + local_i)`; since `_DIRECTION_POOL` has exactly 10 entries, `100 % 10 == 0` cancels `scene_index` out of the rotation entirely — every scene's Nth shot always got the same fixed direction [video.py:_compose_scene] — fixed: multiplier changed to a prime (`_EFFECT_INDEX_STRIDE = 97`) that can't divide the pool size.
- [x] [Review][Patch] A retry whose clip plan drops a shot_id a prior attempt rendered left that stale `shots/scene_NNN_<old_shot_id>.mp4` file on disk forever (AC:8 wants clean overwrite) [video.py:_compose_scene] — fixed: stale `scene_{n:03d}_*.mp4` files are removed before writing the new plan's clips.
- [x] [Review][Patch] A rendered shot whose `sentence_indices` don't land in `[0, n_sentences)` silently vanished from the clip plan with zero log signal [shot_timing.py:plan_shot_clips] — fixed: logs a WARNING naming the dropped shot_id.
- [x] [Review][Patch] AC:10 requires a log line reporting aggregate "shots rendered / merged / scenes" counts; only a per-scene `scene N: K shots -> M clips (merged J)` line existed, no run-level rollup [video.py:video_node] — fixed: added a summary log after the scene loop.
- [x] [Review][Patch] `sentence_cues` and `sentence_windows` each independently recomputed and checked the same word-timings-mismatch condition — two hand-synchronized copies of one boolean [subtitle.py] — simplified: extracted `_word_timings_mismatch()`, both call sites use it.
- [x] [Review][Patch] `_build_card_chain`'s docstring described an empty-`ordered_cards` branch neither caller (`_render_scene_fast`, `_compose_shot_clip`) ever exercises (both branch around calling it entirely when there are no cards) [video.py:_build_card_chain] — corrected the docstring.
- [x] [Review][Defer] No validation/logging when two shots' `sentence_indices` overlap — the gap-attachment sort would silently let one window clobber another [shot_timing.py:plan_shot_clips] — deferred, pre-existing data-integrity assumption (AD-5 promises non-overlapping sentence coverage from upstream); revisit if ever observed live.
- [x] [Review][Defer] `clips[-1].end = audio_duration` is applied unconditionally; if alignment slop ever put the last sentence window's start at/after the TTS-reported `audio_duration`, the final clip would get zero/negative duration with no clamp [shot_timing.py:plan_shot_clips] — deferred, cross-source (STT vs TTS) timing mismatch judged very low probability; revisit if ever observed live.

## Dev Notes

- **Do not re-time audio.** The narration wav is untouched; only visual cut points move. Any drift bug will show as subtitle-vs-cut mismatch — the shared `sentence_windows()` helper is the guard.
- **Concat method:** shot clips share codec/fps/size (same `_OUTPUT_ARGS`/`FPS`/`COMP_W×COMP_H`), so the concat demuxer (`-f concat -safe 0`) or `concat` filter both work; prefer the filter if pass 2 already runs a filter_complex (subtitle burn + sound design), avoiding an intermediate file. Watch the `-loop 1` + `-t` interplay per clip — pin each shot clip with `-t <clip_duration>` exactly as `_compose_scene` pins segments today (video.py:886 comment).
- **Harmonization tier interplay (8.7):** tint/shadow/light-wrap operate on the card chain — they move into pass 1 verbatim. Tier-3 relit card substitution (video.py:1268-1277) becomes per-shot: substitute on each shot's own `location_key`.
- **8.9 lands on top of this:** movement curves need the *shot clip* duration, not scene duration. Keep `_compose_shot_clip`'s duration an explicit parameter — 8.9 consumes it.
- **Cut rhythm sanity from iteration 1 data:** 87 shots / 238s ≈ 2.7s average — punchy but standard for the genre; the 2.0s merge floor keeps flash-cuts ("겨우 0.1초." ≈ 1.2s window) out.
- **ponytail:** no per-shot audio, no crossfades between shots, no new stage, no speculative "transition style" config. One knob (`min_shot_clip_sec`), one helper, one split function.

### Project Structure Notes

- Modify: `src/yt_flow/pipeline/nodes/video.py` (`_compose_scene` split, composition loop, per-shot cards), `src/yt_flow/pipeline/nodes/subtitle.py` (extract `sentence_windows`), `src/yt_flow/config.py` (`min_shot_clip_sec`)
- Tests: `tests/` alongside existing video/subtitle suites (follow current fixture/marker conventions for ffmpeg-dependent tests)

### References

- [Source: _bmad-output/implementation-artifacts/e2e-iteration1-2026-07-09.md] — evidence, run d55a265b
- [Source: src/yt_flow/pipeline/nodes/video.py:714-911] — `_compose_scene` being split
- [Source: src/yt_flow/pipeline/nodes/video.py:1258-1290] — composition loop, first-shot-only card lookup
- [Source: src/yt_flow/pipeline/nodes/subtitle.py:202-249] — `sentence_cues` window math to extract
- [Source: src/yt_flow/domain/state.py:69-93] — `ShotData.sentence_indices`, `SceneState.word_timings`

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- Full regression suite: `python -m pytest -q` → 1298 passed, 1 skipped.
- New/updated suites in isolation: `pytest tests/pipeline/nodes/test_subtitle.py tests/pipeline/nodes/test_shot_timing.py tests/pipeline/nodes/test_video.py tests/pipeline/nodes/test_video_harmonization.py -q` → all green (219 in the video files alone, incl. the new real-ffmpeg `test_per_shot_cut_assembly_integration`).
- Live re-render (AC:10): resumed real checkpoint `d55a265b-6f24-4159-b94f-bb30736142e8` (SCP-049, iteration-1 evidence run — 8 scenes / 87 shots) through `video_node` with the real `CharacterService.resolve_cast_cards` injected, output redirected to an isolated scratch `workspace_path` (never touched the original run's files — read-only against `yt_flow.db`/source images/audio). Result: `error=None`, log lines matched the required `scene N: K shots -> M clips (merged J)` format for all 8 scenes (13→10, 12→9, 9→7, 10→7, 11→6, 12→5, 12→4, 8→6; 87 shots → 54 clips, 33 merged), 67/87 shots got cast cards, `seg_001.mp4` duration 37.057s matched the checkpoint's `audio_duration` (37.057125s) exactly (no A/V desync), and per-shot clip durations were non-uniform (2.44s/4.24s/6.68s for the first three kept clips) confirming real sentence-timed cuts rather than equal division. Total `video.mp4` duration 237.87s, consistent with the story's own "87 shots / 238s" reference figure.

### Completion Notes List

- Extracted `sentence_windows()` out of `subtitle.py`'s `sentence_cues()` (Task 1) — `sentence_cues` now calls it, byte-identical behavior confirmed by the full existing subtitle test suite passing unchanged.
- New `shot_timing.py` (`plan_shot_clips`/`ShotClip`) derives each scene's per-shot clip plan from `sentence_windows()` + `ShotData.sentence_indices`: gap-attachment to the preceding shot, first/last-clip stretch to the full `audio_duration`, and a `min_shot_clip_sec` merge pass (first clip merges forward). Degrades to a single full-duration clip with a WARNING when no usable sentence windows exist (empty timings/narration) — AC:7.
- `video.py`'s `_compose_scene` now: builds the shot-clip plan, logs an INFO summary (`scene N: K shots -> M clips (merged J)`), and dispatches to one of two paths:
  - **Fast path** (plan has exactly 1 clip — the common single-shot-per-scene case, or everything merged down to one): renders through `_render_scene_fast`, a straight extraction of the pre-8.11 single-pass `_compose_scene` body (byte-identical ffmpeg args) — deliberate ponytail call: nothing to concat, so no two-pass overhead, and it kept ~all pre-existing single-shot-scene tests passing unchanged.
  - **Multi-clip path**: pass 1 renders each shot's own silent clip (`_compose_shot_clip`, no audio/subtitle/post-fx) into `shots/scene_NNN_SHOTID.mp4`; pass 2 (`_assemble_scene_from_clips`) concats them (hard cuts, no crossfade) and applies subtitle burn + narration audio + sound design + post-fx exactly once, at scene level.
  - The per-card overlay-chain construction (zoompan + N stacked cards + harmonization) is factored into a shared `_build_card_chain()` helper used by both the fast path and pass 1 — one implementation, so the two render paths can't drift (mirrors the story's "one sentence_windows()" principle for the composition side).
- `video_node`'s composition loop now resolves cast cards **per rendered shot** (`cards_by_shot: dict[shot_id, cards]`) instead of only the scene's first shot; Tier-3 relit-sprite substitution (Story 8.7) now runs per shot using each shot's own `location_key`.
- `_validate_scene_assets` now checks **every** image-bearing shot's file existence (not just the first) — a real behavior change from pre-8.11 (a later shot's missing image used to be silently ignored since it was never rendered; now every image-bearing shot gets its own clip, so it must exist). Updated the one existing test that encoded the old behavior (`test_validate_ignores_unused_later_shot_missing_image` → `test_validate_fails_on_later_shot_missing_image`).
- Added `Settings.min_shot_clip_sec` (`YTFLOW_MIN_SHOT_CLIP_SEC`, default 2.0, `0.0` disables merging).
- Test fallout from the `_compose_scene(cards=...)` → `cards_by_shot=...` signature change was minimal: only 3 direct call sites (2 in `test_video_harmonization.py`, 1 sound-design integration test in `test_video.py`) needed updating, plus both files' fake-`Settings` helpers needed the new `min_shot_clip_sec` field. Every other `video_node`-level test (the overwhelming majority) uses single-shot-per-scene fixtures and kept passing unchanged through the fast path — confirmed by grepping for multi-shot scene fixtures before making the change (found exactly one, the validate test above).
- New integration test `test_per_shot_cut_assembly_integration` (real ffmpeg): a 3-shot scene with distinct solid-color (red/green/blue) backgrounds renders 3 kept clips (no merge), and the assembled segment shows the correct color at each shot's window midpoint (1.0s/3.0s/5.0s) — a direct regression guard for the bug this story fixes.

### File List

- `src/yt_flow/pipeline/nodes/subtitle.py` (modified — extracted `sentence_windows()`)
- `src/yt_flow/pipeline/nodes/shot_timing.py` (new — `plan_shot_clips()`/`ShotClip`)
- `src/yt_flow/pipeline/nodes/video.py` (modified — `_validate_scene_assets` per-shot check, `_build_card_chain`/`_render_scene_fast`/`_compose_shot_clip`/`_assemble_scene_from_clips`/`_compose_scene` split, `video_node` per-shot `cards_by_shot` + per-shot Tier-3 relight)
- `src/yt_flow/config.py` (modified — `min_shot_clip_sec` field)
- `tests/pipeline/nodes/test_shot_timing.py` (new)
- `tests/pipeline/nodes/test_video.py` (modified — `_settings_ns` gains `min_shot_clip_sec`, `_compose_scene` call site updated to `cards_by_shot`, the unused-later-shot test rewritten for the new validation behavior, new `test_per_shot_cut_assembly_integration`)
- `tests/pipeline/nodes/test_video_harmonization.py` (modified — `_settings_ns` gains `min_shot_clip_sec`, 2 direct `_compose_scene` call sites updated to `cards_by_shot`)

## Change Log

- 2026-07-12: Story 8.11 implemented — per-shot cut assembly in `video_node` (shot-level subclips timed to narration sentences, replacing the frozen first-shot-for-the-whole-scene Ken Burns render). Fixes the iteration-1 bug where 87 generated shot backgrounds rendered as only 8 (one per scene).
- 2026-07-12: Code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor) — 9 patch findings fixed, 2 deferred (see Review Findings above / `deferred-work.md`). Full regression: `python -m pytest -q` → 1300 passed, 1 skipped. Closed done.
