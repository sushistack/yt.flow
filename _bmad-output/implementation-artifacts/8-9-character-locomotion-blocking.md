---
created: 2026-07-08
baseline_commit: 2820d1acb625575b4224ec3ba91bd56a304a8165
story_key: 8-9-character-locomotion-blocking
story_id: "8.9"
epic: 8
previous_story: 8-8-character-micro-motion-techniques
depends_on:
  - 8-3-bg-only-generation-multicard-compositing  # N-card overlay and depth/position placement
  - 8-8-character-micro-motion-techniques         # shared motion constants/off-frame guard style
related:
  - 7-3-character-parallax                        # depth/pan sign precedent
  - 8-4-on-demand-special-pose-cards              # special pose art, not screen-space movement
workflow_decision: "No new LangGraph stage. Extend visual_breakdown cast metadata and consume it in video_node."
---

# Story 8.9: Character Locomotion and Screen Blocking

Status: done

## Story

As Jay,
I want character cards to support a small set of industry-standard screen-space movement/blocking modes selected by the scenario LLM,
so that characters can enter, exit, cross, approach, retreat, or drift within a shot in a controlled way, without pretending static cards have true walk-cycle animation or adding a new workflow stage.

## Context

Story 8.8 covers in-place dynamism: breathing, tremble, pulse, and similar secondary motion. This story is deliberately separate because character **movement through the frame** has different failure modes: clipping, impossible depth changes, subtitles being covered, z-order/position conflicts, and the risk of faking "walking" with a cardboard cutout sliding across the image.

The industry standard to borrow is not "generate arbitrary movement text"; it is state/parameter control. Engines commonly use state machines and blend spaces/trees for locomotion states, with parameters such as speed/direction controlling transitions. In yt.flow's static-card compositor, the equivalent is a closed set of screen-blocking modes and pace values that `video_node` maps to deterministic x/y/scale curves.

This is not a skeletal walk-cycle story. If true footfall animation becomes necessary, that is a future sprite-sheet/rigged-animation or generated-video architecture decision. Here, movement is cinematic blocking of an RGBA card.

## Interfaces

Extend `CastMember` with optional movement fields:

```python
CharacterMovementMode = Literal[
    "anchored",   # no travel; only 8.8 micro-motion and/or parallax
    "drift",      # small composition drift while staying in the same slot
    "enter",      # starts just outside frame and settles at position/depth
    "exit",       # starts at position/depth and leaves frame
    "cross",      # traverses between left/right/center thirds
    "approach",   # depth-scale move toward camera, ending at declared depth
    "retreat",    # depth-scale move away from camera, ending at declared depth
]
CharacterMovementDirection = Literal["none", "left", "right", "in", "out"]
CharacterMovementPace = Literal["slow", "medium", "fast"]

class CastMember(TypedDict):
    card_key: str
    position: CastPosition
    depth: CastDepth
    pose: CastPose
    motion_style: NotRequired[CharacterMotionStyle]      # 8.8
    motion_energy: NotRequired[CharacterMotionEnergy]    # 8.8
    movement_mode: NotRequired[CharacterMovementMode]
    movement_direction: NotRequired[CharacterMovementDirection]
    movement_pace: NotRequired[CharacterMovementPace]
```

Parser defaults:

- missing/invalid `movement_mode` -> `"anchored"`.
- missing/invalid `movement_direction` -> `"none"`.
- missing/invalid `movement_pace` -> `"slow"`.
- incompatible pairs are normalized, not failed:
  - `anchored` or `drift` ignores direction -> `"none"`.
  - `approach` forces direction `"in"`.
  - `retreat` forces direction `"out"`.
  - `enter`/`exit` with `"none"` defaults to `"left"` for `position=="left"`, `"right"` for `position=="right"`, otherwise `"left"` for deterministic behavior.
  - `cross` with `"none"` defaults to the opposite side of `position` when possible; center defaults to `"right"`.

Renderer interpretation:

- `position` and `depth` remain the **settled/end composition** for enter/approach and the **start composition** for exit/retreat.
- Movement is a smooth transform curve over the scene segment duration, not a per-shot physics simulation.
- Movement curves use ease-in/ease-out expressions, not linear-only slides, to avoid sticker-like motion.

## Acceptance Criteria

