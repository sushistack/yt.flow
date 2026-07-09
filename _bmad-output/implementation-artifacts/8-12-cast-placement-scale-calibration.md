---
created: 2026-07-09
story_key: 8-12-cast-placement-scale-calibration
story_id: "8.12"
epic: 8
previous_story: 8-11-per-shot-cut-assembly
depends_on:
  - 8-10-cast-decision-split-call        # cast_decision.md is the prompt being calibrated
related:
  - 8-11-per-shot-cut-assembly           # without per-shot cuts, placement variety is invisible on screen
  - 8-3-bg-only-generation-multicard-compositing  # position/depth → x/scale mapping being fed
workflow_decision: "Prompt-only story. No code changes. PROMPT_POLICY change protocol governs (candidate seed → golden-set gate → promote)."
evidence: "Iteration 1 run d55a265b: position center 65 / right 10 / left 8; depth near 37 / mid 44 / far 2. Jay viewing feedback #2/#3 (2026-07-09)."
---

# Story 8.12: Cast Placement & Scale Calibration (prompt-only)

Status: ready-for-dev

## Story

As Jay,
I want the cast_decision LLM to distribute characters across the frame and choose depths that agree with the shot's framing,
so that characters stop being pasted dead-center at a near-arbitrary size in every shot (feedback #2/#3).

## Context

Iteration 1 measured distributions over 83 cast entries:

- `position`: **center 65 / right 10 / left 8** — the compositor supports rule-of-thirds slots (`_POSITION_X_FRAC` 1/3, 1/2, 2/3 from 8.3), but the LLM defaults to center.
- `depth`: **near 37 / mid 44 / far 2** — almost everything renders large; "size looked coincidentally OK" (feedback #3) because the depth→scale rule is deterministic but the depth *choice* is uncalibrated.

Two prompt-side causes, one per file:

1. `prompts/scenario/cast_decision.md` currently teaches the **fields** (`position`, `depth`) but gives **zero guidance** on how to choose them — no composition principle, no distribution expectation, no anti-repetition rule.
2. Backgrounds themselves are overwhelmingly central-vanishing-point corridors/rooms (`visual_breakdown.md` few-shots), which makes `center` always look "safe" to the model and starves left/right slots of natural anchor points.

**Pipeline order constraint (from 8.10):** `cast_decision` runs BEFORE `visual_breakdown` — cast is decided per sentence, then visual_breakdown composes shots *consuming* the already-decided cast. Therefore camera-consistency rules must be split accordingly: cast_decision cannot see `camera_angle` (it doesn't exist yet); visual_breakdown CAN see the chosen `depth` and must pick a `camera_angle` that agrees with it.

## Scope guard

- **Prompt-only.** No schema, parser, or video.py changes. The enums and their rendering semantics are frozen contracts (8.3/8.8/8.9).
- **Derived-entity vocabulary untouched.** `<scp_id>-<n>` (e.g. SCP-049-2) stays in the prompt — the missing-card gap for derived entities is a separate pending decision (iteration-1 report, next-actions #1). Do not "fix" it here by deleting the vocabulary.
- Both prompts follow `docs/PROMPT_POLICY.md`: edit repo file → seed `candidate` → A/B + golden-set gate → Jay promotes.

## Acceptance Criteria

1. **cast_decision.md placement rules added** (new "Composition" section):
   - Rule-of-thirds first: `left`/`right` are the default slots for a lone subject; `center` is reserved for deliberate symmetry beats (confrontation head-on, ritual/reveal, direct-to-camera) — not the fallback.
   - Anti-repetition: do not repeat the same `position` for the same character in consecutive sentences unless the character logically hasn't moved and the beat is continuous; alternate sides across a scene.
   - Multi-cast: two characters facing each other use opposing thirds (left+right), never stacked center.
   - Depth semantics calibrated: `far` = establishing/environmental presence (small figure, ≈30-50% frame height), `mid` = the normal storytelling distance (default), `near` = intentional intimacy/threat only. State an expected shape: most shots `mid`, `near` for emphasis beats, `far` no longer near-zero.
2. **cast_decision.md few-shot example replaced** with one that *demonstrates* the target distribution (a short scene where entries use left/right/center and far/mid/near each at least once, with one empty-cast sentence retained).
3. **visual_breakdown.md consistency rules added** (it consumes decided cast):
   - `camera_angle` must agree with the cast's dominant depth: `wide`/establishing ↔ `far`/`mid`; `close`/detail shots ↔ `near` or empty cast; never a wide shot with `near` cast filling the frame.
   - Background composition variety: at least some shots per scene described with off-center framing (subject anchor on a third, asymmetric lighting, diagonal sightlines) instead of the central-vanishing-point default — this gives left/right cast placements natural anchor points (feedback #2's second root cause).
4. **Seeded as `candidate`** via `uv run python scripts/migrate_prompts.py --label candidate --source prompts` — both files in one candidate set (they are one calibration).
5. **Golden-set gate:** `uv run python scripts/eval_prompts.py --label candidate --baseline production` exits 0 (no axis/total regression, no item failure). Note 8.4a/8.8 history: this gate has produced FAILs from production-side nondeterminism — rerun-and-attribute per 8.4a's stage attribution before concluding the candidate regressed.
6. **Distribution evidence:** one candidate-label scenario run (golden SCP or checkpointed input) measured the same way as iteration 1 — position spread must break the 78% center monopoly (target: no single position >50%, `far` ≥ 5% when environmental beats exist), camera_angle↔depth contradictions absent in a manual spot-check of 10 shots. Record the counts in Dev Agent Record.
7. **No schema drift:** parser regression tests stay green (parse_cast lenient normalization untouched); output JSON shape unchanged.

## Tasks / Subtasks

- [ ] Task 1: Write cast_decision.md Composition section + replace few-shot (AC:1,2)
- [ ] Task 2: Write visual_breakdown.md camera_angle↔depth + off-center background rules (AC:3)
- [ ] Task 3: Seed candidate, run golden-set gate (AC:4,5)
- [ ] Task 4: Candidate distribution run + measurement script snippet (reuse iteration-1 counting: position/depth histograms from scenario artifacts) (AC:6)
- [ ] Task 5: Hand promotion decision to Jay with evidence (PROMPT_POLICY step 5 — label move is Jay's/UI action)

## Dev Notes

- Iteration-1 measurement one-liner lives in the session record; equivalent: load scenario artifacts JSON, `Counter(c["position"])` / `Counter(c["depth"])` over all shots' cast.
- deepseek-v4-flash regressed to an older schema once before under prompt complexity (8.10 root cause) — keep the new Composition section compact and rule-shaped, not essay-shaped; verify output shape in the gate run.
- Don't promise what the renderer can't do: `position` is a 3-slot anchor, not free x. Rules must speak in the enum's vocabulary only.
- **ponytail:** two prompt files, zero code. The measurement is a notebook-grade count, not a new eval axis.

### References

- [Source: prompts/scenario/cast_decision.md] — fields taught, no placement guidance (the gap)
- [Source: prompts/scenario/visual_breakdown.md] — background composition few-shots
- [Source: src/yt_flow/pipeline/nodes/video.py — `_POSITION_X_FRAC`, `_character_scale_filter`] — what position/depth actually do
- [Source: _bmad-output/implementation-artifacts/e2e-iteration1-2026-07-09.md] — distributions, feedback #2/#3
- [Source: docs/PROMPT_POLICY.md] — change protocol this story follows

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
