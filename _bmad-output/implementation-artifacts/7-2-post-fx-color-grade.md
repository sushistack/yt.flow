---
baseline_commit: 382d6e78c2c100f27bac0ad1f8421bdb1607ee07
---

# Story 7.2: 후처리 필터 (색보정 + 비네트 + 필름 그레인)

Status: done

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

- [x] **Task 0 — Verify blocking dependency (AC: all)**
  - [x] Confirm Story 7.1 is merged: `sound_design.py` exists with `resolve_mood`/`MOOD_VALUES`/`DEFAULT_MOOD`, and `SceneState.mood` is present in `state.py`. If not, HALT and report.
- [x] **Task 1 — Create `color_grade.py` (AC: 1,2,3,9,10)**
  - [x] New file `src/yt_flow/pipeline/nodes/color_grade.py`, `from yt_flow.pipeline.nodes.sound_design import resolve_mood`.
  - [x] Define `VIGNETTE_ANGLE = "PI/5"`, `GRAIN_STRENGTH = 8`, `MOOD_GRADE_PARAMS` (4 moods, exact values from spec#L54-L59).
  - [x] Implement `build_post_filter(mood: str | None) -> str` per spec#L62-L66.
  - [x] Add a `# ponytail:` note: extract to a shared `mood.py` only if a *third* consumer needs the taxonomy; two consumers importing from the owner is not worth a new file. [Source: spec#L69-L73]
- [x] **Task 2 — Wire post filter into `_compose_scene` (AC: 4,5,6,8,9)**
  - [x] Resolve `mood = scene.get("mood")` at the top of `_compose_scene`.
  - [x] Read `post_fx_enabled` (see Dev Agent Record: threaded as an explicit `post_fx_enabled` kwarg from the compose loop's `s = _settings()`, matching the existing `sound_design_enabled` parameter-threading pattern rather than reading `_settings()` inside `_compose_scene`).
  - [x] Layered path: when enabled, insert `[ov]{build_post_filter(mood)}[graded];[graded]subtitles='{sub}'[out]` and remap `-map [out]` still to the final label. When disabled, keep today's chain unchanged.
  - [x] Background-only path: when enabled, post filter inserted between zoompan and `subtitles=`; when disabled, unchanged.
- [x] **Task 3 — Grade chapter cards (AC: 7,8)**
  - [x] Add `mood: str | None` param to `_compose_chapter_card`.
  - [x] When `post_fx_enabled`, prepend `f"{build_post_filter(mood)},"` before the `drawtext=` fragment in the card `vf`.
  - [x] At the call site, pass `scenes[i + 1].get("mood")` (upcoming scene) alongside the existing `_card_label(scenes[i + 1])`.
- [x] **Task 4 — Settings (AC: 8)**
  - [x] Add `post_fx_enabled: bool = True` to `src/yt_flow/config.py` near `chapter_cards`/`sound_design_enabled`, with a matching one-line comment.
- [x] **Task 5 — Tests (AC: 11)**
  - [x] New `tests/pipeline/nodes/test_color_grade.py`: pure-function assertions on `build_post_filter` for all 4 moods + `None`/unknown fallback.
  - [x] Extend `tests/pipeline/nodes/test_video.py`: capture-`filter_complex`/`-vf` tests for layered + bg-only post-filter placement, chapter-card placement (incl. upcoming-scene mood wiring), and `post_fx_enabled=False` absence (scene + card).
  - [x] Run `pytest tests/pipeline/nodes/test_color_grade.py tests/pipeline/nodes/test_video.py` and confirm green (112 passed). Full suite also green (643 passed, 1 skipped).

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

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

None — implementation went green on first test run, no debugging required.

### Completion Notes List

- Task 0: confirmed Story 7.1 already `done` in sprint-status; verified `sound_design.py` exports `resolve_mood`/`MOOD_VALUES`/`DEFAULT_MOOD` and `SceneState.mood: str` exists at `state.py:46`. Unblocked, proceeded without HALT.
- Deviation from Dev Notes' suggested implementation, noted here for the record: Task 2's Dev Notes suggested reading `post_fx_enabled` via an in-function `_settings()` call inside `_compose_scene`. By the time 7.2 started, Story 7.1 had already changed `_compose_scene` to receive `sound_design_enabled` as an explicit keyword parameter threaded from the compose loop's `s = _settings()` (not read internally) — the Dev Notes predate that refactor and describe a `_settings()`-in-function shape that no longer matches the code. Followed the codebase's current, actual pattern instead: added `post_fx_enabled` as an explicit kwarg to both `_compose_scene` and `_compose_chapter_card`, threaded from the compose loop, consistent with `sound_design_enabled`. Functionally equivalent to the spec/AC; only the internal wiring mechanism differs from the stale Dev Notes snippet.
- `color_grade.py` implemented as a pure function module per spec, with the required `# ponytail:` note on not extracting a shared `mood.py` until a 3rd consumer exists.
- `_compose_scene`: precomputed two conditional fragments (`post_frag` for comma-chained placement, `post_label` for the layered filter-graph's labeled placement) once per call, reused across the sound-design-enabled/disabled and character/no-character branches — avoids duplicating the `build_post_filter` call or the enable/disable branching four times.
- `_compose_chapter_card` gained `mood`/`post_fx_enabled` keyword params with defaults (`None`/`False`) so existing direct-call tests and the real-ffmpeg integration test needed no changes beyond what Story 7.2 explicitly required.
- Chapter-card mood wiring: compose loop now resolves `scenes[i + 1].get("mood")` at the existing chapter-card call site, alongside the existing `_card_label(scenes[i + 1])` — the card is graded to the *upcoming* scene per AC:7.
- Tests: added `tests/pipeline/nodes/test_color_grade.py` (pure-function, all 4 moods + None/empty/unknown fallback) and extended `tests/pipeline/nodes/test_video.py` with placement tests for the layered path, background-only path, chapter cards (including upcoming-scene-mood wiring and the post_fx-disabled case for both scenes and cards), and a `Settings.post_fx_enabled` default-true test mirroring the existing `chapter_cards` one.
- Full regression suite green: 643 passed, 1 skipped (`test_tts.py` real-Qwen-TTS smoke test, gated behind `YTFLOW_QWEN_TTS_SMOKE=1` — pre-existing, unrelated to this story). `ruff check` clean on all touched files.

### File List

- `src/yt_flow/pipeline/nodes/color_grade.py` (new)
- `src/yt_flow/pipeline/nodes/video.py` (modified)
- `src/yt_flow/config.py` (modified)
- `tests/pipeline/nodes/test_color_grade.py` (new)
- `tests/pipeline/nodes/test_video.py` (modified)

### Review Findings

Reviewed via Blind Hunter (diff-only adversarial), Edge Case Hunter (diff + project read), and Acceptance Auditor (diff + spec, ran the test suite and ruff independently — confirmed the Dev Agent Record's "643 passed, 1 skipped" and "ruff clean" claims are true, not just plausible). No AC violations found.

- [x] [Review][Patch] `MOOD_GRADE_PARAMS[resolve_mood(mood)]` has no guard tying its key set to `sound_design.MOOD_VALUES` — a future taxonomy change would raise an uncaught `KeyError` in production rendering instead of degrading gracefully [src/yt_flow/pipeline/nodes/color_grade.py]
- [x] [Review][Patch] `_compose_scene` calls `build_post_filter(mood)` twice unconditionally (once for `post_frag`, once for `post_label`) even though only one of the two is ever used per branch [src/yt_flow/pipeline/nodes/video.py:480-481]
- [x] [Review][Patch] No test exercises `sound_design_enabled=True` together with `post_fx_enabled=True` (code path confirmed correct by inspection — `video_chain` is built with the post filter before the sound-design branch — but the intersection was untested) [tests/pipeline/nodes/test_video.py]
- [x] [Review][Defer] Pre-existing duplication in `_compose_scene`'s no-sound-design/no-character branch (`video_chain` and `vf` recompute the same `{zp_chain}{post_frag},subtitles=...` expression) predates Story 7.2 (inherited from the 7.1 `-vf`/`-filter_complex` split); 7.2 just threaded `post_frag` through both copies consistently — deferred, not caused by this change [src/yt_flow/pipeline/nodes/video.py]

Dismissed as noise (9): substring-only test assertions (matches existing project-wide `_run_ffmpeg` monkeypatch convention, not a 7.2-specific gap); ungraded assumption about the chapter card "still reading as black" (spec explicitly calls the grain-on-card effect intended); the `[graded]` intermediate label in the layered path (this exact string shape is AC4-mandated, not incidental complexity); `post_frag` reused as a name with opposite comma placement across two functions (local-scope only, no collision risk); unexplained magic constants (values and rationale are traced to the design doc in Dev Notes); missing chapter-card `mood=None`+`post_fx_enabled=True` test (already covered at the unit level by `test_build_post_filter_falls_back_to_default_mood`, wiring already proven by the explicit-mood card test); `post_fx_enabled` defaulting `True` with no ramp/rollback (AC8 explicitly requires default `True`, same precedent as `chapter_cards`); integration test not re-asserting internal filter ordering (already owned by the `color_grade` unit test, correctly not duplicated); design-doc vs. story wording divergence on `.get("mood")` vs. direct key access (informational, story's AC9 leniency requirement correctly wins, no code change needed).