1. **Domain enum extension.** Given `src/yt_flow/domain/state.py`, then movement mode/direction/pace literal types exist and `CastMember` gains optional movement fields. Drift guard updated.
2. **Lenient parse + compatibility normalization.** Given `scenario_chain.parse_cast`, movement fields are normalized per Interfaces. Tests cover every mode, invalid values, and incompatible-pair repair.
3. **Prompt contract.** Given `visual_breakdown.md`, then the prompt teaches movement as cinematic blocking, not physical gait. It must prefer `anchored`/`drift`; use `enter`/`exit`/`cross` sparingly for motivated shot beats; use `approach` for looming/threat reveal; use `retreat` for withdrawal/recession. No free-text path, x/y numbers, velocity, or bezier fields.
4. **No new workflow stage.** Given the LangGraph topology and API stages, nothing changes. This is cast metadata + video compositor behavior only.
5. **Movement curve builder.** Given a cast member and segment duration, a pure helper returns x/y/scale expressions for the movement layer. It composes additively with 8.8 micro-motion and 7.3 parallax in a defined order: base anchor -> movement curve -> parallax drift -> micro-motion jitter/breath.
6. **Ease curves.** Given movement mode other than `anchored`, the transform uses an ease expression such as `smoothstep(t/duration)` or equivalent. A test asserts the expression is not plain `t/duration` only.
7. **Mode mapping.**
   - `anchored`: no travel.
   - `drift`: small bounded same-slot movement, never crossing into another third.
   - `enter`: starts offscreen in `movement_direction` and settles at `position`.
   - `exit`: starts at `position` and exits toward `movement_direction`.
   - `cross`: moves between thirds, but stays within frame at start/end.
   - `approach`: interpolates scale from one shallower depth plane to declared `depth`.
   - `retreat`: interpolates scale from declared `depth` to one shallower/farther plane.
8. **Off-frame and subtitle safety.** Given any mode/pace/depth, overlay expressions keep the visible card within expected bounds except deliberate enter/exit offscreen intervals. Cards must not spend the final settled frame covering subtitle-safe lower bands beyond current composition rules. Tests enforce final settled x/y/scale bounds.
9. **Z-order stability.** Given multi-card movement, stacking is still derived from `depth` and stable cast order. A moving card must not dynamically reorder across another card mid-shot; dynamic z-sorting is out of scope and would be visually chaotic.
10. **Background-only and anchored identity.** Given no movement fields or all `movement_mode="anchored"`, the output filtergraph remains equivalent to 8.8/8.3 except for field parsing. This protects old checkpoints and unpromoted prompts.
11. **Interaction with special poses.** Given a cast member with `pose_hint`, movement still applies to the resolved hint card exactly like any base pose. The movement system never triggers pose generation and never changes pose lookup.
12. **Trace metadata.** Video trace records counts by movement mode and pace; tracing remains non-fatal.
13. **Tests.** Add parser tests, pure curve tests, multi-card filtergraph tests, off-frame invariant tests, and a real-ffmpeg smoke for at least `enter`, `cross`, and `approach` if ffmpeg is available.
14. **DoD live review.** Render a focused sample with at least one anchored subject, one entering/exiting subject, and one approach/looming subject. Jay-facing evidence should call out whether movement reads as intentional cinematic blocking rather than sliding stickers.

## Tasks / Subtasks

- [x] Task 1 — Schema + prompt (AC: 1, 2, 3, 4)
  - [x] Add movement literal types and optional `CastMember` fields.
  - [x] Extend parse normalization with compatibility repair.
  - [x] Update `cast_decision.md` (not `visual_breakdown.md` — see Completion Notes) and seed candidate per `docs/PROMPT_POLICY.md`.
- [x] Task 2 — Movement math (AC: 5, 6, 7, 8)
  - [x] Implement anchor helpers using 8.3's thirds/depth constants.
  - [x] Implement ease helper and mode mapping.
  - [x] Use the same constants table for filter generation and safety tests.
- [x] Task 3 — Video integration (AC: 5, 8, 9, 10, 11)
  - [x] Compose base anchor -> movement -> parallax -> micro-motion in the per-card overlay expression.
  - [x] Keep z-order fixed by declared depth/list order.
  - [x] Preserve sound/post-fx/subtitle ordering from 8.3 and 8.8.
