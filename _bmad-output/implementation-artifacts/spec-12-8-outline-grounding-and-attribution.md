---
title: 'Story 12.8 — Outline grounding: ownerless fabrication and the misaddressed bill'
type: 'feature'
created: '2026-08-16'
baseline_revision: '30893aa'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/12-8-outline-grounding-and-attribution.md'
  - '{project-root}/_bmad-output/implementation-artifacts/12-6-live-validation/ablation.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-12-7-prose-harness-device-allocation.md'
  - '{project-root}/docs/PROMPT_POLICY.md'
warnings: [oversized, multiple-goals]
---

<intent-contract>

## Intent

**Problem:** Nothing checks the outline against the source article. `structure_step` never receives `scp_text` (only the research packet — an LLM paraphrase), `_validate_retention_outline` checks `fact_references`/`event` for *shape* only, and the review/critic that Story 12.1 handed the job to never see the outline at all. So the outline mints facts the source does not contain, the writer obeys them faithfully, and the critic bills the writer for a fabrication it cannot reach — `structure_step` runs once per run and `_full_rewrite` reuses the same outline, so the retry loop rewrites narration that was already correct.

**Approach:** Give the outline the source article and make it carry a verbatim source quote beside each fact statement, so a pure-Python substring check can confirm the evidence exists and a reader can see whether a hedge survived. Then attribute every grounding finding to the layer that minted it — outline or writing — and make an outline-originated finding say, at the gate and in the log, that scene repair cannot fix it.

## Boundaries & Constraints

