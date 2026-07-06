---
baseline_commit: 40b678725c980beb763ccd509889f98e34483834
---

# Story 7.3: 진짜 패럴랙스 (배경/캐릭터 속도 분리)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a video pipeline maintainer,
I want the character (near plane) to move and zoom in the *same direction* as the background (far plane) amplified by a fixed depth factor across all 10 Ken Burns directions,
so that the accidental zoom-only parallax-like artifact flagged in the 5-3 live QA becomes a deliberate, consistent multiplane depth cue — without the character ever clipping off-frame.

## Acceptance Criteria

1. A new pure function `_character_spec(bg_spec: EffectSpec) -> EffectSpec` derives the character's spec from the background's: `direction` passes through unchanged, and the zoom deviation from 1.0 is amplified by `CHAR_DEPTH_FACTOR` (`start_zoom = 1.0 + (bg_spec.start_zoom - 1.0) * CHAR_DEPTH_FACTOR`, same for `end_zoom`). Direction-agnostic — `static` (1.0→1.005) stays tiny after amplification with no special-casing.
2. The character layer is zoomed over time with a `scale` filter using a time-varying expression and `eval=frame` (NOT `zoompan` — the character is a transparent PNG composited via `overlay` and needs no crop). It is applied to the character stream right after the existing `_character_scale_filter()` cap and before `overlay`.
3. `_overlay_filter` gains a macro pan term derived from `spec.direction`, added *on top of* (not replacing) the existing sway/bob sines. The pan term matches the background's **apparent on-screen** motion direction (amplified), not the crop-window sign.
4. `CHAR_MAX_W`/`CHAR_MAX_H` are shrunk to reserve room for the peak character zoom **before** sway/bob is applied: `CHAR_MAX_ZOOM = 1.0 + (ZOOM_IN_MAX - 1.0) * CHAR_DEPTH_FACTOR`, then `CHAR_MAX_W = (COMP_W - 2*SWAY_AMPLITUDE) / CHAR_MAX_ZOOM` and `CHAR_MAX_H = (COMP_H - 2*BOB_AMPLITUDE) / CHAR_MAX_ZOOM`. This is a correctness requirement of the story, not a deferrable nicety — without it the character grows ~19.5% past frame edges at the in-center peak. `_character_scale_filter()` itself is unchanged (it already reads these constants).
5. A `parallax_enabled: bool = True` setting is added to `Settings` (env `YTFLOW_PARALLAX_ENABLED`), following the exact pattern of `chapter_cards`. When `False`, `_overlay_filter` and the character scale step revert to today's fixed-size, sway/bob-only behavior (no character zoom, no macro pan). `CHAR_DEPTH_FACTOR` and `CHAR_PAN_AMPLITUDE_PX` are fixed `video.py` module constants (no per-scene config), matching the `SWAY_AMPLITUDE`/`ZOOM_IN_MAX` precedent.
6. No new file is created — all new functions live in `video.py`, extending the existing `EffectSpec`/`select_effect`/`_zoompan_filter`/`_overlay_filter`/`_character_scale_filter` system.
7. **Pan-sign correctness for all 10 `_DIRECTION_POOL` entries is verified against a live render before merging** — the character must drift with the background's apparent motion, not opposite it. This is a visual judgment call and cannot be trusted from the crop-math convention alone. Record the verification (which directions checked, on what run) in the Dev Agent Record.
8. Unit tests cover: `_character_spec` zoom-amplification math for `in-center`/`out-center`/`static` and direction pass-through; the character zoom/overlay filter strings contain the expected `scale=`/`eval=frame` fragments; and a regression test asserting `CHAR_MAX_W * CHAR_MAX_ZOOM ≤ COMP_W - 2*SWAY_AMPLITUDE` (and the H equivalent) — the off-frame invariant is checked, not just eyeballed.

## Tasks / Subtasks

- [x] Task 1: Add `parallax_enabled` setting (AC: 5)
  - [x] Add `parallax_enabled: bool = True` to `Settings` in [config.py](src/yt_flow/config.py) next to `chapter_cards`, with a comment mirroring the chapter-card pattern (env `YTFLOW_PARALLAX_ENABLED`).
