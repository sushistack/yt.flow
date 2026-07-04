# Story 7.2: 후처리 필터 (색보정 + 비네트 + 필름 그레인)

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **content producer running the yt.flow pipeline**,
I want **each scene (and chapter card) color-graded to its mood plus a constant film grain and vignette applied to the composited frame**,
so that **the footage reads as graded, textured video that reinforces the SCP mood, instead of a flat drift over a raw ComfyUI still — without ever degrading subtitle legibility**.

## ⚠️ Blocking Dependency — read first

`[depends_on: 7.1]` This story **cannot be implemented until Story 7.1 (사운드 디자인) has landed.** As of story creation, `7-1-sound-design` is `backlog`. 7.2 imports from and reuses three things 7.1 creates:

| Thing 7.2 needs | Owner | Exists today? |
|---|---|---|
| `src/yt_flow/pipeline/nodes/sound_design.py` with `resolve_mood`, `MOOD_VALUES`, `DEFAULT_MOOD` | Story 7.1 | ❌ No |
| `SceneState.mood: str` field in `src/yt_flow/domain/state.py` | Story 7.1 | ❌ No (verified: `state.py:37` `SceneState` has no `mood`) |
| `<feature>_enabled: bool` Settings pattern (7.1 adds `sound_design_enabled`) | Story 5.1 (`chapter_cards`) precedent | ✅ pattern exists |

