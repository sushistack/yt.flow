---
story_key: 10-8-cast-pose-angle-coverage
story_id: "10.8"
epic: "Epic 10: 시청 판정 결함 정정 — 2026-08-08 Jay E2E 리뷰"
created: 2026-08-15
source_status_before: backlog
baseline_commit: 4769608b4b1c05b7129ed716f087e22fdcb15495
---

# Story 10.8: 캐스트 포즈·앵글 커버리지 — 같은 정면 그림이 21샷 반복되는 것

Status: draft

## Story

As Jay,
I want a character on screen to face and stand differently as the scene demands,
so that a three-minute video stops showing the same front-facing standing figure twenty-one times with only its size and screen position changing.

## Context

Live run `e5ed4b3a` (2026-08-15, SCP-049, 43 shots) placed cast **40 times**. Of those, **26 were fallbacks** — and the surviving variety was almost nil:

| 실제로 화면에 쓰인 카드 | 샷 수 |
|---|---|
| `SCP-049 standing/front` | 21 |
| `STOCK-researcher standing/front` | 6 |
| `SCP-049-2 standing/front` | 6 |
| `STOCK-d-class standing/front` | 3 |
| `SCP-049 sitting/front` | 2 |
| `SCP-049 hint:b36d4021a2/front` | 1 |
| `STOCK-d-class hint:475c8a9231/front` | 1 |

Fallback reasons: **`angle` 23, `asset` 3**. Every single card actually drawn was `front`.

Jay named this directly on reviewing the render: *"대부분의 캐릭터들이 그냥 정면 서있는 샷 밖에 없음."*

### It is two layers, and fixing either alone changes nothing on screen

**Layer 1 — the prompt asks for almost no variety.** [cast_decision.md:45-53](../../prompts/scenario/cast_decision.md) gives `pose` a closed two-value vocabulary (`standing` | `sitting`) and makes `pose_hint` deliberately rare: *"Most cast entries MUST omit it"*, *"no more than about 3 distinct hints in the whole scene"*. The model obeyed — the whole nine-scene script emitted **2 hints** across 40 placements (`lying on operating table`, `reaching toward camera`).

**Layer 2 — the library has only `front` for the pose actually used.** SCP-049's approved rows are four `sitting_*` angles plus two `hint:` cards; there is no approved `standing` card at any angle, which is why 21 placements resolved through an `angle` fallback to a front-facing standing asset.

There is a third, quieter finding: `pose_guide_conditioning_enabled` was flipped ON on 2026-08-14, but its own comment states it *"reaches only cards that do not exist yet (`_ensure_special_pose_cards` skips any hint with an approved row)"*. With hints this rare, the flag has almost nothing to act on. Turning it on changed nothing visible in this run.

### What is NOT the problem

Card resolution is healthy: the real `resolve_cast_cards` returned **40/40 with a path** — nothing was missing. A hand-rolled DB query on `(scp_id, pose, angle)` makes `SCP-049-2` and `STOCK-researcher` look absent and that reading is wrong; the resolver's angle/asset fallbacks cover them. (This mistake was made and corrected on 2026-08-15 — do not repeat it. Call the resolver.)

Story 13.1 is what made the 26 fallbacks visible at all: before it, the resolved card reported `fallback=False` on a pose miss, so the question was unanswerable downstream. The `cast_card_fallback` warnings this story works from are that mechanism paying off.

## Acceptance Criteria

