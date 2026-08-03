# Story 12.3: Pass-2 Verdict Grounded Gate

Status: ready-for-dev

<!-- Epic 12.3 contains a draft intent rather than a formal user story or BDD criteria. The story and ACs below preserve that intent against the current repository. -->

## Story

As the human scenario reviewer,
I want unresolved pass-2 findings and evidence-grounded contradictions surfaced at the scenario gate,
so that I can knowingly approve or reject a degraded script without silent quality loss or unbounded retries.

## Acceptance Criteria

1. **Existing bounded retry is preserved**
   - **Given** pass 1 returns `critic.verdict == "retry"` or `review.overall_pass == false`,
   - **When** `scenario_node` evaluates the result,
   - **Then** the existing single scoped-repair/full-rewrite fallback executes exactly as today,
   - **And** this story adds no third review, critic, repair, or rewrite pass.

2. **A negative pass-2 verdict becomes a non-fatal gate warning**
   - **Given** a repair/full-rewrite pass has run,
   - **When** the final result still has `critic.verdict == "retry"` or `review.overall_pass == false`,
   - **Then** the scenario stage still succeeds and reaches the existing human gate,
   - **And** a structured `unresolved_pass2` warning is persisted in `PipelineState`,
   - **And** it includes pass index, retry scope, critic verdict, review pass state, concise critic feedback, scene-specific issues, grounded contradiction evidence, and deterministic rule metrics,
   - **And** the human can still approve or reject normally.

3. **Clean final results stay clean**
   - **Given** pass 1 succeeds, or pass 2 finishes with `review.overall_pass == true` and `critic.verdict` equal to `pass` or `accept_with_notes`,
   - **When** the scenario gate is emitted,
   - **Then** no `unresolved_pass2` warning is present,
   - **And** `accept_with_notes` does not trigger another retry or unresolved warning by itself.

4. **Grounded contradictions require quoted evidence**
   - **Given** narration contradicts `entity_sheet` or `frozen_descriptor`,
   - **When** `review_step` evaluates the scenario,
   - **Then** each contradiction identifies the scene, quotes the offending narration, identifies and quotes the conflicting grounding source, explains the conflict, and proposes a correction,
   - **And** it is also represented in `issues[]` with `type: grounded_contradiction` so it participates in the pass-1 repair decision,
   - **And** `overall_pass` is false while a grounded contradiction remains,
   - **And** parser validation rejects a claimed contradiction lacking required evidence.

5. **Deterministic quality metrics are code-derived**
   - **Given** a writing payload is available,
   - **When** quality metrics are computed,
   - **Then** pure Python reports, per scene and in aggregate: non-whitespace character count, sentence count, exact normalized duplicate-sentence count, repeated normalized 4-token n-grams occurring at least three times, and exact matches from a small versioned Korean slop-phrase tuple,
   - **And** Unicode uses `unicodedata.normalize("NFKC", ...)`, whitespace is collapsed, and terminal punctuation is ignored only for duplicate comparison,
   - **And** the LLM cannot overwrite these values because code merges them after review parsing,
   - **And** this story adds no automatic length/slop failure threshold: raw measurements and unambiguous repeat signals are surfaced; Story 12.1 may later supply calibrated word-budget thresholds.

6. **Warning context survives every delivery path**
   - **Given** a warning exists in checkpoint state,
   - **When** `gate_scenario` interrupts, `run_service` publishes `gate_pending`, or the client reloads scenario artifacts,
   - **Then** the same JSON-safe warning is available through each path,
   - **And** the artifact endpoint is the durable authority rather than SSE alone,
   - **And** other stage gate payloads remain backward-compatible.

7. **The operator sees the warning at the decision point**
   - **Given** scenario artifacts contain `unresolved_pass2`,
   - **When** Run Detail renders the scenario gate,
   - **Then** a Korean warning block labelled `2차 검토 경고` appears above approve/reject controls,
   - **And** it shows the critic summary plus scene/evidence details,
   - **And** it uses icon and text besides color with `role="alert"` or `aria-live="polite"`,
   - **And** existing editing, retry, approval, rejection, sidebar, and focus behavior is preserved.

8. **Retries and edits cannot create stale or misleading context**
   - **Given** the scenario is explicitly retried or fully restarted,
   - **When** outputs are nullified,
   - **Then** old scenario quality context is cleared and replaced by the new result,
   - **And** an inline narration edit does not pretend review reran: existing warning evidence remains visible and is labelled as the generation-time review result.

