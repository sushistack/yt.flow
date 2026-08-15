---
title: 'Story 12.6 — Source-grounded story expansion: length as one decision, adaptation as a declared category'
type: 'feature'
created: '2026-08-15'
status: 'done'
baseline_revision: '1be0d27b65e84be784fe61e2fdfdb49f31585e47'
final_revision: 'ba38620'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/12-6-source-grounded-story-expansion.md'
  - '{project-root}/docs/PROMPT_POLICY.md'
warnings: [oversized, multiple-goals]
---

<intent-contract>

## Intent

**Problem:** Run `e5ed4b3a` produced 9 scenes / 304 어절 / ~2.0 min because the length target is pinned in three disagreeing places (`TARGET_DURATION_MINUTES = 3`, the hand-set band `180~360` in `scenario_chain.py`, and the same band re-typed as prose in `structure.md`) — 3 min × 145 어절/min is 435, so the band the model actually obeys targets ~2 minutes, not the declared 3. Separately, `structure.md:115-117` orders the model to split the total evenly across scenes, which is precisely the flat pacing Jay saw, and the critic's `scene_notes[].issue` is untyped free text, so a fabricated-fact violation and a "sounds like a report" gripe arrive at the human gate as the same undifferentiated `unresolved_pass2` warning.

**Approach:** Make `TARGET_DURATION_MINUTES` and a new `TARGET_WPM` the only length inputs, derive every budget band from them, and inject the derived numbers into `structure.md` as template variables so the prompt can no longer disagree with the code. Add deterministic distribution checks to the existing `_validate_retention_outline` so uneven pacing is enforced rather than requested. Give the critic a closed `issue_type` vocabulary (the Story 12.4 pattern), declare the three permitted adaptation categories in `writing.md`/`critic_agent.md`/`review.md` with the missing positive counter-examples, and surface the distinct categories on the gate. Build one measurement script so all of this is verified against real runs instead of asserted.

## Boundaries & Constraints

**Always:**
- `TARGET_DURATION_MINUTES` and `TARGET_WPM` are the only hand-set length inputs; every other length number (total band, per-scene band) is computed from them at import time and reaches the prompt as a template variable.
- Permitted adaptation is an **enumerated** list (sensory rendering / POV-and-scene staging / opening a source gap as a question). Anything not enumerated stays forbidden — a new fact, number, grade, date, event, or capability that the fact sheet does not carry is still `ungrounded_claim` and still forces `retry`.
- Every prohibition added to a prompt ships with a ✅ replacement example in the same block.
- Model-authored `issue_type` is normalised in Python against a closed vocabulary; an unknown value falls back and is logged — it never fails the run and never reaches the gate raw.
- Prompt edits are seeded to Langfuse `production` (DEV MODE) — a repo-only prompt edit does not ship.

**Block If:**
- The work requires choosing a target duration other than the already-declared 3 minutes. Raising it is Jay's call; this story only makes the change a one-line edit and supplies the evidence (iteration 2 `c6be1954` was 8:10).
- Changing the `HOOK_TYPES` closed vocabulary (`question|shock|mystery|contrast`) would be needed — it is already enforced on scene 1 and already covers AC5's three hook shapes.

**Never:**
- Do not loosen the critic. The three findings from run `e5ed4b3a` were all correct; the defect is that they had one category, not that they were wrong.
- Do not touch TTS, subtitle, image, or video stages, `deepseek_max_tokens`, or the Gemini token pins.
- Do not add a third scenario pass — Story 6.5's one-retry limit stands.
- Do not add a new Python dependency; the measurement script uses stdlib `sqlite3`/`json` plus the already-wired LLM seam.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Outline inside derived band | 9 scenes, budgets summing to 420, max/min = 2.1, opening 12% | `_validate_retention_outline` returns; outline unchanged | No error expected |
| Outline below derived band | budgets summing to 304 (the `e5ed4b3a` shape) | `RetentionError("budget_total", …)` naming both derived bounds | Existing structure retry, then run fails |
| Flat distribution | 9 scenes all `word_budget: 46` (spread 1.0) | `RetentionError("budget_uniform", …)` quoting max/min and the required ratio | Same as above |
| Front-loaded opening | scene 1 budget = 30% of total | `RetentionError("budget_opening_share", …)` | Same as above |
| Critic emits a known type | `scene_notes[0].issue_type: "ungrounded_claim"` | Normalised, kept, contributes `ungrounded_claim` to `warning.categories` | No error expected |
| Critic emits junk type | `issue_type: "Fact Problem!!"` | Coerced to `"other"`, `logger.warning` names the rejected value | Never raises |
| Critic omits the field | `scene_notes[0]` has no `issue_type` | Coerced to `"other"` | Never raises |
| Pass-2 still failing | `verdict == "retry"`, notes typed `ungrounded_claim` + `pacing` | `warning = {code: "unresolved_pass2", categories: ["pacing","ungrounded_claim"], message: …}` | No error expected |
| Pass-2 clean | `verdict == "pass"`, `overall_pass` true | No `warning` key at all (unchanged behaviour) | No error expected |
| Measurement over a live run | `measure_script.py --run e5ed4b3a` | JSON + table: scenes, per-scene 어절/share, total, WPM, spread, budget delta | Missing checkpoint → non-zero exit naming the run id |
| Measurement, no audio yet | checkpoint has scenes but no `audio_duration` | WPM reported as `null`, everything else still computed | Never divides by zero |

