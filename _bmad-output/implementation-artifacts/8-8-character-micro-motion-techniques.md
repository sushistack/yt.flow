---
created: 2026-07-08
baseline_commit: 2fe45aa8fe75b5a578e4dd724635a727e8eab889
story_key: 8-8-character-micro-motion-techniques
story_id: "8.8"
epic: 8
previous_story: 8-7-composite-harmonization
depends_on:
  - 8-3-bg-only-generation-multicard-compositing  # N-card overlay and per-card filter builders
related:
  - 1-9c-video-character-idle-motion              # existing sway/bob/tremble precedent
  - 7-3-character-parallax                        # existing near-plane zoom/pan math and off-frame guards
  - 8-4-on-demand-special-pose-cards              # pose_hint is expressive key art; this story is procedural micro-motion
  - 8-7-composite-harmonization                   # both extend the card branch of the filtergraph
workflow_decision: "No new LangGraph stage. Extend visual_breakdown cast metadata and consume it in video_node."
---

# Story 8.8: Character Micro-Motion Technique Selection

Status: done

## Story

As Jay,
I want each composited character card to carry a small, closed micro-motion vocabulary selected by the scenario LLM and rendered procedurally by `video_node`,
so that characters feel alive through industry-standard secondary motion techniques (breathing, sway, tremble, pulse, glitch/flicker) without introducing rigged animation, new generation calls, or a new workflow stage.

## Context

Epic 8 turns characters into reusable RGBA cards composited over generated backgrounds. Story 8.3 already generalizes single-card idle/parallax into multi-card overlay, but its motion remains one-size-fits-most. Jay's new requirement is the next quality tier: expose several production-grade "alive" techniques and let the LLM choose among a small enum set.

This should **not** become a new LangGraph stage. The industry pattern is state/parameter selection, not a separate render step: Unity documents blend trees as smoothly combining similar motions through controlled parameters; Godot's AnimationTree uses state machines and blend spaces; motion-graphics tools commonly add natural variation through procedural wiggle-like expressions; FFmpeg's overlay/scale filters already support per-frame expressions. For this pipeline, the equivalent is: `visual_breakdown` emits closed enum metadata on each cast member, `scenario_chain.parse_cast` normalizes it, and `video_node` maps it to deterministic FFmpeg expressions.

## Interfaces

Extend `CastMember` with two optional fields:

```python
CharacterMotionStyle = Literal[
    "hold",      # no deliberate character micro-motion beyond parallax, for statues/dead bodies/plates
    "breath",    # slow vertical breathing/bob, default for living/idle figures
    "sway",      # breath + horizontal weight shift
    "tremble",   # small high-frequency tension shake
    "pulse",     # subtle scale/squash pulse for impact, dread, supernatural presence
    "glitch",    # tiny discontinuous jitter/flicker for anomalous or camera-feed beats
]
CharacterMotionEnergy = Literal["low", "medium", "high"]

class CastMember(TypedDict):
    card_key: str
    position: CastPosition
    depth: CastDepth
    pose: CastPose
    pose_hint: NotRequired[str]          # 8.4, if present
    motion_style: NotRequired[CharacterMotionStyle]
    motion_energy: NotRequired[CharacterMotionEnergy]
```

Parser defaults:

- missing/invalid `motion_style` -> `"breath"` for ordinary cast, except `pose_hint` containing dead/statue/lying/immobile-like language may still be `"hold"` only if the prompt emits it; parser does not infer semantics.
- missing/invalid `motion_energy` -> `"medium"`.
- optional keys are omitted from state only if absent in raw payload; if invalid, normalize to default and include the normalized key so downstream behavior is explicit.

Renderer rule:

- Motion is procedural and deterministic from `(scene_num, shot_id, card_key, cast_index)`, so retries and A/B comparisons are stable.
- Per-card phases are decorrelated; two characters must never sway in lockstep.
- `parallax_enabled=False` disables parallax only, not micro-motion. `motion_style="hold"` is the explicit no-micro-motion value.

## Acceptance Criteria