## Tasks / Subtasks

- [ ] Task 1: Add the typed, checkpoint-safe quality contract (AC: 2, 3, 6, 8)
  - [ ] Define JSON-safe TypedDicts in `src/yt_flow/domain/state.py` for metrics, grounded evidence, and scenario gate context; add `scenario_quality` as `NotRequired` for old checkpoints.
  - [ ] Keep one authoritative state object. Its `warning` is absent/`None` unless the final pass is unresolved.
  - [ ] Update initial-state/test fixtures only where required; do not require the field in legacy checkpoints.
  - [ ] Clear stale quality context when scenario outputs are nullified or fully restarted.

- [ ] Task 2: Compute and validate grounded review evidence (AC: 4)
  - [ ] Pass `entity_sheet` into `review_step` from `_write_and_review` and `_repair_and_review`; preserve `frozen_descriptor` and `scp_text`.
  - [ ] Add an Entity Sheet section and evidence rules to `prompts/scenario/review.md`.
  - [ ] Extend review YAML with `grounded_contradictions[]`: `scene_num`, `narration_quote`, `grounding_source`, `grounding_quote`, `explanation`, `correction`.
  - [ ] Validate entries and normalize new free-text fields via `_normalize_freetext()`.
  - [ ] Require a matching `issues[]` entry and force `overall_pass=false`; do not trust prompt compliance alone.

- [ ] Task 3: Add deterministic rule metrics without an LLM call (AC: 5)
  - [ ] Implement small pure helpers in `scenario_chain.py` using only stdlib and existing `split_sentences()`.
  - [ ] Produce the exact counts/evidence defined in AC5; keep the Korean slop tuple small, explicit, and versioned.
  - [ ] Do not add a package, fuzzy matcher, embedding, or morphological tokenizer.
  - [ ] Merge code metrics after parsing so model output cannot spoof them. Do not invent new automatic thresholds.

- [ ] Task 4: Persist and surface the final pass-2 verdict (AC: 1, 2, 3)
  - [ ] Evaluate final `review`/`critic` after the existing retry block and before `tts_normalize` discards context.
  - [ ] Build `scenario_quality` on successful runs; create `unresolved_pass2` only when `final_pass_index == 2` and final review/critic is negative.
  - [ ] Bound/sanitize summaries; retain evidence but exclude raw prompts/completions.
  - [ ] Return quality alongside `scenes`, `current_stage`, and `error`; preserve stage success and one-retry limit.

- [ ] Task 5: Carry warning through gate, SSE, and artifacts (AC: 6, 8)
  - [ ] Extend only the scenario interrupt value in `pipeline/gates.py`; other gates retain `{stage}` behavior.
  - [ ] Forward JSON-safe interrupt context in `gate_pending`; keep DB `gate_states` unchanged.
  - [ ] Include `scenario_quality` in scenario artifacts, defaulting safely for old checkpoints.
  - [ ] Clear `scenario_quality` in `_nullify("scenario", ...)` and full-restart initialization. No DB migration.

- [ ] Task 6: Render reload-safe guidance in Run Detail (AC: 7, 8)
  - [ ] Extend scenario artifact and progress types in `frontend/src/lib/api.ts` and `frontend/src/hooks/useRunProgress.ts`.
  - [ ] Refresh/merge scenario artifacts on scenario `gate_pending`; artifact fetch remains authoritative after reload.
  - [ ] Render `2차 검토 경고` above controls with concise Korean copy and scannable evidence.
  - [ ] Label it generation-time review evidence; preserve existing editor and gate behavior; do not use a toast/new page.

- [ ] Task 7: Add regression coverage (AC: 1-8)
  - [ ] `test_scenario.py`: pass-1 clean; pass-1 fail/pass-2 clean; pass-2 critic retry; pass-2 review false; `accept_with_notes`; scoped/full/truncation/coverage branches; no third pass and run succeeds.
  - [ ] `test_scenario_chain.py`: entity-sheet wiring; valid/invalid contradiction evidence; forced failure; Korean NFKC/whitespace/punctuation boundaries; n-gram threshold; model metrics cannot overwrite code metrics.
  - [ ] `test_gates.py`: scenario context, other-gate compatibility, unchanged decision validation.
  - [ ] `test_run_service_gate.py`/`test_stage_artifacts.py`: SSE forwarding, absent context safety, refresh persistence, retry clearing.
  - [ ] Frontend tests: unresolved-only alert, evidence, controls, clean/legacy compatibility, reload path.
  - [ ] Run focused suites, full pytest/Ruff, frontend Vitest, and TypeScript/Vite build. No GPU, ComfyUI, or real LLM call.