- [x] Task 4 — Tests and trace (AC: 12, 13)
  - [x] Add parser, curve, filtergraph, off-frame, and trace tests.
  - [x] Add real-ffmpeg smoke if the existing skip-if-unavailable pattern supports it.
- [x] Task 5 — Live validation (AC: 14)
  - [x] Render the focused movement sample and document evidence.

### Review Findings

- [x] [Review][Patch] `resolve_cast_cards` silently dropped `movement_mode`/`movement_direction`/`movement_pace` when building card dicts (both the pose-hint and base-pose branches copy `position`/`depth`/`motion_style`/`motion_energy` but never the 8.9 fields) — the entire feature was wired end-to-end (schema/parser/curve builder/video overlay/trace) but disconnected at this one boundary, so every real pipeline run silently rendered every card as `movement_mode="anchored"` regardless of what the LLM/parser decided. Tests never caught it because `test_video.py`'s card fixture hand-builds "the shape the resolver returns" including movement fields, bypassing the real resolver. Fixed: both branches now copy the three fields with the same default-on-missing convention as `motion_style`/`motion_energy`; added 3 regression tests (`tests/services/test_character_angle_selector.py`) covering defaults, explicit pass-through, and the pose-hint branch. [`src/yt_flow/services/character_service.py:1227-1240,1273-1291`]
- [x] [Review][Patch] `_repair_movement`'s generic "explicit left/right direction passes through" check ran before `cross`'s opposite-side default, so `movement_mode="cross"` with `movement_direction` equal to `position` (e.g. both `"left"`) collapsed to a zero-amplitude no-op — the card never crosses anything despite `cross` being explicitly requested. A test (`test_parse_cast_cross_keeps_explicit_valid_direction`) had locked in exactly this degenerate combination as "valid." Fixed: `cross` now resolves its direction fully within its own branch, only honoring an explicit direction when it differs from `position`; corrected the test to use a genuinely non-degenerate case (`position="center"`, explicit `"left"` overriding the `"right"` default) and added a new parametrized test asserting the same-side case now repairs to the opposite side. [`src/yt_flow/pipeline/nodes/scenario_chain.py:99-118`]
- [x] [Review][Patch] AC2 ("tests cover every mode, invalid values, and incompatible-pair repair") had no dedicated invalid-value test for `movement_direction` (only `movement_mode`/`movement_pace` had one). Added a parametrized test mirroring the existing pattern. [`tests/pipeline/nodes/test_scenario_chain.py`]
- [x] [Review][Patch] Live-validation README claimed APPROACH shows "no x/y drift" and "symmetric" edge expansion, but its own bounding-box table shows a ~10px vertical centroid shift alongside the scale change. Reworded to match the data (attributed to idle-motion wobble riding on top of the movement curve). [`_bmad-output/implementation-artifacts/8-9-live-validation/README.md`]
- [x] [Review][Defer] Movement curves are built against the scene's full `audio_duration` and only the first shot with an `image_path` per scene is ever composited, so an `enter`/`exit`/`cross`/`approach` curve motivated by one specific sentence beat stretches across the whole scene rather than a shot-local window — deferred, pre-existing Story 1.9/8.3 scene-level compositing architecture, not introduced by this story. [`src/yt_flow/pipeline/nodes/video.py`]
- [x] [Review][Defer] `approach`/`retreat` on `depth="far"` is a silent zero-amplitude no-op (`_SHALLOWER_DEPTH` clamps far to itself) — already covered by an accepting test as "still valid," but `cast_decision.md` never warns the LLM away from pairing these modes with far depth. Deferred as a prompt-tuning follow-up, not a code defect. [`src/yt_flow/pipeline/nodes/character_movement.py`, `prompts/scenario/cast_decision.md`]
- [x] [Review][Defer] The `cast_decision.md` movement-teaching prompt addition landed bundled inside an unrelated commit (`342d6af feat(scenario): add cached YAML stage retries`, alongside an unrelated JSON→YAML output-format change) — a git-history hygiene gap, not fixable without rewriting already-merged history. [`prompts/scenario/cast_decision.md`]
- [x] [Review][Defer] AC14's actual DoD question ("does movement read as intentional cinematic blocking vs. a sliding sticker") is not answered by the synthetic-card live-validation evidence — the README's own "What this does NOT validate" section already says so and defers a real-SCP render + Jay's live viewing judgment, consistent with the story's own Saved Questions. Not a code fix. [`_bmad-output/implementation-artifacts/8-9-live-validation/README.md`]

