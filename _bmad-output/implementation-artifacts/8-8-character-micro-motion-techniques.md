---
created: 2026-07-08
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

Status: ready-for-dev

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

- [ ] Task 1 — Schema + prompt (AC: 1, 2, 3, 4)
  - [ ] Add `CharacterMotionStyle`, `CharacterMotionEnergy`, and optional cast fields.
  - [ ] Extend `parse_cast` with lenient normalization.
  - [ ] Update visual_breakdown prompt and follow `docs/PROMPT_POLICY.md` candidate seeding/eval; production promotion is Jay's decision.
- [ ] Task 2 — Motion parameter table (AC: 5, 6, 7)
  - [ ] Define one constants table mapping `(style, energy)` to amplitude/frequency/scale terms.
  - [ ] Keep constants in pixels and scale deltas, not user/LLM-provided numbers.
  - [ ] Compute max excursion from the same table used to build filters; tests use the table, not duplicated magic numbers.
- [ ] Task 3 — Video integration (AC: 6, 8, 9)
  - [ ] Generalize 8.3's per-card overlay builder to accept `motion_style`, `motion_energy`, `phase_seed`, and depth.
  - [ ] Preserve parallax as an additive layer; `hold` removes idle/micro-motion only.
  - [ ] Confirm sound-design input offsets still match N-card inputs.
- [ ] Task 4 — Tests and trace (AC: 7, 8, 10, 11)
  - [ ] Add parser, drift, expression, filtergraph, and off-frame invariant tests.
  - [ ] Add metadata count tests.
- [ ] Task 5 — Live validation (AC: 12)
  - [ ] Render a focused sample with multiple styles and record evidence in Dev Agent Record.

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

### Debug Log References

### Completion Notes List

### File List

## Change Log

- 2026-07-08: Story created from Jay request for industry-standard character dynamism techniques. Split from locomotion/blocking by design; this story owns in-place/procedural micro-motion and explicitly rejects a new workflow stage.

## Saved Questions / Clarifications

1. If Jay finds `glitch` too stylized for SCP documentary tone, remove it from the prompt while keeping parser support for backward compatibility.
2. If live renders show `pulse` reads like breathing rather than supernatural presence, tune the constants table first; do not add more enum values until evidence demands it.
