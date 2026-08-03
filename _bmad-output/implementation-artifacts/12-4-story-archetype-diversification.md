---
baseline_commit: 71417071ba42a28a3f7e6ef2720f706176041501
---

# Story 12.4: Story Archetype Diversification

Status: ready-for-dev

## Story

As **Jay, the yt.flow operator**,
I want **the scenario research stage to select a source-grounded narrative archetype suited to each SCP instead of forcing every episode through the same INCIDENT-FIRST four-act template**,
so that **episodes vary their documentary/creepypasta pacing while preserving factual fidelity, retention safeguards, and all existing downstream pipeline contracts**.

## Acceptance Criteria

1. **Closed archetype catalogue — four total, no free text**
   - The supported values are exactly:
     - `incident_first` (existing behavior)
     - `discovery_log`
     - `interview_testimony`
     - `containment_breach_realtime`
   - This adds three archetypes, satisfying the Epic requirement to add 2–3 beyond INCIDENT-FIRST while remaining within the research recommendation of 3–5 total templates.
   - `researcher_descent` is explicitly deferred as a future catalogue extension; do not add it in this story.
   - A single typed/immutable vocabulary is the source of truth for parser validation, prompt-guide lookup, tests, state typing, and evaluation validation. Lockstep assertions/tests prevent guide or vocabulary drift.

2. **Research owns one evidence-based selection per run**
   - `prompts/scenario/research.md` emits `story_archetype` and a short non-empty `archetype_rationale` grounded in the supplied SCP source (incident/log/interview/chronology evidence), in addition to every existing research field.
   - Selection is based on source-material fit. Random choice, SCP-index round-robin, and post-research reselection are forbidden.
   - `research_step` normalizes casing/outer whitespace and accepts only the closed vocabulary.
   - **Evidence inventory, deterministically enforced (Jay, 2026-08-03).** Grounding must not rest on the model's own promise that it grounded itself. `research.md` additionally emits a `source_evidence` inventory — a closed set of booleans for which SCP-document addendum types the supplied source actually contains (`incident_log`, `experiment_log`, `interview_log`, `recovery_report`, `dated_chronology`). A pure function maps each archetype to its required evidence (`discovery_log` → `recovery_report` or `dated_chronology`; `interview_testimony` → `interview_log`; `containment_breach_realtime` → `incident_log`; `incident_first` → none), and `research_step` **rejects an archetype whose required evidence is absent**, resolving through the same deterministic path as an invalid value (fall back to `incident_first`, set `story_archetype_fallback_used=true`, WARNING naming the archetype and the missing evidence key). No extra LLM call — reuse the existing bounded semantic-correction path only for malformed values, not for this check.
   - Rationale for the hard check: an archetype whose evidence type is absent from the source forces the writer to **invent** the framing device (an interview that was never logged, a chronology that does not exist), and that loss lands squarely on the `article_fidelity` axis — the same failure class as Story 8.8's SCP-096 `article_fidelity -1.00` golden-set FAIL. AC4's no-fabrication invariant states the rule; this check is what enforces it before generation instead of detecting it afterwards.
   - Diversity is subordinate to fidelity: when the inventory supports only `incident_first`, staying on `incident_first` is the correct outcome, not a degradation. Do not widen the required-evidence map to make more SCPs "eligible".
   - `archetype_rationale` is a required non-empty normalized free-text field. Add it to the existing deterministic YAML free-text repair set so inline `:`/`#` and multiline output cannot bypass the Story 6.11 repair path.
   - Missing, non-string, or unknown archetype values use the existing bounded semantic correction call once. If the corrected response is still invalid, resolve deterministically to `incident_first`, set `story_archetype_fallback_used=true`, emit a WARNING containing the rejected value/reason, and continue. Never add an unbounded LLM retry.
   - Implement the second-failure behavior explicitly: introduce a narrow `StoryArchetypeError` carrying the otherwise-valid parsed research packet, and extend `_call_stage_with_retry` with an optional semantic-fallback callback invoked only when the retry parse raises that exact error. The research callback replaces only `story_archetype`; missing/invalid descriptors, entity fields, logline, rationale, or any unrelated schema failure still propagate and fail the stage.
   - The resolved value is fixed before `structure_step` and is reused unchanged by pass 1, scene-scoped repair, and full-rewrite fallback.