**Always:**
- The quote is *evidence*, the statement stays a Korean paraphrase. `scp_text` is English (5 articles in `data/scps.json`, 696–739 chars); the substring check runs on the quote only, and is therefore language-agnostic.
- Deterministic and LLM-free: no new model call anywhere in the scenario chain.
- The writer's blindfold is unchanged. `fact_references` reaches the writing prompt as the same list of Korean statement strings it sees today — the quote is stripped at the writer boundary.
- Evidence failures degrade to gate-visible notes on the final attempt; they never fail the run and never add a third pass.
- Any summary/category computed from evidence reads the RAW list, never the `_MAX_QUALITY_ITEMS`-capped copy (Story 12.6's two high findings).
- A prompt-shape decision that only reaches `prompts/` does not ship — the seeding guard must fail loudly if the seeded `scenario/structure` predates this story.

**Block If:**
- Closing an AC would require a third scenario pass, re-running `structure_step`, or loosening `critic_agent.md`/`review.md`.
- Live LLM access is unavailable for AC8 — record it and leave AC8 open rather than substituting a stub run.

**Never:**
- Do not give the *writer* the source article (Story 8.8's `article_fidelity -1.00`). The outline getting it is a different seam and is the point of this story.
- Do not make the quote requirement so tight that `fact_references` becomes a copy of the source — the statement remains a paraphrase and the source is English while the statement is Korean, which structurally prevents it.
- Do not re-run or re-measure the 12.6 ablation arms; their numbers are the committed baseline.
- No new service, no abstraction layer — pure functions inside the scenario chain, matching Story 12.1/12.7.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Quote located | `fact_references[i].quote` is a verbatim span of `scp_text` (after NFKC + whitespace collapse) | Item verified; outline passes | No error expected |
| Quote absent, attempt 1 | Quote not found in normalized `scp_text` | `ValueError` from `parse` naming the scene and the offending quote → one corrective LLM retry | Existing `_parse_with_retry` feedback path |
| Quote absent, final attempt | Same, after the retry | `statement` kept, item marked unverified, note recorded in the grounding sink; run continues | Logged, surfaced at the gate |
| Hedge dropped | Quote holds a hedge marker (`appears`, `believed`, …), statement holds none | `hedge_dropped` note, same strict-then-note path | Same |
| Unsupported event | `event.what`/`event.consequence` trigram overlap with the scene's fact statements below threshold | `event_unsupported` note | Note only — dramatization is legitimate, so this never hard-fails |
| No source text | `scp_text` empty/missing (A/B clone, restarted run) | Evidence checks skipped entirely, one note recording the skip | Never raises |
| Old-shape outline | Seeded `scenario/structure` predates this story (`fact_references` are bare strings) | `RuntimeError` at `structure_step` entry naming the re-seed command | Fail loudly before any LLM spend |
| Contradiction traced | `grounded_contradictions[i].narration_quote` overlaps the scene's outline fields | Item carries `origin: "outline"`; warning gains the category and the scene list | No error expected |
| Contradiction untraced | Narration quote matches no outline field | `origin: "writing"` | No error expected |

</intent-contract>

## Code Map

- `src/yt_flow/pipeline/nodes/scenario_chain.py:1661-1735` -- `structure_step`. Gains `scp_text` and a `grounding_sink: list[dict] | None = None` (the `usage_sink` idiom — the live drivers monkeypatch this function and return a plain list, so the return type must not change). Renders the new `scp_source_text` variable at `:1691-1716`; `_validate_retention_outline(scenes)` at `:1727`; `_allocate_devices` write at `:1733`.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:1674-1687` -- `structure_step.parse`. Home of the evidence check: a raise here buys exactly one corrective retry with `parse_error` fed back (`:1405-1412`). This is the "rejection" the story asks for; `RetentionError` (`:820-834`) is deliberately post-await and would fail the run instead.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:920-932` -- the `fact_references` shape check and the Story 12.1 comment that defers grounding to review/critic. Both change: the item is now a mapping, and the comment is replaced by a pointer to the new check.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:913-918` -- `event.who/what/consequence` non-empty check; the support check lands beside it.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:1622-1658` -- `_require_seeded_budget_variables` + `_STRUCTURE_BUDGET_VARIABLES`; the seeding guard extends here with a second, 12.8-specific reason.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:678-684` -- `_metric_text` (NFKC + whitespace collapse), the repo's only normalization idiom. Every comparison in this story runs through it.
- `src/yt_flow/pipeline/nodes/scenario_chain.py:1833-1867` -- `_writing_scene_brief`; `{**scene, ...}` at `:1851` is writer boundary #1.
- `src/yt_flow/pipeline/nodes/scenario.py:532` -- `subset_structure` fed to `writing_scene_repair_step` (`scenario_chain.py:2058` json.dumps) is writer boundary #2.
- `src/yt_flow/pipeline/nodes/scenario.py:646-649` -- the single `structure_step` call site; `state["scp_text"]` is already in scope and simply not passed.
- `src/yt_flow/pipeline/nodes/scenario.py:367-433` -- `_build_quality`; `_bounded` cap at `:352-357`, categories from RAW lists at `:415-428`, `_CONTRADICTION_KEYS` at `:313-315`. Called once at `:745`, where `structure` is in scope.
- `src/yt_flow/domain/state.py:435-489` -- `GroundedContradiction`, `ScenarioWarning`, `ScenarioQuality` TypedDicts.
- `frontend/src/lib/api.ts:75-115` + `frontend/src/components/ArtifactPanel.tsx:216-340` -- `ScenarioQualityWarning`; contradictions render at `:263-280`, the category line at `:237-241`.
- `prompts/scenario/structure.md:47-72` (scene schema), `:66-68` (`fact_references` exemplar), `:79-86` (`event` contract), `:128-139` (the `fact_references` section), `:155`, `:173-177` (self-check). No `{{scp_text}}` anywhere today.
- `prompts/scenario/review.md:83-93` -- the both-sides-quote requirement. **Its parser (`scenario_chain.py:2342-2361`) validates field presence only — it never locates a quote in its source.** The precedent to copy is the strict-on-attempt-1 / degrade-on-retry shape (`_validate_grounded_contradictions:2364-2408`), not a locatability check; this story writes the first one.
- `prompts/scenario/critic_agent.md:42,68` -- the hedge-escalation rule that exists for the writer and not for the outline.
- `_bmad-output/implementation-artifacts/12-6-live-validation/{ablation.md,after_scenes.json,armA_scenes.json,armB_scenes.json}` -- the calibration set: three committed outlines under `structure`, with the four fabrications attributed by hand at `ablation.md:283-288`.
- `_bmad-output/implementation-artifacts/12-7-live-validation/run_writing_only.py` -- the live-driver pattern (state dict, `sc.scenario_node`, dump `{scenes, structure, scenario_quality, stages}`) and the `.gitignore` prose convention.

## Tasks & Acceptance

**Execution:**

- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py` (beside `_metric_text`) -- add `_overlap(text, reference) -> float`: character-trigram containment over `_metric_text`-normalized strings (fraction of the text's trigrams present in the reference), returning `0.0` for empty input and never raising. One deliberately dumb, transparent instrument, in the spirit of `count_devices.py`. -- AC3/AC4 share it, so it is exercised twice.
- [x] `_bmad-output/implementation-artifacts/12-8-live-validation/calibrate.py` -- **do this first.** Load the three committed ablation dumps, run `_overlap` over every `event.what`/`event.consequence` against its own scene's fact statements, and over each of `ablation.md`'s four attributed narration sentences against its outline scene. Print the distribution and pick `_EVENT_SUPPORT_MIN` / `_ATTRIBUTION_MIN` from it, quoting the separation achieved. -- Trap 6 and the "threshold with no sample band" gotcha: the constant ships with the numbers that chose it.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py` -- add `_check_fact_evidence(scenes, scp_text) -> list[dict]`: per scene, per `fact_references` item, verify `_metric_text(quote) in _metric_text(scp_text)`; check hedge preservation (source-side markers `appears/appear/seem/seems/believed/thought/apparently/presumably/reportedly/suspected/estimated/approximately/unknown` and Korean `보인다/추정/알려/듯/가능성` against statement-side Korean hedges); check `event.what`/`event.consequence` support via `_overlap`. Returns notes `{scene, code, detail}` with codes `quote_not_found` / `hedge_dropped` / `event_unsupported` / `source_unavailable`. Empty `scp_text` returns one `source_unavailable` note and nothing else. Never raises. -- AC1/AC2/AC3.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py:1674-1687` -- call `_check_fact_evidence` inside `parse`; on the first attempt raise `ValueError` naming every note (so the corrective retry sees exactly what to fix), on the final attempt keep the outline and hand the notes to `grounding_sink`. Mirrors `_validate_grounded_contradictions`'s strict/lenient switch; comment the reason so the asymmetry with `RetentionError` is not read as an oversight. -- AC1: rejection with one bounded correction, no run failure, no third pass.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py:920-932` -- `fact_references` items become mappings `{statement, quote}`; require both keys non-empty strings, keep the non-empty-list rule, and replace the "review/critic own grounding" comment with a pointer to `_check_fact_evidence`. Unverified items keep their `statement` and gain `quote_verified: false`. -- AC1; the stale comment is the ownership vacuum itself (Trap 2).
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py:1661-1735` -- `structure_step(scp_id, scp_text, research, ...)` plus `grounding_sink`; render `scp_source_text` for the prompt. -- AC1: the outline cannot quote a source it has never seen.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py:1622-1658` -- extend the seeding guard with `scp_source_text` and its own message (an unseeded prompt emits bare-string `fact_references`, which would otherwise burn both attempts and fail the run with a shape error that names nothing). -- Boundaries: a decision that only reaches `prompts/` does not ship.
- [x] `src/yt_flow/pipeline/nodes/scenario_chain.py` -- add `_writer_facts(scene)` returning the scene dict with `fact_references` flattened to `[statement, ...]`; apply at `_writing_scene_brief:1851` and to `subset_structure` (`scenario.py:532`). -- AC6: the two writer boundaries, and the only two.
- [x] `prompts/scenario/structure.md:47-72,66-68,128-139,155,173-177` -- add the `{{scp_source_text}}` block (verbatim article, stated as the only source of truth for `fact_references`), change the `fact_references` schema and exemplar to `- statement:` / `quote:` pairs, require the quote be copied character-for-character from the source (it may be English while the statement is Korean), require the statement to preserve the quote's certainty — port `critic_agent.md:42`'s "'~로 보인다'를 '~이다'로 올리는 것도 단언" verbatim — require `event.what`/`event.consequence` to assert nothing beyond this scene's fact statements, and add both to the self-check. Keep `:130-131`'s "the writer sees only this outline" framing. -- AC1/AC2/AC3.
- [x] `src/yt_flow/pipeline/nodes/scenario.py:646-649,745` -- pass `state["scp_text"]` and a `grounding_sink` list to `structure_step`; hand the notes to `_build_quality` along with `structure`. -- AC4.
- [x] `src/yt_flow/pipeline/nodes/scenario.py:367-433` -- `_build_quality(..., structure, outline_notes)`: stamp each `grounded_contradictions` entry with `origin` (`"outline"` when `_overlap(narration_quote, scene fact statements + event.what + event.consequence)` clears `_ATTRIBUTION_MIN`, else `"writing"`), add `outline_grounding` to `warning["categories"]` when any outline-originated evidence exists, and add `warning["outline_originated"] = {"scenes": [...], "note": "…씬 리페어로는 고칠 수 없습니다 — 아웃라인 재생성이 필요합니다"}`. Read the RAW contradiction list and the raw notes for the summary, never the `_bounded` copy; add `origin` to `_CONTRADICTION_KEYS`. Also carry the outline notes themselves as `quality["outline_grounding"] = _bounded(...)`. -- AC4/AC5 and Trap 7.
- [x] `src/yt_flow/pipeline/nodes/scenario.py` (`scenario_node`, near the existing warning log at `:746-752`) -- `logger.warning` naming the outline-originated scenes and that the retry loop cannot reach them. -- AC5: log AND gate.
- [x] `src/yt_flow/domain/state.py:435-489` -- add `origin` to `GroundedContradiction`, `outline_originated` to `ScenarioWarning`, `outline_grounding` to `ScenarioQuality`. -- the checkpoint payload is a typed contract.
- [x] `frontend/src/lib/api.ts:75-115` + `frontend/src/components/ArtifactPanel.tsx:216-340` -- render the origin beside each contradiction, the outline-originated line beneath the category line, and the outline grounding notes as their own bounded list. -- AC4/AC5: the operator is the reader of this distinction.
- [x] `tests/pipeline/nodes/test_scenario_chain.py` -- `_overlap` totality/bounds; `_check_fact_evidence` over the I/O matrix (located, absent, hedge dropped, unsupported event, empty `scp_text`, malformed scene); strict-on-attempt-1 vs notes-on-final; `structure_step` fills `grounding_sink` and leaves the outline usable; `_writer_facts` strips every quote at both writer boundaries (assert the quote text is absent from the rendered brief and from the repair payload); the seeding guard fires on a template lacking `scp_source_text`; prompt-text pins — `structure.md` contains `{{scp_source_text}}`, `quote:` and the hedge sentence, and no longer contains the bare-string `fact_references` exemplar. -- covers the I/O matrix.
- [x] `tests/pipeline/nodes/test_scenario.py` -- contradiction origin stamping both ways; `outline_grounding` category present only when outline-originated evidence exists; a fact contradiction past entry 20 still reaches `categories` and `outline_originated` (the capped-list regression, per contradiction side this time); warning absent on a clean pass; no third pass. Plus `tests/pipeline/test_gates.py`, `tests/services/test_run_service_gate.py`, `tests/api/test_stage_artifacts.py` and `frontend/src/components/ArtifactPanel.test.tsx` extended for the new keys.
- [x] `_bmad-output/implementation-artifacts/12-8-live-validation/attribute.py` -- **Task 0's instrument.** Given a scene dump, print for each flagged narration sentence the outline field it traces to, reproducing `ablation.md:283-288`'s two-column table mechanically; import `_overlap` from `scenario_chain` so script and runtime cannot disagree. Run it over the three committed ablation dumps and commit that output as the baseline table. -- AC8: "the writer got this from…" becomes a question a script answers.
- [x] `uv run python scripts/migrate_prompts.py --dry-run --source prompts` then `--label production --source prompts` -- confirm the change set is exactly `scenario/structure` before seeding; record in `12-8-live-validation/seeding.md`. Seeding runs BEFORE the live measurement. -- CLAUDE.md DEV MODE; known-drifted `character/*` prompts must not ride along.
- [x] `_bmad-output/implementation-artifacts/12-8-live-validation/` -- driver modelled on `run_writing_only.py` (nothing is pinned here — the outline is what changed), **at least two live runs** on SCP-049, plus `after.md`: outline-originated grounding violations per run beside the ablation baseline (control 1 / A 2 / B 4), the attribution table from `attribute.py`, every `quote_not_found` / `hedge_dropped` / `event_unsupported` note with its outline text, and a `.gitignore` in the sibling directories' prose style. -- AC8, Trap 6.

**Acceptance Criteria:**

- Given an outline whose every `fact_references` quote is a verbatim span of the source, when `structure_step` completes, then no grounding note is recorded and no extra LLM call was made beyond the existing retry budget.
- Given a fabricated quote, when the corrective retry also fails to ground it, then the run completes, the statement survives for the writer, and the note reaches the gate payload — the run is never failed and no third pass is added.
- Given the source says "appears fused" and the outline states it as fact, when the evidence check runs, then a `hedge_dropped` note names that scene and the two texts.
- Given a pass-2 grounding contradiction whose narration traces to the outline, when the gate payload is built, then the contradiction carries `origin: "outline"`, `categories` includes `outline_grounding`, and the payload states that scene repair cannot fix it — with the same true when that contradiction sits past the 20-entry cap.
- Given the writing brief and the scene-repair payload for any scene, when they are rendered, then no source quote text appears in either, and `fact_references` reads as the same list of Korean statements the writer sees today.
- Given the seeded `scenario/structure` does not read `scp_source_text`, when `structure_step` starts, then it raises before any LLM call with the re-seed command in the message.
- Given the two live SCP-049 runs, when `attribute.py` is run over their dumps and over the three ablation dumps, then every outline-originated violation is listed with the outline field that minted it, and the counts are recorded per run against the ablation baseline.
- Given the review and critic prompts, when the diff is inspected, then neither has been loosened — no grounding criterion, threshold or issue type was removed or weakened.

## Spec Change Log

## Review Triage Log

### 2026-08-16 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 20: (high 4, medium 13, low 3)
- defer: 2: (medium 2)
- reject: 4
- addressed_findings:
  - `[high]` `[patch]` A first attempt failing on YAML/shape left the evidence counter at 0 while consuming the one retry, so the *second* payload took the strict branch and raised — the run failed on an evidence verdict, which the I/O matrix forbids. Strictness now keys on a ContextVar set by `_parse_with_retry` around the pre-retry parses only, so it can fire only while a correction actually remains.
  - `[high]` `[patch]` The same counter outlived `reroll_on_truncation`'s restart, so after a truncated corrective call the re-roll's first payload went lenient and the regeneration was silently skipped. The ContextVar is set fresh per `_parse_with_retry`, closing it. (Premise correction: `review_step._make_parse` is scoped per concurrent scene, not per `_parse_with_retry` — it has the identical leak and was not the model to copy. Deferred.) A `ValueError` from the free-text repair path also propagated with the retry unspent; now routed to `parse_error`.
  - `[high]` `[patch]` `warning["outline_originated"]` unioned every grounding-note scene and fired on any negative pass-2, printing "아웃라인 재생성이 필요합니다" over causes the outline never minted — it misfired on run1, whose only listed scene traced to an `event_unsupported` note `after.md` §3 itself judges a false positive. Narrowed to attributed findings plus `quote_not_found`/`hedge_dropped`.
  - `[high]` `[patch]` The origin stamp never fired live: both runs had `grounded_contradictions: []` while the critic's `ungrounded_claim` scene notes carried every grounding finding — the channel the spec attributed had no traffic and the channel with traffic had no attribution. Stamping extended to the critic's fact-typed notes and re-derived offline over the committed dumps (run2 씬9 → outline 0.198, 씬5 → writing 0.085, matching §4's hand attribution); no live run spent.
  - `[medium]` `[patch]` `event_unsupported` raised on attempt 1 and spent the corrective retry, contradicting the I/O matrix's "Note only — never hard-fails"; its measured precision is 2 정탐 / 2 경계 / 2 오탐 live and ~11% on the calibration set, and both runs' notes survived the retry anyway. Made note-only, and the two test fixtures that had been bent into `consequence`-restates-`what` to satisfy it were reverted.
  - `[medium]` `[patch]` A malformed/empty fact list made `reference` empty and fired `event_unsupported` on both event fields, misdiagnosing a `fact_references` defect as an `event` defect and burning the retry on it; sub-trigram event text produced a guaranteed false note. Both now skip.
  - `[medium]` `[patch]` `_stamp_origin` had no unknown state — a missing/unreadable outline or an out-of-range `scene_num` reported `origin: "writing"`, the producer asserting a layer it could not determine. Added an explicit unknown (rendered "귀속 불가"), carried `origin_overlap` so a 0.10-threshold judgment is not shown as a bare determination, and rewrote the test that pinned the old behaviour as "pre-12.8".
  - `[medium]` `[patch]` `_stamp_origin` mutated the parsed review payload in place, adding a code-derived key to dicts still live in `scenario_node`, and normalized a non-list before `_bounded` could warn about it. Now stamps copies and leaves the non-list visible to the warning.
  - `[medium]` `[patch]` Quote matching folded only NFKC and whitespace, so a case or curly-punctuation difference was a false `quote_not_found` that burned the retry; a 1-3 character quote passed vacuously. Added case/curly folding and `_MIN_QUOTE_CHARS = 12`.
  - `[medium]` `[patch]` The source-side hedge vocabulary carried unreachable Korean alternatives (the quote is a proven span of an English article) while the statement side matched bare `수 있`/`듯`, letting a genuine certainty upgrade suppress its own note; and a quote trimmed to exclude the preceding "appears" escaped entirely. Vocabularies split, over-broad markers dropped, and the source search now runs over a ±32-char window around the located span.
  - `[medium]` `[patch]` The corrective retry feedback spent ~280 of its 500 chars on a preamble the prompt already states and named no quote. Now spends the budget on the offending text. (Premise correction: `hedge_dropped` stays correctable too, so both codes carry their detail.)
  - `[medium]` `[patch]` The panel rendered the grounding notes only when a pass-2 `warning` existed, so on a clean pass `quote_not_found` never reached the operator. Renders when either exists.
  - `[medium]` `[patch]` `아웃라인 접지 {n}건` counted the `_MAX_QUALITY_ITEMS`-capped array — the capped-list shape this diff guards against on the summary side — and the log listed capped notes while naming raw scenes. Added `outline_grounding_total` and made the log read the raw notes.
  - `[medium]` `[patch]` The prompt exemplar and the structure cassette both taught `quote:` values present in no article in `data/scps.json`; few-shot copying of them would produce exactly the defect the check catches. Replaced with real SCP-173 spans, plus tests asserting every exemplar and cassette quote locates in `data/scps.json`.
  - `[medium]` `[patch]` `test_the_judging_prompts_were_not_loosened` asserted two substrings and passed after deleting essentially every other grounding criterion. Replaced with 26 parametrized pins covering criterion 7, the certainty-escalation rule, the ALWAYS-retry threshold, all five contradiction evidence fields and every member of both issue-type vocabularies.
  - `[medium]` `[patch]` `5-22-verification-evidence/verify_5_22.py:71` still called the 5-argument `structure_step` and now raised `TypeError` — the reader census stopped one file short. Fixed, and every `structure_step`/`research_step`/`writing_step` caller in `src`, `scripts`, `tests` and `_bmad-output` swept (the 12.6/12.7/12.8 drivers wrap with `*a, **k` and were unaffected).
  - `[low]` `[patch]` `attribute.py` counted a `--sentence` it could not locate as writing-originated, under-reporting AC8; unlocated rows are now reported as such.
  - `[low]` `[patch]` `run_outline.py` raised a bare `StopIteration` on an unknown `--scp`; it now names the id and the catalog.
  - `[low]` `[patch]` `calibrate.py` printed the derived rule and the shipped constant as two independent statements; it now asserts they agree, so editing a threshold cannot silently break "the constant ships with the numbers that chose it".
  - `[medium]` `[patch]` `test_eval_prompts.py`'s outline fixture carried a 4-character quote that the new minimum-span rule rejected; the callers now pass a real hedge-free source sentence rather than weakening the rule.

## Design Notes

**Why the quote is English and the statement Korean.** `data/scps.json` holds 5 English articles (696–739 chars); `fact_references` are Korean sentences. A substring check between them is structurally impossible, which is why the story's "축자 인용 + 부분문자열 검사" only works once the two roles are split: the *quote* is language-agnostic evidence checked by code, the *statement* stays the paraphrase the writer reads. This also disposes of Trap 4 by construction — a Korean statement cannot collapse into an English source sentence.

**Why `parse` and not `_validate_retention_outline`.** A raise inside `parse` buys exactly one corrective regeneration with the error text fed back; `RetentionError` is deliberately raised after the await and fails the run. A ledger violation is a planning failure worth failing on; an ungrounded quote is model wobble on fresh content, and the epic forbids failing the run for a quality verdict. Strict-then-degrade is `_validate_grounded_contradictions`'s own shape.

**What the story got wrong, and what it changes.** (1) `review.md`'s parser never locates a quote — it checks that five fields are non-empty strings. The precedent is the retry shape, not the check; this story writes the first locatability check in the repo. (2) `structure_step` never had `scp_text`, so the outline could not have quoted the source even if asked. AC6 forbids giving the *writer* the article; giving the *outline* the article is the fix, not a violation of it.

**Threshold honesty.** `_EVENT_SUPPORT_MIN` and `_ATTRIBUTION_MIN` are tuning knobs, not truths. They ship with `calibrate.py` and the distribution that chose them, over a labelled set of three committed outlines whose four fabrications were attributed by hand in `ablation.md`. If the separation is not clean, say so in the report and prefer the conservative side: a missed note costs visibility, a false note costs a corrective retry and operator trust.

## Verification

**Commands:**
- `uv run pytest tests/pipeline/nodes/test_scenario_chain.py tests/pipeline/nodes/test_scenario.py -q` -- expected: all pass, including the new evidence, attribution and writer-boundary tests.
- `uv run pytest tests/ -q -x --ignore=tests/e2e` -- expected: no regression; `structure_step`'s new positional parameter reaches every test double and driver.
- `cd frontend && npm test -- --run` -- expected: ArtifactPanel renders origin and the outline-originated line; existing warning tests still pass.
- `uv run python _bmad-output/implementation-artifacts/12-8-live-validation/calibrate.py` -- expected: prints the overlap distribution over the three ablation outlines and the separation between the four known fabrications and the rest.
- `uv run python scripts/migrate_prompts.py --dry-run --source prompts` -- expected: `scenario/structure` lists `scp_source_text` among its variables.
- `uv run python _bmad-output/implementation-artifacts/12-8-live-validation/attribute.py <dump>` -- expected: the two-column attribution table, one row per flagged sentence.

**Manual checks (if no CLI):**
- Read each `hedge_dropped` note's quote/statement pair and confirm the certainty really was raised — the check is keyword-based and will have false positives worth recording.
- Read the rendered writing brief for one scene and confirm no English source text is present anywhere in it.

## Auto Run Result

Status: done

**Change.** Nothing checked the outline against the source article: `structure_step` never received `scp_text`, `_validate_retention_outline` checked `fact_references`/`event` for shape only, and the review/critic Story 12.1 handed the job to never see the outline — so the outline minted facts, the writer obeyed them, and the critic billed the writer for a fabrication the retry loop cannot reach. The outline now receives the source article and carries a verbatim source quote beside each Korean fact statement; a pure-Python substring check (no new LLM call) confirms the evidence exists, one corrective regeneration is spent on a failure, and a failure that survives it becomes a gate-visible note rather than a failed run. Grounding findings are then charged to the layer that minted them, and an outline-originated finding says — in the log and at the gate — that scene repair cannot fix it. The writer's blindfold is unchanged: `fact_references` is flattened back to Korean statements at both writer boundaries.

**Files.**
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — `_overlap`, `_check_fact_evidence`, `_writer_facts`, the `scp_text`/`grounding_sink` parameters on `structure_step`, the evidence check inside `parse` with a ContextVar-scoped strictness switch, the `{statement, quote}` shape in the retention validator, and the extended seeding guard.
- `src/yt_flow/pipeline/nodes/scenario.py` — `_outline_reference`/`_stamp_origin` (outline / writing / unknown, with the overlap score), `_build_quality`'s `outline_grounding` list, category and `outline_originated` block, and the unreachable-retry log line.
- `prompts/scenario/structure.md` — the `{{scp_source_text}}` block, the `statement`/`quote` schema and real-span exemplars, `critic_agent.md`'s certainty rule ported verbatim, the `event` discipline and four self-check lines. `critic_agent.md` and `review.md` are byte-identical (AC7).
- `src/yt_flow/domain/state.py`, `frontend/src/lib/api.ts`, `frontend/src/components/ArtifactPanel.tsx` — the typed payload and the operator's view of origin, the outline notes and the honest total.
- `tests/` — ~90 new tests across the chain, the gate payload, the API, the state contract and the panel; `_bmad-output/implementation-artifacts/5-22-verification-evidence/verify_5_22.py` updated for the new signature.
- `_bmad-output/implementation-artifacts/12-8-live-validation/` — `calibrate.py` (the distribution that chose both thresholds), `attribute.py` (the ablation attribution table, mechanised), `run_outline.py`, two live dumps, `seeding.md`, `after.md`.

**Review.** 20 patches applied (high 4, medium 13, low 3), 2 deferred, 4 rejected; no intent gap and no spec loopback. The four high findings were structural: a first-attempt shape failure could turn an evidence note into a failed run; the strictness counter outlived the truncation re-roll and silently skipped the correction; the "regenerate the outline" imperative fired on notes the outline never minted (it misfired on run1's own false positive); and the attribution stamp had been attached to a channel that was empty in both live runs while the channel that actually carried the findings — the critic's `ungrounded_claim` notes — had no attribution at all. The last was fixed and re-derived offline against the committed dumps rather than by spending another live run.

**Verification.** `uv run pytest tests/ -q --ignore=tests/e2e` → 3103 passed, 1 skipped. `cd frontend && npm test -- --run` → 142 passed. `ruff check` clean. `git diff --stat prompts/scenario/critic_agent.md prompts/scenario/review.md` → empty. Two full live SCP-049 runs on the seeded prompts (DeepSeek research/structure, Gemini writing/review/critic; no GPU): quotes located 15/15 and 11/11, `quote_not_found` 0 after the corrective retry, `hedge_dropped` 0, and the "appears fused → 융합되어 있다" assertion that ran through all three ablation arms is gone — the outline now writes "융합된 것으로 보이는" beside `quote: "…appears fused…"`. Outline-originated violations: run1 0, run2 1 (씬9, traced by script to `event.what`), against the ablation baseline of control 1 / A 2 / B 4. Zero source-quote leakage into narration in either run. `structure` ran once per run and no third pass occurred.

**Residual risks.** The attribution path has still never fired inside a live pipeline: the re-derivation was done offline over the committed dumps, so the runtime stamp on critic notes remains unverified live. Both thresholds are floors on lexical disjointness, not detectors — `_EVENT_SUPPORT_MIN` catches 1 of 3 labelled fabrications at ~11% precision on its calibration set and missed the one live `event.what` violation that reached narration (overlap 0.238, 8× the threshold), which is why it is note-only. `_ATTRIBUTION_MIN` clears 54% of arbitrary narration; the score now ships beside the label so the operator sees the margin. Hedge preservation is measured on one repeated sentence in one SCP, and `hedge_dropped` has zero live fires, so the check itself is unproven — the prompt rule is what moved the outcome. One SCP, two runs, same archetype.