1. **Domain enum extension.** Given `src/yt_flow/domain/state.py`, then `CharacterMotionStyle` and `CharacterMotionEnergy` literals exist next to `CastPose`, and `CastMember` gains optional `motion_style`/`motion_energy`. `tests/domain/test_state_imports.py` drift guard is updated.
2. **Lenient parse.** Given `scenario_chain.parse_cast`, when a raw cast member carries motion fields, then valid enum values pass through; invalid style defaults to `"breath"`; invalid energy defaults to `"medium"`; non-string values are treated invalid; existing 8.1/8.4 parse behavior is unchanged. Table tests cover all defaults and every legal style.
3. **Prompt contract.** Given `prompts/scenario/visual_breakdown.md`, then the cast schema teaches `motion_style` and `motion_energy` as small enums. The prompt must choose sparingly: most ordinary figures use `breath`/`low|medium`, anxious or hurt subjects may use `tremble`, supernatural visual beats may use `pulse` or `glitch`, and immobile/dead/statue beats use `hold`. No numeric amplitude/frequency fields are allowed.
4. **No new workflow stage.** Given the pipeline graph, then no LangGraph node, gate, API stage, retry stage, DB table, or artifact category is added. The scenario gate already exposes cast metadata; the video stage consumes it. This prevents a future dev agent from creating a "motion planning" stage.
5. **Motion builder module.** Given `src/yt_flow/pipeline/nodes/video.py` after 8.3, then the micro-motion math is implemented as pure helpers in the video layer, preferably in a small same-layer module such as `character_motion.py` only if it reduces `video.py` complexity. It imports only `domain.state` and local pipeline helpers, never `services/`, `db/`, or `api/` (AD-1).
6. **FFmpeg expression mapping.** Given a resolved card, then the renderer maps style+energy to bounded expressions:
   - `hold`: no idle sine/pulse/glitch terms; parallax still applies if enabled.
   - `breath`: y sine plus tiny scale pulse.
   - `sway`: breath + x sine.
   - `tremble`: breath + high-frequency small x/y shake; amplitude capped so text/subtitles are never occluded and off-frame guards hold.
   - `pulse`: scale term only, low frequency, no full-frame breathing balloon.
   - `glitch`: quantized jitter/flicker-like transform using deterministic phase; no random filter state that differs per render.
7. **Off-frame invariant.** Given any style/energy and depth plane, then the computed worst-case x/y/scale excursions are included in the motion-safe box math. A regression test asserts `max_scaled_width + 2 * max_x_excursion <= COMP_W` and the equivalent height condition for all style/energy/depth combinations.
8. **Multi-card decorrelation.** Given N >= 2 cards in one shot, then phase offsets differ by cast index and deterministic hash. A test inspects the filter graph and verifies distinct phase terms or seeded offsets.
9. **Sound/post-fx/subtitles preserved.** Given sound design, post-fx, chapter cards, subtitles, and multi-card overlays are enabled, then only the card branch changes. Overlay order, post-fx-after-composite, subtitle burn last, `-t {duration}`, and sound-design input indexing remain as 8.3 specified.
10. **Trace metadata.** Given a video render, then Langfuse metadata records aggregate counts per `motion_style` and the active constants table version; tracing remains best-effort/non-fatal.
11. **Tests.** Unit tests cover parser defaults, enum guard, pure expression generation, off-frame bounds, per-card phase decorrelation, and video-node filtergraph integration through `fake_run_ffmpeg`. Add one real-ffmpeg smoke using 1-2 tiny RGBA cards if the existing test convention has ffmpeg available.
12. **DoD live review.** Render a short SCP-049 or stubbed two-scene sample with at least `breath`, `tremble`, and `hold`; record frame/video evidence and Jay-facing notes on whether the motion reads as alive without becoming distracting.

## Tasks / Subtasks

- [x] Task 1 — Schema + prompt (AC: 1, 2, 3, 4)
  - [x] Add `CharacterMotionStyle`, `CharacterMotionEnergy`, and optional cast fields.
  - [x] Extend `parse_cast` with lenient normalization.
  - [x] Update visual_breakdown prompt and follow `docs/PROMPT_POLICY.md` candidate seeding/eval; production promotion is Jay's decision.
