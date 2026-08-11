---
title: 'Story 13.2 — instrument replacement (DSG) + visual/motion evaluation axes'
type: 'feature'
created: '2026-08-11'
status: 'done'
baseline_revision: 'ffc585c188fce1846122da5f3c10d63f7e505847'  # was fae0b98 at plan time; the concurrent 10-1c session committed 044692d+ffc585c mid-implementation, so this is the revision that isolates 13.2's diff
review_loop_iteration: 0
final_revision: 'e416c17f77be670e30c1671bdac5ba73ae068d42'
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/research/technical-narration-image-semantic-alignment-2026-08-10.md'
  - '{project-root}/_bmad-output/implementation-artifacts/10-4-live-validation/README.md'
  - '{project-root}/_bmad-output/implementation-artifacts/13-2-visual-eval-axes.md'
warnings: [oversized, multiple-goals]
---

<intent-contract>

## Intent

**Problem:** Story 10.4's judgment axis failed twice on its own data — `match` piles 29/66 rows at exactly 3 (15 of 16 merge-probe rows unmoved), and its `missing` free text docks frames for people the card layer composites separately (~13/66 rows mention a person-noun, ~9 unambiguously). Meanwhile `eval_service`'s A/B judge is text-only, so render quality cannot move an evaluation score at all, and the frontend that would display any new axis renders every real score as `—` because its `ab_result` key names never matched the backend's.

**Approach:** Replace the 1–5 Likert with DSG-style proposition decomposition (atomic typed propositions + a dependency graph, scored as a satisfied-fraction) in the shipped offline axis, structurally excluding person-kind propositions to remove the card-absence confound; then wire the resulting visual scores (`unreadable_rate`, `dsg_score`) plus two pure motion metrics and the promoted `cut_alignment_error` through `eval_service` into `ab_result`, Langfuse, the golden-set report, and a corrected frontend contract.

## Boundaries & Constraints

**Always:**
- **DSG, not VQAScore. This is measured, not assumed** (this session, DashScope compatible-mode): `qwen-vl-plus` returns `"logprobs": null` even when sent `logprobs:true, top_logprobs:5` (HTTP 200); `qwen-plus` on the *same endpoint and key* returns full token logprobs. The endpoint supports logprobs; our vision judge does not. Record this verbatim in the new instrument's docstring — it is the reason VQAScore is out.
- Same judge, same 66 frames, same `temperature: 0` as `baseline_v2.json`, so v2↔v3 numbers are comparable. Frame paths come from `baseline_v2.json`'s `frame` field (all 66 verified present on disk: 51 `recomposed/` + 15 `images/`), never re-resolved through a fresh render.
- A proposition whose parent answered "no" is **invalidated and counted unsatisfied**, and its own question is not asked (DSG dependency semantics + a real call saving).
- Person-kind propositions are **generated and then excluded from both numerator and denominator**, with the excluded count recorded per row. Generating-then-excluding is what makes the confound removal a *number* instead of a claim.
- New `eval_service` metrics that derive from state are **pure, no I/O** (existing convention, `_avg_subtitle_sync_error` docstring). Reading the visual-score artifact happens at the `evaluate_ab` edge and is passed in as an already-parsed dict.
- `determine_winner` must read every rule-metric key with `.get(key, default)` — stored `ab_result` rows predate these keys.
- Langfuse score ingestion stays inside the existing `try/except` (AD-10).

**Block If:**
- The 66-frame v3 rescore cannot complete because the vision key is missing or DashScope errors on more than 5 of 66 rows — HALT rather than reporting a partial distribution as the comparison.
- QG returns propositions for fewer than 60 of 66 rows — the instrument is unusable and a threshold guess would hide that.

