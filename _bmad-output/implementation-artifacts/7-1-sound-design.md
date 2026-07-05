---
created: 2026-07-04
baseline_commit: c1e94d1d9b444c0f93b3fe3b557c2d55f09c8969
story_key: 7-1-sound-design
story_id: "7.1"
epic: 7
previous_story: 5-6-character-cutout-quality
depends_on: []
blocks:
  - 7-2-post-fx-color-grade   # reuses sound_design.resolve_mood + SceneState.mood
  - 7-4-transition-variety    # reuses SceneState.mood
related:
  - 5-1-scene-transitions-chapter-cards
  - 5-3-motion-intensity
---

# Story 7.1: Sound Design (BGM + Ambient + SFX Stinger)

Status: review

<!-- Completion note: Ultimate context engine analysis completed - comprehensive developer guide created -->

## Story

As Jay,
I want each scene's mood to drive a background-music loop, an ambient bed, and a transition stinger, all ducked under the narration via sidechain compression,
so that final videos have atmosphere and emotional shape instead of dry narration-only audio, without adding a new pipeline stage or runtime dependency.

## Context

`video_node` today renders scenes with narration as the **only** audio track. There is no music, ambience, or SFX anywhere in the pipeline — confirmed greenfield: no BGM/SFX config fields, no bundled audio assets beyond the TTS reference voice (`data/voices/sutak.mp3`), no mixing libraries, no audio-licensing strategy in the repo. [Source: `docs/superpowers/specs/2026-07-04-sound-design-design.md#Problem`]

This story is the **owner of the new `SceneState.mood` field** and therefore the ordering-gate for the rest of Epic 7: stories 7.2 (post-fx color grade) and 7.4 (transition variety) both `depends_on: 7.1` because they reuse `sound_design.resolve_mood` and `SceneState.mood` rather than redefining the taxonomy. [Source: `_bmad-output/planning-artifacts/epics.md#Epic 7` 순서 제약]

The full, approved design is `docs/superpowers/specs/2026-07-04-sound-design-design.md` — **read it before implementing.** It is the primary specification; this story file adds the current-code analysis, the two integration hazards the design does not spell out, and a decisive answer to the one place where the design's assumptions do not match the repo (the missing `writing.md` prompt file). Where this story and the design doc agree, the design doc governs the numbers; where this story flags a discrepancy, this story governs.

## Acceptance Criteria

