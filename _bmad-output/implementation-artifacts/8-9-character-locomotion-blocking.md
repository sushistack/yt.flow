---
created: 2026-07-08
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

Status: ready-for-dev

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

- [ ] Task 1 — Schema + prompt (AC: 1, 2, 3, 4)
  - [ ] Add movement literal types and optional `CastMember` fields.
  - [ ] Extend parse normalization with compatibility repair.
  - [ ] Update `visual_breakdown.md` and seed/evaluate candidate per `docs/PROMPT_POLICY.md`.
- [ ] Task 2 — Movement math (AC: 5, 6, 7, 8)
  - [ ] Implement anchor helpers using 8.3's thirds/depth constants.
  - [ ] Implement ease helper and mode mapping.
  - [ ] Use the same constants table for filter generation and safety tests.
- [ ] Task 3 — Video integration (AC: 5, 8, 9, 10, 11)
  - [ ] Compose base anchor -> movement -> parallax -> micro-motion in the per-card overlay expression.
  - [ ] Keep z-order fixed by declared depth/list order.
  - [ ] Preserve sound/post-fx/subtitle ordering from 8.3 and 8.8.
- [ ] Task 4 — Tests and trace (AC: 12, 13)
  - [ ] Add parser, curve, filtergraph, off-frame, and trace tests.
  - [ ] Add real-ffmpeg smoke if the existing skip-if-unavailable pattern supports it.
- [ ] Task 5 — Live validation (AC: 14)
  - [ ] Render the focused movement sample and document evidence.

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

### Debug Log References

### Completion Notes List

### File List

## Change Log

- 2026-07-08: Story created from Jay request for industry-standard character movement. Split from 8.8 because locomotion/blocking has different safety and visual validation requirements.

## Saved Questions / Clarifications

1. If live samples make `cross` look like a sliding sticker, keep parser support but remove it from the prompt recommendation until there is a sprite-sheet/rigged option.
2. If approach/retreat works well, consider a later prompt-tuning pass to use it for only the strongest reveal beats; do not broaden movement by default.