**Do not redefine the mood taxonomy in `color_grade.py`.** Import `resolve_mood` from `sound_design`. If 7.1 is not yet merged, HALT and surface this — do not stub `sound_design.py` yourself, that would duplicate the taxonomy owner and defeat the whole "one owner" design decision. [Source: docs/superpowers/specs/2026-07-04-color-grade-postfx-design.md#L44-L73]

## Acceptance Criteria

1. **New pure-function module** `src/yt_flow/pipeline/nodes/color_grade.py` exposes `build_post_filter(mood: str | None) -> str` returning the ffmpeg filter fragment `eq=…,vignette=…,noise=…` in that fixed order. It imports `resolve_mood` from `sound_design` (does not redefine the mood taxonomy). [Source: spec#L44-L73]
2. **Per-mood color grade**: `build_post_filter` maps each of the 4 moods (`dread`/`clinical`/`escalation`/`revelation`) through `MOOD_GRADE_PARAMS` into an `eq=saturation=…:contrast=…:brightness=…:gamma=…` fragment. An unknown / `None` / empty mood falls back to `DEFAULT_MOOD`'s params via `resolve_mood`. [Source: spec#L54-L66, #L98-L100]
3. **Constant vignette + grain**: the returned fragment always appends `vignette=angle=PI/5` and `noise=alls=8:allf=t+u`, identical for every mood (grain/vignette intensity is NOT mood-driven — that was explicitly rejected). [Source: spec#L25-L27, #L51-L66]
4. **Scene filter placement — layered (character) path**: in `_compose_scene`, the post filter is inserted **after** the character overlay `[ov]` and **before** subtitle burn-in, producing `…[bg][char]{overlay}[ov];[ov]{build_post_filter(mood)}[graded];[graded]subtitles='{sub}'[out]`. [Source: spec#L84-L91]
5. **Scene filter placement — background-only path**: the post filter is inserted between the zoompan chain and `subtitles=`: `{zp_chain},{build_post_filter(mood)},subtitles='{sub}'`. [Source: spec#L93-L96]
6. **Subtitles untouched**: burned subtitle text never has grain/vignette/grade applied to it (guaranteed by placement in AC4/AC5 — post filter runs strictly before `subtitles=`). [Source: spec#L30-L31, #L78-L82]
7. **Chapter cards graded to the upcoming scene**: `_compose_chapter_card` gains a `mood: str | None` parameter; `video_node` passes `scenes[i + 1].get("mood")` (the card announces the *upcoming* scene). The post filter is inserted **before** `drawtext` so the label text is not grained: `{build_post_filter(mood)},drawtext=…,fade=…,fade=…`. [Source: spec#L103-L116]
8. **Settings toggle**: `src/yt_flow/config.py` gains `post_fx_enabled: bool = True` (same pattern as `chapter_cards`). When `False`, `_compose_scene` / `_compose_chapter_card` skip `build_post_filter` entirely and render exactly today's ungraded output. [Source: spec#L118-L123, #L148-L149]
9. **Lenient mood resolution**: mood is read as `scene.get("mood")` — pre-mood checkpointed runs (no `mood` key) still render, falling back to `DEFAULT_MOOD`'s grade rather than raising. [Source: spec#L98-L100]
10. **Fixed module constants**: `VIGNETTE_ANGLE`, `GRAIN_STRENGTH`, `MOOD_GRADE_PARAMS` are module-level constants in `color_grade.py`, NOT `Settings` fields or per-scene config (same precedent as `SWAY_AMPLITUDE`/`ZOOM_IN_MAX` in `video.py`). [Source: spec#L124-L129]
11. **Tests**: unit test asserts `build_post_filter` output contains the expected `eq=`/`vignette=`/`noise=` fragments for all 4 moods and that unknown/`None` falls back to `DEFAULT_MOOD`; integration tests via the existing `fake_run_ffmpeg` stub assert the post-filter fragment appears in the captured `filter_complex`/`-vf` string in the correct position (after overlay, before `subtitles=`) for both the layered and background-only paths, plus in the chapter-card `-vf` before `drawtext`. A `post_fx_enabled=False` test asserts the fragment is absent. [Source: spec#L131-L140]

## Tasks / Subtasks

- [ ] **Task 0 — Verify blocking dependency (AC: all)**
  - [ ] Confirm Story 7.1 is merged: `sound_design.py` exists with `resolve_mood`/`MOOD_VALUES`/`DEFAULT_MOOD`, and `SceneState.mood` is present in `state.py`. If not, HALT and report.
- [ ] **Task 1 — Create `color_grade.py` (AC: 1,2,3,9,10)**
  - [ ] New file `src/yt_flow/pipeline/nodes/color_grade.py`, `from yt_flow.pipeline.nodes.sound_design import resolve_mood`.
  - [ ] Define `VIGNETTE_ANGLE = "PI/5"`, `GRAIN_STRENGTH = 8`, `MOOD_GRADE_PARAMS` (4 moods, exact values from spec#L54-L59).
  - [ ] Implement `build_post_filter(mood: str | None) -> str` per spec#L62-L66.
  - [ ] Add a `# ponytail:` note: extract to a shared `mood.py` only if a *third* consumer needs the taxonomy; two consumers importing from the owner is not worth a new file. [Source: spec#L69-L73]
- [ ] **Task 2 — Wire post filter into `_compose_scene` (AC: 4,5,6,8,9)**
  - [ ] Resolve `mood = scene.get("mood")` at the top of `_compose_scene`.
  - [ ] Read `post_fx_enabled` off the resolved `Settings` (see Dev Notes: `_compose_scene` currently has no `Settings` handle — thread it in, mirroring how the compose loop calls `_settings()` at `video.py:654`).
  - [ ] Layered path (`video.py:462-467`): when enabled, insert `[ov]{build_post_filter(mood)}[graded];[graded]subtitles='{sub}'[out]` and remap `-map [out]` still to the final label. When disabled, keep today's chain unchanged.
  - [ ] Background-only path (`video.py:480`): when enabled, `vf = f"{zp_chain},{build_post_filter(mood)},subtitles='{sub}'"`; when disabled, unchanged.
- [ ] **Task 3 — Grade chapter cards (AC: 7,8)**
  - [ ] Add `mood: str | None` param to `_compose_chapter_card` (`video.py:496`).
  - [ ] When `post_fx_enabled`, prepend `f"{build_post_filter(mood)},"` before the `drawtext=` fragment in the card `vf` (`video.py:515-520`).
  - [ ] At the call site (`video.py:680`), pass `scenes[i + 1].get("mood")` (upcoming scene) alongside the existing `_card_label(scenes[i + 1])`.
- [ ] **Task 4 — Settings (AC: 8)**
  - [ ] Add `post_fx_enabled: bool = True` to `src/yt_flow/config.py` near `chapter_cards` (`config.py:75-78`), with a matching one-line comment.
- [ ] **Task 5 — Tests (AC: 11)**
  - [ ] New `tests/pipeline/nodes/test_color_grade.py`: pure-function assertions on `build_post_filter` for all 4 moods + `None`/unknown fallback.
  - [ ] Extend `tests/pipeline/nodes/test_video.py`: capture-`filter_complex` tests (pattern at `test_video.py:307-320`) for layered + bg-only post-filter placement, chapter-card placement, and `post_fx_enabled=False` absence.
  - [ ] Run `pytest tests/pipeline/nodes/test_color_grade.py tests/pipeline/nodes/test_video.py` and confirm green.

## Dev Notes

### Architecture / design constraints

- **No new pipeline stage, no new LangGraph node, no new gate.** This is three filter names appended to a `-vf`/`filter_complex` string that `_compose_scene` already builds and runs once per scene. The "one ffmpeg call per scene" decision is settled — do not re-litigate it. [Source: spec#L34-L42]
- **Zero new dependencies.** `eq`, `vignette`, `noise` are stock ffmpeg filters. [Source: spec#L32]
- **`color_grade.py` is a pure function, no I/O.** Unlike `sound_design.py` (which does asset-path existence checks), color grade has no external files and thus **no new failure modes** — the only degradation path is an unknown mood, already handled by `resolve_mood`'s fallback. [Source: spec#L143-L149]
- **Illustrative param values.** `MOOD_GRADE_PARAMS` values are tuned-by-eye placeholders; ship the spec values, they get refined once real footage exists. Do not invent a config knob for them. [Source: spec#L75-L76, #L124-L129]

### Source tree — files to touch

| File | Action | What changes |
|---|---|---|
| `src/yt_flow/pipeline/nodes/color_grade.py` | **NEW** | The whole module (Task 1). |
| `src/yt_flow/pipeline/nodes/video.py` | UPDATE | `_compose_scene` (both filter paths), `_compose_chapter_card` (+`mood` param), compose-loop call site. |
| `src/yt_flow/config.py` | UPDATE | `+post_fx_enabled: bool = True`. |
| `tests/pipeline/nodes/test_color_grade.py` | **NEW** | Pure-function tests. |
| `tests/pipeline/nodes/test_video.py` | UPDATE | Placement/toggle integration tests. |

### Current state of `video.py` (read before editing — [Source: src/yt_flow/pipeline/nodes/video.py])

- **`_compose_scene(scene, scene_index, out_dir)` (L431-493)** — two branches:
  - **Layered** (character present, L459-477): `filter_complex = "[0:v]{zp_chain}[bg];[1:v]{_character_scale_filter()}[char];[bg][char]{_overlay_filter()}[ov];[ov]subtitles='{sub}'[out]"`, maps `-map [out] -map 2:a`. **Insert post filter between `[ov]` and `subtitles=`.**
  - **Background-only** (L478-488): `vf = f"{zp_chain},subtitles='{sub}'"`. **Insert post filter between `{zp_chain}` and `subtitles=`.**
  - `_compose_scene` **does not currently take or read `Settings`** — it must gain access to `post_fx_enabled`. The compose loop already computes `s = _settings()` (L654) and reads `s.chapter_cards` there; simplest is to read `_settings()` inside `_compose_scene` (matches `_settings()`'s existing use elsewhere in the module, e.g. `_drawtext_font`). Do not add a parameter to the public node signature unnecessarily. `# ponytail:` this if you pick the in-function `_settings()` read.
  - Must preserve: the `-map [out] -map 2:a` (layered) / `-vf` (bg-only) contract, the `rc != 0` and `seg_path.exists()` guards, and the `return seg_path, spec, bool(character_path)` tuple — downstream `_join_with_xfade` and `effects_meta` depend on it.
- **`_compose_chapter_card(label, index, out_dir, duration)` (L496-534)** — builds a `vf` starting with `drawtext=…` then two `fade=` filters. Cards must be graded to the **upcoming** scene's mood (same convention as sound-design's stinger selection). On the solid-black card, `eq`/`vignette` are near-invisible but `noise` shows as grain — that consistency (card not reading as a flat ungraded interstitial) is the *intended* effect. [Source: spec#L112-L116]
- **Compose loop (L652-683)** — `s = _settings()` at L654; chapter cards inserted at L678-682 with `label = _card_label(scenes[i + 1])`; add `mood = scenes[i + 1].get("mood")` there and pass to `_compose_chapter_card`.
- **`_join_with_xfade` (L537+)** — **no changes.** It treats segment audio/video opaquely; post-fx is baked into each segment before joining.

### Config pattern ([Source: src/yt_flow/config.py:75-78])

```python
# Chapter-card transitions (Story 5.1)...
chapter_cards: bool = True
chapter_card_duration_sec: float = 1.75
```
Add `post_fx_enabled: bool = True` in the same block with a one-line comment. This is a `pydantic`/`pydantic-settings` `Settings` model — a plain field default is all that's needed.

### Testing standards ([Source: tests/pipeline/nodes/test_video.py, tests/stubs/fakes.py])

- No live ffmpeg: `_run_ffmpeg` and `_record_trace` are monkeypatched (`test_video.py:133-139`). `fake_run_ffmpeg` (`tests/stubs/fakes.py:35`) writes a 1-byte file to the last argv element so file-existence guards pass.
- **Capture pattern** (`test_video.py:307-320`): monkeypatch `video._run_ffmpeg` with a capture function that records `args[idx+1]` after `"-filter_complex"` (or `"-vf"`), then assert on the captured string. Use this to assert post-filter placement.
- Pure-function tests (like the existing `select_effect`/`_zoompan_filter` tests) assert on returned strings directly — mirror this for `build_post_filter`.
- No new fake needed; no real ffmpeg invocation.

### Project Structure Notes

- `color_grade.py` sits in `pipeline/nodes/` beside `video.py` and `sound_design.py` — same layer, pure helper, not a LangGraph node. No `STAGE_NODES`/graph/gate/DB/API wiring changes (this is what makes the "no new stage" decision cheap). [Source: spec#L34-L42]
- Mood taxonomy has exactly one owner (`sound_design.py`). `color_grade.py` is the second consumer and must import, not redefine. [Source: spec#L69-L73]

### References

- [Source: docs/superpowers/specs/2026-07-04-color-grade-postfx-design.md] — full design (problem, module sketch, filter placement, chapter cards, settings, testing, error handling).
- [Source: docs/superpowers/specs/2026-07-04-sound-design-design.md#L105-L119] — `sound_design.py` API that 7.2 imports (`resolve_mood`, `MOOD_VALUES`, `DEFAULT_MOOD`); #L69-L83 — `SceneState.mood` field + mood taxonomy.
- [Source: _bmad-output/planning-artifacts/epics.md#L984-L986] — Epic 7 Story 7.2 statement + ordering constraint (7.1 precedes 7.2; all of 7.1-7.4 touch `video.py` → run sequentially, not parallel).
- [Source: src/yt_flow/pipeline/nodes/video.py:431-534] — `_compose_scene` / `_compose_chapter_card` current implementation.
- [Source: src/yt_flow/config.py:75-78] — `chapter_cards` settings precedent.
- [Source: tests/pipeline/nodes/test_video.py:307-320] — filter_complex capture-test pattern.

### Ponytail notes (project runs full mode)

- Reuse `resolve_mood` — don't redefine the taxonomy (one owner). Mark the "extract to `mood.py` only on a 3rd consumer" ceiling with a `# ponytail:` comment in `color_grade.py`.
- Prefer reading `_settings()` inside `_compose_scene` over widening its public signature; mark with `# ponytail:`.
- No new dependency, no new stage, no per-scene config knob for grade params — spec values as module constants until real footage demands tuning.
- Non-trivial logic (per-mood branch + fallback) leaves one runnable check: `test_color_grade.py` covers all 4 moods + fallback.

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