**Never:**
- Do not touch the 6.12 A/B promotion gate (`YTFLOW_ALLOW_AB_GATE`) or `compare()`'s verdict logic — 13.4 owns unfreezing, and `scripts/eval_prompts.py` changes are report columns only.
- Do not add anything to `AXES` — it drives LLM judge calls, the 1–5 `QUALITY_FLOOR` scale, and `compare()`'s promotion verdict.
- Do not make the two **visual** axes (`unreadable_rate`, `dsg_score`) tiebreak inputs. They exist only when someone ran the offline scorer, so a winner that silently depends on their presence is a trap. Record-only, exactly as Story 11.4 introduced `cut_alignment_error`; inclusion in winner selection is 13.4's decision. The two **motion** axes are always computable from state and *are* tiebreak inputs.
- No new pipeline runs, no ComfyUI, no re-renders, no GPU (another session holds the GPU). No mapping/cover experiments — a hand-authored cover already failed to move `match`.
- No libcom composite axis, no stub, flag, config field, or reserved `ab_result` key for it (8-16 is backlog; `libcom` is absent from the repo).
- Do not "fix" `_enforce_camera_variety`. A nonzero `motion_repeat_ratio` is not an 11.2 violation.
- Do not import `pipeline/nodes/video.py` into `eval_service` — `select_effect` collapses `push_in` and `shake` both to `"in-center"`, which would measure direction diversity instead of archetype diversity.
- Do not carry "11/66" forward as a baseline quantity. It was a hand count of free text and is not reproducible; re-derive with a written-down rule and report that rule with the number.
- Edit only the Story 13.2 entries in `epics.md` / `sprint-status.yaml` — another session is editing 10-1c concurrently.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| DSG happy path | Frame + sentence yielding 5 propositions, 4 answered yes, 1 person-kind | `dsg_score` over the 4 non-person props; `dsg_excluded_person_n: 1` | No error expected |
| Dependency invalidation | Parent "is there a bed?" = no, child "is the bed disturbed?" | Child not asked; counted unsatisfied; `dsg_invalidated_n: 1` | No error expected |
| All propositions person-kind | Sentence purely about a person ("아주 협조적으로요") | `dsg_score: null`, `dsg_scored_n: 0` — reported as unscorable, never 0.0 or 1.0 | No error expected |
| QG returns non-JSON / empty list | Chatty or fenced reply | One retry, then row gets `dsg_error` and `dsg_score: null`; other axes still scored | Row-level, never fatal |
| Motion metrics, `camera_movement` all `None`/legacy | Legacy run | `coverage: 0.0`; `repeat_ratio` computed over one `"unmapped"` bucket → `1.0` | No error expected |
| Motion metrics, <2 shots | 0 or 1 shot in the run | `repeat_ratio: 0.0`; 0 shots → `coverage: 0.0` | No error expected |
| Legacy `ab_result` re-scored | `rule_based_scores` with none of the new keys | `determine_winner` returns a winner or `"tie"` with no exception | No `KeyError` |
| Visual artifact absent | No `workspace/<run>/visual_score.json` | Visual keys **omitted** from `rule_based_scores` (never defaulted to 0.0, which would read as perfect readability) | No error expected |
| Scene-boundary motion repeat | Scene 1's last shot and scene 2's first shot share an archetype | Counted in `repeat_ratio` — deliberate, and not an 11.2 violation | No error expected |

</intent-contract>

## Code Map

- `scripts/score_shot_narration.py` -- the shipped axis (515 lines). Reuse `ask`/`_ask_once`/`sample`/`_parse`/`_bool_field`/`shot_sentences`/`frame_for`/`report`. `readable` boolean and `MIN_MATCH`/`MIN_MATCH_HOOK` already live here. DSG lands here.
- `_bmad-output/implementation-artifacts/10-4-live-validation/run_baseline.py` -- harness pattern to clone: `ROOT = parents[3]`, `os.chdir(ROOT)` (frame paths are repo-relative), file-location import of the axis via `importlib`, `report(...)` fed a synthesized `argparse.Namespace`, and `compare_instruments()` (lines 76–105) which joins on `shot_id` — the precedent for the v2↔v3 artifact.
- `_bmad-output/implementation-artifacts/10-4-live-validation/baseline_v2.json` -- the 66-row v2 reference. Comparison targets: `mean_match 3.621`, `match {1:2, 2:1, 3:29, 4:22, 5:12}`, `below_min_match 3`, `unreadable 12`, `failure_rate 0.242`. Its 12 unreadable shot ids and 3 sub-threshold ids are the fixed points a new instrument must be checked against.
- `src/yt_flow/services/eval_service.py` (854 lines) -- `AXES`:46, `RuleBasedMetrics`:84-90 (5 fields, **constructed positionally** at 350-355), `_compute_rule_metrics`:344, `_avg_subtitle_sync_error`:284 (11.4 inversion warning at 292-298), `_cut_alignment_error`:315 (tiebreak prohibition is the last docstring line, 326), `_rule_tiebreak`:379 (point-sum), `determine_winner`:595 (lexicographic 3a/3b/3c, eps 0.01, direct `[...]` indexing), `_rule_metrics_to_dict`:760, `_pairwise_to_dict`:770 (`majority_winner = final_winner`), `store_evaluation_results`:656 (`ab_result` assembly 674-683, rule-metric NUMERIC tuple 730-742), `_load_state`:444. No image/vision code anywhere in this file — verified. Only one `pipeline/nodes` import (`plan_shot_clips`:41), guarded by `test_services_does_not_import_api_or_pipeline`.
- `src/yt_flow/domain/state.py` -- `CAMERA_ARCHETYPES = ("push_in", "pull_back", "drift", "locked", "shake")`:161; `ShotData.camera_movement: str | None`:164; `SceneState`:182.
- `scripts/eval_prompts.py` -- `_rule_metrics(scenes)`:309 (report-only, disjoint from `RuleBasedMetrics`), `_to_item_result`:427 (collects `rule_metrics` by negative filter over `AXES`/`total`/`_CATEGORICAL_METRICS`), `compare()`:694 (verdict from `AXES` + `total` only, 757-767).
- `tests/services/test_eval_service.py` (1122 lines) -- `_cut_shot`/`_cut_scene`:107-116 (both set `camera_movement: None`), tiebreak tests at 302/332, `determine_winner` group 646-733, `_rule_metrics_to_dict` key test at 156, store/Langfuse score-name tests 740-876.
- `tests/services/fixtures/eval_pipeline_states.py` -- `state_a`/`state_b`; **every fixture scene has `shots: []`**, so motion metrics need shots added or a new builder.
- `frontend/src/lib/types.ts:12-19` + `frontend/src/pages/RunAbComparisonPage.tsx:28,217-218` + `RunAbComparisonPage.test.tsx:23-32` -- the live schema mismatch: frontend says `llm_scores`/`rule_scores` and `scene_count_match`/`subtitle_sync`; backend stores `axis_scores`/`rule_based_scores` and `scene_count_match_rate`/`subtitle_sync_error`/`audio_duration_variance`/`cut_alignment_error`. Every real score renders `—`; the test fixture uses the frontend's own invented shape and so masks it.

