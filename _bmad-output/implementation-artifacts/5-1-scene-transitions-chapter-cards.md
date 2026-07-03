---
baseline_commit: 8946828f9a1646d0055f1586cd1445d80b7d95e1
---

# Story 5.1: Scene Transitions — Fadeblack + Chapter Cards

Status: in-progress

Completion note: Ultimate context engine analysis completed - comprehensive developer guide created.

## Story

As Jay,
I want scene-to-scene transitions to cut to black, optionally through a chapter title card, instead of cross-fading two scene images over each other,
so that scene boundaries read as intentional chapter breaks rather than accidental visual overlaps.

## Context

This story comes from the first practical render review on 2026-07-03 for run `eb522cf9` / SCP-096. The current Story 1.9b join uses `xfade=transition=fade`, which makes adjacent scene images visible together during the transition. The desired behavior is either:

- No chapter cards: scene A fades through black into scene B with no visible image overlap.
- Chapter cards enabled by default: insert a short black title-card segment between scene A and scene B, with centered scene label text and clean fade-in/fade-out behavior.

Epic 5 is a quality-improvement epic; this story should be implemented as a focused `video_node` join-stage change. Do not alter scenario, image, TTS, subtitle, gates, DB, API, or frontend behavior unless tests expose a direct integration need.

## Acceptance Criteria

1. Given two or more rendered scene segments, when `video_node` performs the final join, then scene boundaries no longer use a plain image-over-image crossfade; the default non-card transition uses FFmpeg `xfade=transition=fadeblack`, so no frame shows both scene images blended together.
2. Given chapter-card mode is enabled with `YTFLOW_CHAPTER_CARDS=true` (default `true`), when scene `N` transitions to scene `N+1`, then a 1.5-2.0 second black card segment is inserted between them with centered label text rendered via `drawtext`.
3. Given a card label is needed, then use a scene title from pipeline state only if a real `SceneState` title field already exists; otherwise use a deterministic fallback label for the upcoming scene: `- N -`. Do not add a title field to `SceneState` in this story.
4. Given `YTFLOW_CHAPTER_CARDS=false`, when `video_node` joins multiple scenes, then no card segment is generated and the join uses `fadeblack` only.
5. Given chapter cards are inserted, then A/V sync stays correct: output duration is approximately `sum(scene_durations) + sum(card_durations) - sum(transition_overlaps)`. Existing `running_offset` / `acrossfade` logic must be adapted rather than replaced with a naive concat.
6. Given a single-scene run, when `video_node` completes, then behavior remains unchanged: no transition, no card segment, and the only scene segment is moved/replaced to `video.mp4`.
7. Given `video_node` records Langfuse metadata, then transition metadata reflects the actual behavior: `transition="fadeblack"`, `transition_duration`, `chapter_cards_enabled`, and card duration/count when applicable. Tracing remains non-fatal.

## Tasks / Subtasks

- [ ] Add settings for chapter cards. (AC: 2, 4)
  - [ ] Add `chapter_cards: bool = True` to `src/yt_flow/config.py` using the existing `YTFLOW_` env prefix.
  - [ ] Add `chapter_card_duration_sec: float = 1.75` unless a simpler module constant is clearly better; keep the accepted range 1.5-2.0 seconds.
  - [ ] Do not introduce per-run DB/API configuration for this story.
- [ ] Change transition semantics in `src/yt_flow/pipeline/nodes/video.py`. (AC: 1, 4, 7)
  - [ ] Change `XFADE_TRANSITION` from `"fade"` to `"fadeblack"`.
  - [ ] Keep `XFADE_DURATION = 0.5` unless a failing live render proves it needs tuning.
  - [ ] Update `_record_trace()` metadata to include chapter-card state and card duration/count.
- [ ] Implement chapter-card segment creation. (AC: 2, 3, 5)
  - [ ] Add a small helper in `video.py`, for example `_compose_chapter_card(scene: SceneState, index: int, out_dir: Path, duration: float) -> Path`.
  - [ ] Generate a black video source with FFmpeg `color`, centered text with `drawtext`, and a silent audio stream with `anullsrc` so each card has both video and audio streams.
  - [ ] Match existing composition invariants: `COMP_W x COMP_H`, `FPS`, H.264/AAC output, `yuv420p`, and an audio stream compatible with `_join_with_xfade`.
  - [ ] Apply video `fade` in/out inside the card segment or use surrounding `fadeblack` joins; keep visual boundaries clean and deterministic.
  - [ ] Escape/quote card text and font paths safely. Prefer `textfile=` with a temporary UTF-8 text file if direct `drawtext=text=...` escaping becomes fragile.