3. **Archetype-specific structure without contradictory global instructions**
   - `structure_step` explicitly receives the resolved `story_archetype` and only that archetype's guide; it must not infer the choice from a buried prose field or choose again.
   - `prompts/scenario/structure.md`, `prompts/scenario/writing.md`, and Section F of `prompts/scenario/format_guide.md` no longer universally require INCIDENT-FIRST or its fixed Act 1→4 reveal order.
   - Each archetype guide defines its own ordered beats, point of view, reveal timing, allowed documentary/creepypasta devices, and ending contract:
     - `incident_first`: consequential event → expanding mystery → identity/properties → unresolved residue.
     - `discovery_log`: dated/ordered evidence discovery → hypothesis changes → dangerous implication → unresolved record gap.
     - `interview_testimony`: testimony/framing → credibility fractures or contradictions → corroborated core event → lingering uncertainty; an unreliable narrator is optional, never fabricated as fact.
     - `containment_breach_realtime`: stable baseline → trigger → escalating response in compressed chronology → consequence/aftermath; real-time language must follow source-supported ordering.
   - Writing follows the selected structure rather than reapplying a global incident-first template.

4. **Universal quality and grounding invariants remain mandatory**
   - Every archetype preserves the existing 8–12 scene contract, source-fact coverage, visual descriptor propagation, scene titles/kickers, valid mood values, varied pacing, first-five-second hook, adjacent emotional-beat variation, viewer immersion, and retention-safe ending.
   - Cold opens, unreliable narrators, nonlinear ordering, quotations, dates, or document/log framing may be used only when they do not present invented details as source facts. Formatting devices cannot weaken article fidelity.
   - Existing research fields (`frozen_descriptor`, `entity_sheet`, `story_logline`, hooks, dramatic beats, environment), writing/visual schemas, sentence-to-shot mapping, review/critic flow, one-retry bound, TTS normalization, and downstream `SceneState`/`ShotData` contracts remain intact.

5. **Curated few-shot guide assets — one per archetype minimum**
   - Add one repo-authored, concise YAML beat-sheet example for each of the four supported archetypes (a second example is optional only when it demonstrates a materially different valid shape).
   - Store each guide/example under `prompts/scenario/archetypes/<story_archetype>.md`; fetch it through the existing label-aware Prompt Hub path and inject only the selected guide into `structure_step` to avoid unrelated prompt/token bloat.
   - Examples teach structure, not SCP facts: use clearly synthetic placeholders or source-neutral fact labels so examples cannot leak unsupported facts into a generated episode.
   - Tests prove every catalogue value has a non-empty guide and at least one example, and that guide keys exactly match the closed vocabulary.

6. **Selected archetype is observable and reusable by Story 6.2 evaluation**
   - Add optional `story_archetype` and `story_archetype_fallback_used` to `PipelineState` and return them from `scenario_node` with `scenes/current_stage/error`. They must be plain JSON-serializable and remain non-authoritative outside LangGraph state.
   - The scenario-only evaluator records the selected value as a categorical `story_archetype` evaluation plus boolean `story_archetype_valid` and `story_archetype_fallback_used` metrics. Local debug artifacts include both fields. The fallback metric is required because post-resolution validity alone would otherwise always be true and hide selector drift.
   - `ItemResult` stores the categorical value in a dedicated optional field. `_to_item_result` must exclude it from numeric `rule_metrics`; `aggregate_runs` may retain the ordered observed values/mode for reporting but must never pass a string into median/delta arithmetic. Candidate/baseline comparison remains limited to the existing quality axes and total.
   - The current fixed `golden-scps` inputs (`SCP-096`, `SCP-173`, `SCP-049`) remain unchanged. They measure scenario quality and observed selection distribution; they do **not** claim exhaustive four-archetype coverage.
   - Exhaustive catalogue coverage is provided by deterministic parser/guide/forced-fixture unit tests. Do not force a different archetype onto each golden SCP and do not require one video to contain multiple archetypes.
   - Archetype metrics are informational in current DEV MODE; do not add them to winner selection or reactivate the frozen promotion gate.