Dismissed as noise (12): center-position tie-break differs between enter/exit (→left) and cross (→right) — matches the Interfaces spec's own literal text, not a bug; `DRIFT_PX` is a fixed-pixel (not `main_w`-relative) constant — moot, the whole compositor hardcodes `COMP_W=1920` with no variable-resolution path; `sign` fallback in enter/exit treating non-"left" as "right" — safe, `_repair_movement` already guarantees left/right upstream; `_normalize_enum` unhashable-input concern — verified safe (`isinstance(raw, str)` guard runs first); story completion notes being self-attested — not a code finding; `_SHALLOWER_DEPTH` comment's "shallower" terminology — matches the Interfaces section's own wording; `_repair_movement`'s trailing fallback return — defensive AD-10 completeness, not true dead code; `_ease_progress`'s `span<=0` guard — harmless defensive code, unreachable only given today's callers; smoothstep expression recomputing its `min()` subterm three times — premature optimization for a per-frame arithmetic cost that doesn't matter at this scale; `drift` mode ignoring `movement_direction` — dead parameter but unreachable via the sanctioned parser path; no atomicity guard at the video.py/resolver boundary for a hypothetical future partial fix — moot once the three fields are copied together atomically (this review's fix #1); AC5 scale-chain composition-order test gap — order is correct by direct inspection of `_compose_scene`'s linear string concatenation (scale → movement → parallax zoom → pulse), not worth new integration-test scaffolding for near-zero real risk.

## Dev Notes

### Current code to read before editing

- `src/yt_flow/domain/state.py` — cast metadata types.
- `src/yt_flow/pipeline/nodes/scenario_chain.py::parse_cast` — enum normalization.
- `src/yt_flow/pipeline/nodes/video.py` after 8.3/8.8 — card placement, depth scale, overlay, parallax, and micro-motion helpers.
- `_bmad-output/implementation-artifacts/8-3-bg-only-generation-multicard-compositing.md` — position/depth/stacking contract.
- `_bmad-output/implementation-artifacts/8-8-character-micro-motion-techniques.md` — shared motion safety philosophy.

### Implementation guidance

- Do not simulate walk cycles by sliding every character all the time. Movement must be rare and motivated by the shot.
- Do not add path points or numeric coordinates to the LLM contract. If the seven modes are insufficient, add one well-named enum later after live evidence.
- Treat `position`/`depth` as the stable composition contract. Movement fields describe how the card arrives, leaves, or shifts relative to that contract.
- Use deterministic ease expressions. Avoid runtime random.
- Do not dynamically change z-order during movement.

## Architecture Compliance

- AD-1: schema in domain; parser and video helpers stay in pipeline; no services/db/api imports.
- AD-2: only enum strings are stored in LangGraph state.
- AD-4: no new service events or DB writes.
- AD-10: invalid LLM values normalize; trace failures never fail the run.

## Latest Technical Information

- Unity's Blend Trees use controlled parameters to blend related motions such as walk/run or leaning during a run: https://docs.unity3d.com/Manual/class-BlendTree.html
- Godot's AnimationTree supports StateMachine transitions and BlendSpace1D/2D parameterized blending: https://docs.godotengine.org/en/latest/tutorials/animation/animation_tree.html
- FFmpeg overlay examples include time-based coordinate expressions and chained overlays, which is the implementation substrate for screen-space blocking: https://ffmpeg.org/ffmpeg-filters.html

## Project Structure Notes

- Expected modifications: `src/yt_flow/domain/state.py`, `src/yt_flow/pipeline/nodes/scenario_chain.py`, `src/yt_flow/pipeline/nodes/video.py` or same-layer motion helper module, `prompts/scenario/visual_breakdown.md`, tests.
- No DB migration.
- No new workflow stage or gate.
- No new runtime dependency.

## References

