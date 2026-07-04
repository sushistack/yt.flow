# Sound Design (BGM + Ambient + SFX Stinger) — Design

**Date**: 2026-07-04
**Status**: Approved for planning
**Scope**: v1 — mood-driven background music, per-scene ambient bed, and mood-matched
transition stingers, ducked under narration. Sub-project of the broader
"영상미 개선" (production-value) initiative; sibling candidates (real parallax,
post-processing color grade/grain, transition/subtitle variety) are deferred —
see "Out of scope" below.

## Problem

`video_node` currently renders scenes with narration as the *only* audio
track. There is no music, ambience, or SFX anywhere in the pipeline — this is
greenfield (confirmed: no BGM/SFX config fields, no bundled audio assets
beyond the TTS reference voice sample, no mixing libraries installed, no
licensing/sourcing strategy documented anywhere in the repo).

## Goals

- Per-scene mood drives a background music loop, an ambient loop, and a
  transition stinger.
- Narration stays fully intelligible — background audio ducks under it via
  sidechain compression, not a fixed low volume.
- Zero new runtime dependencies (ffmpeg already does everything needed).
- No new pipeline stage/LangGraph node — this is audio mixing bolted onto the
  per-scene render `video_node` already does, not a new architectural
  component.

## Out of scope (deferred, tracked separately)

- Real parallax (background/character independent scale animation) — separate
  sub-project, already flagged in `deferred-work.md` (5.3 QA note).
- Post-processing filters (film grain, vignette, color grade).
- Transition/subtitle variety (additional xfade types, kinetic typography).
- Per-scene manual mood override in the UI — mood is LLM-decided only in v1.
- AI-generated or API-sourced music/SFX — v1 uses a small curated CC0 asset
  library (see "Asset library" below); revisit only if the curated set proves
  insufficient.

## Architecture decision

Three placements were considered:

| Approach | Where | Verdict |
|---|---|---|
| A. Extend `video_node._compose_scene` | Same ffmpeg call that already composes background+character+subtitles | **Chosen** |
| B. New `audio_mix` pipeline stage | Between `tts` and `subtitle` | Rejected — pulls in `STAGE_NODES` wiring, gate mechanism, DB projection, API stage list for what is fundamentally "mix a couple more audio tracks into an existing ffmpeg call" |
| C. Post-process final `video.mp4` audio | After `_join_with_xfade` | Rejected — requires recomputing absolute scene-boundary timestamps against the xfade accumulated-offset math, which the codebase already documents as "the #1 source of xfade timing bugs" |

A wins on quality (ducking quality is determined by the filter, not the
architecture — all three approaches could use the same `sidechaincompress`),
dependencies (zero new runtime deps in all three, but B adds *architectural*
surface: graph node, gate, DB schema, API stage enum), and maintainability
(the mixing filter-graph logic is extracted into a new pure-function module,
`sound_design.py`, mirroring the existing `select_effect`/`_zoompan_filter`
split inside `video.py` — so A gets B's "isolated, unit-testable" benefit
without a new LangGraph node).

Scene-boundary mood transitions (BGM/ambient crossfading from one mood to the
next) are handled for free by the existing `_join_with_xfade` acrossfade —
no changes needed there. This works because each mood's BGM/ambient loop is
short (10–30s) and seamless, so restarting it from t=0 at the start of every
scene's render is inaudible; there is no need to track a running playback
position across the whole run.

## Data model changes

`src/yt_flow/domain/state.py`:

```python
class SceneState(TypedDict):
    ...
    mood: str  # one of MOOD_VALUES; see sound_design.py
```

Mood taxonomy (fixed, v1 — 4 values, matches SCP narrative beats):

- `dread` — default/baseline tense unease
- `clinical` — calm, Foundation-procedural documentation tone
- `escalation` — rising action / containment breach / chase
- `revelation` — climax / dramatic reveal

## Scenario chain changes (prompt policy applies)

Per `docs/PROMPT_POLICY.md`, prompt changes are repo-file-first with
Langfuse `production`/`candidate` labels — no direct Langfuse UI edits.

- `prompts/scenario/structure.md`: add `mood` (enum of the 4 values above) to
  the per-scene JSON output schema, decided by the LLM from the scene's
  research/atmosphere context.
- `prompts/scenario/writing.md`: echo `mood` through into its own per-scene
  JSON output, the same way `atmosphere`/`location`/`color_palette` already
  pass from `structure_step`'s scenes into `writing_step`'s output (confirmed:
  `visual_breakdown_step` reads `scene["atmosphere"]` etc. off the
  *writing*-stage scene dict, not the structure-stage one).