7. **Prompt policy and rollout follow the current repository policy**
   - Repo files remain the prompt source of truth; no prompt text or examples exist only in the Langfuse UI.
   - In the current 2026-08-03 DEV MODE, seed changed/new prompts directly to `production` with `uv run python scripts/migrate_prompts.py --label production --source prompts`.
   - Do not run or request candidate-vs-production A/B, `--baseline`, a promotion gate, or `YTFLOW_ALLOW_AB_GATE`. Optional `--profile smoke` feedback is allowed but is not completion evidence.
   - Prompt fetch and compile remain label-aware so the suspended candidate workflow can be restored by Story 13.4 without redesign.

8. **End-to-end compatibility and verification**
   - No new graph stage, service, DB table, API route, frontend surface, GPU/ComfyUI work, provider, or package dependency is introduced.
   - Scenario gates, inline scenario edit/approve UX, prompt variant lookup, Langfuse tracing failure isolation, stage trace accounting, scoped repair/full rewrite, retry/resume, and image/TTS/subtitle/video inputs continue unchanged.
   - Scenario retry nullification clears both new state fields (`story_archetype=None`, `story_archetype_fallback_used=False` or absent-equivalent) together with scenes/video. A failed rerun must never expose the previous attempt's archetype beside a new error.
   - Offline fixtures/stub profile data are updated for the new research contract.
   - Focused scenario/prompt/eval tests, the full suite, and Ruff all pass. Network LLM calls and a live Langfuse evaluation are not required to prove this story.

## Tasks / Subtasks

- [ ] Task 1: Define the closed story-archetype contract (AC: 1, 2, 6)
  - [ ] Add `StoryArchetype` and `STORY_ARCHETYPES` in `src/yt_flow/domain/state.py`; add `story_archetype: NotRequired[StoryArchetype | None]` and `story_archetype_fallback_used: NotRequired[bool]` to `PipelineState`.
  - [ ] Add a narrow `StoryArchetypeError` + optional second-parse semantic-fallback callback seam to `_call_stage_with_retry`; only this error may resolve to `incident_first` after the existing one retry.
  - [ ] Validate/normalize `archetype_rationale`, include it in `FREETEXT_KEYS`, and ensure unrelated research schema errors remain fatal after the retry.
  - [ ] Add lockstep tests for vocabulary, guide keys, and fallback behavior. Keep `PipelineState` key-contract tests synchronized.

- [ ] Task 2: Move selection into research and pass it explicitly to structure (AC: 2, 3, 4)
  - [ ] Extend `research.md` with the four-value catalogue, selection criteria, `story_archetype`, and `archetype_rationale` output fields.
  - [ ] Preserve and normalize all existing research fields; update offline research cassette(s).
  - [ ] Extend `structure_step` to resolve/fetch the chosen archetype guide label-aware and compile `structure.md` with explicit `story_archetype` and `archetype_guide` variables.
  - [ ] Verify the choice is made exactly once and stays fixed through pass 1, scene repair, and full rewrite.

- [ ] Task 3: Author the four archetype guides and remove universal INCIDENT-FIRST overrides (AC: 3, 4, 5)
  - [ ] Add `prompts/scenario/archetypes/{incident_first,discovery_log,interview_testimony,containment_breach_realtime}.md` with beat grammar, POV/timeline rules, fact-safety rules, ending contract, and ≥1 concise YAML example each.
  - [ ] Make `structure.md` catalogue-driven and selected-guide-driven while retaining common scene schema/rules.
  - [ ] Replace `format_guide.md` Section F with archetype-neutral shared principles and a pointer to selected-guide authority.
  - [ ] Remove `writing.md`'s fixed incident-first Act 1–4 instructions; require adherence to the supplied scene structure and selected guide instead.
  - [ ] Add prompt-contract tests that fail if any common prompt again unconditionally forces INCIDENT-FIRST.