- [ ] Task 8: Seed the runtime prompt under current DEV MODE (AC: 4)
  - [ ] After tests pass, run `uv run python scripts/migrate_prompts.py --label production --source prompts`.
  - [ ] Do not run/request A/B, golden-set, promotion, `--baseline`, or `YTFLOW_ALLOW_AB_GATE`; suspended until Story 13.4.

## Dev Notes

### Why This Story Exists

- Pass 1 is not ignored: it correctly triggers the bounded retry.
- Pass-2 `review`/`critic` values returned by scoped repair and all full-rewrite fallbacks are never inspected before TTS normalization and the human gate.
- Story 6.5's one-retry limit is intentional. Visibility and human judgment are the fix, not a third attempt.

### Required State / Payload Shape

Use one compact typed object; exact names may follow repository conventions:

```yaml
scenario_quality:
  final_pass_index: 2
  retry_scope: scene
  review_overall_pass: false
  critic_verdict: retry
  critic_feedback: "..."
  rule_metrics:
    aggregate: {character_count: 0, sentence_count: 0, duplicate_sentence_count: 0, repeated_4gram_count: 0}
    scenes: []
    slop_phrase_hits: []
  grounded_contradictions: []
  review_issues: []
  warning:
    code: unresolved_pass2
    message: "검토 후에도 품질 문제가 남아 있습니다. 확인 후 승인 또는 반려하세요."
```

- `warning` is absent/`null` for clean results. Do not duplicate the object in another state field.
- All values must be JSON/checkpoint safe; exclude exceptions, prompt objects, functions, and raw completions.
- DB `runs.gate_states` remains a flat stage-to-string map.

### Deterministic Metric Semantics

- `character_count`: non-whitespace Unicode code points after NFKC.
- `sentence_count`: existing `split_sentences()` result count; no second tokenizer.
- `duplicate_sentence_count`: occurrences beyond first after NFKC, whitespace collapse, trim, case-fold, and terminal `.?!` stripping.
- `repeated_4gram_count`: distinct normalized whitespace-token 4-grams occurring at least three times; report phrase/count evidence.
- `slop_phrase_hits`: exact normalized matches from a small Korean tuple with scene/phrase evidence; diagnostic, not a semantic classifier.
- No blocking length/slop thresholds without calibration. Story 12.1 owns future per-beat budgets.

### Current Files and Required Preservation

- `src/yt_flow/pipeline/nodes/scenario.py`: preserve retry/fallback classifications, tracing, TTS order, and pure state return.
- `src/yt_flow/pipeline/nodes/scenario_chain.py`: reuse `_normalize_freetext`, `_call_stage_with_retry`, and `split_sentences`; do not add a service for small validators.
- `src/yt_flow/domain/state.py`: stdlib-only TypedDict substrate; no upper-layer imports.
- `src/yt_flow/pipeline/gates.py`: fixed five gates and existing approved/rejected resume values.
- `src/yt_flow/services/run_service.py`: sole graph stream/SSE owner; artifacts read checkpoint state; DB stays projection-only.
- `frontend/src/components/ArtifactPanel.tsx`: preserve scenario editing and controls; no toast.
- `prompts/scenario/review.md`: add entity/evidence rules without weakening current checks.

### Architecture Compliance

- Preserve `api -> services -> (pipeline | db) -> domain`.
- `PipelineState` is authoritative; no DB migration.
- Stage nodes remain pure; `run_service` remains the only SSE owner.
- Keep five stages/gates; do not add a review stage or gate.
- Replace state fields wholesale; do not mutate incoming state.
- AD-10 means non-fatal degradation must still be visible.

### Library / Framework Requirements

- Repository pins supersede stale architecture rows: Python `>=3.12,<3.13`, LangGraph `1.2.7`, checkpoint-sqlite `3.1.0`, FastAPI `0.138.2`, SQLModel `0.0.39`, Langfuse `4.12.0`, React `18.3.1`, Tailwind `4.3.2`, Vite `8.1.1`, TypeScript `^5.6.0`.
- No dependency upgrade/new package.
- LangGraph supports JSON-serializable interrupt values and restarts the gate node from its beginning on resume; pre-interrupt code must stay deterministic/idempotent.
- Langfuse default prompt fetch resolves `production`; current DEV MODE seeds the repo prompt directly there.