## Tasks & Acceptance

**Execution:**
- [x] `scripts/score_shot_narration.py` -- add DSG decomposition behind a `--dsg` flag: `QG_PROMPT` (text-only, `QG_MODEL = "qwen-plus"` on the same DashScope key/endpoint — no new provider), `QA_PROMPT` (one yes/no per proposition, with the frame), `_propositions()`, `_answer_propositions()` (dependency short-circuit), `dsg_score()`. Per-row fields `propositions`/`proposition_answers`/`dsg_score`/`dsg_scored_n`/`dsg_excluded_person_n`/`dsg_invalidated_n`; summary gains `mean_dsg`, `dsg_distribution`, `dsg_unscorable`, `dsg_excluded_person_total`, `dsg_rows_with_person_prop`. Read the flag as `getattr(args, "dsg", False)` so `run_baseline.py`'s synthesized Namespace keeps working. Docstring records the measured logprobs result and why VQAScore is out. -- the instrument replacement; a fraction over ~5 propositions cannot pile at 3.
- [x] `scripts/score_shot_narration.py` (same file, separate concern) -- when `--dsg` ran, also write the report to the artifact path the consumer owns, importing the filename from `eval_service` (`from yt_flow.services.eval_service import VISUAL_SCORE_FILENAME`) rather than respelling it. Direction matters: `src/` is not importable from `scripts/`'s side of the dependency — the script already puts `src` on `sys.path` and imports `yt_flow.*`, so the constant lives in `eval_service` and the script consumes it. -- one spelling of the contract, or the wiring points at a file nothing writes.
- [x] `_bmad-output/implementation-artifacts/13-2-live-validation/run_dsg_rescore.py` -- new harness (clone `run_baseline.py --rescore`): take the 66 frame paths from `10-4-live-validation/baseline_v2.json`, score with `--dsg` at `reps=1`, write `baseline_v3.json` and `instrument_v2_vs_v3.json` (joined on `shot_id`: v2 `match`/`readable` × v3 `dsg_score`/excluded counts, plus both distributions and a rank correlation). Own directory — do not write into `10-4-live-validation/`. -- the termination condition's evidence.
- [x] `_bmad-output/implementation-artifacts/13-2-live-validation/README.md` -- record the re-derivation command, the logprobs probe result, the written-down person-noun rule with its count on `baseline_v2.json` (replacing the unreproducible 11/66), and the v2-vs-v3 resolution and confound-removal numbers. -- an unrecorded measurement is not a result.
- [x] `src/yt_flow/services/eval_service.py` -- (a) pure `_motion_key(shot)` / `_motion_archetype_coverage(scenes)` / `_motion_repeat_ratio(scenes)`, importing `CAMERA_ARCHETYPES` from `domain.state`; docstrings state that scene boundaries are counted deliberately and a nonzero ratio is not an 11.2 violation. (b) `VISUAL_SCORE_FILENAME = "visual_score.json"` + `_load_visual_scores(run_id, workspace_path)` at the edge (reads `<workspace_path>/<run_id>/<filename>`, returns `None` when absent; `settings.workspace_path` defaults to `./workspace`) + pure `_unreadable_rate(report)` / `_mean_dsg_score(report)` over the parsed dict. (c) `RuleBasedMetrics` gains `motion_archetype_coverage`, `motion_repeat_ratio`, `unreadable_rate: float | None`, `mean_dsg_score: float | None`; **switch both constructions to keyword args**. (d) `_rule_metrics_to_dict` emits the two motion keys always and the two visual keys only when not `None`. (e) `_TIEBREAK_CHAIN` table + `_rule_tiebreak_from_dicts(a, b)` with `.get(key, default)`; `_rule_tiebreak` becomes a thin delegating wrapper; `determine_winner` step 3 replaced by one call (steps 1/2 untouched). (f) delete the `"never a determine_winner tiebreak input"` sentence from `_cut_alignment_error` and record the 13.2 promotion; update `_avg_subtitle_sync_error`'s distortion note to "mitigated by demotion in 13.2, not removed". (g) one-line note that the libcom axis is deliberately absent pending 8-16, and one line that the visual axes are record-only pending 13.4. -- one tiebreak definition instead of two that can disagree.
- [x] `src/yt_flow/services/eval_service.py` (`store_evaluation_results` / `evaluate_ab`) -- extend the rule-metric NUMERIC tuple with the four new keys, skipping any absent from `rule_based_scores[variant]`; load the visual artifact in `evaluate_ab` and pass it into `_compute_rule_metrics`. -- an axis nobody records did not ship.
- [x] `scripts/eval_prompts.py` -- add `motion_archetype_coverage`/`motion_repeat_ratio` to `_rule_metrics` by calling the `eval_service` functions (no reimplementation); comment why `cut_alignment_error` is excluded (golden set runs scenario only, so it is always 0.0). Verdict logic untouched. -- report columns, not a gate.
- [x] `frontend/src/lib/types.ts` + `frontend/src/pages/RunAbComparisonPage.tsx` -- rename `llm_scores`→`axis_scores`, `rule_scores`→`rule_based_scores`; `RULE_METRICS` becomes the real backend keys plus the four new ones; leave `formatScore` alone. -- an axis that renders `—` is invisible.
- [x] `frontend/src/pages/RunAbComparisonPage.test.tsx` -- replace the fixture with the backend's actual `ab_result` shape and comment that the fixture *is* the regression guard for this contract. -- the old fixture is why the mismatch survived.
- [x] `tests/services/test_eval_service.py` (+ `tests/services/fixtures/eval_pipeline_states.py` if needed) -- unit-test every I/O-matrix row: motion coverage 1.0 / 0.2 / 0.0, `"unmapped"` bucket → ratio 1.0, scene-boundary pair counted, 0-and-1-shot edges; `_rule_tiebreak` ≡ `determine_winner` step 3 on identical input **including the 1–1 split** that currently returns `"tie"` from one path and `"A"` from the other; `cut_alignment_error` ordered ahead of `subtitle_sync_error`; legacy dict with no new keys raises nothing; `scene_count_match_rate` never fires (symmetric); all-equal → `"tie"`; visual keys omitted when the artifact is absent. Update the tests whose behavior intentionally changes (332, 703-733, 156) and say why in a comment. -- the equivalence test is this story's core regression guard.
- [x] `_bmad-output/planning-artifacts/epics.md` + `_bmad-output/implementation-artifacts/sprint-status.yaml` -- record 13.2's outcome in the **Story 13.2 entry only**. -- concurrent session owns the rest of both files.