- [ ] Task 4: Persist and trace the selected archetype (AC: 6, 8)
  - [ ] Return `story_archetype` and `story_archetype_fallback_used` from `scenario_node` on successful generation; include selection/fallback facts in research/structure trace metadata without changing stage names or token accounting.
  - [ ] Update scenario-stage `_nullify` in `run_service.py` to clear both values before rerun; add a regression test proving a failed scenario retry cannot retain stale selection state.
  - [ ] Preserve error shaping (`stage=scenario run_id=...`) and do not write DB/SSE/gates from pipeline code.
  - [ ] Test successful propagation and verify repair/full-rewrite paths do not change the selection.

- [ ] Task 5: Connect observability to the existing Story 6.2 runner (AC: 5, 6, 7)
  - [ ] Extend `scripts/eval_prompts.py` so full scenario output/debug artifacts retain `story_archetype`.
  - [ ] Emit a categorical `story_archetype` evaluation plus deterministic validity and fallback-used metrics; add a dedicated `ItemResult.story_archetype` field and exclude the categorical value from numeric rule-metric aggregation/deltas.
  - [ ] Keep narrative axes and comparison authority unchanged; multi-repetition aggregation may report observed archetypes but must not treat selection differences as quality regression.
  - [ ] Add runner tests for valid/invalid/missing values, artifact persistence, and the fact that three golden SCPs are not asserted to cover all four archetypes.

- [ ] Task 6: Fixtures, regression, and rollout (AC: 7, 8)
  - [ ] Update `tests/fixtures/cassettes/deepseek_research.json` and any dependent stub fixtures/README contract notes; update structure fixture only if its emitted shape changes.
  - [ ] Run `uv run pytest -q tests/pipeline/nodes/test_scenario_chain.py tests/pipeline/nodes/test_scenario.py tests/test_eval_prompts.py tests/domain/test_state_imports.py` plus the existing run-service scenario retry/nullification test module.
  - [ ] Run `uv run pytest -q` and `uv run ruff check` on changed Python/test files.
  - [ ] Seed from repo to Langfuse production using the exact DEV MODE command in AC7. Record the command/result in the Dev Agent Record; do not run a baseline/promotion gate.

## Dev Notes

### Why this story exists

The live prompt chain is already a strong coarse-to-fine pipeline: research → structure → writing → cast/visual breakdown → review/critic → one bounded repair → TTS normalization. The defect is narrower: `structure.md`, `writing.md`, and `format_guide.md` all force the same INCIDENT-FIRST reveal grammar. Jay's SCP-049 E2E review identified the repeated episode shape as visible sameness, and the 2026-08-01 quality research confirmed that template diversity—not a replacement scenario architecture—is the intended correction.

The cited 2026 narrative-theory survey supplies a taxonomy and argues for theory-based evaluation of individual narrative attributes; it does **not** provide this SCP archetype catalogue. Treat the four values above as a yt.flow product design grounded by narrative-planning literature, not as categories copied from Propp or the survey. Content-planning research supports selecting a principled outline before prose generation; theory-grounded planning work supports explicit suspense/act plans and attribute-level evaluation. Do not force folktale roles/functions into factual SCP documentary scripts.

### Design decisions that close ambiguities in the Epic draft