### UX / Accessibility Guardrails

- Korean operator copy; English monospace stage token unchanged.
- Warning above controls; icon + text + semantic alert, not color alone or toast.
- Preserve two-column layout, sidebar, prose readability, and focus-visible controls.
- SSE is acceleration, not storage; refresh/missed events recover from artifacts.

### Previous Story Intelligence

- No Story 12.1/12.2 implementation artifact exists; both remain backlog. Do not assume their schemas or Gemini wiring.
- Story 6.5 established scoped repair/one retry; Stories 6.9/6.10 added narrow truncation/coverage full-rewrite fallbacks. Preserve them.

### Git Intelligence Summary

- `7141707`: Epic 12.2 planning only; no code precedent.
- `13a47ed`: Epic 12/13 planning and this defect; no code.
- `cc82403`: DEV MODE prompt flow, repo directly to `production`, no quality gates.
- No recent `12-*` story implementation artifact or code commit exists.

### Latest Technical Information

- Official LangGraph guidance supports structured JSON approval context under `interrupt()` and requires the same thread id with `Command(resume=...)`; keep string decisions unchanged.
- The gate node restarts after resume, so derive payload from persisted state and avoid side effects before interrupt.
- Langfuse prompt versions are immutable and labels point to versions; default production fetch matches current `get_prompt()` usage.
- Do not upgrade pinned libraries.

### Project Structure Notes

Expected production updates:

- `src/yt_flow/domain/state.py`
- `src/yt_flow/pipeline/nodes/scenario.py`
- `src/yt_flow/pipeline/nodes/scenario_chain.py`
- `src/yt_flow/pipeline/gates.py`
- `src/yt_flow/services/run_service.py`
- `prompts/scenario/review.md`
- `frontend/src/lib/api.ts`
- `frontend/src/hooks/useRunProgress.ts`
- `frontend/src/pages/RunDetail.tsx`
- `frontend/src/components/ArtifactPanel.tsx`

Expected test updates:

- `tests/pipeline/nodes/test_scenario.py`
- `tests/pipeline/nodes/test_scenario_chain.py`
- `tests/pipeline/test_gates.py`
- `tests/services/test_run_service_gate.py`
- `tests/api/test_stage_artifacts.py`
- `frontend/src/components/ArtifactPanel.test.tsx`
- `frontend/src/pages/RunDetail.test.tsx`

No new DB migration, service module, pipeline stage, or page.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-123-pass-2-판정-활용--접지grounded-모순-검사`]
- [Source: `_bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#11-Pipeline-structures-that-beat-single-shot-generation`]
- [Source: `_bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#15-Practical-generation-control`]
- [Source: `_bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#Phase-3--Script-quality-upgrades-structure-stays-four-changes`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Invariants--Rules`]
- [Source: `docs/superpowers/specs/2026-07-03-scenario-multistage-design.md#Retry-loop`]
- [Source: `docs/PROMPT_POLICY.md#Prompt-Policy`]
- [Source: `src/yt_flow/pipeline/nodes/scenario.py#scenario_node`]
- [Source: `src/yt_flow/pipeline/nodes/scenario_chain.py#review_step`]
- [Source: `src/yt_flow/domain/state.py#PipelineState`]
- [Source: `src/yt_flow/pipeline/gates.py#_gate`]
- [Source: `src/yt_flow/services/run_service.py#get_stage_artifacts`]
- [Source: `frontend/src/components/ArtifactPanel.tsx#ArtifactPanel`]
- [Source: [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)]
- [Source: [Langfuse Prompt Management](https://langfuse.com/docs/prompt-management/get-started)]

## Dev Agent Record

### Agent Model Used

OpenAI GPT-5 Codex

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Story synthesized from Epic 12.3's draft because no formal user story/BDD criteria existed.
- Validation reconciled pass-2 behavior, state/gate/SSE/artifact delivery, grounded evidence, deterministic metrics, UI durability, prompt policy, and stale-context clearing.

### File List

- `_bmad-output/implementation-artifacts/12-3-pass2-verdict-grounded-gate.md`