- [ ] Adapt join input construction without rewriting the whole join engine. (AC: 5, 6)
  - [ ] Keep `_compose_scene()` unchanged except where required for integration.
  - [ ] For multi-scene card mode, build an interleaved segment list: `scene1, card2, scene2, card3, scene3, ...`.
  - [ ] Pass the interleaved list into `_join_with_xfade()` with each card duration included in the duration list.
  - [ ] Preserve the existing single-scene fast path: `segs[0].replace(output)`.
- [ ] Update and extend tests in `tests/pipeline/nodes/test_video.py`. (AC: 1-7)
  - [ ] Update xfade expectations from `transition=fade` to `transition=fadeblack`.
  - [ ] Add chapter-card enabled test that monkeypatches `_run_ffmpeg`, captures card-render and join calls, and verifies a 3-scene run produces 3 scene segments + 2 card segments.
  - [ ] Add chapter-card disabled test with fake settings and verify no card render call occurs while `fadeblack` remains in the join filtergraph.
  - [ ] Add single-scene regression test verifying no card segment and no join call.
  - [ ] Add trace metadata test for `chapter_cards_enabled`, card count, duration, and `transition`.
  - [ ] Add one skippable live FFmpeg integration test for card generation if it stays fast; use `color` and a known font, not real pipeline assets.
- [ ] Manual/live validation after automated tests pass. (AC: 1, 2, 5)
  - [ ] Retry only the `video` stage for a completed run such as `eb522cf9`.
  - [ ] Extract boundary frames around at least two scene transitions and verify there is no image-over-image overlap.
  - [ ] Check final video duration with `ffprobe` against expected duration tolerance.

## Dev Notes

### Source Documents And Discovery

- Loaded sprint status from `_bmad-output/implementation-artifacts/sprint-status.yaml`; `epic-5` and `5-1-scene-transitions-chapter-cards` were `backlog` before this story was created.
- Loaded epic context from `_bmad-output/planning-artifacts/epics.md`; Epic 5 is the video-quality follow-up from the 2026-07-03 render review, with recommended order `5.1 -> 5.2 -> 5.3 -> 5.4 -> 5.5`.
- Loaded architecture from `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`; relevant rules are AD-1, AD-2, AD-4, AD-10, and the `PipelineState`/`SceneState` contract.
- Loaded PRD from `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md`; relevant base requirement is FR-6, compose image/audio/subtitle assets into final video via FFmpeg.
- No `project-context.md` file was found under the project root despite the skill persistent-fact glob.

### Existing Code State To Preserve

- `src/yt_flow/pipeline/nodes/video.py` currently owns the full FFmpeg composition stage. It renders per-scene segments with `_compose_scene()`, then joins two or more segments with `_join_with_xfade()`.
- `_compose_scene()` handles two paths:
  - background-only: `zoompan` + burned subtitles via `-vf`.
  - layered character: background `zoompan`, character scaling, `overlay=...:eval=frame`, then subtitles via `-filter_complex`.
- `_join_with_xfade()` is the key update target. It builds pairwise video `xfade` and audio `acrossfade` filters with cumulative offsets. Preserve this accumulator pattern; it exists because `xfade` offsets are relative to the combined prior output.
- `video_node()` sorts scenes by `scene_num`, validates assets before FFmpeg, optionally applies the Story 1.13 angle selector, renders scene segments under `workspace/{run_id}/`, and returns `{"current_stage": "video", "video_path": ..., "error": None}`.
- `_record_trace()` currently records `transition`, `transition_duration`, `effects`, `upscale_pass`, character-motion metadata, and optional angle-selection metadata. Extend it; do not make tracing a hard dependency.
- `src/yt_flow/config.py` already uses Pydantic `BaseSettings` with env prefix `YTFLOW_`; adding `chapter_cards` here makes `YTFLOW_CHAPTER_CARDS=false` work naturally.
- `src/yt_flow/domain/state.py` has no `SceneState.title` field. AC3 explicitly says to check for a title field if it exists, but current implementation should fall back to `- N -`.

### Architecture Compliance

- Keep `video.py` inside the pipeline layer. It may import `domain`, `config`, and observability helpers, but must not import `db`, `api`, or `services`.
- Pipeline nodes remain pure functions of `PipelineState` from the system boundary perspective: no DB writes, no SSE fan-out, no service calls except the already-injected angle selector seam.
- `PipelineState` remains the single source of truth; do not add a scenes/artifacts table or persist chapter-card paths in DB.
- Runtime artifacts stay under `workspace/{run_id}/`.
- Failure contract must remain: on FFmpeg or validation error, return `current_stage="video"` and an error string containing `stage=video run_id=<id>`, with no `video_path`.

### FFmpeg Implementation Guidance