</intent-contract>

## Code Map

- `src/yt_flow/pipeline/nodes/scenario_chain.py:65` -- `TARGET_DURATION_MINUTES = 3`; the only place it reaches a prompt is `:1532` as `{{target_duration}}` for `scenario/structure`.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:95-112` -- Story 12.1 retention constants, including the hand-set `MIN/MAX_SCENE_WORD_BUDGET = 20, 90` and `MIN/MAX_TOTAL_WORD_BUDGET = 180, 360` that the header comment already flags as uncalibrated.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:818-962` -- `_validate_retention_outline`, the LLM-free contract enforcer; per-scene budget check at `:901-911`, total at `:955-959`. New distribution checks belong here.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:1527-1551` -- `structure_step` prompt variables + the `_validate_retention_outline` call site.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:2318-2381` -- `critic_step` and its `parse()`; `scene_notes[]` fields are normalised as free text only.
- `src/yt_flow/pipeline/nodes/scenario.py:298-311` -- `_UNRESOLVED_PASS2_MESSAGE`, `_ISSUE_KEYS`, `_CONTRADICTION_KEYS`.
- `src/yt_flow/pipeline/nodes/scenario.py:352-380` -- `_build_quality`, sole writer of `scenario_quality` and its `warning`.
- `src/yt_flow/domain/state.py:47-90` -- Story 12.4's closed-vocabulary pattern (`StoryArchetype`, `STORY_ARCHETYPES`, fallback, total helper). Copy it.
- `src/yt_flow/domain/state.py:392-410` -- `ScenarioWarning` / `ScenarioQuality` TypedDicts.
- `prompts/scenario/structure.md:113-120` -- the word-budget rule; `:115-117` is the "divide the total by scene count" instruction that produces flat pacing. Self-check restates the band at `:165`.
- `prompts/scenario/writing.md:24-31` -- OK/BAD tone block (has no counter-example for the report-recitation failure); `:96`, `:106-113` -- fact-grounding rules with the sensory carve-out.
- `prompts/scenario/critic_agent.md:21-22` -- criterion 7 Fidelity (already carves out sensory description); `:36-42` -- `scene_notes[]` schema; `:44-56` -- verdict rules.
- `prompts/scenario/review.md:107` -- issue `type` enum containing `invented_content`; `:93-94` -- absence-vs-contradiction note.
- `prompts/scenario/format_guide.md:113` -- "오프닝 ~15% / 중심 최대 / 마지막 ~15%", the rule nothing verifies.
- `frontend/src/components/ArtifactPanel.tsx:216-240` -- `ScenarioQualityWarning`, renders `warning.message` at `:234`.
- `frontend/src/lib/api.ts:109` -- `scenario_quality` client type.
- `scripts/migrate_prompts.py:60-67` -- `prompts/scenario/x.md` → Langfuse `scenario/x` derivation.
- `_bmad-output/implementation-artifacts/5-22-verification-evidence/verify_5_22.py` -- precedent for driving scenario steps directly, no graph/DB.
- `yt_flow.db` -- LangGraph `checkpoints` table; verified to hold both `e5ed4b3a-…` (51 rows) and `c6be1954-…` (20 rows). This is the **only** surviving source of either run's scenario payload — `c6be1954` has no workspace directory left.

## Tasks & Acceptance

**Execution:**