**Acceptance Criteria:**
- Given `baseline_v2.json`'s 66 frames, when the DSG instrument is run over them, then `instrument_v2_vs_v3.json` states the v3 score distribution against v2's `{1:2, 2:1, 3:29, 4:22, 5:12}` and shows strictly more distinct values than v2's 5 — and if it does not, the README says so as the finding rather than the run being retried until it does.
- Given the same run, when the confound is measured, then the number of rows carrying at least one excluded person-proposition, and the total excluded propositions, are both reported — quantifying what the opaque `match` number could not separate.
- Given the reference run's checkpoint, when the motion metrics are computed, then they reproduce the values already measured this session — `coverage 1.0`, `repeat_ratio 0.0154` (1/65) — confirming 11.2's wiring is alive (Epic 13's "silent success" defence) and pinning the implementation against a known-correct pair rather than against a hoped-for one.
- Given those measured values, when the metrics' docstrings are written, then each states its observed value and range on the reference run, so a later session cannot read `coverage 1.0` as a broken metric or as evidence of A/B discriminating power it does not have.
- Given identical `rule_based_scores` input, when both `_rule_tiebreak` and `determine_winner` are called, then they return the same winner for every input including the 1–1 split, and `EvaluationResult.winner` can no longer disagree with the stored `ab_result.winner`.
- Given a real `ab_result` row from the backend, when the A/B comparison page renders it, then every measured score cell shows a number instead of `formatScore`'s not-measured placeholder (`결과 없음` — the Intent's `—` was the wrong symbol; the substance is unchanged), and only genuinely unmeasured metrics keep the placeholder.
- Given the golden-set evaluator, when it runs after this change, then its promotion verdict is byte-identical to before and only two report columns are added.

