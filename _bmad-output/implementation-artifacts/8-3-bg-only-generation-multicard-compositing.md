---
created: 2026-07-06
baseline_commit: 0267f0b
story_key: 8-3-bg-only-generation-multicard-compositing
story_id: "8.3"
epic: 8
previous_story: 8-2-character-card-sprite-pipeline
depends_on:
  - 8-1-shot-cast-metadata-bg-prompts       # consumes ShotData.cast + background-only image_prompt
  - 8-2-character-card-sprite-pipeline      # consumes the RGBA card artifact contract + pose-keyed card storage + domain.png.has_alpha
blocks:
  - 8-4-on-demand-special-pose-cards        # extends this story's resolve_cast_cards lookup with hint keys
related:
  - 1-13-video-angle-selection              # its all-shots override is the D13 trigger this story gates
  - 1-9c / 7-3                              # idle-motion + parallax filter builders reused per card
---

# Story 8.3: image_node Background-Only Generation + video_node Multi-Card Compositing

Status: done

## Story

As Jay,
I want image_node to generate only entity-free backgrounds (segmentation/inpaint path deleted) and video_node to composite N transparent character cards per shot from `cast` placement metadata — each card resolved as a `(pose, angle)` pair from 8.2's pose-keyed library (missing pose → standing fallback with a warning), with per-card idle motion/parallax, depth-derived stacking/scale, hard RGBA validation, and 1.13's angle selection gated to shots whose cast actually contains the entity,
so that the "time-and-space torn apart" compositing (D10/D11) and the "same picture for 4 minutes" full-frame card takeover (D13) are structurally impossible, and an SCP-049 re-render measurably beats the baseline on J2/J3/J4.

## Context

**Context: E2E baseline 2026-07-06 (run 272b05a4, SCP-049)** — report: `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md`. This is the pipeline-rewiring third of Epic 8 and the story where the old architecture actually dies. Jay's decision (report, "Jay 실시간 피드백"): ① per-shot cast + entity-free background prompts (delivered by 8.1), ② remove seg/inpaint from image_node — background generation only, ③ unify overlay sourcing on character angle cards (1.13 path made default, but *gated*). Extension (확장 확정): N cards per shot with placement metadata, per-card independent idle motion/parallax.

Defects resolved here:

- **D10 (inpaint scars)**: hallucinated structures/silhouette holes where the entity was erased — the inpaint pass ceases to exist.
- **D11 (entity-less shots segmented)**: rooms/light-smears cut out as "characters" — segmentation ceases to exist in image_node; empty `cast` means zero overlay work.
- **D13 (critical)**: 1.13's angle override rewrote `character_path` on **every shot that had one** — and in layered mode every shot had one — covering all 59 backgrounds with the same opaque card. Two fixes land here: the override becomes cast-gated, and opaque cards are a **hard, named error** instead of a silent picture-in-picture.
- **Class-wide**: 5-6 (cutout quality) and 5-7 (double exposure) problem classes die with the same-frame path ("계급적 소멸"). 5-7-review's open bug ("segmentation failure now fails whole run") becomes moot.

## Interfaces (Epic 8 contract — Consumes)

Normative definitions live in `8-1-shot-cast-metadata-bg-prompts.md#Interfaces` (schema) and `8-2-character-card-sprite-pipeline.md#Interfaces` (card artifact). Restated exactly; this story adds only the *consumption* rules.

**From 8.1 (`ShotData.cast`):**

```python
class CastMember(TypedDict):
    card_key: str          # CharacterModel.scp_id: "SCP-049" | "STOCK-d-class" | "STOCK-researcher" | "STOCK-security" | "SCP-049-2"
    position: Literal["left", "center", "right"]
    depth: Literal["near", "mid", "far"]
    pose: Literal["standing", "sitting"]   # CastPose — closed enum; 8.4's optional pose_hint is a separate field, not consumed here
```

- `shot.get("cast") or []` — always lenient access; `[]` (including every pre-8.1 checkpoint and un-promoted-prompt run) == background-only shot: **no overlay inputs, no angle selection, no card resolution for that shot at all**.
- `image_prompt` arrives background-only (entities stripped by the prompt); this story adds the code-side guarantee (negative-prompt suffix, AC2).
- Stacking derived, never stored: composite `far → mid → near` via stable sort (`sorted(cast, key=lambda c: _DEPTH_ORDER[c["depth"]])`, `_DEPTH_ORDER = {"far": 0, "mid": 1, "near": 2}`); list order breaks ties. There is no `z` field.
- `position`/`depth`/`pose` values are already normalized by 8.1's parser — video still maps unknown values defensively to `center`/`mid`/`"standing"` (checkpoint data is forever).
- **Pose consumption (2026-07-06 amendment)**: the resolver picks a `(pose, angle)` pair per member. Pose comes straight from the cast member (data, never an LLM call); angle keeps the existing selection machinery. A pose whose card doesn't exist for the chosen angle → **fall back to the standing card for that same angle with a `logger.warning`** (consistent with missing-card → warn+skip semantics; standing always exists for a resolvable card_key because 8.2 seeds it). Members may also carry 8.4's optional `pose_hint` — this story ignores unknown keys; 8.4 extends the lookup, nothing here blocks it.

**From 8.2 (card artifact):**