1. **The scenario asks for the variety the composition needs.** `cast_decision`'s pose/angle vocabulary is widened so a shot can express facing (at minimum: which way the figure faces relative to camera) without needing a rare free-text `pose_hint`. The closed-vocabulary discipline stays — the fix is a richer closed vocabulary, not free text. Story 12.4 established that closed vocabularies with code-side rejection are how this project keeps LLM fields honest.
2. **Angle actually reaches the resolver.** Today 23 placements fell back with `fallback_reason: angle`, which means an angle *was* requested and was unavailable. Trace where the requested angle comes from and make the scenario's intent reach it; a widened prompt that the resolver ignores is a no-op.
3. **The library covers the base poses at all canonical angles.** For every card key a run can place, the approved set spans `CANONICAL_ANGLES` for each base pose in the vocabulary. Generation reuses the existing card pipeline; no new generation architecture.
4. **Coverage is measurable before a render.** A command reports, per card key, which (pose, angle) combinations are approved and which are missing. The gap should be visible without running a three-hour E2E and counting warnings afterwards.
5. **Fallback rate is the acceptance number.** Re-run the same scenario (or an equivalent 40-placement script) and report the fallback count and reasons against this story's baseline of **26/40 (angle 23, asset 3)**. State the target before measuring.
6. **`pose_guide_conditioning_enabled`'s reach is re-examined (AC: 3 interaction).** If the new vocabulary produces more special poses, the 10.5 guide path starts mattering; confirm whether its "skip any hint with an approved row" behaviour is still right when the library is being deliberately filled.
7. **Style consistency is not regressed.** New cards must match the epoch of the approved cards they sit beside. Run `e5ed4b3a` already mixes epochs on screen (SCP-049 approved at epoch 1, STOCK-d-class at epoch 2) — do not widen that gap while filling coverage. Story 10.3's style work is the reference.
8. **Known generation caveat is handled, not rediscovered.** `pose_guide_conditioning_enabled`'s comment records that one of three guided seeds drew **two figures in one sprite**, and that "a figure-count check on the generated sprite is the thing that would retire this caveat". Filling the library at scale multiplies that risk; either add the check or state explicitly why it is deferred.
9. **Live gate.** A rendered comparison — same scenario, before/after — showing the on-screen variety changed. Committed per CLAUDE.md's live-validation rules: adjudication images plus the scripts that re-derive the counts.

## Tasks / Subtasks

- [ ] **Task 0 — Coverage report first (AC: 4)** — it tells you how big Task 3 is.
- [ ] **Task 1 — Vocabulary (AC: 1, 2)** — prompt + the schema/validator that rejects invalid values, then follow the value through `cast_decision` → `resolve_cast_cards` and prove it lands.
- [ ] **Task 2 — Generate the missing cards (AC: 3, 7)**
- [ ] **Task 3 — Figure-count check on generated sprites (AC: 8)**
- [ ] **Task 4 — Re-measure fallbacks (AC: 5)**
- [ ] **Task 5 — Live gate (AC: 9)**

## Dev Notes

### Traps

1. **Do not simulate the resolver.** `resolve_cast_cards` has angle and asset fallbacks; a hand-written `(scp_id, pose, angle)` lookup reports missing cards that in fact resolve. Call the real thing.
2. **Card approval is publication.** `gotcha_standing-cards-have-no-approval-gate` — writing `angle_*_path` ships the card; there is no status/epoch filter downstream. Approve deliberately.
3. **Framing is arithmetic, not prompting.** `gotcha_sprite-scale-and-two-figure-detection` — card framing comes from alpha-bbox arithmetic, and overlapping two-figure cards are a bbox problem. Do not try to prompt your way out of scale issues.
4. **"SCP Foundation" in a card prompt is the mask attractor** (`gotcha_scp-foundation-token-poisons-cards`), and one negative clause per defect has wrecked renders twice (`gotcha_negative-prompt-overstuffing`). Screen prompt changes as text before spending GPU (`gotcha_screen-a-prompt-change-before-you-render-it` — 109 seconds saved ~6 GPU-hours).
5. **`pose` is a writing-adjacent field.** Check which step owns it before editing schemas; `gotcha_location-is-a-writing-field-not-a-structure-field` records the sibling mistake for `location`.

### Files

**UPDATE**
- [prompts/scenario/cast_decision.md](../../prompts/scenario/cast_decision.md) — pose/pose_hint/pose_guide_key vocabulary at ~45-62 and the "use sparingly" guidance at ~113.
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — cast normalisation/validation (`_normalize_enum`, `_VALID_POSES`).
- [src/yt_flow/services/character_service.py](../../src/yt_flow/services/character_service.py) — `resolve_cast_cards`, `_ensure_special_pose_cards`, `CANONICAL_ANGLES`.
- Prompt change requires seeding per CLAUDE.md DEV MODE; verify beforehand which prompts actually differ so unrelated drift is not collaterally promoted (2026-08-15 found `character/angle_selection` and `character/generation` already drifted from Langfuse).

### References

- [Source: _bmad-output/implementation-artifacts/13-1-surface-silent-degradations.md] — the `cast_card_fallback` warning this story measures
- [Source: _bmad-output/implementation-artifacts/10-5-action-state-on-cards.md] — the ControlNet guide path and its two-figure caveat
- [Source: _bmad-output/implementation-artifacts/10-6-cast-visual-identity.md]
- Project memory: `project_e2e-iteration3-done` (the 26/40 breakdown), `project_13-1-review-done`, `gotcha_sprite-scale-and-two-figure-detection`, `gotcha_standing-cards-have-no-approval-gate`

## Dev Agent Record