1. **Four total archetypes, not five.** The Epic says to add 2–3 beyond INCIDENT-FIRST. Three additions gives adequate diversity without expanding example/evaluation cost. `researcher_descent` overlaps discovery-log and is deferred.
2. **Research chooses; structure obeys.** The full research dict already flows into `structure_step`, so no new stage/service is needed. Selection after research would allow retries to drift between templates.
3. **Bounded correction plus safe fallback.** Existing `_call_stage_with_retry` gives one semantic correction opportunity. A narrow error/callback seam handles only a second invalid archetype; every other validation error stays fatal. `incident_first` preserves current production behavior, while the WARNING, trace flag, and evaluation metric prevent silent degradation.
4. **Prompt component per archetype.** A selected guide under `prompts/scenario/archetypes/` prevents every run from paying for or being confused by all examples. `migrate_prompts.py --source prompts` preserves full folder names; never seed from the nested directory directly.
5. **Golden examples and golden-set evaluation are related but distinct.** Few-shot examples teach each template at runtime. The Story 6.2 runner observes selection and quality on real fixed inputs. Four-value exhaustiveness belongs in deterministic tests because the existing dataset has only three items and source-fit selection must not be overridden for coverage theatre.

### Current state of files to update

**`src/yt_flow/domain/state.py` (UPDATE)**
- Current: pure TypedDict substrate; `PipelineState` has no narrative-template field.
- Change: add closed type/vocabulary and optional JSON-serializable `story_archetype` state field.
- Preserve: no imports from pipeline/services/db/api; all existing required state keys and all SceneState/ShotData shapes.

**`src/yt_flow/pipeline/nodes/scenario_chain.py` (UPDATE — core code)**
- Current: `research_step` parses/normalizes research fields; `structure_step` serializes the whole research packet into a single prompt; `_call_stage_with_retry` performs at most one semantic correction. There is no archetype validation or guide lookup.
- Change: resolve the research-owned value, fetch the selected guide using the same label, and pass explicit variables into structure. Keep the full research packet for all current information.
- Preserve: deterministic YAML free-text repair, truncation handling, one semantic retry, candidate/production fallback semantics, title compatibility, and every later parse/build function.

**`src/yt_flow/pipeline/nodes/scenario.py` (UPDATE — narrow propagation only)**
- Current: builds research once, structure once, reuses structure through repair, and returns only scenes/current_stage/error.
- Change: return/trace the resolved `story_archetype` and fallback-used flag on success.
- Preserve: stage order, concurrent per-scene cast/visual work, retry scope, failure conversion, TTS normalization, and `build_scenes` behavior.

**`prompts/scenario/research.md` (UPDATE)**
- Current: produces research facts/hooks but no template choice.
- Change: add the closed selection and source-grounded rationale.
- Preserve: non-empty frozen/entity/story fields and source-only fact rule.

**`prompts/scenario/structure.md` (UPDATE)**
- Current: unconditionally says “Design ... INCIDENT-FIRST” and encodes its four acts.
- Change: use `{{story_archetype}}` and `{{archetype_guide}}`; keep common 8–12 scene schema and cross-archetype rules.
- Preserve: mood/title/kicker contract, fact references, pacing, hook, emotional variation, and viewer immersion.

**`prompts/scenario/writing.md` (UPDATE)**
- Current: independently reasserts incident-first reveal order, overriding a diversified outline.
- Change: follow the selected scene structure and its act/POV/timeline decisions.
- Preserve: Korean narration contract, source fidelity, sentence-count/downstream expectations, and visual identity consistency.

**`prompts/scenario/format_guide.md` (UPDATE)**
- Current: Section F globally defines INCIDENT-FIRST as the act structure and is injected into several stages.
- Change: retain universal retention principles but remove global template authority.
- Preserve: hook library, progressive disclosure where applicable, emotional curve, immersion, and pacing guidance. Phrase progressive disclosure as a common safety/retention principle that an archetype guide may realize differently, not a fixed act order.

**`prompts/scenario/archetypes/*.md` (NEW — four files)**
- One selected, label-aware prompt component per closed value. Repo-authored, concise, source-neutral examples only.

**`scripts/eval_prompts.py` (UPDATE — observability only)**
- Current: fixed three-SCP dataset; rule metrics see scenes only and record scene/shot/empty counts. No template value survives scenario output.
- Change: preserve categorical selection, validity, and fallback-used signal in experiment results/artifacts without mixing strings into numeric aggregation.
- Preserve: dataset IDs/content, scenario-only isolation, existing axes, caching, timeouts, label mapping, failure isolation, statistical comparison, and frozen-gate safeguards.

