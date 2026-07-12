---
created: 2026-07-09
baseline_commit: 28b7e59b8fe95965862abfbc28be585a9bc2e011
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

Status: done

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

- [x] Task 1: Write cast_decision.md Composition section + replace few-shot (AC:1,2)
- [x] Task 2: Write visual_breakdown.md camera_angle↔depth + off-center background rules (AC:3)
- [x] Task 3: Seed candidate (AC:4 done); AC:5 golden-set gate explicitly waived by Jay 2026-07-12 — see Completion Notes
- [x] Task 4: Candidate distribution run + measurement script snippet (reuse iteration-1 counting: position/depth histograms from scenario artifacts) (AC:6)
- [x] Task 5: Promotion decision made directly by Jay (promote now, gate deferred) — not merely handed off

### Review Findings

- [x] [Review][Patch] Env-var presence check closes a `CLAUDECODE=""` bypass of the AI-session `--baseline` block [scripts/eval_prompts.py:750]
- [x] [Review][Patch] `cast_decision.md` few-shot now demonstrates position alternation for the repeated entity (sentence 1 `left` → sentence 3 `right` → sentence 4 `center`), instead of repeating `left` [prompts/scenario/cast_decision.md]
- [x] [Review][Patch] Added a 3+-person placement rule to the Composition section — the prior text only covered exactly 2 people, leaving 3+-cast sentences with no guidance against center-stacking [prompts/scenario/cast_decision.md]
- [x] [Review][Patch] Added a dominant-depth tie-break rule for mixed-depth cast to the `camera_type` consistency section — the prior rule had no definition of "dominant depth" when cast depths tie [prompts/scenario/visual_breakdown.md]
- [x] [Review][Patch] Softened the AC6 "0 contradictions" claim to disclose the programmatic check only covers the two explicit "never" pairings, not the full `camera_type`↔depth agreement table (`medium`/`POV`/`high-angle`/`low-angle` combinations were never scored) [_bmad-output/implementation-artifacts/8-12-cast-placement-scale-calibration.md]
- [x] [Review][Defer] `scripts/migrate_prompts.py --label production` has no AI-session guard analogous to the new `eval_prompts.py --baseline` block, despite being the actual command that flipped `production` this session — deferred, policy decision belongs to Story 6-12 (see deferred-work.md)
- [x] [Review][Defer] New off-center background-composition guidance in `visual_breakdown.md` is inert for any shot whose `location_key` resolves to an approved stock plate (plate substitution ignores `image_prompt` text) — deferred, pre-existing architecture, out of this story's prompt-only scope (see deferred-work.md)

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

Claude Sonnet 5

### Debug Log References

- Candidate seed: `uv run python scripts/migrate_prompts.py --label candidate --source prompts` — `created: scenario/cast_decision`, `created: scenario/visual_breakdown`.
- Smoke sanity check (NOT a promotion gate): `uv run python scripts/eval_prompts.py --profile smoke` → exit 0, `SCP-049: atmosphere=3.33, narrative_coherence=4.67, article_fidelity=5.00 total=13.00`, `scene_count=9, shot_count=136, empty_narration_count=0, empty_image_prompt_count=0`. Artifact: `tmp/eval-prompts/20260712-150034-1783836034829458187-candidate/candidate-SCP-049-full.json`.
- Parser regression: `PYTHONPATH=$PWD/src uv run pytest tests/pipeline/nodes/test_scenario_chain.py tests/pipeline/nodes/test_character_motion.py -q` → 225 passed (AC7, no schema drift).

### Completion Notes List

