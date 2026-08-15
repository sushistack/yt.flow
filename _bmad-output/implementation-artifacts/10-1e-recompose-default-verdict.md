---
story_key: 10-1e-recompose-default-verdict
story_id: "10.1e"
epic: "Epic 10: 시청 판정 결함 정정 — 2026-08-08 Jay E2E 리뷰"
created: 2026-08-15
source_status_before: backlog
baseline_commit: 4769608b4b1c05b7129ed716f087e22fdcb15495
depends_on: 10-1d-recompose-runtime-preflight
---

# Story 10.1e: Recompose on/off 페어 채점과 기본값 판정 — 10.1c 해제 조건 (a)

Status: draft

## Story

As Jay,
I want a paired recompose-on/off render set scored on 13-2's rebuilt axes,
so that the decision to make LLM re-composition the default rests on a measurement rather than on two conflicting impressions — my own PASS verdict on the motion, and 10.4's audit that said the recomposed frames were harder to read.

## Context

Story 10.1c shipped recompose and left it off. Its verdict names three reasons; this story addresses the first and decisive one:

> (a) 10.4's post-hoc audit scored recomposed frames **WORSE** on blind legibility than the plates they replaced — unreadable 20% vs 13%, misread-as-corridor 57% vs 27% — on this epic's largest defect cluster

The tension is genuine and unresolved: the same feature passed Jay's motion review on the 3:06 render (findings 3·11 gone, 0 composition collapses across a 42-plate sweep) while failing a legibility audit. Those are different axes, measured by different means, on different sample sets. Nobody has scored **the same shots both ways**.

Story 13-2 rebuilt the visual evaluation axes precisely because the old Likert scale collapsed to a single value (`gotcha_likert-axis-with-no-variance-below-4`) and replaced it with DSG; it is `done`. The 10.1c comment's own unblock condition is therefore now runnable:

> UNBLOCK: when 13-2's rebuilt evaluation axes score a paired recompose-on/off set, flip if legibility is neutral-or-better AND a runtime-prerequisite guard exists.

**This story is condition (a). Story 10.1d is condition (b) and must land first** — without the preflight, a recompose render run on a stock ComfyUI swap-deadlocks for ~12 minutes per pass with no fallback, which would silently corrupt the sample rather than fail it.

## Acceptance Criteria

1. **Paired, not parallel.** The same shots, same seeds, same plates, rendered once with `shot_recompose_enabled=False` and once with it True. A comparison across different scenes or different runs cannot separate the treatment from the content — Story 10.4 died as an A/B precisely because its lever was confounded (`project_10-4-blocked-ab-in-noise`).
2. **Scored on 13-2's axes, blind.** The scorer must not be able to tell which arm produced a frame. Story 12.5 recorded that provider-named originals sitting beside a blind package are a second reveal (`gotcha_blind-package-raw-originals-are-a-second-reveal`) — put every identifiable artifact behind one boundary.
3. **Legibility is the deciding axis, and it is pre-registered.** The 10.1c verdict's numbers (unreadable 20% vs 13%, misread-as-corridor 57% vs 27%) are the incumbent claim. State before scoring what result would flip the default and what would keep it off; do not choose the threshold after seeing the numbers.
4. **Sample size is stated with its band.** Report n, the per-arm counts, and the coordinates/criteria of every measurement, so the numbers are re-derivable. A measurement without its sample band is unreproducible (`gotcha_a-measurement-without-its-sample-band`).
5. **Cost is measured, not assumed.** The 10.1c verdict's third reason is 90–120s × 51 passes adding 1.3–1.7h to a 2h E2E budget. Re-measure it *with 10.1d's prerequisites satisfied* — the earlier figure was taken on a stock install, and run `e5ed4b3a` showed the same class of misconfiguration inflating a 14.8s shot to 491s. The cost objection may be much smaller than recorded, or unchanged; either way it should be a fresh number.
6. **The verdict is written down wherever the default lives.** Whatever the outcome, `config.py`'s verdict comment is updated with the new evidence and date. If the default flips, the comment records what flipped it; if it stays off, it records that (a) was tested and what failed.
7. **The retirement question is answered explicitly.** The 10.1c comment states that the flip commit is also what retires the overlay-only machinery (ground placement, `_GROUND_Y_MAX`, occlusion, contact shadow, 11.5 parallax, 1.9c idle motion) — *"while this stays False they are the production path, not dead code"*. If the default flips, say plainly whether that retirement happens here or in a follow-up; do not leave two production paths without an owner.
8. **Opposite-direction results are preserved.** If some axes favour recompose and others do not, report both rather than a single verdict number — 13-2 kept 3 contrary results for exactly this reason.

## Tasks / Subtasks

- [ ] **Task 0 — Confirm 10.1d has landed.** Without the preflight this story cannot produce a trustworthy sample.
- [ ] **Task 1 — Pick the paired sample (AC: 1, 4)** — reuse an existing shot set with committed plates if one fits; run `e5ed4b3a`'s 43 shots are a candidate and their provenance sidecars (Story 13.3) record the exact workflow hash and seeds.
- [ ] **Task 2 — Render both arms**
- [ ] **Task 3 — Blind package + scoring on 13-2 axes (AC: 2, 3, 8)**
- [ ] **Task 4 — Cost re-measurement (AC: 5)**
- [ ] **Task 5 — Verdict + config comment (AC: 6, 7)**
- [ ] **Task 6 — Live-validation artifacts** per CLAUDE.md: commit the adjudication images the verdict cites plus the scripts that re-derive every number; gitignore the raw renders with a header explaining what is regenerable.

## Dev Notes

### Traps

1. **Do not flip the default as a side effect of measuring.** The flip is a separate, deliberate act with a written rationale.
2. **`--disable-smart-memory` offloads to system RAM**, which is the scarce resource on this box (31 GB, and run `e5ed4b3a` hit 14 GB resident + 4 GB swap on a *lighter* path). The recompose prerequisites and the box's memory ceiling interact; measure with headroom, not against it.
3. **Legibility is this epic's largest defect cluster** — `project_10-4b-blocked-measurability` recorded `visible_event 84.9%` as the surviving live defect. A recompose default that worsens legibility trades the epic's main axis for motion quality.
4. **Story 8.20's Qwen-Image-Edit VRAM figures are not transferable** — `gotcha_qwen-image-edit-rejection-was-version-specific` records that rejection notes were misapplied three times. Check version and purpose before citing any prior VRAM number.

### References

- [Source: src/yt_flow/config.py#L293-307] — the verdict and its unblock condition, verbatim
- [Source: _bmad-output/implementation-artifacts/10-1c-shot-recompose-qwen.md]
- [Source: _bmad-output/implementation-artifacts/13-2-visual-eval-axes.md] — the scoring axes
- Project memory: `project_10-4-blocked-ab-in-noise`, `gotcha_a-measurement-without-its-sample-band`, `gotcha_blind-package-raw-originals-are-a-second-reveal`, `gotcha_likert-axis-with-no-variance-below-4`, `project_card-plate-recreation-not-overlay`

## Dev Agent Record
