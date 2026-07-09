---
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

Status: ready-for-dev

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

- [ ] Task 1: Extract `sentence_windows()` from `sentence_cues()` in `subtitle.py`; keep `sentence_cues` behavior byte-identical (AC:1, AC:7)
- [ ] Task 2: Shot-window derivation helper in `video.py` (or a small `shot_timing.py`): sentence_indices → merged, gap-attached, min-duration-filtered clip plan per scene (AC:1,2,3)
  - [ ] Unit tests for the clip plan (AC:9)
- [ ] Task 3: Split `_compose_scene` into `_compose_shot_clip` (pass 1: zoompan + cards + motion/parallax/harmonization, silent) and scene assembly (pass 2: concat + audio + subtitles + sound design + post-fx) (AC:4,5,6)
  - [ ] Move per-card chain construction (current lines ~770-855) into pass 1 unchanged in behavior
  - [ ] Wire per-shot resolver keys + per-shot alpha validation (AC:4)
- [ ] Task 4: `min_shot_clip_sec` Settings field + config wiring (AC:3)
- [ ] Task 5: Degrade paths + logging (AC:7) — WARNING for single-shot fallback, INFO summary `scene N: K shots → M clips (merged J)`
- [ ] Task 6: Integration test with solid-color shot fixtures (AC:9)
- [ ] Task 7: Live verification + Dev Agent Record evidence (AC:10)

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

### Debug Log References

### Completion Notes List

### File List