- [x] Task 2: Add module constants + `CHAR_MAX_W`/`H` fix (AC: 1, 4)
  - [x] Add `CHAR_DEPTH_FACTOR = 1.3` and `CHAR_PAN_AMPLITUDE_PX` (tune by eye, start conservative — see Dev Notes) as `video.py` module constants, with `# ponytail:` comments noting they're fixed constants tuned via live-render QA (same style as `ZOOM_IN_MAX`).
  - [x] Add `CHAR_MAX_ZOOM = 1.0 + (ZOOM_IN_MAX - 1.0) * CHAR_DEPTH_FACTOR`.
  - [x] Change `CHAR_MAX_W`/`CHAR_MAX_H` to divide by `CHAR_MAX_ZOOM` as in AC:4. Update the existing comment above them to explain the zoom-growth reservation.
- [x] Task 3: `_character_spec` derivation function (AC: 1, 6)
  - [x] Add pure `_character_spec(bg_spec: EffectSpec) -> EffectSpec` per the spec formula.
- [x] Task 4: Character zoom via `scale` filter (AC: 2, 5, 6)
  - [x] Add `_character_zoom_filter(spec: EffectSpec, duration: float) -> str` building `scale=w='iw*({start}+({end}-{start})*t/{duration})':h='ih*(...)':eval=frame` from the *character* spec.
  - [x] Insert it in `_compose_scene`'s layered filtergraph on the character stream between `_character_scale_filter()` and `overlay` (i.e. `[1:v]{_character_scale_filter()},{_character_zoom_filter(...)}[char]`). When `parallax_enabled` is False, omit the zoom filter.
- [x] Task 5: Extend `_overlay_filter` with the macro pan term (AC: 3, 5, 6)
  - [x] Give `_overlay_filter` the parameters it needs (`spec` + `duration`, and an enable flag or pass `None` spec when disabled) to add the direction-derived pan term on top of the existing sway/bob sines. Keep the centering `(main_w-overlay_w)/2` base intact (it stays correct under `eval=frame` even as the character scales).
  - [x] Map each of the 10 directions to an on-screen pan sign for x and y (see Dev Notes sign table — provisional, MUST be live-verified per AC:7). `static`/center directions contribute ~zero pan.
  - [x] Update `_compose_scene`'s `_overlay_filter()` call site to pass the character spec + duration.
- [x] Task 6: Wire `parallax_enabled` through `_compose_scene` (AC: 5)
  - [x] Read the flag from `_settings()` (or thread it in) and branch the character scale/zoom + overlay so `False` yields today's exact behavior. Background-only scenes (`character_path is None`) are unaffected either way.
- [x] Task 7: Unit tests (AC: 8)
  - [x] Add tests to [test_video.py](tests/pipeline/nodes/test_video.py) following existing conventions (see Testing Requirements).
- [x] Task 8: Live-render sign verification (AC: 7)
  - [x] Render a run exercising all 10 directions and confirm the character drifts *with* the background on screen for each. Fix any inverted signs in the Task 5 map. Document in Dev Agent Record.

## Review Findings

_Code review 2026-07-06 (baseline `40b6787`, 3 adversarial layers: Blind Hunter / Edge Case Hunter / Acceptance Auditor). 2 findings survived triage; 14 dismissed as noise (see summary below)._

- [x] [Review][Patch] pan-진폭 off-frame 리스크를 박스 수식에 예약해 구조적으로 차단 — **해소됨 (2026-07-06 review patch)** [src/yt_flow/pipeline/nodes/video.py:106-107]. 원 문제: AC:7이 "crop-math 규약만으로 신뢰 불가"라 명시했으나 Task 8은 배경 centroid drift로 `_PAN_SIGN` 부호 일치만 재확인(=규약의 알고리즘적 재유도)했고, pan-* 방향 peak(char zoom→1.195) + sway ±12 + pan ±12가 겹치면 ~12px 프레임 밖으로 밀릴 수 있었음 (박스 여유가 SWAY_AMPLITUDE=12px뿐이었음). 부호 자체는 Acceptance Auditor가 `_zoompan_filter` crop 식에서 8방향 독립 재유도로 정확함을 확인. 해소: `CHAR_MAX_W/H`를 `(COMP − 2·(SWAY/BOB + CHAR_PAN_AMPLITUDE_PX)) / CHAR_MAX_ZOOM`로 변경해 최악 코너(zoom+sway+pan 동시 peak)가 구조적으로 프레임 안에 남도록 함. AC:8 회귀 테스트(`test_char_max_box_reserves_zoom_growth`)도 pan 여유를 포함하도록 강화. 남은 AC:7 항목은 순수 미적 sign-off(스펙이 "taste call"로 규정)로 축소됨. [sources: auditor A7 + blind B8]