## Spec Change Log

_No `bad_spec` loopback occurred. Every review finding was fixable inside the diff without
re-deriving code from an amended spec._

## Review Triage Log

### 2026-08-11 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 19: (high 6, medium 10, low 3)
- defer: 4: (high 0, medium 3, low 1)
- reject: 2: (high 0, medium 0, low 2)
- addressed_findings:
  - `[high]` `[patch]` `e2e/ab-comparison-accessibility.spec.ts` carried the SAME `llm_scores`/`rule_scores` schema bug as the vitest fixture, so its score-table assertion passed while every cell rendered the placeholder — and the 3→8 rule-row change broke its `dl dd` count. Fixed mock + assertions; verified by running Playwright: **both** tests in that file failed before, the mocked one passes after (the other drives a real pipeline and fails at `approveStage` with and without this change).
  - `[high]` `[patch]` `_load_visual_scores` returned any valid JSON, so a top-level list/string reached `_unreadable_rate` and raised `AttributeError` **inside** `evaluate_ab`'s span — a wrong-shaped optional artifact could abort an evaluation that does not depend on it. Added an `isinstance(dict)` guard.
  - `[high]` `[patch]` `_rule_tiebreak_from_dicts` defaulted a missing key to `0.0`, the BEST value for four lower-is-better metrics, so the unmeasured run won that step. It also raised `TypeError` on a stored `null` and silently tied on NaN (`abs(nan-x) > eps` is `False`). Now skips any step whose two sides are not both comparable finite numbers, via `_comparable`.
  - `[high]` `[patch]` `_cut_alignment_error` returned `0.0` for both "perfectly aligned" and "no timings to check" — harmless as 11.4's record, wrong once 13.2 promoted it to chain position 2, where lower-is-better handed the top-priority tiebreak to whichever run had LESS data. Now returns `None`, is omitted from the dict, and the chain skips it. Relocating that ambiguity would have reproduced, at higher priority, the exact distortion demoting `subtitle_sync_error` was meant to fix.
  - `[high]` `[patch]` `about_body` — the one field the confound removal rests on — was unvalidated. `"true"`/`1` fail `is True` and would put a body back in the denominator; a MISSING field both degraded `_is_person` to kind-only and made `dsg_label_disagreements` read `0` (perfect compliance). Now required and must be a real `bool`. Checked against the live run: all 353 propositions already comply, so the recorded figures reproduce unchanged.
  - `[high]` `[patch]` `--dsg --limit 3` published `visual_score.json`, and nothing downstream could tell 3 scored frames from 66 — a smoke run's readability rate would be persisted, ingested into Langfuse and rendered as the run's. The write is now gated on a complete sweep of the plates (`--frames shots` excluded as a different population), and the exit code counts `dsg_errored`.
  - `[medium]` `[patch]` `_unreadable_rate` / `_mean_dsg_score` did no type or range checking on a file another process writes: a string raised, and `unreadable > scored` published a "fraction" above 1.0. Both now read as unmeasured.
  - `[medium]` `[patch]` One shared `_TIEBREAK_EPS = 0.01` spanned four incompatible units, and the docstring's claim that the pct→ratio conversion "cannot change the winner" was false (8.0 % vs 8.6 % → old point-sum "A", shared-epsilon dict "tie"). Epsilon is now per key, with the reasoning in the table.
  - `[medium]` `[patch]` The Langfuse loop called `float()` inside the AD-10 `try`, so one `null` aborted every remaining score including all of variant B's. Now uses `_comparable` and skips one key.
  - `[medium]` `[patch]` Nothing capped the proposition count (the prompt asks 3–7); each extra proposition is one paid image call per frame. Added `_MAX_PROPOSITIONS = 12`.
  - `[medium]` `[patch]` A QA call dying after its retry counts unsatisfied, so DashScope flakiness lowered `mean_dsg` indistinguishably from the frame genuinely not showing the thing. Added `dsg_qa_errors_n` / `dsg_qa_errors_total` (0 on this run).
  - `[medium]` `[patch]` The harness wrote both artifacts *before* evaluating the HALT thresholds, leaving a halted distribution on disk looking like a good one; and a scored row with a null `frame` would crash mid-run after the paid calls. HALT now precedes every write, `--limit` suppresses the consumer artifact, and the exit code no longer contradicts the printed verdict.
  - `[medium]` `[patch]` `_motion_archetype_coverage`'s docstring claimed it "collapses to 0.2", but `CAMERA_PREFERENCES` exposes only 3 of 5 archetypes per mood and `_enforce_camera_variety` guarantees ≥2 distinct per multi-shot scene — so 0.2 is effectively unreachable and ~0.4–0.6 is the healthy single-mood floor. A docstring written to prevent a misreading was itself misreading the metric. Corrected.
  - `[medium]` `[patch]` Both motion docstrings said the metrics have no discriminating power while the code has them deciding winners at positions 3–4, where coverage's 0.2 step and repeat_ratio's 1/65 step both clear their epsilon. Now states what a win on each actually means: mood variety, and how scenes are cut up — not motion quality.
  - `[medium]` `[patch]` `summarize_dsg` and the harness comparison now surface the QA-error and label-disagreement totals, so the compliance rate of the mechanism the exclusion depends on is visible rather than implicit.
  - `[medium]` `[patch]` README §4's headline figures (distinct 5→9, largest bucket 44 %→27 %) hid boundary saturation: **32/66 (48 %) of rows sit on 0.0 or 1.0**. Added that row, the honest reading (clear gain for attribution, arguable for ranking), and a pointer in the verdict box.
  - `[low]` `[patch]` `AbAxis` declared `"total"` and the new fixture supplied it, but `_axis_scores_to_dict` emits three axes only — the same "assert a key the backend never writes" defect the type was corrected to fix. Removed from both.
  - `[low]` `[patch]` README §5 said the blind-body rule "reproduces 10.4 §2.3's figure exactly … at 28" in the same clause as reporting 26. Rewritten: the rule is 10.4's, and 26-vs-28 is the two scoring passes differing on two rows.
  - `[low]` `[patch]` Added README §8 recording every post-run hardening change plus the check that the live figures still reproduce under the tightened validator — otherwise the evidence describes an instrument that no longer exists.