**`src/yt_flow/services/run_service.py` (UPDATE — scenario nullification only)**
- Current: scenario retry clears `scenes` and `video_path` but cannot know about the new selection fields.
- Change: clear `story_archetype` and `story_archetype_fallback_used` in the same scenario-owned nullification update.
- Preserve: AD-9 update-state/reinvoke flow, other stage nullification scopes, DB projection, SSE fan-out, and retry error handling.

**Tests/fixtures (UPDATE)**
- `tests/domain/test_state_imports.py`: synchronize optional state key/type contract.
- `tests/pipeline/nodes/test_scenario_chain.py`: resolver, retry/fallback, guide lookup, compile variables, prompt contract.
- `tests/pipeline/nodes/test_scenario.py`: output/trace propagation and repair stability.
- `tests/test_eval_prompts.py`: categorical/validity observation and artifact persistence.
- Existing run-service scenario retry/nullification tests: both new fields are cleared before rerun and stay cleared on failure.
- `tests/fixtures/cassettes/deepseek_research.json` plus dependent fixture notes/stubs: add the research fields.
- Preserve unrelated `.serena/` user files and any dirty-worktree content.

### Architecture compliance and regression guardrails

- **AD-1 / existing prompt seam:** `scenario_chain.py` already imports `yt_flow.services.prompt_service`, a pre-existing exception to the documented downward dependency rule. Reuse that exact seam for guide lookup; add no new cross-layer dependency and no archetype service. Do not claim this story repairs the pre-existing architecture debt.
- **AD-2:** The chosen value is in LangGraph state, not a DB shadow or global mutable cache.
- **AD-4:** Nodes return replacement state fields; they do not mutate input state or emit SSE/DB writes.
- **AD-10:** Prompt/Langfuse tracing behavior stays non-fatal where already designed; an invalid model selection falls back observably after the bounded retry.
- Prompt guide loading must use `prompt_service`, never runtime reads from the repo path. Repo files are authoring sources; Langfuse remains the runtime provider.
- Do not change gate topology, artifact editing, API serializers, frontend types, or image sidecars. The only retry/resume change is clearing the two new scenario-owned state fields during scenario nullification.
- Do not invent an aggregate “narrative quality” score or add archetype diversity to per-run winner selection. One episode correctly has one template.

### Previous story and Git intelligence

- Story 12.3 now has a `ready-for-dev` context artifact but no implementation commit. It plans `scenario_quality`/`unresolved_pass2` state, grounded review fields, deterministic text metrics, and scenario retry nullification across `domain/state.py`, `scenario.py`, `scenario_chain.py`, and `run_service.py`—the same four code files this story touches. Implement 12.3 first per Epic order, then re-read its completed File List/review notes before starting 12.4; do not develop both stories against the same files in parallel.
- Preserve 12.3's one-retry rule and its requirement that scenario retry clears all scenario-owned quality context. Extend that same nullification update with this story's two fields rather than replacing it. Archetype diversification must continue through 12.3's review/critic and human warning gate; it must not bypass or duplicate them.
- Story 12.4 was previously only the draft Story 10.1 and was moved into Epic 12 by commit `13a47ed`. At baseline commit `7141707`, no Epic 12 implementation code existed; newly created 12.x files are planning context, not reusable implementation.
- Closest proven code precedent: Story 11.2 (`ce4bcef`) introduced a closed camera-archetype vocabulary, accepted valid LLM output, used deterministic repair/fallback, asserted vocabulary lockstep, and tested pure functions without changing downstream state shape.
- Stories 6.7/6.11/8.18 reinforce bounded/deterministic repair without extra LLM loops. Story 6.2 supplies the scenario-only experiment runner; Story 6.13 supplies exact-rendered-prompt caching.
- Recent commits `13a47ed` and `7141707` modify only planning/status artifacts for Epic 12. They contain no hidden implementation to reuse.

### Library and latest technical information