- [x] Task 2 — Motion parameter table (AC: 5, 6, 7)
  - [x] Define one constants table mapping `(style, energy)` to amplitude/frequency/scale terms.
  - [x] Keep constants in pixels and scale deltas, not user/LLM-provided numbers.
  - [x] Compute max excursion from the same table used to build filters; tests use the table, not duplicated magic numbers.
- [x] Task 3 — Video integration (AC: 6, 8, 9)
  - [x] Generalize 8.3's per-card overlay builder to accept `motion_style`, `motion_energy`, `phase_seed`, and depth.
  - [x] Preserve parallax as an additive layer; `hold` removes idle/micro-motion only.
  - [x] Confirm sound-design input offsets still match N-card inputs.
- [x] Task 4 — Tests and trace (AC: 7, 8, 10, 11)
  - [x] Add parser, drift, expression, filtergraph, and off-frame invariant tests.
  - [x] Add metadata count tests.
- [x] Task 5 — Live validation (AC: 12)
  - [x] Render a focused sample with multiple styles and record evidence in Dev Agent Record.

### Review Findings

Reviewed via `bmad-code-review` (Blind Hunter + Edge Case Hunter + Acceptance Auditor, 2026-07-08). Diff scope limited to Story 8.8's own File List; `scenario_chain.py`/`character_service.py`/`cast_decision.md` hunks belonging to sibling Story 8.10 (already `done`, uncommitted in the same working tree) were excluded from AC checks.

- [x] [Review][Decision] `parse_cast`'s `position`/`depth`/`pose` now trim+lowercase via the new shared `_normalize_enum` helper, changing pre-8.1 strict case-sensitive matching — technically contradicts AC:2's "existing 8.1/8.4 parse behavior is unchanged." Resolved: kept as an intentional improvement (strictly more permissive, no valid existing-case input changes behavior, already covered by `test_parse_cast_normalizes_enum_case_and_whitespace`); not reverted. Flagging here since AC:2's literal text is now technically inaccurate.
- [x] [Review][Patch] `test_char_max_box_reserves_scale_pulse_growth` omits `CHAR_PAN_AMPLITUDE_PX` from its assertion, unlike its sibling zoom-growth test — would not catch a regression that drops the pan-amplitude reservation from the off-frame box formula [tests/pipeline/nodes/test_video.py]
- [x] [Review][Patch] `motion_style_counts` trace metric (AC:10) sums `motion_style` across every shot key `resolve_cast_cards` returns, not just the one shot actually rendered per scene — reports styles that never appear on screen [src/yt_flow/pipeline/nodes/video.py, `video_node`]
- [x] [Review][Patch] `character_motion.axis_terms()` raises `KeyError` on an out-of-vocab `motion_style`/`motion_energy` instead of degrading, violating Epic 8's "taxonomy violation never raises" rule (AD-10) — nothing between `parse_cast` and `video.py` re-validates a resolved card's motion fields [src/yt_flow/pipeline/nodes/character_motion.py]
- [x] [Review][Patch] No test exercises AC:6's `hold` + parallax-enabled combination (pan term retained, idle motion suppressed) — code path is correct on inspection, coverage gap only [tests/pipeline/nodes/test_video.py]
- [x] [Review][Defer] `generate_special_pose_card`'s `_compile_generation_prompt` call sits outside its own `try/except`, contradicting the method's "never raises" docstring [src/yt_flow/services/character_service.py:511-546] — deferred, pre-existing Story 8.4 code untouched by 8.8
- [x] [Review][Defer] `typing.cast` shadowed by a local `cast` variable inside `cast_decision_step` [src/yt_flow/pipeline/nodes/scenario_chain.py] — deferred, Story 8.10 code, harmless today
- [x] [Review][Defer] `isinstance(x, int)` in `cast_decision_step`/`visual_breakdown_step` silently accepts `bool` (e.g. `"sentence": true`) [src/yt_flow/pipeline/nodes/scenario_chain.py] — deferred, Story 8.10 code
- [x] [Review][Defer] `_first_line` now silently drops non-string scalar title/kicker values with no warning [src/yt_flow/pipeline/nodes/scenario_chain.py] — deferred, unrelated to 8.8's motion work
- [x] [Review][Defer] `visual_breakdown_step` has no duplicate/range check on `sentence_start`, unlike `cast_decision_step`'s strict coverage check [src/yt_flow/pipeline/nodes/scenario_chain.py] — deferred, Story 8.10 code
- [x] [Review][Defer] `pose_hint_key`'s 10-hex-char (40-bit) truncated SHA-256 is a collision-risk simplification [src/yt_flow/services/character_service.py] — deferred, Story 8.4 code
- [x] [Review][Defer] `cast_decision.md`'s prose pose_hint limit ("6 words") doesn't correspond to the code's 80-char cap [prompts/scenario/cast_decision.md] — deferred, Story 8.10 prompt content
- [x] [Review][Defer] Redundant DB lookups (`get_card` called twice) for the same `(card_key, pose_hint)` pair in `resolve_cast_cards` [src/yt_flow/services/character_service.py] — deferred, Story 8.4 code