- Local runtime check: `ffmpeg version 6.1.1-3ubuntu5` is installed and compiled with `--enable-libfreetype`, `--enable-libfontconfig`, `--enable-libfribidi`, `--enable-libx264`, and AAC support. This supports `drawtext`, Korean-capable font fallback, `xfade`, `color`, `anullsrc`, `fade`, and existing subtitles usage.
- Local `ffmpeg -h filter=xfade` lists `fadeblack` as transition value 12, so this project runtime supports the desired no-image-overlap transition.
- Official FFmpeg filter docs confirm:
  - `xfade` cross-fades one video with another and accepts `transition`, `duration`, and `offset`.
  - `drawtext` draws text onto video and requires libfreetype; font fallback needs fontconfig, and text shaping needs fribidi.
  - `color` provides a uniformly colored video source.
  - `fade` supports video fade in/out with black as the default color.
  - `anullsrc` is the built-in null audio source.
- Suggested card generation shape:

```text
ffmpeg -y
  -f lavfi -i color=c=black:s=1920x1080:r=25:d=<card_duration>
  -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100
  -filter_complex "[0:v]drawtext=fontfile=<font>:textfile=<label_file>:fontcolor=white:fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2,fade=t=in:st=0:d=0.25,fade=t=out:st=<duration-0.25>:d=0.25[v]"
  -map "[v]" -map "1:a" -t <card_duration>
  -c:v libx264 -preset fast -c:a aac -b:a 128k -pix_fmt yuv420p
  card_002.mp4
```

- Prefer the `textfile=` form for Korean labels and escaping. If direct `text=` is used, add tests for colon, apostrophe, comma, bracket, and Korean text.
- Font guidance: `fc-match 'Noto Sans CJK KR'` returns `NotoSansCJK-Regular.ttc` locally. A robust helper can try Noto Sans CJK first, then DejaVu Sans; do not hardcode a machine-specific absolute path unless obtained through `fc-match` or a stable OS package path.

### Regression Traps

- Do not remove Ken Burns or character idle motion. This story changes scene joins and optional interstitial cards only.
- Do not silently drop the audio stream from card segments; `_join_with_xfade()` expects every segment to have video and audio.
- Do not use concat without accounting for `XFADE_DURATION`; that will change the output duration contract and can desync audio/video.
- Do not validate or fail on unused later shots beyond current `_validate_scene_assets()` behavior; that was intentionally fixed in Story 1.9b.
- Do not add per-shot timing or multi-shot rendering. The inherited limitation that only the first image-bearing shot per scene renders is explicitly deferred from Story 1.9b/1.9c.
- Do not solve the deferred audio-duration-vs-real-duration drift here unless an AC cannot pass without it. This story can continue using declared `audio_duration` and a card duration constant.
- Do not add a `SceneState.title` field only for cards; that would ripple through scenario/artifact contracts and is not required by AC3.

### Testing Requirements

- Primary command: `uv run pytest tests/pipeline/nodes/test_video.py`.
- Also run the full suite if the join helper signature or config loading changes broadly: `uv run pytest`.
- If coverage gates are active, preserve current coverage. The project coverage config targets 80% package-level coverage.
- Existing tests monkeypatch `_run_ffmpeg`, `_settings`, and `_record_trace`; follow those seams instead of invoking real FFmpeg in unit tests.
- Keep at least one real-FFmpeg integration test skippable with `shutil.which("ffmpeg")`.

### Previous Work Intelligence

- Story 1.9b introduced the exact code being changed: `XFADE_TRANSITION = "fade"`, `XFADE_DURATION = 0.5`, `_join_with_xfade()`, and transition trace metadata.
- Story 1.9b review fixed important edge cases: subtitle path escaping, explicit zero-scene failure, validation only for the rendered shot, duplicate join branch removal, `Path.replace`, normalized camera movement hints, and the xfade offset docstring.
- Story 1.9c added layered character overlay and explicitly warns not to break `overlay=...:eval=frame` or the background-only fallback path.
- Recent commits touching this area include Story 1.13 angle-selector wiring; `video_node` now mutates selected `character_path` through the injected selector before segment rendering. Chapter-card work must leave that behavior intact.

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 5 and Story 5.1 quality-review context.
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` — AD-1, AD-2, AD-4, AD-10, structural seed, state contracts.
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md` — FR-6 video composition, observability, performance and local execution requirements.
- `_bmad-output/implementation-artifacts/1-9b-video-effects-kenburns-transitions.md` — existing Ken Burns + xfade implementation and review learnings.
- `_bmad-output/implementation-artifacts/1-9c-video-character-idle-motion.md` — current layered character overlay behavior to preserve.
- `src/yt_flow/pipeline/nodes/video.py` — UPDATE target.
- `tests/pipeline/nodes/test_video.py` — UPDATE target.
- `src/yt_flow/config.py` — UPDATE target for `YTFLOW_CHAPTER_CARDS`.
- Official FFmpeg filters documentation: https://ffmpeg.org/ffmpeg-filters.html

## Dev Agent Record

### Agent Model Used

TBD by dev-story agent.

### Debug Log References

### Completion Notes List

### File List