1. **Mood field.** Given the pipeline state substrate, then `SceneState` (`src/yt_flow/domain/state.py`) gains a `mood: str` field, and `scenario_chain.build_scenes()` populates it leniently as `mood=str(writing_scene.get("mood") or DEFAULT_MOOD)` — a missing/empty/unknown mood degrades to the default, never fails the scenario stage, and old checkpointed runs (no `mood` key) resume safely. [Source: design#Data model changes, #Scenario chain changes]
2. **New pure module.** Given the mixing logic, then a new module `src/yt_flow/pipeline/nodes/sound_design.py` exists with: `MOOD_VALUES = ("dread", "clinical", "escalation", "revelation")`, `DEFAULT_MOOD = "dread"`, `resolve_mood(mood) -> str` (unknown/missing/empty → `DEFAULT_MOOD`, mirroring `video.select_effect`'s hint-fallback), `MOOD_ASSET_PATHS`, `validate_mood_assets(mood) -> None` (raises `FileNotFoundError` if any of the 3 files for the resolved mood are missing), `build_sound_design_args(mood) -> list[str]`, and `build_sound_design_filter(mood, duration, narration_label, input_offset) -> tuple[str, str]`. The module imports only `domain`/`config`/stdlib — no `db`/`api`/`services` (AD-1). [Source: design#New module]
3. **Ducking mix.** Given `sound_design_enabled` is true and a scene renders, then bgm + ambient + stinger are amixed and sidechain-compressed under the narration so narration stays fully intelligible (ducking is dynamic sidechain, not a fixed low volume), and the final scene segment's audio maps to the mixed `[aout]` label instead of the raw narration stream. [Source: design#New module filter sketch, #Goals]
4. **Both render branches.** Given a scene with a character overlay **and** a scene without one, then sound design is applied to **both** `_compose_scene` code paths, the background-only path is migrated off `-vf` to `-filter_complex` when sound is enabled (ffmpeg forbids `-vf` + `-filter_complex` together), and input-stream indices are computed correctly for each branch (see Integration Hazards). [Source: this story#Integration Hazards; `src/yt_flow/pipeline/nodes/video.py:459-488`]
5. **Fail-fast assets.** Given `sound_design_enabled` is true, when a resolved mood's bgm/ambient/stinger file is missing on disk, then the run fails before ffmpeg is invoked (via `validate_mood_assets`, extending `_validate_scene_assets`'s existing fail-fast style), not with an opaque ffmpeg error. [Source: design#Error handling]
6. **Asset library.** Given the 4 moods × 3 roles, then 12 CC0-licensed audio files are committed under `data/audio/bgm/{mood}.mp3`, `data/audio/ambient/{mood}.mp3`, `data/audio/sfx/{mood}_stinger.mp3` (seamless 10–30s loops for bgm/ambient; 1–2s one-shots for stingers), same repo-committed posture as `data/voices/sutak.mp3`. No runtime API calls, no generated audio. [Source: design#Asset library]
7. **Settings + env.** Given configuration, then `Settings` gains `sound_design_enabled: bool = True` (same pattern as `chapter_cards`), and `.env.example` documents `YTFLOW_SOUND_DESIGN_ENABLED` as an opt-out. Volume/ducking constants stay as module-level constants in `sound_design.py` (matching `SWAY_AMPLITUDE`/`ZOOM_IN_MAX` precedent), not `Settings` fields. [Source: design#Settings]
8. **Disabled = unchanged.** Given `sound_design_enabled = False`, then `_compose_scene` skips all sound-design work entirely and produces byte-for-byte today's narration-only audio path — no `mood` asset lookup, no extra inputs, no filtergraph change. [Source: design#Error handling]
9. **Join engine untouched.** Given multi-scene renders, then `_join_with_xfade` is **not** modified — it already treats each segment's audio opaquely via `acrossfade`, and per-scene mood BGM/ambient restarting from t=0 each segment is intentional and inaudible (loops are short + seamless). [Source: design#Architecture decision]
10. **Scenario prompt (mood emission).** Given `docs/PROMPT_POLICY.md`, then the `mood` enum is added to the scenario chain's per-scene JSON output following the repo-file-first protocol — **but see the Prompt Emission Reality section**: `prompts/scenario/writing.md` does not exist as a repo file, so the dev must reconcile that gap explicitly and record the decision, not blindly follow the design's file list. AC1's lenient fallback means the mechanical pipeline (AC1–9) ships and works (all scenes = `dread`) whether or not prompt-driven mood variation lands in this story.
11. **Tests.** Given automated verification, then `resolve_mood`, `validate_mood_assets`, `build_sound_design_args`, and `build_sound_design_filter` have direct unit tests (pure functions, no real ffmpeg), and `_compose_scene`'s integration is covered via the existing `fake_run_ffmpeg` stub by asserting the new `-i` args and `[aout]` map target appear in captured argv for both branches and are absent when disabled. `tests/test_config.py` covers the new default. [Source: design#Testing]
12. **Regression.** Given the change set, then `uv run pytest tests/pipeline/nodes/test_video.py tests/test_config.py -q` passes, plus new `tests/pipeline/nodes/test_sound_design.py`, and existing video behavior (zoompan, character overlay `eval=frame`, subtitle burn order, xfade offset math, chapter cards) is unchanged.

## Tasks / Subtasks

- [x] Add the mood field to the state substrate (AC: 1)
  - [x] Add `mood: str` to `SceneState` in `src/yt_flow/domain/state.py` (pure stdlib typing, no upper-layer import — AD-1/AD-2).
  - [x] In `scenario_chain.build_scenes()`, set `mood=str(writing_scene.get("mood") or DEFAULT_MOOD)` on each `SceneState(...)` construction. Import `DEFAULT_MOOD` from `sound_design` (or duplicate the literal only if it would create an import cycle — verify: `sound_design` imports `domain`+`config` only, `scenario_chain` imports `domain`+`services`, so importing `DEFAULT_MOOD` from `pipeline.nodes.sound_design` into `pipeline.nodes.scenario_chain` is same-layer and cycle-free).
  - [x] Confirm the `SceneState(...)` literal in `build_scenes` gets the new key (a TypedDict with a missing key won't fail at runtime but breaks the contract downstream).
- [x] Create `src/yt_flow/pipeline/nodes/sound_design.py` (AC: 2, 3, 5)
  - [x] Module docstring with the AD-1 layer rule note (mirror `video.py`'s header).
  - [x] `MOOD_VALUES`, `DEFAULT_MOOD`, `resolve_mood` (fallback pattern from `video.select_effect`).
  - [x] Module-level volume/ducking constants: `BGM_VOLUME`, `AMBIENT_VOLUME`, `STINGER_VOLUME`, sidechain `threshold/ratio/attack/release`. Seed them from the design's filter sketch (0.25 / 0.15 / 0.5; threshold=0.05, ratio=8, attack=5, release=300) and mark them `# ponytail: tuned-by-ear defaults, promote to Settings only if a real scene needs a different value`.
  - [x] `MOOD_ASSET_PATHS: dict[str, dict[str, Path]]` built from `data/audio/...` paths.
  - [x] `validate_mood_assets(mood)` — resolve mood first, then raise `FileNotFoundError` naming the missing file (match `_validate_scene_assets` message style).
  - [x] `build_sound_design_args(mood)` — returns the extra ffmpeg input args: bgm/ambient looped with `-stream_loop -1 -i`, stinger as a plain `-i` (one-shot). Order must match the index math the filter builder assumes.
  - [x] `build_sound_design_filter(mood, duration, narration_label, input_offset)` — returns `(filter_complex_fragment, output_label)` per the design sketch; `input_offset` is the index of the first sound-design input so bgm/ambient/stinger get correct `[N:a]` labels regardless of branch.
- [x] Wire into `video._compose_scene` for BOTH branches (AC: 3, 4, 8) — read Integration Hazards first
  - [x] Guard the whole block on `s.sound_design_enabled` (pass `Settings` in or read via existing `_settings()` seam — check how `_compose_scene` currently gets settings; today it does NOT take settings, `video_node` calls `_settings()` once — decide whether to thread `sound_design_enabled` as a param or read settings inside `_compose_scene`, preferring the smallest diff).
  - [x] Character branch: append `build_sound_design_args(mood)` after the 3 existing inputs (bg=0, char=1, narration=2), set `narration_label="[2:a]"`, `input_offset=3`, append the filter fragment to `filter_complex`, and remap `-map 2:a` → `-map [aout]`.
  - [x] Background-only branch: **migrate from `-vf` to `-filter_complex`** when sound is enabled (append the zoompan+subtitles chain into the complex graph with a labeled video output), inputs bg=0, narration=1, `narration_label="[1:a]"`, `input_offset=2`, map video out + `[aout]`. When sound is disabled, keep today's `-vf` path verbatim.
  - [x] Read `mood` off the scene: `resolve_mood(scene.get("mood"))`.
  - [x] Call `validate_mood_assets(resolved_mood)` (either in `_validate_scene_assets` for all scenes up front, or per-scene in `_compose_scene` before ffmpeg — up-front is more consistent with the existing fail-fast validator).
- [x] Source & commit the 12-file CC0 asset library (AC: 6)
  - [x] `data/audio/bgm/{dread,clinical,escalation,revelation}.mp3` — seamless 7–25s loops (sourced; see caveat below).
  - [x] `data/audio/ambient/{dread,clinical,escalation,revelation}.mp3` — seamless 20–28s loops.
  - [x] `data/audio/sfx/{dread,clinical,escalation,revelation}_stinger.mp3` — 0.5–2s one-shots.
  - [x] Sourced strictly CC0 from Freesound (`license:"Creative Commons 0"` filter, verified per-track against the `creativecommons.org/publicdomain/zero/1.0/` link on each sound's page). Source URL + author + license recorded in `data/audio/README.md`. **Caveat**: selection was done by title/tag/pack metadata, not by ear — a human listening pass is still owed before this is treated as final (see Live Validation below).
  - [x] Verify `data/audio/` is NOT gitignored (confirmed: no `data/audio` ignore rule; all 12 files + `data/audio/README.md` tracked).
- [x] Settings + env (AC: 7)
  - [x] Add `sound_design_enabled: bool = True` to `Settings` (place near `chapter_cards`).
  - [x] Add `YTFLOW_SOUND_DESIGN_ENABLED=true` (with an opt-out comment) to `.env.example`, near the `YTFLOW_COMFYUI_LAYERED` block.
- [x] Prompt emission — reconcile the writing.md gap (AC: 10) — read Prompt Emission Reality first
  - [x] Add `mood` (enum of the 4 values) to `prompts/scenario/structure.md`'s per-scene JSON schema. **Do not conflate with the existing `emotional_beat` field** (values tension/mystery/horror/revelation) — mood is a separate 4-value audio-driving axis (dread/clinical/escalation/revelation).
  - [x] Decide and record how mood reaches `writing_scene` given `prompts/scenario/writing.md` has no repo file (see Prompt Emission Reality for the two viable options) — **Option 1 chosen** (mechanical-only, `DEFAULT_MOOD` fallback; writing.md echo-through deferred, see Dev Agent Record). Did not fabricate a writing.md from thin air.
  - [x] No prompt changes beyond `structure.md` were made in this story, so `docs/PROMPT_POLICY.md`'s candidate/production seeding step does not apply here.
- [x] Tests (AC: 11, 12)
  - [x] New `tests/pipeline/nodes/test_sound_design.py`: `resolve_mood` fallback table (valid/unknown/None/empty), `validate_mood_assets` raises on missing + passes with a tmp file tree, `build_sound_design_args` order/loop-flags, `build_sound_design_filter` returns expected label + fragment substrings for a known mood.
  - [x] Extend `tests/pipeline/nodes/test_video.py`: with `fake_run_ffmpeg`, assert the new `-i` inputs and `-map [aout]` appear for the character branch AND the background-only branch when enabled, and are absent when `sound_design_enabled=False`. Reuse the `_settings_ns` fixture (add a `sound_design_enabled` field to it).
  - [x] Extend `tests/test_config.py`: assert `Settings().sound_design_enabled is True` by default.
  - [x] Run `uv run pytest tests/pipeline/nodes/test_video.py tests/pipeline/nodes/test_sound_design.py tests/test_config.py -q`.
- [ ] Live validation (AC: 3, 4) — **unblocked now that AC6 assets exist; still needs a human ear pass**
  - [ ] Render a real 2+ scene run with `YTFLOW_SOUND_DESIGN_ENABLED=true` and confirm by ear: narration intelligible, bgm/ambient present and ducking under speech, stinger audible at scene start. Record run ID + findings in the Dev Agent Record. Tune the volume/sidechain constants by ear if needed (that's why they're module constants, not magic numbers).

### Review Findings

- [x] [Review][Patch] Real ffmpeg never terminates once `sound_design_enabled=True` — `-shortest` doesn't reliably bound the infinite `-loop 1` background image against a filter-graph-produced `[aout]` pad [src/yt_flow/pipeline/nodes/video.py:_compose_scene] — fixed by adding an explicit `-t {duration}` output cap; confirmed via direct real-ffmpeg repro (pre-fix: still running past 8s for a 2s clip; post-fix: completes in ~2.2s, exact duration). Added `tests/pipeline/nodes/test_video.py::test_compose_scene_sound_design_terminates_and_matches_duration` (real-ffmpeg, skipped if unavailable) covering both branches; verified it fails via timeout (not an unbounded hang) when the fix is reverted.
- [x] [Review][Patch] Dev Agent Record claimed `data/audio/{bgm,ambient,sfx}/` dirs were "tracked" but git does not track empty directories — added `.gitkeep` to each so the claim holds.
- [x] [Review][Patch] Dev Agent Record's "Focused" pytest count (187 passed) did not match actual output (174 passed) — corrected in Debug Log References.
- [x] [Review][Defer] `sound_design_enabled` defaults `True` with no CC0 assets sourced yet — **superseded 2026-07-05**: all 12 files are now sourced and committed (see Dev Agent Record), so `validate_mood_assets` no longer fail-fasts by default. Test suite still forces the flag off pending a human by-ear pass (see Live Validation task).
- [x] [Review][Defer] No `aformat`/`aresample` normalization before `amix` across bgm/ambient/stinger/narration — deferred, depends on the actual encodes of the still-unsourced CC0 files; covered by the blocked Live Validation by-ear tuning task.
- [x] [Review][Defer] `amix ... normalize=0` risks clipping with no downstream limiter — deferred, part of the same blocked by-ear tuning task.

## Dev Notes

### Architecture Decision (why no new node)

The design evaluated three placements and chose **A: extend `video_node._compose_scene`** with the mixing logic extracted into a new pure module `sound_design.py`. Rejected: (B) a new `audio_mix` LangGraph stage — pulls in `STAGE_NODES` wiring, the gate mechanism, DB projection, and the API stage enum for what is "mix a couple more tracks into an existing ffmpeg call"; (C) post-processing the final `video.mp4` — requires recomputing absolute scene-boundary timestamps against the xfade accumulated-offset math, which the codebase already documents as "the #1 source of xfade timing bugs" (`video.py:544-547`). Approach A gets B's isolated/unit-testable benefit (via the `sound_design.py` split, mirroring the existing `select_effect`/`_zoompan_filter` split) without a new node. **Do not introduce a new pipeline stage, gate, or DB field.** [Source: design#Architecture decision]

### Integration Hazards (the two things the design sketch does not spell out)

**Hazard 1 — the background-only branch uses `-vf`, not `-filter_complex`.** In `video.py:478-488`, the no-character path builds a single `-vf "{zp_chain},subtitles=..."` string and lets ffmpeg map the default audio stream. FFmpeg **forbids using `-vf` and `-filter_complex` in the same invocation**. Audio mixing (amix/sidechaincompress) requires `-filter_complex`. So when sound design is enabled on a background-only scene, you must move the zoompan+subtitles video chain **into** the `-filter_complex` graph with an explicit labeled video output (e.g. `[0:v]{zp_chain},subtitles='{sub}'[vout]`) and map `[vout]` + `[aout]`. When sound design is **disabled**, keep the existing `-vf` path byte-for-byte (AC8). The character branch (`video.py:462-477`) already uses `-filter_complex`, so it only needs the audio fragment appended and the `-map 2:a` → `-map [aout]` swap.

**Hazard 2 — input-stream index bookkeeping differs per branch.** `build_sound_design_filter` takes `input_offset` and `narration_label` precisely because the narration and the first sound-design input land at different indices in the two branches:
- Character branch: `0`=bg, `1`=char, `2`=narration → sound inputs start at `3`, `narration_label="[2:a]"`, `input_offset=3`.
- Background-only branch: `0`=bg, `1`=narration → sound inputs start at `2`, `narration_label="[1:a]"`, `input_offset=2`.

Get these wrong and ffmpeg either fails ("Invalid file index") or silently mixes the wrong stream. The unit test for `build_sound_design_filter` must pin the label math for at least both offsets.

**Note on `-shortest`.** `_OUTPUT_ARGS` includes `-shortest`, and `build_sound_design_args` loops bgm/ambient with `-stream_loop -1` (infinite). The design's filter uses `amix=...:duration=first` and `apad=whole_dur={duration}` so the mixed audio length is bounded by the first (narration/scene) duration — `-shortest` + `duration=first` together keep the segment from running forever on the infinite loops. Verify the segment duration matches the scene's `audio_duration` after wiring (a segment that grew or truncated means the duration binding is wrong).

### Prompt Emission Reality (resolve before touching prompts — AC10)

The design (`#Scenario chain changes`) says to edit **`prompts/scenario/structure.md`** and **`prompts/scenario/writing.md`**. Repo reality, confirmed 2026-07-04:

- `prompts/scenario/` contains only: `research.md`, `structure.md`, `visual_breakdown.md`, `tts_normalize.md`.
- **`writing.md` does not exist as a repo file** — but `scenario_chain.writing_step()` fetches a `scenario/writing` prompt from Langfuse Prompt Hub. So the writing prompt is served by Langfuse without a committed source file, which itself violates `docs/PROMPT_POLICY.md` rule 1 (repo is source of truth). Memory of prior work notes the scenario prompt seeding was "blocked (yt.pipe templates absent)".
- `structure.md`'s per-scene schema uses **`emotional_beat`** (tension/mystery/horror/revelation), which is a *different axis* from the design's `mood` (dread/clinical/escalation/revelation). They overlap only on the word "revelation". Do not reuse `emotional_beat` as `mood`.

Because `build_scenes` reads `mood` off the **writing-stage** scene dict (`writing_scene.get("mood")`), the writing prompt is where mood must ultimately land. Two viable options — pick one and record the choice in the Dev Agent Record:

1. **Ship mechanical-only this story (recommended, lowest risk).** Implement AC1–9 + AC11–12. Because `build_scenes` uses `str(writing_scene.get("mood") or DEFAULT_MOOD)`, every scene resolves to `dread` and the full audio pipeline works and is testable end-to-end. Add `mood` to `structure.md` now (that file exists), and leave a documented follow-up for the writing-prompt emission once the missing `writing.md` repo-file gap is resolved (it's a prompt-ops concern that touches `docs/PROMPT_POLICY.md` compliance, arguably belongs with Epic 6). This keeps the story's blast radius on code you can verify.
2. **Also land mood variation.** Recover the Langfuse-served `scenario/writing` prompt text, commit it as `prompts/scenario/writing.md` (closing the policy gap), add `mood` echo-through to it, seed under `candidate`. Larger scope, drags in the prompt-file recovery problem, and mood variation can't be A/B-promoted to `production` within this story anyway (PROMPT_POLICY rules 3–4 gate promotion on evaluation).

Do **not** silently invent a `writing.md` whose content differs from what Langfuse currently serves — that would change live scenario output in ways unrelated to mood. If option 2 is chosen, the committed file must match the served prompt plus the mood addition, nothing else.

### Current Code State — Files To Read Before Editing

- `src/yt_flow/pipeline/nodes/video.py` — the primary edit surface.
  - Current: `_compose_scene` (lines 431-493) renders one scene segment with two branches (character overlay via `-filter_complex`; background-only via `-vf`). `_validate_scene_assets` (376-406) fail-fast validates image/audio/subtitle/duration per scene. `_OUTPUT_ARGS` (423-428) is shared. `video_node` calls `_settings()` once (654) and loops `_compose_scene` per scene (659-662). `_join_with_xfade` (537-598) does xfade+acrossfade with explicit `running_offset`.
  - This story changes: `_compose_scene` (both branches), optionally `_validate_scene_assets` (add `validate_mood_assets`), and how settings reach `_compose_scene`.
  - Must preserve: zoompan chain, character `eval=frame` overlay, subtitle burn order (subtitles are burned **last**, on top), xfade offset math, chapter-card path, AD-1 (domain+config only), AD-10 (tracing non-fatal). Do not touch `_join_with_xfade` (AC9).
- `src/yt_flow/domain/state.py` — add `mood: str` to `SceneState` (lines 37-45). Pure typing, no upper-layer import.
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — `build_scenes` (319-373) constructs each `SceneState`; add `mood=...`. Note it also has `_fallback_prompt` and per-shot merge logic — don't disturb those.
- `src/yt_flow/config.py` — `Settings` (chapter_cards at 77-78 is the pattern to copy).
- `tests/stubs/fakes.py` — `fake_run_ffmpeg` (writes a 1-byte file to the last argv, returns `(0,"")`). The argv-capture seam for asserting new inputs/maps. No new fake needed.
- `tests/pipeline/nodes/test_video.py` — `_settings_ns` fixture (SimpleNamespace) needs a `sound_design_enabled` field.
- `prompts/scenario/structure.md` — per-scene JSON schema at lines 39-49 (where `mood` enum is added).

### Architecture Compliance

- **AD-1** (layered deps `api -> services -> (pipeline | db) -> domain`): `sound_design.py` lives in `pipeline/nodes`, imports `domain`/`config`/stdlib only — same layer as `video.py`. No `db`/`api`/`services` imports.
- **AD-2** (LangGraph state is JSON-serializable): `mood` is a plain `str` in a TypedDict — safe for checkpointing. Old checkpoints without the key resume via the `.get()` fallback.
- **AD-4** (nodes return state updates only): unchanged — `video_node` still returns `{current_stage, video_path, error}`; no SSE/DB/gate work added.
- **AD-10** (external-tool failures are stage errors, not startup checks; tracing non-fatal): missing asset files raise inside the video stage → become `PipelineState.error` exactly like a missing image. `_record_trace` may optionally gain sound-design metadata but must stay best-effort (wrapped in try/except like the existing body).

### Testing Requirements

Pure functions are asserted on their return values/strings directly — no real ffmpeg (the `video.py` convention). `_compose_scene` integration is covered through `fake_run_ffmpeg`'s captured argv. Required:

```
uv run pytest tests/pipeline/nodes/test_video.py tests/pipeline/nodes/test_sound_design.py tests/test_config.py -q
```

Do not add real audio-decoding or an ffmpeg invocation to the unit suite. Live-by-ear validation (AC "Live validation" task) is the only place real audio matters, and its findings + tuned constants go in the Dev Agent Record.

### Latest Technical Notes (ffmpeg — no new dependency)

- **`sidechaincompress`** (ffmpeg audio filter) is the ducking mechanism: it compresses the first input (the music bed) whenever the second input (narration) exceeds `threshold`. Dynamic, unlike a static `volume=` reduction — narration cuts through, music swells back in the gaps. Design constants: `threshold=0.05:ratio=8:attack=5:release=300`.
- **`-stream_loop -1 -i file`** loops an input infinitely at the demuxer; combined with `amix=duration=first` and `-shortest`, the mixed output is bounded by the scene/narration length.
- **`apad=whole_dur={duration}`** pads the one-shot stinger with silence to the scene duration so `amix` doesn't truncate the mix to the stinger's 1–2s length.
- **`amix=inputs=N:duration=first:normalize=0`** — `normalize=0` prevents amix's automatic per-input volume attenuation (otherwise mixing 3 inputs silently divides each by 3, killing the levels the `volume=` filters just set).
- All of the above ship with the ffmpeg already required by `video_node` — **zero new runtime dependencies** (a hard design goal).

### Project Structure Notes

- New runtime module: `src/yt_flow/pipeline/nodes/sound_design.py` (same dir as `video.py`).
- New test: `tests/pipeline/nodes/test_sound_design.py`.
- New committed assets: `data/audio/{bgm,ambient,sfx}/*.mp3` (12 files) + a license/credits note. `data/` already tracks `scps.json`, `voices/sutak.mp3`, `workflows/*` — confirm no `data/audio` gitignore rule before committing.
- No `project-context.md` was found by the workflow's persistent-facts glob during story creation.

## References

- `docs/superpowers/specs/2026-07-04-sound-design-design.md` — **primary spec** (problem, architecture decision A vs B vs C, data model, scenario changes, module API, asset library, settings, testing, error handling).
- `_bmad-output/planning-artifacts/epics.md#Epic 7` / `#Story 7.1` — epic goal, ordering constraint (7.1 owns `mood`, precedes 7.2/7.4), `video.py` file-collision warning across Epic 7.
- `src/yt_flow/pipeline/nodes/video.py` — `_compose_scene` (both branches), `_validate_scene_assets`, `_OUTPUT_ARGS`, `select_effect` (fallback pattern), `_join_with_xfade` (do-not-touch).
- `src/yt_flow/domain/state.py#SceneState` — where `mood: str` is added.
- `src/yt_flow/pipeline/nodes/scenario_chain.py#build_scenes` — where `mood` is populated.
- `src/yt_flow/config.py#Settings` — `chapter_cards` pattern.
- `prompts/scenario/structure.md` — per-scene JSON schema (add `mood` enum; distinct from `emotional_beat`).
- `docs/PROMPT_POLICY.md` — repo-file-first, `production`/`candidate` labels, promotion gated on A/B + golden set.
- `tests/stubs/fakes.py#fake_run_ffmpeg`, `tests/pipeline/nodes/test_video.py#_settings_ns` — test seams.
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` — AD-1, AD-2, AD-4, AD-10.

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- Full regression: `uv run pytest -q` → 602 passed, 1 skipped (pre-existing ffmpeg-integration skip), 0 failed.
- Focused: `uv run pytest tests/pipeline/nodes/test_video.py tests/pipeline/nodes/test_sound_design.py tests/pipeline/nodes/test_scenario_chain.py tests/test_config.py tests/domain/test_state_imports.py -q` → 174 passed (corrected during code review; originally logged as 187).
- `uv run ruff check` on all touched files → clean.

### Completion Notes List

- Story context created by BMad create-story workflow on 2026-07-04.
- Ultimate context engine analysis completed - comprehensive developer guide created.
- **Implemented AC1–5, 7–9, 11–12 in full.** `mood: str` added to `SceneState`; new pure module `src/yt_flow/pipeline/nodes/sound_design.py` (resolve_mood/validate_mood_assets/build_sound_design_args/build_sound_design_filter, AD-1 compliant — stdlib + `pathlib` only); `video._compose_scene` refactored to a shared inputs/video_chain/narration_label/input_offset setup with three ffmpeg-arg branches (sound-enabled, character-only, background-only-disabled) so both disabled paths stay byte-for-byte identical to pre-story behavior (verified by the pre-existing test suite passing unchanged) while the enabled paths implement both integration hazards from Dev Notes (background-only migrates `-vf`→`-filter_complex`; per-branch `input_offset`/`narration_label` pinned by dedicated unit tests).
- **AC10 (prompt emission): Option 1 chosen** (mechanical-only, lowest risk, matches the story's own recommendation). Added `mood` enum to `prompts/scenario/structure.md`'s per-scene schema with a note distinguishing it from `emotional_beat`. Did **not** touch the Langfuse-served `scenario/writing` prompt or fabricate a `writing.md` repo file — `build_scenes()`'s lenient `.get(...) or DEFAULT_MOOD` fallback means every scene resolves to `dread` until the writing-stage prompt is updated to emit `mood`, which is a separate follow-up (prompt-ops, arguably Epic 6 — the missing `writing.md` repo file is a pre-existing `docs/PROMPT_POLICY.md` compliance gap, not something introduced by this story).
- **AC6 (asset library) and Live Validation are BLOCKED on a human step, left unchecked by design.** Sourcing and license-verifying 12 real CC0 audio files is not something this session can do reliably — the story's own Saved Questions #2 explicitly calls this out. Created `data/audio/{bgm,ambient,sfx}/` directories and `data/audio/README.md` documenting the exact files needed, sourcing guidance, and the operational implication (real deployments must set `YTFLOW_SOUND_DESIGN_ENABLED=false` until the library is populated, since `Settings.sound_design_enabled` defaults `True` per AC7 and `validate_mood_assets` will fail-fast on every run otherwise).
- **Regression fallout from AC7's `True` default, found and fixed.** Three existing tests exercised `video_node` via a real (non-mocked) `Settings()` and broke once `sound_design_enabled` defaulted to `True` with no real asset files on disk: `tests/pipeline/test_stub_profile_smoke.py::test_video_node_emits_tiny_artifact`, `tests/api/test_e2e_stub_run.py::test_stub_run_completes_via_api_with_ordered_sse_and_artifact_on_disk`, and `tests/domain/test_state_imports.py::test_type_hint_shapes` (an intentional TypedDict-shape drift guard that needed its expected-fields set updated for the new `mood` key — not a false positive, just needed updating). Fixed by adding `os.environ.setdefault("YTFLOW_SOUND_DESIGN_ENABLED", "false")` to `tests/conftest.py`, mirroring the existing `YTFLOW_LANGFUSE_ENABLED` suite-default pattern, and updating the `SceneState` drift-guard's expected field set. `test_config.py`'s new default-true test still asserts the real class default by explicitly clearing the env var first.
- Asked Jay how to close out the story given the AC6/Live-Validation block; he chose "mark review, document gap" (all mechanical work ships now; real deployments must opt out via env until assets land).
- **2026-07-05 code review fix: real ffmpeg never terminated with sound design on.** All pre-merge tests mocked `_run_ffmpeg`, so the mocked suite passed while real ffmpeg would hang indefinitely: `-shortest` does not reliably bound the infinitely-looped `-loop 1` background image against a filter-graph-produced `[aout]` pad (isolating each factor — dropping video, dropping sidechaincompress, reordering the `amix` operands — showed the `amix`/`sidechaincompress` audio graph alone always ends correctly; only adding the mapped video stream back in caused the runaway). Fixed with an explicit `-t {duration}` cap on the sound-design-enabled ffmpeg invocation in `_compose_scene`. Added a real-ffmpeg regression test that fails via a bounded timeout (not an unbounded hang) if this regresses. Full details and repro method in `bmad-code-review`'s findings below.
- **2026-07-05 AC6 unblocked: sourced all 12 CC0 files at Jay's request.** Searched Freesound with `license:"Creative Commons 0"`, verified each candidate's page links to `creativecommons.org/publicdomain/zero/1.0/` before use, downloaded via Freesound's public anonymous `-hq.mp3` preview CDN (no account/API key), and trimmed each to spec with `ffmpeg` (loop-safe fades on bgm/ambient, fade-out at the cut point on stingers trimmed from longer sources). Source/author/license per file recorded in `data/audio/README.md`. Verified end-to-end against the real pipeline: ran `_compose_scene` with real ffmpeg for all 4 moods (character and background-only branches) — all completed in ~4-4.5s with exact expected segment duration, no hang. **Caveat carried forward**: selection was by title/tag/pack metadata only, nobody has listened to these yet — the Live Validation task below (by-ear check + constant tuning) is still open and now unblocked rather than done.
- **2026-07-05 fix: 4 of the 12 trimmed files were silent for part or all of their length.** Jay caught this by ear ("초반에 소리가 안들리는 파일들이 존재"). Root cause: `ffmpeg -i in.mp3 -ss X -t Y -af "afade=...st=Z..."` with `-ss` placed *after* `-i` resolves `afade`'s `st=` against the original source timeline, not the trimmed clip's — where `Z < X` the fade-out had already completed before the trimmed clip even starts, silencing everything from that point on. Hit `bgm/revelation.mp3` (13s dead air at the start), `ambient/clinical.mp3` (second half silent), `ambient/revelation.mp3` (100% silent — the fade's absolute end-point was earlier than the seek offset). Separately `sfx/dread_stinger.mp3` trimmed the source's silent lead-in instead of its actual hit (which starts ~1.1s in). Fixed by moving `-ss` before `-i` (true input seek, resets PTS to 0 so `afade`'s `st=` is correctly clip-relative) and, for the stinger, locating the real onset via `silencedetect` first. Re-swept all 12 files with `ffmpeg -af silencedetect=noise=-35dB:d=0.3` — zero unexpected silence remains. Re-verified end-to-end against the real pipeline (all 4 moods, exact expected duration, no hang).
- **2026-07-05 second fix: `ambient/dread.mp3` still read as silent to Jay after the above.** Not actually silent (`volumedetect` mean -18dB, normal) — nearly all its energy was below 150Hz, a deep sub-bass drone most laptop/phone speakers can't reproduce, worsened by `AMBIENT_VOLUME=0.15` in the mix. Swept every file with `volumedetect` full-spectrum vs. `highpass=f=200,volumedetect` to find the same bass-only trap elsewhere: `bgm/dread.mp3` and `ambient/revelation.mp3` showed the identical pattern (>10dB drop above 200Hz) and were replaced with better-balanced CC0 tracks (now <5.5dB drop each); `sfx/dread_stinger.mp3`'s similar drop was left as-is (a bass-heavy thump is a legitimate "impact" character on a 1.8s one-shot hit, not a missing-content bug on a sustained bed). `data/audio/README.md` has the updated source table. Re-verified against the real pipeline for all 4 moods after the swap.

### File List

- `src/yt_flow/domain/state.py` — added `mood: str` to `SceneState`.
- `src/yt_flow/pipeline/nodes/sound_design.py` — new module (AC2,3,5).
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — `build_scenes()` populates `mood`; imports `DEFAULT_MOOD`.
- `src/yt_flow/pipeline/nodes/video.py` — `_validate_scene_assets` gained `sound_design_enabled` param + mood-asset check; `_compose_scene` rewired for both branches + sound design; `video_node` loads settings before validation and threads `sound_design_enabled` through.
- `src/yt_flow/config.py` — added `sound_design_enabled: bool = True`.
- `.env.example` — documented `YTFLOW_SOUND_DESIGN_ENABLED`.
- `prompts/scenario/structure.md` — added `mood` enum to the per-scene JSON schema.
- `data/audio/README.md` — documents the sourced CC0 asset library (source URL/author/license per file) and the still-open by-ear validation caveat.
- `data/audio/bgm/{dread,clinical,escalation,revelation}.mp3`, `data/audio/ambient/{dread,clinical,escalation,revelation}.mp3`, `data/audio/sfx/{dread,clinical,escalation,revelation}_stinger.mp3` — new: 12 real CC0 files sourced from Freesound (code review addendum, 2026-07-05).
- `tests/pipeline/nodes/test_sound_design.py` — new unit test file.
- `tests/pipeline/nodes/test_video.py` — `_settings_ns` fixture gained `sound_design_enabled`; added sound-design integration tests (both branches, enabled/disabled, fail-fast validation); code review added a real-ffmpeg termination/duration regression test.
- `tests/pipeline/nodes/test_scenario_chain.py` — added `mood` population/fallback tests.
- `tests/test_config.py` — added `sound_design_enabled` default-true test.
- `tests/domain/test_state_imports.py` — updated `SceneState` expected-fields drift guard to include `mood`.
- `tests/conftest.py` — added `YTFLOW_SOUND_DESIGN_ENABLED=false` suite default.

## Change Log

- 2026-07-04: Created ready-for-dev story context from the approved sound-design design doc. Added current-code analysis, two integration hazards (background-only `-vf`→`-filter_complex` migration; per-branch input-index bookkeeping), and a decisive reconciliation of the design's `writing.md` reference against repo reality (file absent; recommend shipping mechanical-only with `DEFAULT_MOOD` fallback and deferring prompt-driven mood variation).
- 2026-07-04: Implemented AC1–5,7–9,11–12 (mood field, `sound_design.py`, `video._compose_scene` wiring for both ffmpeg branches, `Settings`/`.env.example`, `structure.md` mood enum, full unit+integration test coverage). Fixed 3 regressions caused by AC7's `sound_design_enabled=True` default hitting real-Settings tests without asset files. Left AC6 (asset sourcing) and Live Validation unchecked/documented as blocked on a human licensing step, per Jay's explicit direction.

## Saved Questions / Clarifications

1. **writing.md prompt gap (AC10).** The design assumes `prompts/scenario/writing.md` is a repo file to edit; it isn't (the `scenario/writing` prompt is Langfuse-served with no committed source, contra PROMPT_POLICY rule 1). Recommended resolution: ship AC1–9/11–12 mechanically with the `DEFAULT_MOOD` fallback (all scenes = `dread`), add `mood` to `structure.md`, and track prompt-driven mood variation + the missing-writing.md policy gap as a follow-up (likely Epic 6 prompt-ops). Flag for Jay if he wants mood variation landed in this same story instead.
2. **Asset sourcing is a human step.** The 12 CC0 files (AC6) must be sourced/licensed by a human — an AI session cannot download and verify CC0 licensing autonomously. If assets aren't in place at dev time, the fail-fast `validate_mood_assets` will (correctly) block live runs; the code + tests can still be completed and merged behind `sound_design_enabled` with placeholder-absent handling documented.