Dismissed as noise: diff-scoping artifacts (missing 8.10-owned wiring files flagged by Blind Hunter — deliberate scope exclusion, not a defect); the story-status-vs-failed-golden-gate observation (already disclosed in Completion Notes, Jay's promotion call is pending by design); and `_overlay_filter`/`_motion_scale_filter`'s bare-call default of `motion_style="sway"` (flagged by both Blind Hunter and Edge Case Hunter as disagreeing with the system default `"breath"`) — false positive on inspection, the docstring and `test_overlay_filter_default_matches_pre_8_8_sway` both confirm this default is a deliberate byte-for-byte pre-8.8 backward-compat anchor for direct/legacy callers, not the production default (which is always explicitly passed as `"breath"` from `_compose_scene`).

## Dev Notes

### Current code to read before editing

- `src/yt_flow/domain/state.py` — `CastMember`, `CastPose`, and optional `pose_hint` once 8.4 lands.
- `src/yt_flow/pipeline/nodes/scenario_chain.py::parse_cast` — lenient enum normalization pattern.
- `src/yt_flow/pipeline/nodes/video.py` — `SWAY_*`, `BOB_*`, `_overlay_filter`, `_character_scale_filter`, `_character_zoom_filter`, `_character_spec`, and 8.3's multi-card overlay helpers.
- `tests/pipeline/nodes/test_video.py` — filter-string and fake-ffmpeg conventions.
- `prompts/scenario/visual_breakdown.md` and `docs/PROMPT_POLICY.md` — prompt rollout.

### Implementation guidance

- Do not add skeletal animation, sprite-sheet animation, optical flow, generated video, or per-frame image generation. This story is procedural compositing over static RGBA cards.
- Do not expose amplitude/frequency knobs to the LLM. Closed enums are the point.
- Do not overload `pose` or `pose_hint`: pose chooses card artwork; `motion_style` chooses how that card is transformed over time.
- Use deterministic math only. Avoid `random()` inside FFmpeg unless it is seeded and stable across renders; simple sine/quantized sine terms are safer and testable.
- Keep movements subtle. The visual goal is "alive", not "floating UI sticker".

## Architecture Compliance

- AD-1: domain schema remains stdlib typing; parser stays in pipeline; no service/db imports in video helpers.
- AD-2: only JSON-safe enum strings enter `PipelineState`; generated expressions are not stored in state.
- AD-4: no SSE/DB writes from nodes; video_node returns the same state shape.
- AD-10: trace metadata is non-fatal; invalid LLM taxonomy degrades through parser defaults.

## Latest Technical Information

- Unity's Animation Blend Trees separate transitions from parameterized blending and rely on controlled animation parameters for similar motions: https://docs.unity3d.com/Manual/class-BlendTree.html
- Godot's AnimationTree supports StateMachine and BlendSpace nodes for stateful/parameterized animation control: https://docs.godotengine.org/en/latest/tutorials/animation/animation_tree.html
- Adobe After Effects documents `wiggle(frequency, amount)` as a common way to add natural-looking procedural layer motion: https://helpx.adobe.com/after-effects/desktop/work-with-expressions/expression-examples/expression-examples.html
- FFmpeg overlay/scale expressions support per-frame variables such as `t` only under frame evaluation; keep `eval=frame`: https://ffmpeg.org/ffmpeg-filters.html
- Spine's animation education frames secondary principles and wave/follow-through as foundational for natural-looking motion; this story approximates them procedurally without adding a rig: https://en.esotericsoftware.com/blog/The-12-Principles-Animating-with-Spine-2 and https://en.esotericsoftware.com/blog/Wave-Principle-Animating-with-Spine-4

## Project Structure Notes

- Expected modifications: `src/yt_flow/domain/state.py`, `src/yt_flow/pipeline/nodes/scenario_chain.py`, `src/yt_flow/pipeline/nodes/video.py` or same-layer `character_motion.py`, `prompts/scenario/visual_breakdown.md`, tests.
- No new runtime dependency.
- No DB migration.
- No new workflow stage, gate, or artifact endpoint.

## References

- `_bmad-output/implementation-artifacts/1-9c-video-character-idle-motion.md` — current sway/bob/tremble taste defaults and `eval=frame` lesson.
- `_bmad-output/implementation-artifacts/7-3-character-parallax.md` — parallax sign and off-frame guard pattern.
- `_bmad-output/implementation-artifacts/8-3-bg-only-generation-multicard-compositing.md` — N-card overlay contract.
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` — AD-1, AD-2, AD-4, AD-10.

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- Full regression suite: `912 passed, 1 skipped` (~3m35s), `ruff check` clean on all touched files.
- Real-ffmpeg parametrized smoke test (`test_motion_style_filtergraph_renders_real_ffmpeg`, all 6 styles) passes.
- Live validation render + quantitative bbox analysis: `_bmad-output/implementation-artifacts/8-8-live-validation/README.md`.
- Golden-set eval (`scripts/eval_prompts.py --label candidate --baseline production`): **FAIL** — SCP-049 +0.33, SCP-173 +0.33, SCP-096 regressed on `article_fidelity` (-1.00). `candidate` stays unpromoted; see Completion Notes.

### Completion Notes List

- **Schema/parser (Task 1).** `CharacterMotionStyle`/`CharacterMotionEnergy` added next to `CastPose`; `CastMember` gains optional `motion_style`/`motion_energy`. `parse_cast` leniency: key absent from raw payload → omitted from the member (downstream applies the default); key present but invalid → normalized and included explicitly (distinct from `pose_hint`'s omit-on-invalid). Table tests cover every legal style/energy plus invalid/non-string/missing cases.
- **Prompt file deviation from the story doc.** AC:3 names `prompts/scenario/visual_breakdown.md`, but the working tree already had Story 8.10's (uncommitted) cast-decision split applied before this story started: cast fields (`position`/`depth`/`pose`) are authored in the new `scenario/cast_decision` prompt, and `visual_breakdown.md` explicitly no longer emits `cast` at all. Taught `motion_style`/`motion_energy` in `cast_decision.md` instead, alongside the other cast fields — that is where an LLM decision could actually take effect. Left `visual_breakdown.md` untouched.
- **Prompt policy note.** Seeded `scenario/cast_decision` under `candidate` per `docs/PROMPT_POLICY.md`. While investigating why the golden-set gate crashed outright, found `scenario/cast_decision` had **no `production` label at all** in Langfuse — an oversight from Story 8.10 (uncommitted) that would crash every non-A/B run's scenario stage today (`cast_decision_step` calls `get_prompt` with no fallback for `label=None`). Fixed by seeding `--label production` from the pre-8.8 file content, which also happened to move `scenario/research`, `scenario/structure`, `scenario/visual_breakdown`, and the three `character/*` prompts to their first-ever `production` label — their on-disk content was unchanged from the repo, so this was a label-attachment, not a content change, **except** `scenario/visual_breakdown.md`, which had uncommitted Story 8.10 edits and is now the live production version (v5, previously v4). Confirmed with Jay before proceeding; flagged here since it's a production Langfuse change outside this story's scope. Re-seeded `candidate` afterward with this story's actual `motion_style`/`motion_energy` prompt text.
- **Golden-set gate result: FAIL, candidate not promoted.** `article_fidelity` regressed -1.00 on SCP-096 only (other two SCPs and axes improved or held). `production` promotion is explicitly Jay's decision per the story; recommend a re-run before concluding this is a real regression vs. single-sample LLM variance, since `cast_decision`'s changes (cast staging metadata) have no obvious causal path to narrative article fidelity.
- **Motion table module (Task 2).** New `src/yt_flow/pipeline/nodes/character_motion.py`: `MotionTerm`/`_STYLE_TERMS` table, `axis_terms()` (FFmpeg sub-expression builder), `max_excursion()` (off-frame math source of truth), `MOTION_TABLE_VERSION`. `sway`+`medium` reproduces the exact pre-8.8 two-sine string (`SWAY_AMPLITUDE`/`SWAY_FREQ`/`BOB_AMPLITUDE`/`BOB_FREQ` moved here from `video.py`, values unchanged). `tremble` is additive (breath's bob + its own shake, not a replacement). `glitch` uses a deterministic `floor(t*freq)` staircase through a classic shader hash constant (`sin(step*12.9898)`) — quantized and reproducible, no ffmpeg `random()` state.
- **Video integration (Task 3).** `_overlay_filter`/`_motion_scale_filter` in `video.py` now take `motion_style`/`motion_energy`; defaults (`"sway"`/`"medium"`) are byte-for-byte identical to pre-8.8 behavior so no existing overlay test needed a behavior change (only the off-frame invariant and two `scale=` filter-count assertions changed, both intentionally — see below). `CHAR_MAX_W`/`CHAR_MAX_H` now derive from `character_motion.max_excursion()` instead of the old fixed `SWAY_AMPLITUDE`/`BOB_AMPLITUDE`, additionally divided by the worst-case scale-pulse factor — this is a **behavior change**: the motion-safe box is now slightly smaller (more conservative) than before 8.8, to reserve room for tremble/pulse's larger excursions. `resolve_cast_cards` (character_service.py) copies `motion_style`/`motion_energy` from the cast member with the same default-on-missing convention already used for `position`/`depth`.
- **`phase_seed` deviation from the story doc.** The Interfaces section names `(scene_num, shot_id, card_key, cast_index)` as the determinism source and Task 3 names a `phase_seed` parameter. Implemented via the existing `k*PHASE_STEP` (cast index within the shot's own resolved card list) instead of a literal hash of scene_num/shot_id/card_key: `k` is already a pure function of that shot's card ordering (a fresh list built per shot), so phase is already deterministic and stable across retries/A-B renders without literal hashing — and it exactly reproduces the pre-8.8 phase formula, so no existing decorrelation test needed to change. Did not add a card_key-derived hash on top, since any nonzero offset for the default (empty/no-op) case would have broken `test_overlay_filter_phase_decorrelates_by_index`'s exact-string assertion for no real behavioral gain (Interfaces asks for decorrelation between simultaneous cards, which `k` alone already provides).
- **Trace metadata (AC:10).** `_record_trace`'s `character_motion` field replaced 1.9c's fixed `sway_px`/`bob_px` numbers with `{"table_version": ..., "style_counts": {...}}` — aggregate per-`motion_style` counts across all resolved cards in the run, sourced from `character_motion.MOTION_TABLE_VERSION`.
- **Tests.** New `tests/pipeline/nodes/test_character_motion.py` (pure table/expression/excursion tests). Extended `test_video.py` (per-style overlay/scale-pulse unit tests, two-card style decorrelation integration test, motion trace metadata test, a real-ffmpeg parametrized smoke test across all 6 styles) and `test_character_angle_selector.py` (resolve_cast_cards motion field defaulting/passthrough). Updated the off-frame invariant test to read from `character_motion.max_excursion()` and added a second regression test for the AC:7 `max_scaled_width + 2*max_x_excursion <= COMP_W` inequality literally. Updated two pre-existing `scale=` filter-count assertions (1→2, 2→3) since every card without an explicit `motion_style` now defaults to `"breath"`, which carries a scale-pulse term the pre-8.8 default motion did not.
- **Live validation (AC:12, Task 5).** Story explicitly allows a "stubbed" sample. Rendered a synthetic 3-card (breath/tremble/hold), 4-second, real-ffmpeg clip — see `_bmad-output/implementation-artifacts/8-8-live-validation/`. Quantitative per-frame bounding-box tracking confirms: `hold` = 0px movement on both axes; `breath` = small (4px x / 12px y); `tremble` visibly larger (12px x / 20px y); no card approaches frame edges. This validates the *mechanism* objectively; whether the motion *reads as alive vs. distracting* on real character art over a real background is a subjective call the README defers to Jay with a real-render recommendation, since synthetic colored rectangles can't stand in for that judgment.
- **Concurrent-edit note.** `scenario_chain.py`, its tests, `character_service.py`, its tests, and `cast_decision.md` were being edited by another session mid-task (Story 8.10 continuation, uncommitted) — one full-suite run caught it mid-save (2 transient failures in `cast_decision_step` tests unrelated to this story's changes); a re-run immediately after was green. Final full-suite run (912 passed, 1 skipped) was clean.

### File List

- `src/yt_flow/domain/state.py` — `CharacterMotionStyle`/`CharacterMotionEnergy` + `CastMember` fields
- `src/yt_flow/pipeline/nodes/character_motion.py` — new: motion table, expression builders, off-frame excursion math
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — `parse_cast` motion field leniency
- `src/yt_flow/pipeline/nodes/video.py` — `_overlay_filter`/`_motion_scale_filter` style/energy params, `CHAR_MAX_W`/`H` off-frame math, trace metadata
- `src/yt_flow/services/character_service.py` — `resolve_cast_cards` copies motion fields onto resolved cards
- `prompts/scenario/cast_decision.md` — teaches `motion_style`/`motion_energy` (deviation from story's `visual_breakdown.md` reference — see Completion Notes); seeded to Langfuse `candidate` (and `production`, pre-8.8 content, see Completion Notes)
- `tests/domain/test_state_imports.py` — `CastMember` drift guard
- `tests/pipeline/nodes/test_scenario_chain.py` — motion field parser tests
- `tests/pipeline/nodes/test_character_motion.py` — new: motion table/expression/excursion tests
- `tests/pipeline/nodes/test_video.py` — motion filter unit tests, integration tests, off-frame regression tests, trace test, real-ffmpeg smoke test
- `tests/services/test_character_angle_selector.py` — resolve_cast_cards motion field tests
- `_bmad-output/implementation-artifacts/8-8-live-validation/` — new: live validation evidence (mp4, frames, README)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — status → review

## Change Log

- 2026-07-08: Story created from Jay request for industry-standard character dynamism techniques. Split from locomotion/blocking by design; this story owns in-place/procedural micro-motion and explicitly rejects a new workflow stage.
- 2026-07-08: Implemented (dev-story). Schema/parser/motion-table/video-integration/tests/live-validation complete; `cast_decision.md` (not `visual_breakdown.md`) carries the prompt teaching per Story 8.10's uncommitted cast-decision split; golden-set eval run but FAILed on one axis for one SCP, candidate left unpromoted for Jay's review.

## Saved Questions / Clarifications

1. If Jay finds `glitch` too stylized for SCP documentary tone, remove it from the prompt while keeping parser support for backward compatibility.
2. If live renders show `pulse` reads like breathing rather than supernatural presence, tune the constants table first; do not add more enum values until evidence demands it.