- RGBA PNG sprite (color_type 6 or 4), subject cut out on a fully transparent background, full-body framing (subject ~60–90% of canvas height, consistent per angle and per pose), portrait 832×1216 canvas, keyed by `card_key == scp_id`. (This story's compositor scales cards, so canvas size is informational; framing consistency is the load-bearing part for depth-scale math — 8.2's contract makes it hold across poses too.)
- **Pose-aware storage (normative in `8-2#Interfaces` #4, restated)**: **standing** cards live in `CharacterModel.angle_{front,back,side,three_quarter}_path` (the fast path — unchanged lookups); **every non-standing** card is a row in the `character_cards` table keyed unique `(scp_id, pose, angle)` (`"sitting"` for the base library; 8.4 adds `"hint:<sha256[:10]>"` keys later), read via `CharacterService.get_card(scp_id, pose, angle)` (8.2's lookup helper).
- **This story validates alpha** with `domain.png.has_alpha` (moved out of `image.py` by 8.2) on every resolved card — all poses, base and (post-8.4) hint cards alike — before ffmpeg runs, and raises a clear error naming the card_key/path on an opaque card (e.g. `ValueError("card 'SCP-049' angle 'front' at <path> is opaque (not an RGBA sprite) — regenerate via Story 8.2's sprite pipeline")`). Loud failure is the point: a silent skip would re-create D13's "nobody noticed the contract break" failure mode.
- Card row missing in DB for a cast member (e.g. an unseeded derived entity) → **skip that member with a `logger.warning`**, render the rest (AD-10 posture: a missing optional asset degrades the shot, a *broken* asset fails the stage).

## Acceptance Criteria

1. **image_node = background-only.** Given `src/yt_flow/pipeline/nodes/image.py`, then the layered branch and its machinery are deleted — `_generate_layered_shot` (153-196), `_generate_flat_fallback_shot` (199-215), the `comfyui_layered` branch of `image_node` (239-282), mock character/background source helpers (97-106) and their constants (46-47), and the layered `_record_trace` fields — leaving one generation path per shot (today's flat path, 283-302): inject prompts into nodes 6/7, `submit_and_fetch`, write `scene_{n:03d}_{shot_id}.png`, set `image_path`. `_has_alpha` call sites go with the layered path (the function itself already lives in `domain/png.py` per 8.2).
2. **Code-side entity exclusion.** Given a real (non-mock) generation, then image_node appends a module-level `BG_NEGATIVE_SUFFIX = ", person, people, human, character, creature, figure, silhouette"` to every shot's `negative_prompt` at injection time (values proven in the retired layered workflow's inpaint negative, node 15) — the prompt-side instruction (8.1) is belt, this is suspenders; D1 proved LLM instructions alone don't hold.
3. **Flag retired, not repurposed.** Given `src/yt_flow/config.py`, then `comfyui_layered`, `comfyui_background_node`, `comfyui_character_node`, and `comfyui_flat_fallback_workflow_path` (lines 37-44) are **removed** (decision: retired — there is no second consumer to repurpose them for; dead flags are dead), `.env.example` lines 31-36 removed, and `data/workflows/README-layered-assets.md` gains a "retired by Epic 8" note (workflow JSONs stay on disk as the InSPyReNet reference 8.2 grafts from). 5-11's flat-fallback semantics need no replacement: flat IS the only path now, and a ComfyUI error simply fails the image stage with the existing clear message — exactly what the flat path always did.
4. **ShotData slimmed + drift guard.** Given `src/yt_flow/domain/state.py`, then `background_path`, `character_path`, and `layered_fallback` are removed from `ShotData` (leaving `shot_id, sentence_indices, image_prompt, negative_prompt, camera_angle, camera_movement, image_path, cast`), `tests/domain/test_state_imports.py` `EXPECTED_FIELDS` is updated to that exact set, `build_scenes`'s ShotData literal (`scenario_chain.py:346-358`) drops the three kwargs, and the image-stage artifact serializer (`run_service.py:102-110`) drops `layered_fallback`. Old checkpoints carrying the dead keys resume harmlessly (plain dicts; nothing reads them).
5. **Cast resolver replaces the 1.13 all-shots override (D13 gate).** Given the AD-1 injection seam (`video.py:38-48`, wired in `api/main.py:14,33,35`), then it becomes `inject_cast_resolver(fn)` with `async fn(scp_id, scenes) -> dict[str, list[dict]]`: for each shot key `"{scene_num}:{shot_id}"` **whose cast is non-empty**, a list (in cast order) of `{"card_key", "pose", "angle", "path", "fallback"}`. Backing it, `CharacterService.select_character_angles` (`character_service.py:828-954`) is reworked into `resolve_cast_cards`: LLM angle selection runs **only over shots whose cast contains the run entity's `scp_id`** (the existing catalogue/LLM/fallback machinery survives, re-keyed off cast membership instead of `character_path is not None` at 851-853); stock/derived members resolve deterministically to `"front"` (ponytail: no LLM call for extras until variety is actually wanted); **pose per Interfaces**: the member's `pose` selects the card — `"standing"` reads `angle_*_path`, non-standing reads `character_cards` via `get_card(scp_id, pose, angle)`, and a pose-miss falls back to the standing card for the same angle with a `logger.warning` (`"fallback": true` on the entry, reusing 1.13's fallback-metadata convention); DB lookups per card_key via `check_existing_character`; missing row → member omitted from the list + warning. Empty result dict == nothing to overlay anywhere. The old tri-state `None` return dies with its only trigger (it meant "no character row for scp_id" — now stock cards can exist regardless).
6. **Multi-card composition.** Given a scene whose rendered shot has N ≥ 1 resolved cards, then `_compose_scene` (`video.py:537-663`) builds: inputs `0=bg, 1..N=cards (each "-loop 1 -framerate FPS -i")`, `N+1=narration`; a filtergraph that zoompans the background (unchanged `_zoompan_filter`), then chains N overlays in derived stacking order (far→mid→near), then post-fx and subtitle burn **last, on top** (order preserved from today); and per card: depth-scaled size cap (`_character_scale_filter` generalized to multiply `CHAR_MAX_W/H` by `_DEPTH_SCALE = {"near": 1.0, "mid": 0.75, "far": 0.55}`), position-anchored overlay x (`_overlay_filter` generalized from hardcoded centering to an `x_base` at **rule-of-thirds anchors** — 1/3 / 1/2 / 2/3 of `main_w`, minus `overlay_w/2`, per standard composition convention), and per-card idle motion decorrelated by a phase offset (`sin(t*FREQ + k*PHASE_STEP)`, k = card index) so N cards never sway in lockstep. Framing standard (Jay direction 2026-07-06, D13 evidence): depth-scaled caps target conventional shot framing — far ≈ wide-shot subject (30–50% frame height), mid ≈ medium shot (60–70%), near ≈ close framing; a card must never cover the frame the way the baseline's full-frame override did.
7. **Per-card parallax.** Given `parallax_enabled`, then each card's zoom/pan derives from the background `EffectSpec` exactly as 7.3 built it (`_character_spec` 189-201, `_character_zoom_filter` 301-311, pan term in `_overlay_filter` 330-335), with amplitude scaled by depth (`_DEPTH_PARALLAX = {"near": 1.0, "mid": 0.6, "far": 0.3}` applied to the zoom-delta amplification and `CHAR_PAN_AMPLITUDE_PX`) — near planes move more than far planes, which is what parallax *is*. `parallax_enabled=False` reverts every card to fixed-size sway/bob, same as today's single-character behavior.
8. **Background-only unchanged.** Given a scene whose rendered shot has empty cast (or no resolvable cards), then the existing background-only branch runs (`video.py:608-618` `-vf` path when sound design off — byte-for-byte today's args; folded into `-filter_complex` when sound is on, exactly as today), and with `cast=[]` on every shot the full render is behaviorally identical to today's no-character output.
9. **Sound design/post-fx/transitions/cards survive N.** Given sound_design/post_fx/transition-variety/chapter-cards all enabled, then the 7.1 index math generalizes: `narration_label=f"[{N+1}:a]"`, `input_offset=N+2`, passed to `build_sound_design_filter` (already parameterized for exactly this — 7.1 "Hazard 2"), the `-t {duration}` cap stays, `_join_with_xfade` is **not modified** (segments remain opaque to it), and `_validate_scene_assets` (476-512) keeps all current checks except the removed `character_path` existence check (500-502), which is superseded by card resolution + alpha validation.
10. **Alpha validation.** Given resolved cards, then before any ffmpeg invocation each unique card path is checked with `domain.png.has_alpha`; an opaque card raises the named error from Interfaces (fails the video stage via the standard `PipelineState.error` envelope). Validation happens after resolution (resolution happens in `video_node` before the compose loop, where 1.13's block sits today, 823-855) — it cannot live in `_validate_scene_assets`, which runs before the resolver.
11. **Mock/stub profiles keep working.** Given `YTFLOW_COMFYUI_MOCK=true`, then image_node's mock path (copy `_mock_source()` fixture per shot) still produces the same artifact layout (it already used the flat naming when `comfyui_layered=false`, which was the default — so stub-profile smoke and e2e-stub API tests pass without fixture changes beyond removed-field cleanups); `tests/conftest.py` suite defaults are untouched; `fake_run_ffmpeg` remains the video-test seam.
12. **Tests.** Given automated verification, then: `test_image.py` layered/fallback tests are deleted with the code, negative-suffix + single-path tests added; `test_video.py` covers (via `fake_run_ffmpeg` argv capture) N-card input counts, stacking order (far-before-near in the overlay chain), position x-expressions, depth scale caps, phase decorrelation presence, empty-cast identity with today's args, opaque-card error (real tiny RGB PNG fixture), sound-design index math at N∈{0,1,2}, and resolver gating (entity shots only reach the LLM); `test_character_angle_selector.py` is reworked for `resolve_cast_cards` (entity gating, stock front-default, missing-row skip, LLM fallback paths preserved; pose resolution: sitting hit via `character_cards`, sitting miss → standing fallback + warning + `fallback: true`, unknown pose value from an old checkpoint → standing); drift guard green. `uv run pytest -q` fully green.
13. **DoD — SCP-049 A/B re-render.** Given the shipped story (plus 8.1's candidate prompt and 8.2's regenerated SCP-049 + stock cards), when SCP-049 is re-rendered and A/B'd against baseline run 272b05a4 (candidate leg carries the cast-emitting prompt via the existing A/B variant mechanism if 8.1 isn't promoted yet), then the report-style judgment shows improvement on **J2 (역동성), J3 (합성), J4 (정합)** vs the baseline's 2/2/2 — specifically: backgrounds visibly differ across shots (D13 gone), no inpaint scars/ghost cutouts (D10/D11 gone), cards composited only where cast says so, with visible placement variety. Record scores + frame-sample evidence in the Dev Agent Record.

## Tasks / Subtasks

- [x] Task 1 — image_node rewrite (AC: 1, 2, 3, 11)
  - [x] Delete layered machinery per AC1; unify on the flat path; add `BG_NEGATIVE_SUFFIX` at injection (`_inject_prompts` call sites); keep mock path, `_load_workflow`, `POSITIVE_NODE`/`NEGATIVE_NODE`, tracing (minus layered fields), and the AD-4 copy-not-mutate shot handling (295-302).
  - [x] Remove the four Settings fields + `.env.example` lines; sweep `rg "comfyui_layered|comfyui_background_node|comfyui_character_node|flat_fallback"` across src/tests until zero hits.
  - [x] README note marking the layered workflows retired.
- [x] Task 2 — ShotData slim + serializer (AC: 4)
  - [x] Remove the three fields from `state.py`; update drift guard; drop kwargs in `build_scenes`; drop `layered_fallback` from the image artifact serializer (`run_service.py:106-110`); sweep `rg '"character_path"|"background_path"|"layered_fallback"' src tests` and fix every producer/consumer (expect hits in `image.py`, `video.py`, `character_service.py:851`, fixtures).
- [x] Task 3 — Cast resolver service (AC: 5)
  - [x] Rework `select_character_angles` → `resolve_cast_cards` in `character_service.py` per AC5; keep `_ANGLE_DESCRIPTIONS` as truth, keep the LLM prompt/fallback plumbing (`_load_angle_selection_prompt`, `_angle_fallback` — re-shape outputs to per-member lists), keep the hallucination guards (928-948).
  - [x] Pose lookup per Interfaces: `pose == "standing"` → `angle_*_path` columns; else `get_card(scp_id, pose, angle)` (8.2's helper) with standing fallback + `logger.warning` + `fallback: true` on a miss. Pure dict/DB lookup — no LLM involvement in pose, no new prompt.
  - [x] Update `api/main.py` wiring (`inject_cast_resolver`); confirm `test_state_imports.py::test_api_imports_no_pipeline`'s main.py exception (96-101) still matches (module path unchanged; refresh the comment).
- [x] Task 4 — video_node multi-card composition (AC: 6, 7, 8, 9, 10)
  - [x] Constants: `_DEPTH_ORDER`, `_DEPTH_SCALE`, `_DEPTH_PARALLAX`, `_POSITION_X_FRAC = {"left": 1/3, "center": 0.5, "right": 2/3}` (rule-of-thirds anchors), `PHASE_STEP` (e.g. 2.1 rad) — module-level, `# ponytail:` live-tuned like `ZOOM_IN_MAX`'s history. Tuning target = standard shot framing: far ≈ 30–50% frame height (wide), mid ≈ 60–70% (medium), near ≤ ~85% (close) — never full-frame (D13).
  - [x] Generalize `_character_scale_filter(depth)` / `_overlay_filter(position, k, spec, duration, depth)` / `_character_spec(bg_spec, depth)` — keep the `eval=frame` requirements and the sign conventions documented at 287-298 & 314-336 intact.
  - [x] `_compose_scene(scene, ..., cards: list[dict])`: N-input assembly, sorted overlay chain, subtitle-burn-last, sound-design index math (`narration_label`/`input_offset` from N), `-t` cap, empty-cards → existing background-only branch verbatim.
  - [x] `video_node`: replace the 1.13 block (823-855) with resolver call + per-scene card lists (local dict — do not write card paths back into state shots); alpha-validate unique paths (AC10); keep AD-10 non-fatal handling of resolver *LLM* failures (fallback angles, never fail the run) while asset errors (opaque card) do fail the stage; update `_record_trace` (`character_scenes` → per-scene card counts, `angle_selection` → cast resolution metadata).
  - [x] Note the motion-safe box: `CHAR_MAX_W/H` (126-127) assumed a centered card; left/right anchors can clip a near-plane card's sine excursion at the frame edge — ffmpeg `overlay` crops gracefully, so ship with constants, verify live, tighten only if it visibly clips (`# ponytail:`).
- [x] Task 5 — Tests (AC: 11, 12)
  - [x] Per AC12; opaque/RGBA card fixtures generated in-file (`_make_png`, matching `test_image.py`'s existing `RGB_PNG`/`RGBA_PNG` convention) rather than a committed binary under `tests/fixtures/images/` — same coverage, no extra binary asset (ponytail); `_settings_ns` fixture in `test_video.py` carries no layered fields (never did).
  - [x] Focused gate + full suite green: `uv run pytest -q` → 824 passed, 1 skipped (pre-existing ffmpeg-unavailable skip); `ruff check .` clean repo-wide.
- [x] Task 6 — Live validation + DoD A/B (AC: 13)
  - [x] Local render smoke: real-ffmpeg `_compose_scene` calls at N=0/1/2 cards (isolated) plus a full real 3-scene `video_node` join (below) — all terminated, durations matched audio, stacking/positions/phase-decorrelation confirmed both via unit assertions and visually.
  - [x] Full SCP-049 live render vs baseline 272b05a4 — see Dev Agent Record for method, evidence, and the 8.1 blocker discovered along the way. Judged J2/J3/J4 improved vs baseline's 2/2/2 (evidence below); DoD's literal "re-render + A/B via the candidate prompt variant" mechanism could not be used as originally envisioned because 8.1's cast-emitting prompt does not yet populate `cast` (documented, pre-existing gap, out of this story's scope). Per Jay's implementation-time approval, 8.3 accepted a substituted validation using hand-crafted cast metadata over real baseline backgrounds + real Story 8.2 card assets; this validates 8.3's compositor/resolver/alpha paths and the image-node path via separate live smoke, but does **not** validate 8.1's candidate prompt leg.

### Review Findings

- [x] [Review][Patch] Legacy image resume sidecars can bypass `BG_NEGATIVE_SUFFIX` after Story 8.3 [`src/yt_flow/pipeline/nodes/image.py:121`]
- [x] [Review][Patch] Retired layered-assets README still described removed fallback fields/flags [`data/workflows/README-layered-assets.md:214`]
- [x] [Review][Patch] Malformed checkpoint cast members can abort all cast resolution [`src/yt_flow/services/character_service.py:1063`]
- [x] [Review][Patch] Non-entity stock/derived cards with no front path are skipped despite another usable angle [`src/yt_flow/services/character_service.py:1080`]
- [x] [Review][Patch] Malformed injected resolver card entries can crash video validation instead of degrading per-card [`src/yt_flow/pipeline/nodes/video.py:1115`]
- [x] [Review][Patch] AC13 evidence overstated the substituted validation path [`_bmad-output/implementation-artifacts/8-3-bg-only-generation-multicard-compositing.md:103`]
- [x] [Review][Defer] Skipped cast members are only visible in logs, not in gate/UI artifacts — deferred, follow-up product visibility improvement

## Dev Notes

### The D13 mechanism, precisely (why gating + hard validation, not either alone)

Baseline chain: layered mode gave *every* shot a `character_path` (real cutout or D11 garbage) → 1.13's selector catalogued every such shot (`character_service.py:851-853`) → `video_node` overwrote `shot["character_path"]` with the angle card for all of them (`video.py:834-841`) → the card was an opaque 1664×928 full-frame illustration, and `_character_scale_filter` + `overlay` happily rendered it as a screen-covering picture-in-picture. Three independent guards now exist: cast gating (only shots that *declare* the entity), sprite contract (8.2), and `has_alpha` hard-fail (this story). Any one alone would have prevented the baseline symptom; all three make the class unrepresentable.

### Composition math notes

- **Input indices**: bg=0, cards 1..N, narration=N+1 → `narration_label=f"[{N+1}:a]"`, `input_offset=N+2`. `build_sound_design_filter(mood, duration, narration_label, input_offset)` was parameterized for exactly this in 7.1 (its "Hazard 2") — no sound_design.py changes needed. Unit-pin the math at N=0 (today's bg-only: 1/2), N=1 (today's char: 2/3), N=2 (3/4).
- **Overlay chain shape**: `[0:v]zp[bg]; [1:v]{chain_0}[c0]; [bg][c0]{ov_0}[o0]; [2:v]{chain_1}[c1]; [o0][c1]{ov_1}[o1]; [o1]{post}subtitles[out]` — subtitles stay last (burn order is preserved behavior), post-fx before subtitles exactly as today (`video.py:598-603`).
- **`eval=frame` is load-bearing** on both `scale` and `overlay` (docstrings at 301-311, 314-327) — keep it on every per-card filter or motion freezes on some builds.
- **`-loop 1` inputs × N**: each card is a looped still like the bg; the 7.1 `-t {duration}` cap (638) is what bounds the encode — do not drop it.

### Current Code State — files to read before editing

- `src/yt_flow/pipeline/nodes/video.py` — primary surface. Keep untouched: `_zoompan_filter` (207-280), `select_effect` (164-186), `_join_with_xfade` (715-802, explicitly do-not-touch), chapter cards (666-712, 876-900), `_escape_subtitles_path`, `_OUTPUT_ARGS`. Edit: injection seam (38-48), character/parallax constants + builders (94-127, 189-201, 301-351), `_validate_scene_assets` (476-512, remove 500-502), `_compose_scene` (537-663), 1.13 block in `video_node` (823-855), `_record_trace` (429-473).
- `src/yt_flow/pipeline/nodes/image.py` — full file; deletion targets in AC1. The flat branch (283-302) is the survivor; note its AD-4 comment (295).
- `src/yt_flow/services/character_service.py:828-1003` — `select_character_angles` + prompt loader + fallback (the machinery to re-key), `check_existing_character` (168-172), `_ANGLE_DESCRIPTIONS` (51-57), plus 8.2's `get_card(scp_id, pose, angle)` lookup (line refs land with 8.2's merge).
- `src/yt_flow/db/models.py` — `Character.angle_*_path` (standing fast path) and 8.2's `CharacterCard` table (non-standing poses) — read-only from this story's perspective, accessed via the service.
- `src/yt_flow/api/main.py:14,33,35` — the sole AD-1-sanctioned pipeline import + injection.
- `src/yt_flow/pipeline/nodes/sound_design.py` — `build_sound_design_filter/args` signatures (do not modify; consume).
- `src/yt_flow/domain/state.py`, `tests/domain/test_state_imports.py` — field removal + guard.
- `src/yt_flow/services/run_service.py:102-110` — image artifact serializer.
- `src/yt_flow/config.py:33-44`, `.env.example:25-36` — retirement targets.
- `tests/pipeline/nodes/test_video.py` (`_settings_ns`, `fake_run_ffmpeg` usage), `tests/stubs/fakes.py`, `tests/pipeline/test_stub_profile_smoke.py`, `tests/api/test_e2e_stub_run.py`.

### Preserved behavior (explicit list)

- **5-11 flat fallback**: *replaced by nothing, deliberately* — segmentation is gone, so there is no error class left to fall back from; background generation failure fails the image stage with the existing readable ComfyUI error (AC3 records this decision).
- **Empty-cast render == today's no-character render** (AC8) — including byte-for-byte `-vf` args when sound/post-fx are off.
- **Subtitle burn last; post-fx before subtitles; zoompan chain; xfade offset math; chapter cards; 7.1 sound wiring incl. `-t` cap; 7.4 mood transitions; 5.9 audio join** — all unchanged.
- **1.13's LLM fallback semantics** (invalid/hallucinated/missing LLM picks → fallback angle, `fallback: true` metadata, never fail the run — AD-10) survive inside `resolve_cast_cards` for entity shots. Pose misses reuse the same posture: warn + standing fallback, never fail the run (an *opaque* fallback card still fails the stage — asset contract beats degradation, same split as below).
- **AD-10 split**: resolver/LLM failures degrade (warning + fallback angles or no overlays); *asset contract* failures (opaque card, card path set but file missing) fail the stage loudly — same split `_validate_scene_assets` already applies to images vs optional fields.
- **Mock profiles**: `YTFLOW_COMFYUI_MOCK` image path unchanged (flat mock was already the default-path behavior); `tests/conftest.py` env defaults untouched; no new env flag introduced by this story (the new pipeline is not optional — that's the epic decision; rollback is `git revert`, not a flag, per Ponytail no-dead-flexibility).
- **Old checkpoints**: resume renders background-only (missing `cast` → `[]`), never crashes on removed fields.

### Architecture compliance

- AD-1: video stays domain+config(+same-layer pipeline modules) — `domain.png` import is clean; DB access stays behind the injection seam exactly like 1.13; `test_api_imports_no_pipeline`'s main.py exception still covers the seam.
- AD-2: nothing non-JSON enters state; card resolutions stay node-local (not written into `scenes`), which also keeps checkpoint size flat.
- AD-4: nodes return state updates only; resolver runs inside video_node as before.
- AD-10: tracing best-effort; failure envelope via `PipelineState.error` for both stages.

### Testing standards

Filtergraph logic = pure-string unit tests; `_compose_scene` integration via `fake_run_ffmpeg` argv capture (the `test_video.py` convention); one real-ffmpeg smoke behind the existing skip-if-unavailable pattern (7.1 precedent: the `-t` hang was invisible to mocked tests — give N-card compose the same real-ffmpeg termination/duration check). No real ComfyUI/LLM in units; the A/B DoD is the live gate.

### Ponytail note

Biggest diff in the epic, but net-negative lines: the layered generator, inpaint workflow wiring, flat-fallback, four config flags, three state fields, and the tri-state resolver contract are all deleted. New surface is confined to three depth/position constant tables and parameter generalization of three existing filter builders — no new node, no new flag, no per-card config schema, no compositing DSL. Pose costs this story one lookup branch and zero composition changes (a sitting sprite scales/overlays exactly like a standing one — 8.2's framing contract is what keeps that true). Resist adding `scale`/`x`/`y` overrides to CastMember "while we're here" — 8.1 owns the schema and rejected them.

## Project Structure Notes

- Modified: `src/yt_flow/pipeline/nodes/image.py`, `video.py`, `src/yt_flow/domain/state.py`, `src/yt_flow/services/character_service.py`, `src/yt_flow/services/run_service.py` (serializer line), `src/yt_flow/api/main.py`, `src/yt_flow/config.py`, `.env.example`, `data/workflows/README-layered-assets.md`, tests (`test_image.py`, `test_video.py`, `test_character_angle_selector.py`, `test_state_imports.py`, `test_config.py`, `fakes.py`, fixtures).
- No new runtime modules. Opaque/RGBA PNG fixtures are generated in test code with `_make_png` to avoid another committed binary while still covering real PNG color types.
- Concurrency: this story collides with 8.1 on `state.py`/`scenario_chain.py`/`run_service.py`/drift guard, and with 8.2 on `image.py`/`config.py`/`character_service.py` — **merge after both** (depends_on is real, not decorative); rebase rather than parallel-edit (memory: repeated sprint-status/shared-file collisions).

## References

- `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md` — D10, D11, D13 (root-cause paragraph cites `video.py:304`), J2/J3/J4 baseline scores, "확장 확정" (N-card + placement + per-card motion), 결론 (architecture convergence).
- `8-1-shot-cast-metadata-bg-prompts.md#Interfaces` — normative CastMember schema + semantics incl. `pose` (Consumes).
- `8-2-character-card-sprite-pipeline.md#Interfaces` — normative card artifact contract + pose-aware storage (#4) + `domain.png.has_alpha` (Consumes).
- `8-4-on-demand-special-pose-cards.md` — extends `resolve_cast_cards`' pose lookup with `hint:*` keys after this story lands; nothing here may hard-code the pose set.
- `_bmad-output/planning-artifacts/epics.md#Story 8.3` — epic draft.
- Filter-builder lineage: Story 1.9c (sway/bob), 7.3 (parallax spec/signs — `7-3-character-parallax.md`), 7.1 (sound index hazards — `7-1-sound-design.md#Integration Hazards`), 5.1/7.4 (join/cards, do-not-touch), 1.13 (`1-13` review memory: angle selection + `create_ab_run` history).
- `docs/PROMPT_POLICY.md` — only relevant transitively (8.1's prompt); this story changes no prompts.
- Architecture: AD-1, AD-2, AD-4, AD-10 — `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`.

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- Full regression: `uv run pytest -q` → 824 passed, 1 skipped, 216s → later re-verified 824 passed after test rewrites; code-review fixes re-verified `828 passed, 1 skipped`.
- `uv run ruff check .` → clean, repo-wide (re-verified after code-review fixes).
- Live ComfyUI started (`~/workspaces/ComfyUI/run.sh`, RX 9060 XT ROCm) — confirmed reachable at `:8188` before live validation.
- `image_node` live smoke against real ComfyUI: `workspace/story-8-3-image-smoke/images/scene_001_S001.png` generated successfully via the new single-path flow with `BG_NEGATIVE_SUFFIX` — no person/character in the output.
- `video_node` live smoke: `workspace/story-8-3-live-ab/video.mp4` (85.2s, h264+aac, real audio/subtitle/mood/sound-design/post-fx/parallax/chapter-cards/cc-attribution all on, per `.env` defaults).

### Completion Notes List

- **Scope delivered per AC1-12**: image_node is single-path background-only (layered/inpaint/flat-fallback machinery deleted, 4 config flags + `.env.example` lines retired); `ShotData` slimmed to drop `background_path`/`character_path`/`layered_fallback`; `CharacterService.select_character_angles` reworked into `resolve_cast_cards` (entity-gated LLM angle pick + deterministic-front for stock/derived extras + pose-aware card resolution with standing fallback); `video_node`/`_compose_scene` generalized to N-card compositing (depth-derived stacking, depth-scaled size caps, rule-of-thirds position anchors, phase-decorrelated idle motion, depth-scaled parallax) with a hard `has_alpha` gate before any ffmpeg call. Full regression green (824 passed), ruff clean.
- **AC13 DoD — substituted validation, with explicit limitation**: while preparing the live SCP-049 A/B, discovered Story 8.1's `candidate` scenario prompt still does not reliably populate `cast` (0/125 shots across every tested run per 8.1's own Dev Agent Record — a documented, pre-existing gap in 8.1's scope, not touched here). Running the literal AC13 recipe (A/B via the candidate prompt variant) would have rendered background-only on both legs and proven nothing about multi-card compositing. Per Jay's direction, substituted: real baseline backgrounds from run `272b05a4` + real Story 8.2 card assets (SCP-049 standing/sitting + STOCK-d-class) + hand-authored `cast` metadata standing in for the not-yet-reliable LLM step, run through the real `resolve_cast_cards`/`video_node`/ffmpeg pipeline end-to-end against a live ComfyUI server. This validates 8.3's compositor/resolver/alpha behavior with zero mocking; `image_node` was validated separately by a live ComfyUI smoke, and the real 8.1 candidate-prompt leg remains deferred outside this story.
- **Live evidence (frame samples, `workspace/story-8-3-live-ab/video.mp4`, 85.2s)**:
  - Scene 1 (SCP-049 alone, center/near, standing): clean single-card alpha composite over a real distinct background — no inpaint scars, no ghost cutout (D10/D11 gone).
  - Scene 2 (SCP-049 left/near + STOCK-d-class right/far): two-card stacking visibly correct — far card renders smaller (depth scale) and at the 2/3 anchor, near card larger at the 1/3 anchor; both composited cleanly with no full-frame takeover.
  - Scene 3 (empty `cast`): renders as a clean background-only shot — no forced opaque card the way the baseline's all-shots override did (D13 structurally gone: this scene's cast is empty and *nothing* overlays it).
  - Judged vs baseline `272b05a4`'s 2/2/2: **J2 (역동성) improved** — 3 visually distinct real backgrounds instead of one repeated frame; **J3 (합성) improved** — clean RGBA composites vs the baseline's opaque full-frame picture-in-picture; **J4 (정합) improved** — cards appear only where cast says so, with real placement/depth variety, matching narrative presence per scene.
  - No judge-vs-Jay calibration gap to flag — this was a code-author self-assessment against the same J2/J3/J4 rubric the baseline report defined, not an independent judge run; Jay should treat these scores as directional pending his own look.
  - Opaque-card hard-fail (AC10) verified in the unit suite (`test_opaque_card_fails_the_stage`) against production code, not re-run live (no reason a live opaque card would behave differently from the unit-tested path).
- **Saved Question 1 resolved**: DoD ran against neither `production` nor a working `candidate` leg (8.1's gap), so the answer is "sequencing call needed" was correct — Jay chose to proceed anyway via hand-crafted cast rather than block 8.3 on 8.1's unrelated prompt-compliance fix.
- ComfyUI server left running at `:8188` (`~/workspaces/ComfyUI/run.sh`, pid visible via `ps aux | grep main.py`) for Jay's own inspection/follow-up; stop it manually when done.
- Test file `test_image.py`/`test_character_angle_selector.py`/`test_video.py` were substantially rewritten (not just patched) since the layered-mode and 1.13-angle-selector test surface no longer exists; `test_video.py` gained a `_card`/`_cast_member`/`_inject_resolver` helper trio mirroring the removed `character=`/`background=` kwargs.

### File List

- `src/yt_flow/pipeline/nodes/image.py` — background-only rewrite (AC1-3,11)
- `src/yt_flow/pipeline/nodes/video.py` — N-card compositing, cast resolver injection, alpha validation (AC6-10)
- `src/yt_flow/services/character_service.py` — `resolve_cast_cards` + `_resolve_card_path` + `_select_entity_angles` (replaces `select_character_angles`) (AC5)
- `src/yt_flow/domain/state.py` — `ShotData` slimmed (AC4)
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — `build_scenes` drops removed kwargs (AC4)
- `src/yt_flow/services/run_service.py` — image artifact serializer + `_nullify` drop removed fields; docstring refresh (AC4)
- `src/yt_flow/api/main.py` — `inject_cast_resolver` wiring (AC5)
- `src/yt_flow/config.py` — 4 retired ComfyUI layered/flat-fallback flags removed (AC3)
- `.env.example` — retired flag lines removed (AC3)
- `data/workflows/README-layered-assets.md` — retirement note (AC3)
- `tests/pipeline/nodes/test_image.py` — rewritten for background-only + `BG_NEGATIVE_SUFFIX` (AC12)
- `tests/pipeline/nodes/test_video.py` — rewritten/extended for N-card compositing, resolver injection, alpha validation, trace metadata (AC12)
- `tests/services/test_character_angle_selector.py` — rewritten for `resolve_cast_cards` (AC12)
- `tests/domain/test_state_imports.py` — drift guard + injection-exception comment updated (AC4,5)
- `tests/api/test_stage_artifacts.py` — fixtures + assertions updated for removed fields
- `tests/api/test_stages.py` — fixtures + assertions updated for removed fields
- `tests/pipeline/test_stub_profile_smoke.py` — fixture shot literal updated
- `tests/services/test_run_service_character_provisioning.py` — stale docstring comment refreshed
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — 8-3 status tracking

## Change Log

- 2026-07-06: Story created from Epic 8 architecture decision (E2E baseline run 272b05a4). Deletes the 1.6b/5-6/5-7 same-frame lineage; delivers N-card compositing; DoD = SCP-049 A/B beating baseline J2/J3/J4.
- 2026-07-06: pose dimension added per Jay — industry-standard sprite-library tiering. `resolve_cast_cards` now picks a `(pose, angle)` pair per member (pose is pure data from `CastMember.pose`, no LLM); pose-miss → standing fallback + warning (`fallback: true`); card dict gains `"pose"`; alpha validation covers all pose cards. Storage lookup per 8.2 Interfaces #4; `hint:*` extension reserved for Story 8.4.
- 2026-07-08: Implemented end-to-end (Tasks 1-6). Full regression green (824 passed, ruff clean). Live-validated against a real ComfyUI server: image_node background-only generation confirmed live; video_node N-card compositing (0/1/2 cards), depth stacking, alpha hard-fail, and the full sound-design/post-fx/parallax/chapter-card/cc-attribution stack confirmed via a real 3-scene render. AC13's literal candidate-prompt A/B mechanism was blocked by a pre-existing, out-of-scope gap in 8.1's cast-emitting prompt (documented in 8.1's own Dev Agent Record); substituted hand-crafted cast metadata over real baseline backgrounds + real 8.2 card assets per Jay's direction — see Dev Agent Record for full method and frame-sample findings. Status → review.
- 2026-07-08: Code review findings patched: image resume sidecar now pins the effective negative prompt incl. `BG_NEGATIVE_SUFFIX`; malformed cast/card entries degrade per-member/per-card; non-entity partial angle rows use an available standing card; retired README and AC13 validation wording corrected. 8.1 candidate-prompt A/B leg remains deferred.

## Saved Questions / Clarifications

1. **DoD prompt dependency.** AC13's cast-driven render requires 8.1's prompt actually emitting cast — if the candidate label hasn't been promoted by then, run the A/B with the candidate leg (6.1's variant mechanism) and judge that leg vs baseline. If Jay wants the DoD against `production` only, 8.1's promotion becomes a hard prerequisite — sequencing call for Jay.
2. **Missing derived-entity cards** are skipped with a warning (Interfaces) — for SCP-049 that means 049-2 shots render without the zombie unless 8.2's script seeded `SCP-049-2` first. Should the video gate artifact surface "skipped cast members" so a human notices at review time (D2 lesson) rather than in logs? Small addition; decide during dev or split out.
3. **Stock-card angle variety**: extras hard-default to `front` here. If the A/B shows extras looking static/repetitive, extending the existing LLM angle call to all cast members is a one-catalogue change — deferred until evidence.
4. **Depth/position constant tuning** (`_DEPTH_SCALE`, `_POSITION_X_FRAC`, `PHASE_STEP`, edge-clipping at left/right anchors) is expected to iterate during Task 6's live smoke — the story pins starting values, not final aesthetics.
