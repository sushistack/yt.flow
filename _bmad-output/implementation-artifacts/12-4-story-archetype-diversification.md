---
baseline_commit: 71417071ba42a28a3f7e6ef2720f706176041501
---

# Story 12.4: Story Archetype Diversification

Status: done

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

- [x] Task 1: Define the closed story-archetype contract (AC: 1, 2, 6)
  - [x] Add `StoryArchetype` and `STORY_ARCHETYPES` in `src/yt_flow/domain/state.py`; add `story_archetype: NotRequired[StoryArchetype | None]` and `story_archetype_fallback_used: NotRequired[bool]` to `PipelineState`.
  - [x] Add a narrow `StoryArchetypeError` + optional second-parse semantic-fallback callback seam to `_call_stage_with_retry`; only this error may resolve to `incident_first` after the existing one retry.
  - [x] Validate/normalize `archetype_rationale`, include it in `FREETEXT_KEYS`, and ensure unrelated research schema errors remain fatal after the retry.
  - [x] Add lockstep tests for vocabulary, guide keys, and fallback behavior. Keep `PipelineState` key-contract tests synchronized.

- [x] Task 2: Move selection into research and pass it explicitly to structure (AC: 2, 3, 4)
  - [x] Extend `research.md` with the four-value catalogue, selection criteria, `story_archetype`, and `archetype_rationale` output fields.
  - [x] Preserve and normalize all existing research fields; update offline research cassette(s).
  - [x] Extend `structure_step` to resolve/fetch the chosen archetype guide label-aware and compile `structure.md` with explicit `story_archetype` and `archetype_guide` variables.
  - [x] Verify the choice is made exactly once and stays fixed through pass 1, scene repair, and full rewrite.

- [x] Task 3: Author the four archetype guides and remove universal INCIDENT-FIRST overrides (AC: 3, 4, 5)
  - [x] Add `prompts/scenario/archetypes/{incident_first,discovery_log,interview_testimony,containment_breach_realtime}.md` with beat grammar, POV/timeline rules, fact-safety rules, ending contract, and ≥1 concise YAML example each.
  - [x] Make `structure.md` catalogue-driven and selected-guide-driven while retaining common scene schema/rules.
  - [x] Replace `format_guide.md` Section F with archetype-neutral shared principles and a pointer to selected-guide authority.
  - [x] Remove `writing.md`'s fixed incident-first Act 1–4 instructions; require adherence to the supplied scene structure and selected guide instead.
  - [x] Add prompt-contract tests that fail if any common prompt again unconditionally forces INCIDENT-FIRST.

- [x] Task 4: Persist and trace the selected archetype (AC: 6, 8)
  - [x] Return `story_archetype` and `story_archetype_fallback_used` from `scenario_node` on successful generation; include selection/fallback facts in research/structure trace metadata without changing stage names or token accounting.
  - [x] Update scenario-stage `_nullify` in `run_service.py` to clear both values before rerun; add a regression test proving a failed scenario retry cannot retain stale selection state.
  - [x] Preserve error shaping (`stage=scenario run_id=...`) and do not write DB/SSE/gates from pipeline code.
  - [x] Test successful propagation and verify repair/full-rewrite paths do not change the selection.

- [x] Task 5: Connect observability to the existing Story 6.2 runner (AC: 5, 6, 7)
  - [x] Extend `scripts/eval_prompts.py` so full scenario output/debug artifacts retain `story_archetype`.
  - [x] Emit a categorical `story_archetype` evaluation plus deterministic validity and fallback-used metrics; add a dedicated `ItemResult.story_archetype` field and exclude the categorical value from numeric rule-metric aggregation/deltas.
  - [x] Keep narrative axes and comparison authority unchanged; multi-repetition aggregation may report observed archetypes but must not treat selection differences as quality regression.
  - [x] Add runner tests for valid/invalid/missing values, artifact persistence, and the fact that three golden SCPs are not asserted to cover all four archetypes.

- [x] Task 6: Fixtures, regression, and rollout (AC: 7, 8)
  - [x] Update `tests/fixtures/cassettes/deepseek_research.json` and any dependent stub fixtures/README contract notes; update structure fixture only if its emitted shape changes.
  - [x] Run `uv run pytest -q tests/pipeline/nodes/test_scenario_chain.py tests/pipeline/nodes/test_scenario.py tests/test_eval_prompts.py tests/domain/test_state_imports.py` plus the existing run-service scenario retry/nullification test module.
  - [x] Run `uv run pytest -q` and `uv run ruff check` on changed Python/test files.
  - [x] Seed from repo to Langfuse production using the exact DEV MODE command in AC7. Record the command/result in the Dev Agent Record; do not run a baseline/promotion gate.

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

claude-opus-5[1m] (Claude Opus 5, 1M context) — Claude Code dev-story workflow