## Design Notes

**Why DSG and not a better Likert.** v2's own numbers: 29 of 66 rows sit at exactly 3, and the merge probe left 15 of 16 rows unmoved. `S00202` is the shape of the problem in one row — a plate that is a wall-texture study, `readable: false`, `event: "unclear"`, and `match: 5`, earned entirely off the composited card's mask. A single opaque integer cannot separate "the place is right", "the consequence is visible", and "the person is composited later"; five yes/no propositions can, and their fraction is continuous.

Proposition shape (one row's worth, abbreviated):

```
sentence: "디 계급 인원이 격리실로 들어옵니다."
p1 {kind: place,  parent: null, q: "Is this a containment cell?"}
p2 {kind: object, parent: p1,   q: "Is there a heavy steel door in this cell?"}
p3 {kind: state,  parent: p2,   q: "Is that door open?"}
p4 {kind: person, parent: null, q: "Is a D-class person present?"}   <- excluded, counted
dsg_score = satisfied({p1,p2,p3}) / 3      # p3 invalidated if p2 = no
```

`p4` is what inflated this row to `match: 5` ("A person in an orange jumpsuit…"). Excluding it is the confound removal, and recording it is the evidence.

**The motion axes are regression detectors, not A/B discriminators — measured, not assumed.** On the reference run (`8a9a288b`, 9 scenes / 66 shots, all `camera_movement` values real archetypes: push_in 20, drift 16, locked 15, pull_back 9, shake 6):

```
motion_archetype_coverage = 1.0        # 5/5 — saturates on any healthy run
motion_repeat_ratio       = 0.0154     # 1/65 pairs; the single repeat is a
                                       # locked→locked SCENE BOUNDARY
```

`repeat_ratio`'s whole reachable range is `[0, (scenes-1)/(shots-1)]` = `[0, 0.123]` here, because 11.2's `_enforce_camera_variety` already guarantees zero within-scene repeats — scene boundaries are the only pairs that can ever repeat. So neither metric separates two *healthy* variants by much; both collapse loudly if 11.2's wiring dies (coverage → 0.2, ratio → 1.0). Ship them for that role, say so in the docstrings with these numbers, and do not claim discriminating power. This is the same failure shape as 10.4's dead `legible` Likert, caught before implementation this time rather than after.

**Two classes of axis, deliberately not symmetric.** The motion metrics are pure functions of checkpoint state — free, always available, so they join the tiebreak chain. The visual metrics need a paid VLM pass over rendered frames and only exist if someone ran it; they are recorded in `ab_result`/Langfuse/UI and excluded from winner selection until 13.4 decides. Defaulting a missing `unreadable_rate` to 0.0 would read as "no unreadable frames", so absence is expressed by omitting the key, not by a value.

**Tiebreak chain order** (lexicographic, eps `> 0.01`, unified from two implementations):

| # | key | direction | note |
|---|---|---|---|
| 1 | `scene_count_match_rate` | higher | symmetric across the pair — never fires; kept for compatibility |
| 2 | `cut_alignment_error` | lower | promoted here; the only timing metric whose meaning is not inverted |
| 3 | `motion_repeat_ratio` | lower | new |
| 4 | `motion_archetype_coverage` | higher | new |
| 5 | `subtitle_sync_error` | lower | **demoted** — 11.4 inverted its meaning, so lower-is-better now weakly prefers a run that fell back to degraded provisional timings |
| 6 | `audio_duration_variance` | lower | existing |

Putting an un-inverted metric ahead of `subtitle_sync_error` *is* the redesign 11.4 deferred; the warning docstring is amended, not deleted. Unifying the two implementations changes `_rule_tiebreak` from point-sum to lexicographic and its epsilon from strict `<` to `> 0.01` — both intended, both recorded in the docstring, and the pct-vs-ratio scale difference does not reorder anything.

## Verification

**Commands:**
- `uv run ruff check src/ scripts/ tests/` -- expected: clean.
- `PYTHONPATH=$PWD/src uv run pytest tests/` -- expected: 0 failures; collected count ≥ 2615 (current baseline, measured this session — the story file's "1569" is stale) and rising only by the new tests.
- `cd frontend && npm test` -- expected: green, with the corrected fixture.
- `uv run python _bmad-output/implementation-artifacts/13-2-live-validation/run_dsg_rescore.py` -- expected: 66 rows scored, ≤5 errored, `baseline_v3.json` + `instrument_v2_vs_v3.json` written.
- `PYTHONPATH=$PWD/src uv run python -c "import asyncio;from yt_flow.services.eval_service import _load_state,_motion_archetype_coverage,_motion_repeat_ratio as r;s=asyncio.run(_load_state('8a9a288b-800f-4c73-88a2-25ae6b5a4d7d','yt_flow.db'));sc=s['scenes'];print(_motion_archetype_coverage(sc),r(sc),sorted({h['camera_movement'] for x in sc for h in x['shots']}))"` -- expected: non-degenerate values (neither 0.0 nor 1.0), and the printed set is archetype members, confirming 11.2's wiring is alive. That checkpoint holds 9 scenes / 66 shots and was confirmed loadable this session.

**Manual checks (if no CLI):**
- `instrument_v2_vs_v3.json` and the 13-2 README together answer: how many distinct v3 values vs v2's 5, how many rows moved off the 3-pile, how many person-propositions were excluded and from how many rows. If the resolution did not improve, that is the recorded finding.

## Auto Run Result

Status: done

**What was built.** Story 13.2's scope items ①②③, in the order the 2026-08-10 research
made non-negotiable. ① The 1–5 VLM Likert is replaced by a DSG-style proposition
decomposition (`scripts/score_shot_narration.py --dsg`): atomic typed propositions plus a
dependency graph, scored as a satisfied-fraction, with person-kind propositions generated,
excluded from both halves of the fraction, counted, and — the part that turned out to be
load-bearing — treated as satisfied for dependency purposes so they cannot invalidate
scenery. ② `unreadable_rate` is wired as an axis through `eval_service` into `ab_result`,
Langfuse and the UI. ③ Two pure motion metrics plus the promoted `cut_alignment_error`,
behind a single unified tiebreak chain that replaced two implementations able to disagree.

**VQAScore was ruled out by measurement, as instructed.** `qwen-vl-plus` on DashScope
compatible-mode returns `"logprobs": null` even when sent `logprobs: true, top_logprobs: 5`;
`qwen-plus` on the same endpoint and key returns full token logprobs. The endpoint supports
them, our vision judge does not.

### Files changed

- `scripts/score_shot_narration.py` — the DSG instrument (QG on `qwen-plus` text-only, one
  yes/no vision call per non-person proposition, dependency short-circuit, per-row
  proposition/exclusion/invalidation/QA-error counts), plus the consumer artifact write
  gated on a complete sweep.
- `src/yt_flow/services/eval_service.py` — motion metrics, the visual-artifact edge read
  plus two pure readers, four new `RuleBasedMetrics` fields (keyword construction), the
  `_TIEBREAK_CHAIN` table with per-key epsilon and uncomparable-value skipping,
  `cut_alignment_error` promoted and made `None`-when-unmeasured, Langfuse ingestion that
  skips absent/uncomparable keys instead of publishing 0.0.
- `scripts/eval_prompts.py` — two report-only golden-set columns, reusing the
  `eval_service` functions; verdict logic untouched.
- `frontend/src/lib/types.ts`, `RunAbComparisonPage.tsx`, `RunAbComparisonPage.test.tsx`,
  `e2e/ab-comparison-accessibility.spec.ts` — the `ab_result` contract corrected to the
  backend's actual keys, and both fixtures replaced with the backend's real output shape.
- `tests/services/test_eval_service.py`, `tests/test_score_shot_narration.py` — +48 tests.
- `_bmad-output/implementation-artifacts/13-2-live-validation/` — `run_dsg_rescore.py`,
  `baseline_v3.json`, `instrument_v2_vs_v3.json`, `README.md`.
- `epics.md` / `sprint-status.yaml` — Story 13.2 entries only (the concurrent 10-1c session
  committed `044692d`+`ffc585c` mid-implementation; its edits are untouched and this
  spec's `baseline_revision` was rebased onto `ffc585c` so the review diff isolates 13.2).

### Result on the 66 preserved frames

| | v2 Likert | v3 DSG |
|---|---|---|
| distinct values | 5 | **9** |
| largest bucket | 29/66 (44 %) | 18/66 (27 %) |
| rows on an extreme | 14/66 (21 %) | 32/66 (48 %) |

The 29 rows v2 piled on exactly 3 spread across 7 v3 values; **18 moved off the pile**. The
card-absence confound, recorded by 10.4 as an unreproducible "11/66", touches **61 of 66
rows** and **163 of 353 propositions (46 %)**.

**Three results reported against interest rather than smoothed:** the v2↔v3 rank
correlation is **0.0263** (the instruments do not agree — evidence they differ, not that v3
is right); mean DSG is **higher** on unreadable frames (0.5694 vs 0.4892, n=12); and 48 % of
rows sit on 0.0/1.0, so the resolution gain is clear for attribution and only arguable for
ranking. Consequence recorded in code and evidence: `readable` and `dsg_score` stay separate
axes, and `dsg_score` is not a gate (13.4's call).

Two instrument defects were caught in a 3-row smoke run *before* the real run and fixed:
the decomposer mislabelled `hand`/`robe`/`silhouette` as scenery on 3 of 3 rows (confound
fully re-imported), and a missing person invalidated a genuine plate proposition.

### Review

19 patches applied (high 6, medium 10, low 3), 4 deferred, 2 rejected, 0 intent gaps, 0
spec loopbacks. The six high-severity findings were all "silently produces a wrong number"
rather than crashes: a broken Playwright mock hiding the same schema bug twice, a
wrong-shaped optional artifact able to abort an evaluation, a tiebreak that let the
*unmeasured* run win a step, `cut_alignment_error`'s 0.0 meaning both "perfect" and "never
measured" at chain position 2, an unvalidated `about_body` that could re-import the
confound while reporting perfect compliance, and a `--limit` smoke run publishing itself as
the run's readability. Full detail in the Review Triage Log.

`followup_review_recommended: true` — 19 fixes across measurement, winner selection,
published artifacts and validation, six of them high-severity and several changing behaviour
(`cut_alignment_error`'s return contract, per-key epsilon, absent-key semantics in Langfuse).
That is significant by both volume and consequence.

### Verification

- `uv run ruff check src/ scripts/ tests/` — clean.
- `PYTHONPATH=$PWD/src uv run pytest tests/` — **2668 passed, 1 skipped, 0 failed** (baseline
  `ffc585c`: 2620; +48 new).
- `cd frontend && npm test` — 119 passed; `tsc --noEmit` clean.
- `npx playwright test e2e/ab-comparison-accessibility.spec.ts` — the mocked score-table test
  passes; it and the live-pipeline test both failed before the fix, and the live-pipeline one
  fails identically at `approveStage` with and without this change (pre-existing).
- Live: 66 frames, 0 errored, 0 unscorable, ~6 min, 0 renders, no GPU.
- `evaluate_ab`'s consumer path exercised with the real artifact: `unreadable_rate 0.1818`
  (= 12/66, matching 10.4) and `mean_dsg_score 0.5038`.
- Motion metrics reproduce the pre-implementation live measurement: coverage 1.0,
  repeat_ratio 0.0154 (1/65, a `locked`→`locked` scene boundary).
- All 353 live propositions satisfy the tightened validator, so the recorded figures
  reproduce under the post-review instrument.

### Residual risks

- **No human validation of `dsg_score`.** DSG's published human correlation is on general
  T2I benchmarks — not Korean narration, not SCP horror, not background plates whose subject
  is composited afterwards. Nobody has hand-scored these 66 frames.
- **No threshold, deliberately.** A threshold invented at the sight of a first distribution
  is what 10.4 got wrong. `fail_reason` still turns on `readable` and `match` only.
- **`--reps 1`.** QG was not resampled, so decomposition variance is unmeasured; a rerun may
  produce a different proposition set for the same sentence.
- **The two motion axes are tiebreak inputs whose wins mean something other than their
  names.** A coverage win means more mood variety; a repeat_ratio win means a different
  scene-cut structure. Recorded in both docstrings, but they can still decide a stored
  winner.
- **12 % QG label disagreement is unexplained.** The union rule makes it harmless to the
  score; a decomposer contradicting itself on 42 of 353 propositions is not a solved
  component.
- The new golden-set columns do not reach the `--baseline` comparison report (deferred,
  pre-existing `aggregate_runs` behaviour).