- `scenario_chain.build_scenes()`: `mood=str(writing_scene.get("mood") or
  DEFAULT_MOOD)`. Deliberately lenient (`.get()` + fallback), unlike the
  strict `writing_scene["location"]`-style access used for image-generation-
  critical fields — a missing/invalid mood degrades to a default audio bed,
  it does not need to fail the whole scenario stage. This same fallback also
  makes old checkpointed runs (recorded before this feature existed, with no
  `mood` key at all) resume safely.

## New module: `src/yt_flow/pipeline/nodes/sound_design.py`

Pure functions, no I/O except read-only asset-path existence checks — same
layer as `video.py` (`pipeline/nodes`), no AD-1 violation, no new LangGraph
node:

- `MOOD_VALUES = ("dread", "clinical", "escalation", "revelation")`
- `DEFAULT_MOOD = "dread"`
- `resolve_mood(mood: str | None) -> str` — unknown/missing/empty → `DEFAULT_MOOD`
  (mirrors `select_effect`'s hint-fallback pattern in `video.py`)
- `MOOD_ASSET_PATHS: dict[str, dict[str, Path]]` — `{mood: {"bgm": ..., "ambient": ..., "stinger": ...}}`
- `validate_mood_assets(mood: str) -> None` — raises `FileNotFoundError` if any
  of the three files for the resolved mood are missing (fail-fast, same style
  as `_validate_scene_assets` in `video.py`)
- `build_sound_design_args(mood: str) -> list[str]` — extra ffmpeg `-i` /
  `-stream_loop -1 -i` input args for bgm/ambient/stinger
- `build_sound_design_filter(mood: str, duration: float, narration_label: str, input_offset: int) -> tuple[str, str]` —
  returns `(filter_complex_fragment, output_label)`. Sketch (exact
  volume/threshold constants tuned by ear once real assets are in place):

  ```
  [{bgm_input_idx}:a]volume=0.25[bgm_v]
  [{ambient_input_idx}:a]volume=0.15[amb_v]
  [{stinger_input_idx}:a]volume=0.5,apad=whole_dur={duration}[stg_v]
  [bgm_v][amb_v][stg_v]amix=inputs=3:duration=first[bgmix]
  [bgmix]{narration_label}sidechaincompress=threshold=0.05:ratio=8:attack=5:release=300[ducked]
  [ducked]{narration_label}amix=inputs=2:duration=first:normalize=0[aout]
  ```

`video.py._compose_scene` calls these three functions when
`s.sound_design_enabled` is true, appending to the existing ffmpeg invocation
and remapping `-map` from the raw narration stream to `[aout]`. No changes to
`_join_with_xfade` — it already treats segment audio opaquely.

## Asset library

```
data/audio/bgm/{mood}.mp3        # 1 per mood, seamless 10-30s loop
data/audio/ambient/{mood}.mp3    # 1 per mood, seamless loop
data/audio/sfx/{mood}_stinger.mp3  # 1 per mood, 1-2s one-shot
```

12 files total (4 moods × 3 roles), sourced from curated CC0 libraries
(e.g. Pixabay Audio, Freesound filtered to CC0) and committed to the repo —
same posture as `data/voices/sutak.mp3` and the CC-BY-SA-compliant SCP wiki
reference images from Story 5-5 Phase 2. No dynamic/generated audio, no
external API calls at runtime — avoids the same licensing-risk class that
got the DDG-search-image approach rejected (`deferred-work.md`, 2026-07-03).

## Settings

```python
# src/yt_flow/config.py
sound_design_enabled: bool = True   # same pattern as chapter_cards
```

Volume/ducking constants (`BGM_VOLUME`, `AMBIENT_VOLUME`, `STINGER_VOLUME`,
sidechain threshold/ratio/attack/release) are fixed module constants in
`sound_design.py`, not `Settings` fields or per-scene config — matches the
existing `SWAY_AMPLITUDE`/`ZOOM_IN_MAX` precedent in `video.py`. Add a knob
only if a real scene ever needs a different value.

## Testing

Follow the existing `video.py` convention: `resolve_mood` and
`build_sound_design_filter` are pure functions tested by asserting their
return values/strings directly, no real ffmpeg invocation. `_compose_scene`'s
integration with the new args/filters is covered via the existing
`fake_run_ffmpeg` stub in `tests/stubs/fakes.py` (assert the new `-i` args
and `[aout]` map target appear in the captured argv) — no new fake needed.

## Error handling

- Missing/invalid `SceneState.mood` → `resolve_mood` fallback to `dread`
  (lenient — this is a cosmetic-audio field, not load-bearing).
- Missing asset file on disk for a resolved mood → `validate_mood_assets`
  raises `FileNotFoundError` before ffmpeg runs, extending
  `_validate_scene_assets`'s existing fail-fast style (same treatment as a
  missing `image_path`/`audio_path`/`subtitle_path`).
- `sound_design_enabled = False` → `_compose_scene` skips all of the above
  entirely, falling back to today's narration-only audio path unchanged.