- [x] `scripts/measure_script.py` -- new: `--run <run_id>` reads the newest `checkpoints` row for that thread from `yt_flow.db` (stdlib `sqlite3` + the checkpointer's serde), and reports scene count, per-scene 어절 (whitespace split of each scene's narration), per-scene share of total, total 어절, spread (`max/min`), declared `word_budget` vs actual delta, and WPM (`total 어절 / (Σ audio_duration / 60)`, `null` when absent). `--baseline <run_id>` prints a second run beside the first. `--coverage` adds exactly one LLM call via `scenario._call_gemini` that lists source facts from the SCP text and marks each 반영/버려짐, printing used/dropped counts and the dropped statements. Output JSON to stdout, human table to stderr. -- measurement precedes every other task; AC6 and AC8 have no instrument today.
- [x] `_bmad-output/implementation-artifacts/12-6-live-validation/baseline.md` + `baseline.json` -- new: run the script over `e5ed4b3a` and `c6be1954` (with `--coverage`) and commit both outputs plus the exact commands. -- Task 0: answers "what changed between 8:10 and 2:00" with two measurements instead of a guess.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py:95-112` -- replace the four hand-set budget literals with a derivation: add `TARGET_WPM = 145`, `WORD_BUDGET_TOLERANCE = 0.15`, `MIN_SCENE_WORD_SHARE = 0.05`, `MAX_SCENE_WORD_SHARE = 0.30`; compute `_TARGET_TOTAL_WORDS = round(TARGET_DURATION_MINUTES * TARGET_WPM)` and derive `MIN/MAX_TOTAL_WORD_BUDGET` and `MIN/MAX_SCENE_WORD_BUDGET` from it. Keep the existing constant names so all readers and tests still resolve. Add `MAX_OPENING_WORD_SHARE = MAX_CLOSING_WORD_SHARE = 0.20` and `MIN_BUDGET_SPREAD = 1.6`. -- AC3/AC4: one knob for length, a separate knob for density, so "make it longer" can never become "make it faster".
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py:818-962` -- extend `_validate_retention_outline` with three checks after the existing total check: `budget_opening_share` (first scene > `MAX_OPENING_WORD_SHARE` of total), `budget_closing_share` (last scene, same bound), `budget_uniform` (`max/min < MIN_BUDGET_SPREAD`). Each raises `RetentionError` with the measured value and the bound. -- AC5: format_guide's distribution rule becomes enforced instead of merely requested.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py:1527-1541` -- pass `total_word_budget_min`, `total_word_budget_max`, `scene_word_budget_min`, `scene_word_budget_max`, `max_opening_word_pct`, `max_closing_word_pct`, `min_budget_spread` into the `scenario/structure` variables alongside `target_duration`. -- AC3: the prompt reads the code's numbers instead of re-typing them.
- [x] `prompts/scenario/structure.md:113-120,165` -- replace every hardcoded band (`씬당 20~90`, `총합 180~360`, `현재 3분 파이프라인 기준`) with the new placeholders; **delete** the `:115-117` "총합을 먼저 잡고 씬 수로 나눠 배분하세요 — 8씬이면 평균 약 30" instruction and replace it with the distribution rule (오프닝 ≤ `{{max_opening_word_pct}}`%, 마지막 ≤ `{{max_closing_word_pct}}`%, 중심 비트에 최대 분량, 최대 씬 ≥ 최소 씬 × `{{min_budget_spread}}`), naming the rejection codes. Update the self-check line at `:165` to the same placeholders and add a spread checkbox. -- AC3/AC5: removes the direct cause of the flat 9-scene outline.
- [x] `src/yt_flow/domain/state.py:47-90` -- add `CriticIssueType` Literal (`ungrounded_claim`, `substance_gap`, `report_tone`, `pacing`, `hook`, `ending`, `other`), `CRITIC_ISSUE_TYPES = get_args(...)`, `CRITIC_ISSUE_TYPE_FALLBACK = "other"`, `FACT_ISSUE_TYPES = ("ungrounded_claim",)`, and a total `normalize_critic_issue_type(value: str) -> str` that lowercases/strips and returns the fallback for anything unrecognised. -- AC1/AC7: the 12.4 pattern — closed vocabulary in `domain/`, readable by both `pipeline/` and `scripts/`.
- [x] `prompts/scenario/critic_agent.md:21-22,36-42,44-56` -- add a "허용되는 각색" block naming the three permitted categories (감각적 묘사 / 시점·장면화 / 원문의 빈칸을 답 없는 질문으로 열기) and stating each is **not** a fidelity violation; add the required `issue_type` field to the `scene_notes[]` schema with the closed enum and one line per value; keep the existing "Fact Sheet에 없는 사실 단언 → ALWAYS retry" rule but bind it to `issue_type: ungrounded_claim`. -- AC1/AC2.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py:2348-2360` -- in `critic_step.parse`, run each note's `issue_type` through `normalize_critic_issue_type`, logging any coerced value. -- AC1: the gate never sees an uncontrolled category string.
- [x] `prompts/scenario/writing.md:24-31,96,106-113` -- add the ❌/✅ pair the report-recitation failure lacks, using the real regression verbatim (❌ "재단 공식 기록을 낭독합니다." → ✅ a staged version of the same fact); add the same three-category "허용되는 각색" block so writer and critic share one vocabulary, positioned inside the 사실 접지 규칙 section so the enumeration and the prohibition read together. -- AC2.
- [x] `prompts/scenario/review.md:93-94,107` -- state that a sensory/atmospheric addition carrying no new fact is **not** `invented_content`, matching `critic_agent.md:22`. -- AC1: the two judges stop disagreeing about the same sentence.
- [x] `src/yt_flow/domain/state.py:392-410` -- add `categories: NotRequired[list[str]]` to `ScenarioWarning` and `critic_scene_notes: NotRequired[list[dict]]` to `ScenarioQuality`. -- AC7.
- [x] `src/yt_flow/pipeline/nodes/scenario.py:298-311,352-380` -- add `_CRITIC_NOTE_KEYS = ("issue_type", "issue", "suggestion")`; put `_bounded(critic.get("scene_notes"), _CRITIC_NOTE_KEYS, …)` into `quality`; when the warning fires, set `categories` to the sorted distinct union of critic note `issue_type`s and review `issues[].type`. -- AC7: fact violations and craft violations become separable at the gate.
- [x] `frontend/src/lib/api.ts:109` + `frontend/src/components/ArtifactPanel.tsx:216-240` -- extend the `warning` type with `categories?: string[]` and render them under the message as a labelled line (e.g. `유형: ungrounded_claim · pacing`), omitted when absent. -- AC7. Keep the `unresolved_pass2` code so the existing `ArtifactPanel.test.tsx:284` / `RunDetail.test.tsx:219` assertions stay valid.
- [x] `tests/pipeline/nodes/test_scenario_chain.py` -- add: the four derived constants match `TARGET_DURATION_MINUTES * TARGET_WPM` within tolerance; each new `RetentionError` code fires on its own minimal outline and a valid uneven outline passes; `structure_step` passes all seven new variables; `structure.md` contains the placeholders and none of the strings `"180~360"`, `"20~90"`, `"3분 파이프라인"`; `critic_agent.md` names every `CRITIC_ISSUE_TYPES` member; critic `parse` coerces unknown/absent `issue_type`. -- covers the I/O matrix rows and makes AC3's "어긋나면 드러나야 한다" a real failure.
- [x] `tests/pipeline/nodes/test_scenario.py` -- add: `_build_quality` emits `categories` sorted-distinct when the warning fires, emits no `warning` key when pass-2 is clean, and bounds `critic_scene_notes`. -- AC7.
- [x] `frontend/src/components/ArtifactPanel.test.tsx` -- add: categories line renders when present, absent otherwise. -- AC7.
- [x] `_bmad-output/implementation-artifacts/12-6-live-validation/after.md` -- run one live scenario chain on the same SCP as the baseline (SCP-049) after seeding, measure it with the same script, and record the after-vs-baseline table (scenes, 어절, WPM, per-scene shares, spread, source exhaustion). If live LLM access is unavailable, record that explicitly and leave AC8 open rather than substituting a stub run. -- AC8.
- [x] `uv run python scripts/migrate_prompts.py --label production --source prompts` -- run `--dry-run` first, confirm the diff is limited to `scenario/structure`, `scenario/writing`, `scenario/critic_agent`, `scenario/review`, then seed. Record the dry-run output in `12-6-live-validation/seeding.md`. -- CLAUDE.md DEV MODE; `character/angle_selection` and `character/generation` are known-drifted and must not ride along.

**Acceptance Criteria:**

- Given `TARGET_DURATION_MINUTES` is edited to any integer ≥ 1, when the module is imported, then `MIN/MAX_TOTAL_WORD_BUDGET` and `MIN/MAX_SCENE_WORD_BUDGET` all move with it and `structure.md` renders the moved numbers, with no second edit anywhere.
- Given `structure.md` is edited to re-introduce a hardcoded budget band, when the test suite runs, then a test fails naming the literal it found.
- Given a critic report whose `scene_notes` mix a fabricated-fact finding and a pacing finding, when pass 2 still fails, then the gate payload's `warning.categories` lists both types and the UI shows them on a separate line from the message.
- Given the pipeline runs end to end on SCP-049 after this change, when `measure_script.py` is run on the new run and on `e5ed4b3a`, then the new run's total 어절 lands inside the derived band, its WPM stays at or below 165, and its scene-share spread is at least `MIN_BUDGET_SPREAD` — all three read off the same committed report.
- Given a narration that adds only sensory atmosphere to a fact the sheet carries, when critic and review judge it, then neither reports it as a fidelity or `invented_content` violation.
- Given a narration that asserts a number, grade, date, event, or capability absent from the fact sheet, when the critic judges it, then the verdict is `retry` and the note carries `issue_type: ungrounded_claim`.
- Given the seeding dry run, when it is inspected, then only the four edited scenario prompts appear in the change set.

## Spec Change Log

- **2026-08-16 — `FACT_ISSUE_TYPES` dropped from the `domain/state.py` task line (deliberate).** It shipped with zero production readers, and as written (`("ungrounded_claim",)`) it is wrong for the namespace it would be read against: `categories` merges both judges, and the review side's `invented_content` / `fact_error` mean the same thing, so anything consulting the tuple would classify a real fact violation as craft. Ponytail — no scaffolding for later. The fact/craft distinction lives in the two vocabularies (`CRITIC_ISSUE_TYPES`, `REVIEW_ISSUE_TYPES`) and in the operator's reading of the category line; when a code reader actually needs the subset, it can be added against a call site.
- **2026-08-16 — `REVIEW_ISSUE_TYPES` added to `domain/state.py` (not in the original task list).** `issues[].type` reaches `_build_quality` as unvalidated model text clipped to 600 chars, so the review half of `warning.categories` had no vocabulary at all — a 600-character sentence could render as a "category". Mirrors `prompts/scenario/review.md`'s enum verbatim and is pinned against that line by a test.

## Review Triage Log

### 2026-08-16 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 24: (high 2, medium 12, low 10)
- defer: 4: (high 0, medium 2, low 2)
- reject: 3
- addressed_findings:
  - `[high]` `[patch]` `warning.categories` was computed from the `_MAX_QUALITY_ITEMS`-capped `critic_scene_notes`, so a lone `ungrounded_claim` behind 20 `pacing` notes fell out of the gate summary — the exact fact/craft confusion AC7 exists to remove. Now reads the raw `scene_notes`; safe because it is a set over a 7-value closed vocabulary.
  - `[high]` `[patch]` Same defect on the review half (`review_issues` is capped too): a `fact_error` past entry 20 vanished from `categories`. Now reads raw `review.get("issues")` through the same membership filter.
  - `[medium]` `[patch]` The `issue_type` coercion log fired on successful normalization — `"PACING"` was classified as `pacing` but logged "recorded as 'other'", telling an operator the opposite of what happened.
  - `[medium]` `[patch]` Review-side `issues[].type` had no vocabulary; a 600-char model sentence could render as a gate category. Added `REVIEW_ISSUE_TYPES` in `domain/state.py`, pinned against `review.md`'s enum by a test.
  - `[medium]` `[patch]` `FACT_ISSUE_TYPES` shipped unused and misclassified the merged namespace — deleted (see Spec Change Log).
  - `[medium]` `[patch]` `critic_scene_notes` rode every checkpoint, interrupt and SSE frame with nothing rendering it; now rendered in `ScenarioQualityWarning` led by `issue_type`.
  - `[medium]` `[patch]` The `budget_uniform` message promised "central beats get the largest budgets", a rule the check never evaluated; rewritten to state only the max/min ratio it enforces.
  - `[medium]` `[patch]` `deepseek_structure.json` froze budgets summing to exactly `MIN_TOTAL_WORD_BUDGET`, so AC3's "one line, no second edit" was false — budgets are now solved from the derived constants at load, via one shared helper in `tests/stubs/fakes.py`.
  - `[medium]` `[patch]` `test_every_bound_moves_with_the_target_duration` was a tautology that recomputed the formula in the test body; replaced with derivation-identity assertions.
  - `[medium]` `[patch]` The written narration was never re-measured (the outline's ±15% band and `writing.md`'s ±20% per-scene tolerance leave a legal path to shipping under the band); actual total 어절 added to `rule_metrics`. Measurement only — failing after writing would burn a run.
  - `[medium]` `[patch]` Below 4 scenes the distribution contract is unsatisfiable and died with a misleading `budget_opening_share`; now `RetentionError("scene_count", …)` names the real cause.
  - `[medium]` `[patch]` The runtime prompt comes from Langfuse and `compile()` ignores unknown variables, so a stale `production` version would show the model `180~360` while the validator enforced 370–500 and every run died with no diagnostic. `structure_step` now verifies the served template carries the new placeholders and tells the operator to re-seed.
  - `[medium]` `[patch]` `measure_script.py` counted every word against partial TTS durations, overstating WPM; now `null` unless durations cover every scene.
  - `[medium]` `[patch]` `measure_script.py` read the newest checkpoint blind — a manual narration edit (`source: "update"`, which run `e5ed4b3a` genuinely has) would be measured as pipeline output. Now warns.
  - `[medium]` `[patch]` `TARGET_WPM = 145` is a measurement taken at `qwen_tts_speed = 1.2`; the condition is now recorded beside the constant.
  - `[low]` `[patch]` Boundary tests for spread and opening share never reached their boundaries (landing at 5.0 and 19.86%); replaced with explicit at-bound and just-past outlines.
  - `[low]` `[patch]` `--durations-json` without `--scenes-json` was silently ignored; now a usage error.
  - `[low]` `[patch]` `measure_script.py`: missing/unreadable DB, non-dict scenes, and empty source text now give named errors instead of raw tracebacks or a coverage number computed from nothing.
  - `[low]` `[patch]` Two test budget helpers lacked the `<4` guard (`ZeroDivisionError` at 2 scenes, contract-violating outline at 3); both now delegate to one shared helper.
  - `[low]` `[patch]` The Story 12.1 header comment still said the constants below it were hand-set and uncalibrated, directly above the block that calibrated them.
  - `[low]` `[patch]` `normalize_critic_issue_type` was annotated `str` while being total over `None`/`int`/`dict`; annotated `object`, matching `missing_archetype_evidence`.
  - `[low]` `[patch]` `test_scenario.py`'s AC7 headline test claimed the review contributed `missing_fact`, but the fixture had no `type` — the assertion passed because the review contributed nothing. Fixture now carries a real type.
  - `[low]` `[patch]` A non-list `scene_notes` was swallowed to `[]` with no trace; `_bounded` now warns, covering its three call sites.
  - `[low]` `[patch]` The spec's own derived-values block said `131` where the code computes `130` (banker's rounding) — the exact drift class this story exists to remove.

## Design Notes

**Why the length was wrong, precisely.** 304 어절 over 2.01 min is 151 어절/min. At that density the declared 3-minute target needs ~435 어절, but the enforced ceiling is 360 — so the outline validator was, by construction, refusing to let the pipeline reach its own stated target. Nothing was disobeyed; the two numbers simply never met. Deriving the band closes the gap without anyone choosing a new duration, which is why this story can ship with `TARGET_DURATION_MINUTES` still at 3. Raising it to 8 (iteration 2's measured length) is one line and Jay's decision.

**Derived values at `TARGET_DURATION_MINUTES = 3`, for review convenience** — these are outputs, never to be typed in as literals:

```
_TARGET_TOTAL_WORDS   = 3 * 145            = 435
MIN/MAX_TOTAL_WORD_BUDGET = 435 * (1∓0.15) = 370 / 500
MIN/MAX_SCENE_WORD_BUDGET = 435 * 0.05/0.30 =  22 / 130   # round(130.5) is banker's rounding
```

**What AC5 already had.** The hook half is done: `HOOK_TYPES` is closed, scene 1 is forced to carry one, and `hook_invalid`/`hook_misplaced` already fire. The story's three hook shapes map onto the existing four (결과 먼저 → `shock`, 반직관적 단언 → `contrast`, 구체적 통증 → `question`/`mystery`), so touching that vocabulary is churn. The unenforced half is distribution — `format_guide.md:113` states the ~15%/max/~15% rule and the archetype guides restate it per act, but no code has ever read either, and run `e5ed4b3a` came out flat. That is what the three new `RetentionError` codes cover.

**What AC1 already had.** `critic_agent.md:22` and `writing.md:106-107` both already exempt sensory description from the fidelity rule, so the story's premise that adaptation is uniformly treated as a defect is only half true. The real defect is the untyped `scene_notes[].issue`: a fabricated fact and a flat-pacing complaint land in the same free-text field, get joined into one `critic_feedback` blob, and reach the gate under one warning code. Typing the field is the change; loosening the judgment is explicitly not.

**Truncation (story trap 3) needs no token change.** `writing_step` is one call per scene, so raising per-scene budgets from 20–90 to 22–130 어절 moves one call's output by well under the 32k pin, and `structure_step`'s YAML does not grow when the integers inside it do. Confirm on the live run rather than pre-emptively raising any limit.

**Reading a run's script.** Both target runs' scenario payloads exist only in `yt_flow.db`'s `checkpoints` table — `c6be1954` has no workspace directory left, and `e5ed4b3a`'s `scenario/scene_00N.txt` files are hand-edits from the narration-edit endpoint, not pipeline output. Measure from the checkpoint, never from disk, and never `git clean` or prune that DB.

## Verification

**Commands:**
- `uv run ruff check .` -- expected: clean.
- `uv run pytest -q tests/pipeline tests/domain` -- expected: all pass, including the new constant-derivation, distribution, issue-type, and prompt-consistency tests.
- `bash scripts/ci-local.sh` -- expected: ruff + full pytest (≥80% coverage gate on services/pipeline/api) + tsc + vitest all pass.
- `uv run python scripts/measure_script.py --run e5ed4b3a-fabb-46e6-8adb-5c1c0fc68889 --baseline c6be1954-da0f-4dee-ab07-a2b4f3bcf21e` -- expected: two columns of metrics, `e5ed4b3a` reproducing 9 scenes / 304 어절 / ~151 WPM.
- `uv run python scripts/migrate_prompts.py --label production --source prompts --dry-run` -- expected: exactly the four edited `scenario/*` prompts listed as changed.

**Manual checks (if no CLI):**
- Open a run at the scenario gate with an unresolved pass-2 warning and confirm the UI shows the category line beneath the message, and that a clean run shows no warning block at all.
- Read `12-6-live-validation/after.md` beside `baseline.md`: totals, WPM, spread and source-exhaustion must be present for both, from the same script version.

## Auto Run Result

Status: done

### What changed

Length stopped being three disagreeing numbers. `TARGET_DURATION_MINUTES` and a new
`TARGET_WPM = 145` are now the only hand-set length inputs; the total band (370–500) and
the per-scene band (22–130) are derived from them at import time and injected into
`scenario/structure` as template variables, so the prompt can no longer restate a band the
code does not enforce. The instruction that caused the flat pacing Jay saw — "총합을 먼저
잡고 씬 수로 나눠 배분하세요" — is gone, replaced by the distribution rule, and three new
`RetentionError` codes (`budget_opening_share`, `budget_closing_share`, `budget_uniform`)
enforce what `format_guide.md:113` has always merely requested.

On the adaptation side, the three permitted categories (감각적 묘사 / 시점·장면화 / 빈칸을
질문으로 열기) are now enumerated in `writing.md`, `critic_agent.md` and `review.md` with the
positive counter-examples the prohibitions lacked, and the critic's `scene_notes[].issue`
gained a closed `issue_type` vocabulary (the Story 12.4 pattern) that Python normalizes
before it reaches the gate. The gate's `unresolved_pass2` warning now carries the distinct
categories behind it, and the UI renders them.

`TARGET_DURATION_MINUTES` is still 3 — the spec's Block If reserved the target value for
Jay. Raising it to iteration 2's measured 8 minutes is now one line.

### Files changed

- `src/yt_flow/pipeline/nodes/scenario_chain.py` — derived budget constants; three
  distribution checks plus `scene_count` in `_validate_retention_outline`; seven new
  `structure_step` variables; a served-prompt version guard; `issue_type` normalization in
  `critic_step.parse`; actual total 어절 in `compute_rule_metrics`.
- `src/yt_flow/domain/state.py` — `CriticIssueType`/`CRITIC_ISSUE_TYPES` and
  `ReviewIssueType`/`REVIEW_ISSUE_TYPES` closed vocabularies, `normalize_critic_issue_type`,
  `ScenarioWarning.categories`, `ScenarioQuality.critic_scene_notes`.
- `src/yt_flow/pipeline/nodes/scenario.py` — `_build_quality` emits `critic_scene_notes` and
  the merged `categories`, both read from the raw model payloads rather than the capped copies.
- `prompts/scenario/{structure,writing,critic_agent,review}.md` — derived-band placeholders,
  the distribution rule, the 허용되는 각색 enumeration, the ❌/✅ pair for the report-recitation
  regression, the `issue_type` enum, and the sensory carve-out on `invented_content`.
- `frontend/src/components/ArtifactPanel.tsx`, `frontend/src/lib/api.ts` — category line and
  critic-note block on the scenario gate warning.
- `scripts/measure_script.py` — new: the story's measuring instrument (checkpoint or JSON
  dump → scenes, 어절, per-scene shares, spread, declared-vs-actual budget, WPM, and a
  single-call source-exhaustion judge).
- `tests/` — `test_measure_script.py` (new) plus additions across `test_scenario_chain.py`,
  `test_scenario.py`, `test_state_imports.py`, `test_eval_prompts.py`, `ArtifactPanel.test.tsx`;
  the budget-solving helper is shared from `tests/stubs/fakes.py` instead of copied three times.
- `_bmad-output/implementation-artifacts/12-6-live-validation/` — `baseline.md`/`.json`,
  `after.md`/`.json`, the drivers that re-derive both, and `seeding.md`.

### Review findings

24 patches applied (2 high, 12 medium, 10 low), 4 deferred, 3 rejected. No intent gaps and
no spec-level defects — the two adversarial passes found localized defects, not a wrong
design. The two high-severity findings were the same defect on each judge: `warning.categories`
was computed from the `_MAX_QUALITY_ITEMS`-capped evidence lists, so a fact violation sitting
past entry 20 silently vanished from the gate summary — defeating AC7 in exactly the runs
(long, note-heavy) where it matters most. Both now read the raw payload; the union is a set
over closed 7-value vocabularies, so it cannot grow the checkpoint. Deferred items are in
`deferred-work.md`; three of the four are deliberately deferred because fixing them means
editing a prompt, which would invalidate the live evidence below and cost a re-run.

### Verification

- `uv run ruff check src tests scripts _bmad-output/implementation-artifacts/12-6-live-validation` — clean.
  (`scripts/ci-local.sh` still exits at stage 1 on a **pre-existing** E731 in Story 10.1b's
  committed evidence script, untouched here and reproducible from `git show HEAD:` — the four
  stages it wraps were run individually instead.)
- `uv run pytest -q` — **2948 passed, 1 skipped**.
- `npx tsc -b` clean; `npm test` — **132 passed (17 files)**.
- Live: one scenario chain on SCP-049 after seeding, plus TTS on its 8 scenes for the density
  reading. **417 어절** (band 370–500), **spread 2.03** (contract ≥1.6), opening 16.1% / closing
  9.4% (cap 20%), **148.1 WPM** (ceiling 165, and 0.1 off the baseline's 148.2 while the script
  grew 40%), source exhaustion 100% with 0 dropped facts. Baseline `e5ed4b3a` re-measured with
  the same instrument: 298 어절, spread 1.54, 148.2 WPM. Every number reproduces after the
  review patches.
- AC7 confirmed live rather than only in tests: the gate returned
  `categories: ["descriptor_violation", "report_tone", "ungrounded_claim"]`, with the critic
  correctly typing an SCP-049 certainty-upgrade ("융합된 것처럼 보인다" → "융합되어 있었죠") as
  `ungrounded_claim`. The critic did not get more lenient — it still returned `retry`.
- Prompts seeded to Langfuse `production`; the dry run's change set was exactly the four
  edited `scenario/*` prompts.

### Residual risks

- **One live sample.** spread 2.03 and the 417-어절 landing are one outline's values. The
  contract guarantees the floor, not the average (`gotcha_measure-densely-before-declaring-a-fix`).
- **The length increase is real and untested downstream.** 417 어절 → ~2.8 minutes of narration
  means more shots per run. No image/video stage ran here, so ComfyUI cost at the new length is
  unmeasured — start the next E2E with `--cache-lru 10`
  (`gotcha_comfyui-cache-classic-evicts-on-workflow-alternation`).
- **`qwen_tts_speed` is still an unguarded density knob.** `TARGET_WPM = 145` is a measurement
  taken at speed 1.2; raising the setting shortens the video without moving any constant here.
  Recorded in a comment, not enforced.
- **The story's premise was half stale and the evidence says so.** `critic_agent.md` already
  exempted sensory description before this story, source exhaustion was already 100%, and
  iteration 2's 8:10 script was equally flat (spread 1.48). The gains here are depth per source
  fact (22.9 → 37.9 어절) and enforcement, not coverage.