- No package addition or upgrade is required. Use Python 3.12, existing PyYAML parsing, Langfuse SDK 4.12.0, and the current prompt service.
- Langfuse's current SDK experiment model supports dataset tasks plus item/run evaluators and categorical/boolean/numeric evaluations. Existing `Dataset.run_experiment` is the correct integration point; do not build a second evaluator.
- Langfuse prompt versions are immutable and labels point to versions. The project-specific DEV MODE direct-to-production rule remains authoritative for this story despite the general candidate/promotion workflow supported by Langfuse.
- The 2026 survey recommends theory-based metrics for individual narrative attributes and notes that a unified narrative-quality benchmark remains unresolved. This supports retaining yt.flow's existing axes plus explicit archetype validity/selection rather than claiming one new universal score.

### Project Structure Notes

- Expected new files are limited to four prompt components under `prompts/scenario/archetypes/`.
- Do not create `archetype_service.py`, a new graph node, an archetype DB table, or frontend controls.
- `scripts/migrate_prompts.py` derives prompt names relative to the supplied source directory. Always seed with `--source prompts`, yielding names such as `scenario/archetypes/discovery_log`; using the nested directory would create wrong prompt names.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 12.4] — draft intent, 2–3 additions, examples, research-stage selection, Story 6.2/PROMPT_POLICY linkage.
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 10] — original SCP-049 viewing feedback and fixed-template diagnosis.
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 12] — Epic objective, GPU-free boundary, predecessor order 12.2 → 12.1 → 12.3 → 12.4.
- [Source: _bmad-output/implementation-artifacts/12-3-pass2-verdict-grounded-gate.md] — immediate predecessor contract, shared-file collision surface, one-retry preservation, and scenario-owned nullification requirements.
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#Area 5.1] — current multi-stage chain and only-one-template diagnosis.
- [Source: _bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#Phase 3] — recommended template catalogue and research-stage owner.
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Invariants & Rules] — AD-1/2/4/10 and state/pipeline contracts.
- [Source: _bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#Functional Requirements] — FR-1 structured scenario generation, FR-14–17 prompt management, FR-18–23 evaluation.
- [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run Detail — artifact panel by stage] — scenario remains editable and separately approved.
- [Source: docs/PROMPT_POLICY.md#Prompt Policy] — repo source of truth, current DEV MODE rollout, forbidden baseline/promotion actions.
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:644] — bounded stage retry and deterministic YAML repair.
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:705] — current research parsing/validation.
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:753] — current research→structure handoff.
- [Source: src/yt_flow/pipeline/nodes/scenario.py:311] — orchestration, repair reuse, and current return shape.
- [Source: scripts/eval_prompts.py:170] — fixed three-SCP dataset and seeding.
- [Source: scripts/eval_prompts.py:289] — current scenario rule metrics.
- [Source: prompts/scenario/research.md] — current research output schema.
- [Source: prompts/scenario/structure.md] — current unconditional INCIDENT-FIRST structure.
- [Source: prompts/scenario/writing.md] — second unconditional incident-first override.
- [Source: prompts/scenario/format_guide.md#F. Act Structure & Ratios] — third unconditional incident-first override.
- [Narrative Theory-Driven LLM Methods survey](https://arxiv.org/abs/2602.15851) — theory taxonomy and attribute-level evaluation direction; not the source of this catalogue.
- [Strategies for Structuring Story Generation](https://arxiv.org/abs/1902.01109) — coarse-to-fine content planning precedent.
- [Plan-and-Write / principled plot structure study](https://aclanthology.org/2020.emnlp-main.351/) — structured content planning improves story generation quality.
- [Theory-grounded iterative suspense planning](https://aclanthology.org/2024.eacl-long.147/) — explicit narrative planning and human attribute evaluation.
- [Act-plan effects across languages](https://aclanthology.org/2024.lrec-main.929/) — explicit act planning supports coherence/interest in multilingual generation.
- [Structural homogeneity in LLM stories](https://aclanthology.org/2024.emnlp-main.978/) — supports measuring and preventing repetitive generated structures.

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.

### File List