- [x] [Review][Defer] `_character_spec`가 char zoom을 `CHAR_MAX_ZOOM`으로 런타임 clamp하지 않음 [src/yt_flow/pipeline/nodes/video.py:169] — deferred, pre-existing. 현재 `select_effect`가 배경 zoom을 `ZOOM_IN_MAX`로 상한하므로 안전하나, 향후 배경 zoom 상한을 올리면 박스 수식과 어긋나 off-frame 회귀 발생 (오늘은 도달 불가). [sources: blind B7 + edge E4]

## Dev Notes

### Current state of the file being modified — [video.py](src/yt_flow/pipeline/nodes/video.py)

This story extends the existing Ken Burns system; you must preserve every current behavior. Read the whole file, but the critical pieces:

- **`EffectSpec`** ([video.py:91](src/yt_flow/pipeline/nodes/video.py#L91)) — `direction`, `start_zoom`, `end_zoom`. Reused as-is for the character.
- **`select_effect`** ([video.py:122](src/yt_flow/pipeline/nodes/video.py#L122)) — produces the *background* spec. `in-center`/`pan-*` zoom 1.0→`ZOOM_IN_MAX`; `out-center` zooms `ZOOM_IN_MAX`→1.0; `static` → 1.0→1.005 on `in-center`. Do NOT change this — `_character_spec` derives from its output.
- **`_zoompan_filter`** ([video.py:150](src/yt_flow/pipeline/nodes/video.py#L150)) — background crop-and-pan. **Read the crop-space sign carefully**: `pan-right` uses `x_expr = (iw-iw/zoom)*on/{frames}`, which moves the *crop window* right, so visible content drifts **left** on screen (classic pan-camera). Your character pan term must match apparent on-screen motion, i.e. the *opposite* sign of the crop-window expression. This is the exact bug the story exists to prevent (AC:7).
- **`_overlay_filter`** ([video.py:226](src/yt_flow/pipeline/nodes/video.py#L226)) — currently `overlay=x='(main_w-overlay_w)/2 + sin(t*SWAY_FREQ)*SWAY_AMPLITUDE':y='(main_h-overlay_h)/2 + sin(t*BOB_FREQ)*BOB_AMPLITUDE':eval=frame`. `eval=frame` is REQUIRED (some ffmpeg builds collapse `t`/`n` to NAN under `eval=init`). Your added pan term rides on top of both sines; keep `eval=frame`.
- **`_character_scale_filter`** ([video.py:239](src/yt_flow/pipeline/nodes/video.py#L239)) — caps an oversized character to `CHAR_MAX_W`/`CHAR_MAX_H`, downscale-only. Unchanged; it reads the module constants you shrink in Task 2, which is why shrinking them is sufficient.
- **`_compose_scene`** ([video.py:431](src/yt_flow/pipeline/nodes/video.py#L431)) — layered branch builds `[0:v]{zp_chain}[bg];[1:v]{_character_scale_filter()}[char];[bg][char]{_overlay_filter()}[ov];[ov]subtitles=...[out]`. This is where the character zoom filter is inserted and where `_overlay_filter` is called. The background-only branch (`character_path is None`, AC:3 background-only) must remain untouched.
- **Constants** ([video.py:42-85](src/yt_flow/pipeline/nodes/video.py#L42-L85)): `FPS=25`, `COMP_W=1920`, `COMP_H=1080`, `ZOOM_IN_MAX=1.15`, `SWAY_AMPLITUDE=12`, `BOB_AMPLITUDE=8`, and the current `CHAR_MAX_W/H` definitions.

**Peak zoom sanity check**: `CHAR_MAX_ZOOM = 1.0 + (1.15 - 1.0) * 1.3 = 1.195`. Old `CHAR_MAX_W = 1920 - 24 = 1896`; new `CHAR_MAX_W = (1920 - 2*(12+12)) / 1.195 = 1872/1.195 ≈ 1566` (post-review: the box reserves SWAY *and* CHAR_PAN_AMPLITUDE_PX per side — see Review Findings [Patch]). A character capped to the new box then zoomed to 1.195× peaks at ≈1872px — leaving 24px per side (=SWAY 12 + PAN 12), so the worst-case corner stays on-frame. That invariant is exactly what the AC:8 regression test asserts.

### Provisional direction→on-screen-pan sign table (MUST live-verify — AC:7)

Background crop expression → apparent on-screen drift → character pan sign (character moves *with* the apparent drift, amplified by `CHAR_PAN_AMPLITUDE_PX`). This table is derived from the crop-math convention and is a **starting point only**; confirm every sign against a live render before merge.

| direction | bg crop moves | apparent on-screen | char x term | char y term |
|-----------|---------------|--------------------|-------------|-------------|
| pan-right | crop→right | content→left | −x | 0 |
| pan-left | crop→left | content→right | +x | 0 |
| pan-up | crop→down | content→up | 0 | −y |
| pan-down | crop→up | content→down | 0 | +y |
| pan-up-right | crop→right+down | content→left+up | −x | −y |
| pan-up-left | crop→left+down | content→right+up | +x | −y |
| pan-down-right | crop→right+up | content→left+down | −x | +y |
| pan-down-left | crop→left+up | content→right+down | +x | +y |
| in-center | zoom only | none | 0 | 0 |
| out-center | zoom only | none | 0 | 0 |

`static` → treated as center, ~zero pan. Express the pan as a linear ramp over the shot (`... * t/{duration}` or `on`-based, matching how the zoom expr ramps) so it reads as a slow depth-coupled drift, not a sine.

### `CHAR_PAN_AMPLITUDE_PX` tuning

Start deliberately conservative (the spec calls it "conservative relative to the background's own effective pan range" because it stacks with the zoom growth). A value in the ~8–16px range is a reasonable starting point given `SWAY_AMPLITUDE=12`; tune by eye during Task 8. Mark it with a `# ponytail:` comment noting it's eyeball-tuned, same as `ZOOM_IN_MAX`'s history. Note the pan amplitude is NOT reserved for in the `CHAR_MAX_W/H` box math — the spec's box formula only accounts for zoom growth + sway/bob; keep the pan amplitude small enough that it doesn't reintroduce clipping (that's part of what Task 8 visually confirms).

### Ponytail guidance

- No new file, no new dependency, no per-scene config — the whole story is filter-string math on already-validated inputs (design spec §"No new file", §Settings).
- `_character_spec`, `_character_zoom_filter`, and the extended `_overlay_filter` are pure string/dataclass builders — no I/O, no error handling needed (design spec §"Error handling": no new failure modes; `character_path` presence is already validated by `_validate_scene_assets`).
- Prefer extending `_overlay_filter`'s signature over adding a parallel function — one code path, gated by the enable flag.

### Project Structure Notes

- Touches exactly two files: [src/yt_flow/config.py](src/yt_flow/config.py) (one setting) and [src/yt_flow/pipeline/nodes/video.py](src/yt_flow/pipeline/nodes/video.py) (constants + 2 new functions + `_overlay_filter`/`_compose_scene` edits). Tests in [tests/pipeline/nodes/test_video.py](tests/pipeline/nodes/test_video.py).
- Layer rule (AD-1, [video.py:7](src/yt_flow/pipeline/nodes/video.py#L7)): video.py imports domain + config only. No db/api/services. `_character_spec` etc. are pure and layer-clean.
- **Epic 7 parallel-session hazard**: stories 7-1/7-2/7-3/7-4 all edit `video.py` (audio mixing / filter chain / motion math / `_join_with_xfade`). Per epics.md §"순서 제약", sequential work is recommended. If any of 7-1/7-2 land concurrently, expect merge conflicts in the constants block and `_compose_scene`.

### Testing Requirements

Test file conventions (from [test_video.py](tests/pipeline/nodes/test_video.py)):
- Import from `yt_flow.pipeline.nodes.video`; also `import ... as video` for module constants (`video.ZOOM_IN_MAX`, `video._DIRECTION_POOL`).
- Filter-string tests build an `EffectSpec` directly and assert substring fragments in the returned string (see `test_zoompan_filter_contains_zoompan`, `test_zoompan_filter_diagonal_has_expected_axis_expressions`). Mirror this for `_character_zoom_filter` (assert `scale=` and `eval=frame` present) and the extended `_overlay_filter`.
- Async ffmpeg tests monkeypatch `video._run_ffmpeg` with a capture stub (see `test_xfade_offset_math_3_scenes`) — not needed for pure-function tests here.
- Required new tests (AC:8):
  1. `_character_spec` amplification for `in-center` (1.0→1.15 ⇒ 1.0→1.195), `out-center` (1.15→1.0 ⇒ 1.195→1.0), `static` (1.0→1.005 ⇒ 1.0→1.0065), and `direction` pass-through for a pan direction.
  2. `_character_zoom_filter` string contains `scale=` and `eval=frame`.
  3. `_overlay_filter` (parallax on) contains the pan term for a pan direction and still contains the sway/bob sines; (parallax off) equals today's fixed-size output.
  4. Regression: `video.CHAR_MAX_W * video.CHAR_MAX_ZOOM <= video.COMP_W - 2*video.SWAY_AMPLITUDE` and the H equivalent (float tolerance ok).
- Run: `PYTHONPATH=$PWD/src python -m pytest tests/pipeline/nodes/test_video.py -q` (worktree note below).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (BMAD dev-story workflow)

### Debug Log References

- `PYTHONPATH=$PWD/src python -m pytest tests/pipeline/nodes/test_video.py tests/test_config.py -q` → 129 passed
- `ruff check src/yt_flow/pipeline/nodes/video.py src/yt_flow/config.py tests/pipeline/nodes/test_video.py` → clean
- Task 8 live-render harness (scratchpad `verify_parallax.py`, real ffmpeg 8.0.1): full parallax filtergraph rc=0 for all 10 directions; pan-sign map objectively matches measured background apparent drift for all 10.

### Completion Notes List

- **Approach**: pure filter-string/dataclass extensions to the existing Ken Burns system in `video.py`; no new file, no new dependency, no per-scene config (design spec §"No new file"/§Settings). Character (near plane) reuses the background's `EffectSpec`; `_character_spec` amplifies only the zoom delta (×`CHAR_DEPTH_FACTOR=1.3`), direction passes through.
- **Character zoom** uses a `scale` filter with a time-ramped expression + `eval=frame` (not `zoompan` — transparent PNG needs no crop; zoompan alpha handling unreliable), inserted on the `[char]` stream between `_character_scale_filter()` and `overlay`.
- **Character pan** rides on top of the existing sway/bob sines inside `_overlay_filter` via `_PAN_SIGN[direction]` × `CHAR_PAN_AMPLITUDE_PX=12`, ramped linearly over the shot. Signs are in *apparent on-screen* space (opposite the crop-window sign), so the character drifts WITH the background.
- **Off-frame fix (AC:4)**: `CHAR_MAX_W/H` now divide by `CHAR_MAX_ZOOM` (=1.195) so a character capped to the box then zoomed to peak lands back inside the sway-safe frame. AC:8 regression test asserts the invariant.
- **`parallax_enabled=False`** yields byte-identical prior behavior: `_overlay_filter()` with no spec reverts to the fixed-size sway/bob-only string and the character zoom step is omitted. `_settings_ns` test helper defaults it OFF so pre-7.3 tests are untouched.
- **AC:7 live verification** (all 10 `_DIRECTION_POOL` entries, real ffmpeg): the provisional Dev-Notes sign table was correct with **no inversions**. Objective method — track a centered marker through the real `_zoompan_filter` and read its centroid drift, compare sign to `_PAN_SIGN`:
  - in-center (0,0)→(+0.000,+0.000) OK · out-center (0,0)→(+0.000,+0.000) OK
  - pan-right (−1,0)→(−0.074,+0.000) OK · pan-left (1,0)→(+0.074,+0.000) OK
  - pan-up (0,−1)→(+0.000,−0.072) OK · pan-down (0,1)→(+0.000,+0.072) OK
  - pan-up-right (−1,−1)→(−0.074,−0.072) OK · pan-up-left (1,−1)→(+0.074,−0.072) OK
  - pan-down-right (−1,1)→(−0.074,+0.072) OK · pan-down-left (1,1)→(+0.074,+0.072) OK
  - Sign correctness (the bug the story exists to prevent) is proven; the remaining human aesthetic sign-off — whether depth *feels* right and whether `CHAR_PAN_AMPLITUDE_PX`/`CHAR_DEPTH_FACTOR` want tuning — is a taste call for a real SCP render, same iteration style as `ZOOM_IN_MAX`'s history.

### File List

- `src/yt_flow/config.py` — added `parallax_enabled: bool = True` setting.
- `src/yt_flow/pipeline/nodes/video.py` — parallax constants (`CHAR_DEPTH_FACTOR`, `CHAR_PAN_AMPLITUDE_PX`, `CHAR_MAX_ZOOM`), `CHAR_MAX_W/H` zoom-growth fix, `_character_spec`, `_character_zoom_filter`, `_PAN_SIGN`, extended `_overlay_filter(spec, duration)`, `_compose_scene` parallax branch + `parallax_enabled` param, `video_node` flag wiring.
- `tests/pipeline/nodes/test_video.py` — `_settings_ns` gains `parallax_enabled`; updated `test_character_scale_filter_downscale_only_within_motion_box`; new Story 7.3 tests (`_character_spec` math ×4, `_character_zoom_filter`, `_overlay_filter` on/off/center, box regression, config default, 2 video_node integration).

## Change Log

- 2026-07-06 — Implemented real character parallax: near-plane zoom (`_character_spec` + `_character_zoom_filter`) and macro pan (`_PAN_SIGN` in `_overlay_filter`) coupled to the background `EffectSpec`, `CHAR_MAX_W/H` zoom-growth off-frame fix, `parallax_enabled` toggle. 14 new unit tests + AC:7 live sign-verification across all 10 directions (no inversions). Status → review.
- 2026-07-06 — Code review (3 adversarial layers). 1 decision-needed resolved via patch, 1 deferred, 14 dismissed. Patch: `CHAR_MAX_W/H` now reserve `CHAR_PAN_AMPLITUDE_PX` per side in addition to sway/bob, closing a ~12px off-frame risk at simultaneous zoom+sway+pan peak that AC:4's box math had left to visual QA; AC:8 regression test strengthened to cover the pan margin. 129 tests pass, ruff clean. Status → done.

## References

- [Source: docs/superpowers/specs/2026-07-04-character-parallax-design.md] — full design (approach, formulas, sign warning, `CHAR_MAX` fix, testing, error handling).
- [Source: _bmad-output/planning-artifacts/epics.md#Story 7.3] — story scope, dependency on 5-3, `YTFLOW_PARALLAX_ENABLED`, sequential-work constraint.
- [Source: _bmad-output/implementation-artifacts/deferred-work.md#Deferred from: 5-3 motion-intensity 라이브 QA (2026-07-04)] — the accidental-parallax artifact this story converts to a deliberate feature; reconsideration condition met.
- [Source: src/yt_flow/pipeline/nodes/video.py] — `EffectSpec`, `select_effect`, `_zoompan_filter`, `_overlay_filter`, `_character_scale_filter`, `_compose_scene`, `CHAR_MAX_W/H`, motion constants.
- [Source: src/yt_flow/config.py:77] — `chapter_cards` setting, the pattern `parallax_enabled` follows (`env_prefix="YTFLOW_"`).
- [Source: tests/pipeline/nodes/test_video.py] — filter-string + async test conventions.
- Worktree gotcha (memory `worktree-editable-install-shadowing`): if run from a git worktree, set `PYTHONPATH=$PWD/src` so pytest imports the worktree's `src`, not the global editable install.

Status set to ready-for-dev — comprehensive developer guide created.