- `_bmad-output/implementation-artifacts/8-3-bg-only-generation-multicard-compositing.md` — card placement, derived stacking, position/depth meaning.
- `_bmad-output/implementation-artifacts/8-8-character-micro-motion-techniques.md` — micro-motion split and shared safety constraints.
- `_bmad-output/implementation-artifacts/7-3-character-parallax.md` — pan sign/off-frame invariant pattern.
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` — AD-1, AD-2, AD-4, AD-10.

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5

### Debug Log References

None — no HALT conditions hit. `--profile smoke` single-run diagnostics on the
candidate hit two unrelated flaky YAML-parse failures (`visual_breakdown`,
`tts_normalize` stages, not `cast_decision`), consistent with the
already-documented generation-noise findings from Stories 6.9/6.10/6.11; the
`--stage cast_decision` isolation diagnostic (the stage this story actually
changes) passed clean for all three golden SCPs (SCP-049, SCP-096, SCP-173).

### Completion Notes List

- Schema (`CharacterMovementMode/Direction/Pace`, `CastMember` fields),
  parser normalization (`_repair_movement`/`_parse_movement_fields` in
  `scenario_chain.py`), the pure curve builder (`character_movement.py`), and
  video integration (`_movement_scale_filter`/`_overlay_filter` composition
  order in `video.py`) were already implemented and merged to master prior to
  this session (commit `29f5a74`), with full parser/curve/filtergraph/
  off-frame/z-order/trace/real-ffmpeg-smoke test coverage already in place
  (1274 passed / 1 skipped, ruff clean). This session picked the story up
  in-progress, verified every AC against the actual code/tests/prompt rather
  than trusting the (still-unchecked) task list, and closed the two gaps that
  were genuinely outstanding: the prompt-policy candidate-eval step and the
  Task 5 live validation render.
- **AC:3 deviation, deliberate.** The story's Interfaces section names
  `visual_breakdown.md` as the prompt to update. The actual implementation
  teaches `movement_mode`/`movement_direction`/`movement_pace` in
  `prompts/scenario/cast_decision.md` instead, alongside 8.8's
  `motion_style`/`motion_energy` — cast decisions (including movement) are a
  separate LLM stage from visual composition since the 8.10 stage split, and
  `cast_decision.md` is the prompt that actually owns per-card cast fields.
  This mirrors 8.8's own precedent (recorded in that story's Completion
  Notes) and keeps all card-level cast vocabulary in one prompt. No AC:3
  content requirement is unmet — sparse/anchored-first guidance, all seven
  modes, and the "no free-text path/numbers/velocity" constraint are present.
- **Prompt-policy step.** `prompts/scenario/cast_decision.md` (with the
  movement teaching) is already seeded to Langfuse as `scenario/cast_decision`
  candidate v8 (verified live against the project's Langfuse host); production
  is still v3 (pre-movement). Per Story 6-12 (concurrent work landing this
  same day — `docs/PROMPT_POLICY.md`'s new frozen-gate banner), the
  candidate-vs-production A/B promotion gate (`--baseline`, `--profile
  promotion`) is intentionally FROZEN project-wide during pipeline
  development and requires `YTFLOW_ALLOW_AB_GATE=1` to run — promoting this
  candidate to `production` is out of scope here and deferred to the
  quality-tuning phase per that policy. What *is* in scope and done: the
  candidate is seeded, and `scripts/eval_prompts.py --stage cast_decision
  --label candidate` (single-label, not frozen) passed clean on all three
  golden-set SCPs.
- **Task 5 / AC:14 live validation.** Rendered a real one-scene, 3-card,
  4-second sample through the actual `_compose_scene()` code path (real
  ffmpeg, not a hand-rolled filtergraph) with one `anchored`, one `enter`,
  and one `approach` card. Quantitative bounding-box tracking across 5
  sampled frames confirms: anchored holds a ~3px-wide box (idle-motion-only
  wobble, no travel); enter is undetected (offscreen) for the first ~1.5s
  then settles into a stable window by t=3s; approach's width grows ~39%
  toward camera with no x/y drift. Evidence, frames, and the rendered clip
  are at `_bmad-output/implementation-artifacts/8-9-live-validation/`
  (README + `motion_sample.mp4` + 5 frame grabs). Per the same precedent 8.8
  set: this validates the mechanism objectively; whether `enter`/`approach`
  *reads* as intentional cinematic blocking rather than a sliding sticker on
  real character art is a subjective call the README defers to Jay, with a
  real-SCP render recommended before broadening `movement_mode` use beyond
  what `cast_decision.md` already recommends sparingly.
- AC:11 (pose_hint interaction) is satisfied by construction, not a
  dedicated new test: `video.py` reads `movement_mode`/`direction`/`pace`
  unconditionally off the resolved card dict (no branch on `pose_hint`
  presence), and `parse_cast` treats `pose_hint` and the movement fields as
  independent optional keys on the same entry — both already have full
  passing coverage in isolation.
- Full regression: `uv run pytest tests/ -q` → 1274 passed, 1 skipped
  (unrelated Qwen TTS smoke, opt-in only), `ruff check` clean.

### File List

- `src/yt_flow/domain/state.py` (movement literal types + `CastMember` fields — pre-existing this session)
- `src/yt_flow/pipeline/nodes/character_movement.py` (new — pure movement curve builder, pre-existing this session)
- `src/yt_flow/pipeline/nodes/scenario_chain.py` (`_repair_movement`/`_parse_movement_fields`/`parse_cast` — pre-existing this session)
- `src/yt_flow/pipeline/nodes/video.py` (`_movement_scale_filter`, `_overlay_filter` movement params, trace mode/pace counts — pre-existing this session)
- `prompts/scenario/cast_decision.md` (movement teaching — pre-existing this session; supersedes the story's `visual_breakdown.md` reference, see Completion Notes)
- `tests/domain/test_state_imports.py` (pre-existing this session)
- `tests/pipeline/nodes/test_character_movement.py` (new — pre-existing this session)
- `tests/pipeline/nodes/test_scenario_chain.py` (movement parser tests — pre-existing this session)
- `tests/pipeline/nodes/test_video.py` (movement integration/z-order/trace/real-ffmpeg tests — pre-existing this session)
- `_bmad-output/implementation-artifacts/8-9-live-validation/README.md` (new, this session)
- `_bmad-output/implementation-artifacts/8-9-live-validation/motion_sample.mp4` (new, this session)
- `_bmad-output/implementation-artifacts/8-9-live-validation/frame_t{0.0,1.0,2.0,3.0,3.9}.png` (new, this session)

## Change Log

- 2026-07-08: Story created from Jay request for industry-standard character movement. Split from 8.8 because locomotion/blocking has different safety and visual validation requirements.
- 2026-07-12: Resumed in-progress story. Verified Tasks 1-4 (schema, parser, movement math, video integration, tests, trace) were already implemented and merged (commit `29f5a74`); confirmed via full regression (1274 passed/1 skipped, ruff clean) and stage-isolated candidate-prompt diagnostics (3/3 golden SCPs OK). Closed remaining Task 5 (AC:14 live validation render + evidence). Recorded the AC:3 `cast_decision.md` vs `visual_breakdown.md` prompt-target deviation and the Story 6-12 A/B-gate-freeze scope boundary. Status -> review.
- 2026-07-12: Code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor). Found and fixed a critical wiring bug: `resolve_cast_cards` never copied `movement_mode`/`movement_direction`/`movement_pace` onto resolved cards, so the entire feature rendered as `anchored` in every real run despite full schema/parser/curve/video-integration test coverage passing. Also fixed a `cross`-mode direction-repair bug that collapsed to a zero-amplitude no-op when the LLM's explicit direction matched its position (a test had locked in the buggy behavior). Added AC2 test coverage gap (invalid `movement_direction`) and corrected an overstated claim in the live-validation README. 4 patches applied, 4 items deferred (pre-existing scene-vs-shot timing granularity, far-depth approach/retreat no-op, a git-hygiene commit-bundling note, and AC14's live-viewing judgment already flagged by this story's own Saved Questions), 12 findings dismissed as noise/already-safe. Full regression: 1298 passed/1 skipped, ruff clean. Status -> done.

## Saved Questions / Clarifications

1. If live samples make `cross` look like a sliding sticker, keep parser support but remove it from the prompt recommendation until there is a sprite-sheet/rigged option.
2. If approach/retreat works well, consider a later prompt-tuning pass to use it for only the strongest reveal beats; do not broaden movement by default.