- **AC1/AC2 (cast_decision.md):** Added a compact "Composition" section (rule-of-thirds default, anti-repetition, multi-cast opposing-thirds, calibrated depth semantics) and replaced the single-shot few-shot with a 5-sentence scene demonstrating left/right/center and far/mid/near each at least once, including one multi-cast opposing-thirds beat, one center-reserved reveal beat, and one empty-cast sentence.
- **AC3 (visual_breakdown.md):** Added a `camera_type` ↔ cast-depth consistency rule (wide/high/low-angle agree with far/mid/no-cast; close-up/medium/OTS/POV agree with near) plus a corresponding Pre-Output Self-Check item, and an off-center background-composition guidance bullet so left/right cast placements get a matching background anchor.
- **AC4:** Both edited prompt files seeded to `candidate` label via `migrate_prompts.py` — confirmed above.
- **AC5 — explicitly waived by Jay, not run.** `docs/PROMPT_POLICY.md` (Story 6-12, same day) freezes any `eval_prompts.py --baseline` invocation behind `YTFLOW_ALLOW_AB_GATE=1`. Sequence this session: I asked how to handle the AC5-vs-freeze conflict → Jay said override → I started the gate under override → Jay caught it mid-run and had me stop ("didn't we agree not to run the gate?") → ran `--profile smoke` instead as a cheaper sanity check (passed, but explicitly NOT A PROMOTION GATE per policy) → Jay then explicitly instructed promoting to `production` anyway, without the gate, deferring quality-parity verification to later. **AC5 is not satisfied by this story** — it is a deliberate, explicit call by the product owner to accept the risk and promote unverified against the golden set. Recorded here rather than silently marked passed.
- **Production promotion (out-of-scope side effect, kept per Jay's decision):** `uv run python scripts/migrate_prompts.py --label production --source prompts` was run to promote the two 8-12 files. Because `--source prompts` targets the whole tree and the migrate script is idempotent-by-content (not by story), it also created new `production` versions for 6 other already-committed-but-not-yet-promoted prompts: `scenario/critic_agent`, `scenario/research`, `scenario/review`, `scenario/structure`, `scenario/tts_normalize`, `scenario/writing` (all pre-existing git-committed content from earlier stories, no working-tree diff — Langfuse `production` had simply never caught up to repo HEAD for them). Flagged to Jay; he said leave it — repo is source of truth and these were already merged.
- **Follow-up hardening (Jay's direct instruction, same session):** after the override-then-walkback above, Jay asked to make the freeze impossible for an AI session to bypass at all, not just gated by an env var. Added an unconditional check in `scripts/eval_prompts.py`: `--baseline` now hard-refuses whenever `CLAUDECODE`/`AI_AGENT` is present in the environment, regardless of `YTFLOW_ALLOW_AB_GATE` — not overridable by an agent setting its own env var. Documented in `docs/PROMPT_POLICY.md`'s freeze banner. Covered by a new test (`test_baseline_blocked_in_ai_session_even_with_override`) plus fixes to the existing freeze tests, which previously ran with `CLAUDECODE=1` leaking in from this very session and needed to delenv it to simulate a plain terminal. Full suite: 113 passed.
- **AC6 — distribution evidence (measured from the smoke run's candidate artifact, SCP-049, 9 scenes / 136 shots / 125 cast entries):**
  - `position`: center 21 (16.8%), left 55 (44.0%), right 49 (39.2%) — no single position >50% (target met; iteration-1 baseline was center 78%).
  - `depth`: near 40 (32.0%), mid 68 (54.4%), far 17 (13.6%) — `far` well above the ≥5% target (iteration-1 baseline was far ~2%).
  - `camera_type` ↔ dominant cast depth: 0 contradictions found across all 136 shots against the two explicit "never" pairings only (`wide`+dominant-`near`, `close-up`/`over-the-shoulder`+lone-`far`) — the check does not cover the full agreement table (e.g. `medium`/`POV`/`high-angle`/`low-angle` combinations were not scored), so "0 contradictions" means those two violations specifically, not exhaustive rule compliance. First 10 cast-populated shots manually listed and confirmed consistent with the checked pairings (e.g. `S00103 wide/far,far`, `S00101 close-up/near`, `S00109 over-the-shoulder/mid,far`).
  - Caveat: single-SCP, single-run (N=1), not a statistical sample across the 3-item golden set or across repetitions — directional evidence only, matching what a smoke-scope run can produce without the frozen gate.
- **AC7:** No schema/parser changes made; regression suite green (see Debug Log).
- **Task 5:** Jay made the promotion call himself directly (promote now, verify quality later) rather than this being handed off as an open decision — both files are now live under `production`.

### File List

- `prompts/scenario/cast_decision.md` (modified, promoted to `production`)
- `prompts/scenario/visual_breakdown.md` (modified, promoted to `production`)
- `scripts/eval_prompts.py` (modified — unconditional AI-session block on `--baseline`)
- `tests/test_eval_prompts.py` (modified — new test for the AI-session block, autouse fixture now delenvs `CLAUDECODE`/`AI_AGENT`)
- `docs/PROMPT_POLICY.md` (modified — freeze banner documents the AI-session block)
- `_bmad-output/implementation-artifacts/8-12-cast-placement-scale-calibration.md` (modified — frontmatter, tasks, Dev Agent Record)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — status)