### Debug Log References

- `uv run pytest -q` (full suite): **2328 passed, 1 skipped, 0 failed** in 295s.
  Baseline before this story was 2251 passed / 1 skipped → **+77 tests**.
  ⚠️ **Review re-measurement (2026-08-07): this number does not reproduce.**
  `PYTHONPATH=$PWD/src uv run pytest -q` in this worktree gives
  **2339 passed, 1 skipped** in 304s. The review added exactly 3 tests, so the
  pre-review suite was **2336**, not 2328 — the recorded figure is 8 low. Same
  upward-drift class the 12.3 review flagged (recorded 2238/114 vs measured
  2251/117): the counts in these records are being written from memory rather
  than from the run. Nothing is failing; only the bookkeeping was wrong.
- `uv run ruff check src scripts tests`: **All checks passed**.
- Focused modules: `tests/pipeline/nodes/test_scenario_chain.py` (582 passed),
  `tests/pipeline/nodes/test_scenario.py` (86 passed), `tests/test_eval_prompts.py`
  (152 passed), `tests/domain/test_state_imports.py`, `tests/services/test_run_service_gate.py`
  (28 passed — the run-service scenario retry/nullification module).
- Prompt rollout (AC7, DEV MODE, no baseline/promotion gate):
  `uv run python scripts/migrate_prompts.py --label production --source prompts`
  → `created:` `scenario/archetypes/{incident_first,discovery_log,interview_testimony,containment_breach_realtime}`,
  `scenario/format_guide`, `scenario/research`, `scenario/structure`, `scenario/writing`;
  every other prompt `skipped`. **No incidental promotion** — a read-only pre-check
  computed the would-create set first and it was exactly these 8. Post-seed
  verification: repo text == `production` for all 20 prompts, and a live
  `get_prompt("scenario/archetypes/discovery_log").compile()` returned 1934 chars,
  confirming the nested name derived by `--source prompts` is fetchable at runtime.
  (Langfuse credentials came from the main tree's `.env`; this worktree has none.)

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- **Selection is deterministic where it matters, LLM where it can't be.** Research
  reports a five-key boolean inventory of what the *source* contains; code maps each
  archetype to the evidence its framing device requires and rejects a choice whose
  evidence is absent. The model picks among *eligible* candidates only.
- **Two failure classes, two different resolutions — deliberately.** A malformed
  archetype value is a formatting slip, so it gets the existing one semantic-correction
  retry via a new narrow `StoryArchetypeError` + `semantic_fallback` seam on
  `_parse_with_retry`; a second bad value resolves to `incident_first` with the packet
  intact. A *missing-evidence* archetype is not a slip the model can talk its way out
  of, so that check runs **after** `_call_stage_with_retry` returns and spends **zero**
  extra provider calls (asserted: `calls["n"] == 1`).
- `archetype_rationale` stays a plain `ValueError` (fatal after the retry) on purpose —
  the archetype fallback must not smuggle through a packet with no stated grounding.
  It is also in `FREETEXT_KEYS`, because a rationale citing "Addendum 173-1: …" hits the
  Story 6.11 inline-colon class almost every time.
- **`incident_first` on a bare source is not a fallback.** `story_archetype_fallback_used`
  stays `false` when the inventory legitimately supports only the default. Diversity is
  subordinate to fidelity, and the flag has to keep meaning "the selector failed" or it
  is useless as a drift signal.
- **Resolved once.** `scenario_node` computes the value before `structure_step` and
  passes it as an explicit keyword. Tests pin `structure_step` at exactly one call and
  the same value across pass 1, scene-scoped repair, and the full-rewrite fallback.
- Three prompts each independently re-imposed the same reveal grammar; that was the
  actual defect. `structure.md` is now `{{story_archetype}}` + `{{archetype_guide}}`
  driven, `format_guide.md` §F keeps only cross-archetype principles and points at the
  selected guide for act authority, and `writing.md` follows the supplied outline
  instead of restating Act 1–4. A parametrized prompt-contract test fails if any of the
  three starts doing it again.
- Only the **selected** guide is fetched and injected (asserted), through the same
  label-aware `prompt_service` seam every other stage uses — no new cross-layer
  dependency, no `archetype_service.py`, and the suspended candidate workflow still works.
- Eval side: categorical `story_archetype` + boolean `story_archetype_valid` /
  `story_archetype_fallback_used`. The categorical value lives in its own
  `ItemResult.story_archetype` field and is excluded from `rule_metrics` (a test asserts
  no `rule_metrics` value is ever a `str`, since median/delta arithmetic iterates it);
  `aggregate_runs` reports the modal value and the ordered observations. `compare()` is
  untouched — a different archetype is not a regression.
- `researcher_descent` is deliberately absent, and a test asserts its absence from both
  the vocabulary and `research.md` so it cannot be half-added later.
- ⚠️ **Not verified live (Jay).** No network scenario run was made, per AC8 ("Network LLM
  calls and a live Langfuse evaluation are not required"). So the *live* questions remain
  open: whether DeepSeek reports the evidence inventory honestly, and how the observed
  archetype distribution actually looks on the golden set. Both are one command:
  `uv run python scripts/eval_prompts.py --label production --profile smoke --scp-id SCP-049`
  from the main tree. Worst case if the inventory is over-reported is a fidelity risk the
  code cannot catch — the check trusts research's *reading* of the source, only its
  *choice* is constrained.
- ⚠️ Making `archetype_rationale`/`story_archetype` unconditional (no `label`-gated
  leniency, matching Story 12.1's precedent rather than the older entity_sheet pattern)
  means an un-seeded `scenario/research` prompt would fall back on every run. The seeding
  above closes that; a future environment that skips seeding would see 100%
  `story_archetype_fallback_used=true`, which is exactly the drift signal AC6 asks for.

### File List

**New**
- `prompts/scenario/archetypes/incident_first.md`
- `prompts/scenario/archetypes/discovery_log.md`
- `prompts/scenario/archetypes/interview_testimony.md`
- `prompts/scenario/archetypes/containment_breach_realtime.md`

**Modified — code**
- `src/yt_flow/domain/state.py`
- `src/yt_flow/pipeline/nodes/scenario_chain.py`
- `src/yt_flow/pipeline/nodes/scenario.py`
- `src/yt_flow/services/run_service.py`
- `scripts/eval_prompts.py`

**Modified — prompts**
- `prompts/scenario/research.md`
- `prompts/scenario/structure.md`
- `prompts/scenario/writing.md`
- `prompts/scenario/format_guide.md`

**Modified — tests / fixtures**
- `tests/api/test_e2e_stub_run.py`  <!-- added during review: 3 production-wiring E2E tests, was missing from this list -->
- `tests/domain/test_state_imports.py`
- `tests/pipeline/nodes/test_scenario_chain.py`
- `tests/pipeline/nodes/test_scenario.py`
- `tests/services/test_run_service_gate.py`
- `tests/test_eval_prompts.py`
- `tests/fixtures/cassettes/deepseek_research.json`
- `tests/fixtures/cassettes/README.md`
- `tests/stubs/fakes.py`

## Senior Developer Review (AI)

**Reviewer:** Jay (adversarial AI review, `bmad-story-automator-review`) · **Date:** 2026-08-07
**Outcome:** **Approve** — 5 findings, all fixed in place. 0 CRITICAL.

Every AC was checked against code rather than against the task checkboxes, and the
verification claims were re-run rather than taken on trust. What holds up: the
selection really is resolved once (`scenario.py:556`) and pinned by tests across
pass 1 / scoped repair / full rewrite; the evidence gate really does sit outside
the retry boundary and spends zero extra provider calls (`calls["n"] == 1`); only
the selected guide is ever fetched, asserted both in unit tests and through real
`POST /runs` wiring; the categorical value really is kept out of `rule_metrics`,
with a test that no `rule_metrics` value is ever a `str`. `researcher_descent` is
absent and asserted absent. No new stage, service, table, route, or dependency.

Findings and fixes:

1. **HIGH — an overridden choice left its argument on the packet.**
   `structure_step` dumps the whole research packet into `{{research_packet}}`,
   immediately below a prompt declaring the injected guide the sole authority. On
   either fallback path the packet still carried the model's original
   `archetype_rationale` — a written case for the archetype the gate had just
   refused ("Addendum 173-4의 심문 기록이 증언 서사를 지지함" next to
   `story_archetype: incident_first`). That is a contradictory instruction (AC3) and
   it points at exactly the invented framing device AC4 forbids and the evidence
   gate exists to prevent — the `article_fidelity` failure class the story itself
   cites. **Fixed:** `_fallback_rationale()` replaces the invalidated field on both
   override paths (`scenario_chain.py`); the model's original wording stays in the
   WARNING beside it. Two new tests cover both paths and assert a kept choice is
   *not* rewritten.

2. **MEDIUM — the guide examples are injected as if they were the schema.**
   All four guides end in an example outline that omits every hard-required
   Retention Contract field (`event`, `word_budget`, `hook_type`,
   `loops_planted/closed`, `pattern_interrupt`, `fact_references`, `mood`,
   `title`, `kicker`) and skips scene numbers (1, 3, 5, 7, 9) — and it lands
   *above* the field schema, under the line naming the guide 유일한 권위. This is not
   a soft quality risk: `_validate_retention_outline` hard-fails a scene with no
   `event` or no `word_budget`, so imitation of the example shape fails the run.
   **Fixed:** an explicit excerpt disclaimer in `structure.md` directly after
   `{{archetype_guide}}` (one place, covers all four guides, cannot drift).

3. **MEDIUM — File List omitted the strongest tests in the story.**
   `tests/api/test_e2e_stub_run.py` gained 169 lines / 3 production-wiring E2E
   tests (checkpoint round trip, mid-run fallback, retry-clears-then-reresolves)
   and was absent from the Dev Agent Record. **Fixed:** added.

4. **LOW — the drift signal read clean while drifting.** `scenario_node` degraded a
   research packet with no `story_archetype` to `incident_first` but reported
   `story_archetype_fallback_used=False`. A seam that has stopped selecting *is* the
   selector failure AC6 added that flag to expose. **Fixed:** the flag now derives
   from the same expression; the existing degradation test was updated to assert
   the corrected meaning.

5. **LOW — `ARCHETYPE_REQUIRED_EVIDENCE` values were untyped `str`.** AC1 asks for a
   typed source of truth. **Fixed:** values are `tuple[SourceEvidenceKey, ...]`; the
   key stays `str` deliberately (with a comment) because
   `missing_archetype_evidence` must remain total over unvalidated input.

Verified, not assumed:

- `uv run pytest -q` (full suite, this worktree, `PYTHONPATH=$PWD/src`) after the
  fixes: **2339 passed, 1 skipped** in 304s. Focused modules (838 passed) re-run
  after every fix. The story's recorded `2328` does not reproduce — see the ⚠️ note
  in the Debug Log.
- `uv run ruff check src scripts tests` — **All checks passed**, re-run after the fixes.
- `scripts/migrate_prompts.py` uses `source.rglob("*")` + `relative_to(source)`, so
  the nested `scenario/archetypes/*` names the record claims are in fact derivable.
- `langfuse.Evaluation` does accept `data_type=Literal["NUMERIC","CATEGORICAL","BOOLEAN"]`
  in the installed 4.x SDK — the categorical evaluation is not a guess.
- Module-level lockstep `assert`s in `domain/state.py` match established project
  idiom (`color_grade.py`, `camera_path.py`, `video.py`) — not a finding.

Left for Jay (unchanged from the Dev record, and correct to leave):

- The prompt seeding to `production` was performed from the main tree's `.env`;
  this worktree has no credentials, so the review could not re-verify it live.
- Nothing here proves DeepSeek reports `source_evidence` **honestly**. The gate
  constrains the model's *choice*, never its *reading* of the source — an
  over-reported inventory is a fidelity risk no code in this story can catch. The
  one command that would show it: `uv run python scripts/eval_prompts.py --label
  production --profile smoke --scp-id SCP-049` from the main tree.

## Change Log

| Date | Change |
|------|--------|
| 2026-08-07 | **Review (adversarial, auto-fix).** 5 findings, 0 CRITICAL, all fixed. HIGH: after either archetype override the packet still carried the model's rationale for the *rejected* archetype into `{{research_packet}}` — a written invitation to reintroduce the framing device the evidence gate had just refused (AC3 contradiction → AC4 fabrication → `article_fidelity`); `_fallback_rationale()` now replaces the invalidated field on both paths. MEDIUM: the four guides' example outlines omit every hard-required Retention Contract field and land *above* the schema under "유일한 권위", so imitating them fails `_validate_retention_outline` — excerpt disclaimer added to `structure.md`. MEDIUM: `tests/api/test_e2e_stub_run.py` (169 lines, 3 production-wiring E2E tests) was missing from the File List. LOW: a research seam that stopped selecting reported `story_archetype_fallback_used=false`, blinding the one signal AC6 added to catch that drift. LOW: `ARCHETYPE_REQUIRED_EVIDENCE` values now `tuple[SourceEvidenceKey, ...]`. +3 tests, 1 existing test corrected. Status → done. |
| 2026-08-07 | Story 12.4 implemented. Closed four-value `StoryArchetype` vocabulary + `SOURCE_EVIDENCE_KEYS` + `ARCHETYPE_REQUIRED_EVIDENCE` and the pure `missing_archetype_evidence()` gate in `domain/state.py`; `research_step` now selects/normalizes the archetype, validates `archetype_rationale`, and resolves an unusable choice deterministically (narrow `StoryArchetypeError` + `semantic_fallback` seam, one bounded retry, zero extra calls for the evidence check); `structure_step` receives the value explicitly and injects only that archetype's Prompt Hub guide; `scenario_node` returns/traces `story_archetype` + `story_archetype_fallback_used` and `run_service` clears both on scenario nullification/restart; four new archetype guides authored and the three shared prompts stripped of their universal INCIDENT-FIRST overrides; `eval_prompts.py` records the selection as categorical + two booleans without letting a string into numeric aggregation. Prompts seeded repo→`production` (8 created, no incidental promotion). 2328 passed / 1 skipped, ruff clean, +77 tests. |
