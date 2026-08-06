---
baseline_commit: f95427dbd7c98dc2d22368ef99e5d27a51fbbec1
---

# Story 12.3: Pass-2 Verdict Grounded Gate

Status: done

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

- [x] Task 1: Add the typed, checkpoint-safe quality contract (AC: 2, 3, 6, 8)
  - [x] Define JSON-safe TypedDicts in `src/yt_flow/domain/state.py` for metrics, grounded evidence, and scenario gate context; add `scenario_quality` as `NotRequired` for old checkpoints.
  - [x] Keep one authoritative state object. Its `warning` is absent/`None` unless the final pass is unresolved.
  - [x] Update initial-state/test fixtures only where required; do not require the field in legacy checkpoints.
  - [x] Clear stale quality context when scenario outputs are nullified or fully restarted.

- [x] Task 2: Compute and validate grounded review evidence (AC: 4)
  - [x] Pass `entity_sheet` into `review_step` from `_write_and_review` and `_repair_and_review`; preserve `frozen_descriptor` and `scp_text`.
  - [x] Add an Entity Sheet section and evidence rules to `prompts/scenario/review.md`.
  - [x] Extend review YAML with `grounded_contradictions[]`: `scene_num`, `narration_quote`, `grounding_source`, `grounding_quote`, `explanation`, `correction`.
  - [x] Validate entries and normalize new free-text fields via `_normalize_freetext()`.
  - [x] Require a matching `issues[]` entry and force `overall_pass=false`; do not trust prompt compliance alone.

- [x] Task 3: Add deterministic rule metrics without an LLM call (AC: 5)
  - [x] Implement small pure helpers in `scenario_chain.py` using only stdlib and existing `split_sentences()`.
  - [x] Produce the exact counts/evidence defined in AC5; keep the Korean slop tuple small, explicit, and versioned.
  - [x] Do not add a package, fuzzy matcher, embedding, or morphological tokenizer.
  - [x] Merge code metrics after parsing so model output cannot spoof them. Do not invent new automatic thresholds.

- [x] Task 4: Persist and surface the final pass-2 verdict (AC: 1, 2, 3)
  - [x] Evaluate final `review`/`critic` after the existing retry block and before `tts_normalize` discards context.
  - [x] Build `scenario_quality` on successful runs; create `unresolved_pass2` only when `final_pass_index == 2` and final review/critic is negative.
  - [x] Bound/sanitize summaries; retain evidence but exclude raw prompts/completions.
  - [x] Return quality alongside `scenes`, `current_stage`, and `error`; preserve stage success and one-retry limit.

- [x] Task 5: Carry warning through gate, SSE, and artifacts (AC: 6, 8)
  - [x] Extend only the scenario interrupt value in `pipeline/gates.py`; other gates retain `{stage}` behavior.
  - [x] Forward JSON-safe interrupt context in `gate_pending`; keep DB `gate_states` unchanged.
  - [x] Include `scenario_quality` in scenario artifacts, defaulting safely for old checkpoints.
  - [x] Clear `scenario_quality` in `_nullify("scenario", ...)` and full-restart initialization. No DB migration.

- [x] Task 6: Render reload-safe guidance in Run Detail (AC: 7, 8)
  - [x] Extend scenario artifact and progress types in `frontend/src/lib/api.ts` and `frontend/src/hooks/useRunProgress.ts`.
  - [x] Refresh/merge scenario artifacts on scenario `gate_pending`; artifact fetch remains authoritative after reload.
  - [x] Render `2차 검토 경고` above controls with concise Korean copy and scannable evidence.
  - [x] Label it generation-time review evidence; preserve existing editor and gate behavior; do not use a toast/new page.

- [x] Task 7: Add regression coverage (AC: 1-8)
  - [x] `test_scenario.py`: pass-1 clean; pass-1 fail/pass-2 clean; pass-2 critic retry; pass-2 review false; `accept_with_notes`; scoped/full/truncation/coverage branches; no third pass and run succeeds.
  - [x] `test_scenario_chain.py`: entity-sheet wiring; valid/invalid contradiction evidence; forced failure; Korean NFKC/whitespace/punctuation boundaries; n-gram threshold; model metrics cannot overwrite code metrics.
  - [x] `test_gates.py`: scenario context, other-gate compatibility, unchanged decision validation.
  - [x] `test_run_service_gate.py`/`test_stage_artifacts.py`: SSE forwarding, absent context safety, refresh persistence, retry clearing.
  - [x] Frontend tests: unresolved-only alert, evidence, controls, clean/legacy compatibility, reload path.
  - [x] Run focused suites, full pytest/Ruff, frontend Vitest, and TypeScript/Vite build. No GPU, ComfyUI, or real LLM call.

- [x] Task 8: Seed the runtime prompt under current DEV MODE (AC: 4)
  - [x] After tests pass, run `uv run python scripts/migrate_prompts.py --label production --source prompts`.
  - [x] Do not run/request A/B, golden-set, promotion, `--baseline`, or `YTFLOW_ALLOW_AB_GATE`; suspended until Story 13.4.

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

OpenAI GPT-5 Codex (story context) · Claude Opus 5 (implementation)

### Debug Log References

- `Dev Notes → Previous Story Intelligence` was **stale**: it claims "No Story 12.1/12.2 implementation
  artifact exists; both remain backlog." Both are `done` and committed (`f95427d`, `2f28e2c`).
  Implementation therefore targeted the real current code: `review_step`/`critic_step` are already
  batched **per scene** (Story 6.6) and `review`/`critic` already run on **Gemini** (Story 12.2's
  `_GEMINI_STAGES`). Two consequences the story text did not anticipate:
  1. `entity_sheet` is rendered into every per-scene review call, not one whole-script call.
  2. `grounded_contradictions` needed adding to `_aggregate_review`'s `_stamped` merge, otherwise
     every per-scene contradiction would have reported `scene_num: 1` (the isolated-call habit).
- Three of my own first-draft tests asserted the wrong branch: `_stub_chain`'s `review_retry` /
  `critic_retry` arguments key off the **writing** call count, so they only fire on the
  *full-rewrite* path and never on the *scoped-repair* path. Added a `_sequenced()` per-call seam
  instead of changing the shared stub.
- `frontend/node_modules` was absent in this worktree; ran `npm ci` before Vitest/tsc.
- `RunDetail` tests initially matched two nodes for `/승인/` — `StatusBadge` renders "승인 대기" for
  `awaiting_approval`. Switched to the exact name `"승인"`.
- `tests/domain/test_state_imports.py::test_type_hint_shapes` is the intended tripwire for a
  `PipelineState` shape change; updated it and registered every new quality TypedDict there, since
  the object is a checkpoint AND interrupt serialization surface.

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Story synthesized from Epic 12.3's draft because no formal user story/BDD criteria existed.
- Validation reconciled pass-2 behavior, state/gate/SSE/artifact delivery, grounded evidence, deterministic metrics, UI durability, prompt policy, and stale-context clearing.
- **The defect is closed at its source.** `scenario_node` now reads the FINAL `review`/`critic` at the
  one point where both are still in scope — after the retry block, before `tts_normalize_step`
  rebinds `writing` — and returns `scenario_quality` alongside `scenes`. Previously pass-2's
  recomputed verdicts overwrote pass-1's locals and were never read by anyone.
- **Non-fatal by construction.** An unresolved pass 2 sets `warning.code = "unresolved_pass2"` and
  logs a WARNING; the stage still returns `error: None` and reaches the human gate. No third
  review/critic/repair/rewrite pass was added — Story 6.5's one-retry limit is untouched
  (`test_unresolved_pass2_critic_retry_warns_but_run_succeeds` pins review==2 / critic==2 /
  writing==1 / repair==1).
- **`warning` only when the retry itself failed.** Gate condition is
  `final_pass_index == 2 and (verdict == "retry" or not overall_pass)`. A pass-1 failure the repair
  fixed is clean, and `accept_with_notes` neither triggers a retry nor a warning by itself (AC3).
  All four retry_scope branches are covered: `scene`, `full-fallback`,
  `scene-repair-truncated-fallback`, `scene-repair-coverage-fallback`.
- **Grounded contradictions are evidence-or-nothing, enforced in code.** `_validate_grounded_contradictions`
  requires five non-empty quoted fields (raises `ValueError`, which buys the chain's standard single
  prompt-level correction); `_apply_grounded_contradictions` then *re-derives* the consequences rather
  than trusting the prompt — it forces `overall_pass = False` and **rebuilds** the mirrored
  `issues[]` entries from scratch (dropping any model-authored `grounded_contradiction` issue first),
  so the mapping is exactly 1:1 and the contradiction always reaches `scenario._retry_scope`.
- **Metrics are unspoofable by construction, not by instruction.** `compute_rule_metrics` runs in
  `scenario._build_quality` *after* review parsing, over the writing payload the judge actually saw
  (not the TTS-normalized rewrite). Aggregates are computed over **pooled per-scene** sentence
  keys/tokens, so `aggregate.sentence_count` is exactly the sum of the per-scene counts (no
  concatenation boundary artifacts) while duplicates and repeated 4-grams still catch phrases
  recycled *between* scenes. `scene_num` is positional everywhere. No threshold was added.
- **Bounded, whitelisted payload.** `_clip` (600 chars per evidence field, 2000 for critic feedback)
  and `_bounded` (20 entries, whitelisted keys only). A dropped entry is **logged** — a silently
  truncated list would read as "that was everything".
- **Only the scenario interrupt grew.** `gates._gate` adds `scenario_quality` for `stage ==
  "scenario"` and only when truthy, so a pre-12.3 checkpoint's payload stays byte-identical
  (`{"stage": "scenario"}`) and the other four gates are provably unchanged. No side effect before
  `interrupt()`, since LangGraph re-runs the node from the top on resume. DB `gate_states` remains a
  flat stage→string map — no migration.
- **Artifacts are the durable authority.** `get_stage_artifacts("scenario")` always returns
  `scenario_quality` (`null` for legacy/cleared). SSE forwarding is acceleration only, and
  `RunDetail` re-reads artifacts on a scenario `gate_pending` via an explicit `artifactRefresh`
  counter rather than relying on the `run` object's identity changing.
- **Stale context cannot survive.** `_nullify("scenario", …)` and `_initial_state` set
  `scenario_quality: None`; downstream `_nullify` calls deliberately do NOT (an image retry does not
  invalidate the scenario review). Proven by a fixture whose scenario node reports a warning only on
  its *first* execution — the clean re-run omits the key, so `None` can only come from an explicit
  clear. An inline narration edit touches `scenes` only, so the warning stays visible and is
  labelled "대본 생성 시점의 자동 검토 결과입니다. 이후 직접 수정한 내용은 재검토되지 않았습니다."
- **Verification:** 2238 passed / 1 skipped / 0 failed (full pytest), ruff clean, frontend 114 passed
  (17 files), `tsc -b` + `vite build` clean. `+62` backend tests, `+12` frontend tests. No new dependency
  (`pyproject.toml`/`uv.lock`/`package.json` unchanged); metrics use `unicodedata` +
  `collections.Counter` from the stdlib.
- **Prompt seeding (Task 8, DEV MODE):** `uv run python scripts/migrate_prompts.py --label production
  --source prompts` → `created: scenario/review`, every other prompt `skipped`. **No collateral
  promotion this time** (contrast Story 12.1, which incidentally promoted `scenario/cast_decision`).
  The worktree has no `.env`, so the main tree's was copied in for the single command and deleted
  immediately after. No A/B, golden set, `--baseline`, or `YTFLOW_ALLOW_AB_GATE` — suspended per
  CLAUDE.md DEV MODE until Story 13.4.
- **Not done (out of scope, flagged for Jay):** no live LLM run exercised the new
  `grounded_contradictions` path — the offline tests drive real repo prompts through the real parser,
  but whether Gemini actually *emits* well-evidenced contradictions at a useful rate is a live
  question. Worth one `--profile smoke --scp-id SCP-049` run from the main tree before trusting the
  contradiction signal (as opposed to the metrics/verdict signal, which needs no model cooperation).

### File List

- `_bmad-output/implementation-artifacts/12-3-pass2-verdict-grounded-gate.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `prompts/scenario/review.md`
- `src/yt_flow/domain/state.py`
- `src/yt_flow/pipeline/gates.py`
- `src/yt_flow/pipeline/nodes/scenario.py`
- `src/yt_flow/pipeline/nodes/scenario_chain.py`
- `src/yt_flow/services/run_service.py`
- `frontend/src/components/ArtifactPanel.tsx`
- `frontend/src/hooks/useRunProgress.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/pages/RunDetail.tsx`
- `tests/api/test_e2e_stub_run.py`
- `tests/api/test_sse.py`
- `tests/api/test_stage_artifacts.py`
- `tests/domain/test_state_imports.py`
- `tests/pipeline/nodes/test_scenario.py`
- `tests/pipeline/nodes/test_scenario_chain.py`
- `tests/pipeline/test_gates.py`
- `tests/services/test_run_service_gate.py`
- `frontend/src/components/ArtifactPanel.test.tsx`
- `frontend/src/pages/RunDetail.test.tsx`
- `_bmad-output/implementation-artifacts/tests/test-summary.md`

## Senior Developer Review (AI)

**Reviewer:** Jay · **Date:** 2026-08-07 · **Outcome:** Approve (6 findings fixed in place)

All eight ACs verified against the code, not the checkboxes. Task 8's prompt seeding was
re-verified as unnecessary to repeat: the fixes below changed no runtime prompt text.

| # | Sev | Finding | Fix |
|---|-----|---------|-----|
| 1 | HIGH | **An optional diagnostic field could kill a run.** After the one prompt-level correction, an unevidenced `grounded_contradictions` entry propagated `ValueError` out of `review_step` → `scenario_node` → `error` → whole run failed. This is a *new* fatal surface, added on top of a working pipeline, on the one path with no live validation (the dev's own "Not done" note) — and multiplied by N concurrent per-scene calls. AD-10 says degradation must be visible, not fatal. | `_validate_grounded_contradictions(..., strict=)`: strict on the first parse (unchanged — still buys the correction and still satisfies AC4's "rejects"), then **drops the claim with a WARNING** instead of failing. Required contract fields (`overall_pass`) still fail hard. Parser is now built per scene (`_make_parse()`) so the attempt counter can't leak between concurrently-reviewed scenes. |
| 2 | HIGH | **`_apply_grounded_contradictions` never wrote the validated list back**, so `_aggregate_review` merged the *raw* model list. Latent before finding 1 (strict validation made raw ≡ validated); with the lenient retry it would have shipped exactly the unevidenced claims the validator had just rejected. | Validated entries are written back to `data["grounded_contradictions"]`. |
| 3 | MEDIUM | **Aggregate 4-grams straddled scene boundaries.** `all_tokens` was one flat list, so a window spanning scene *k*'s last tokens and scene *k+1*'s first tokens counted as a repeated phrase. Reproduced: six 3-token scenes produced 3 "repeated phrases" occurring nowhere in the script — phantom evidence at the human gate. The docstring claimed the aggregate avoided exactly this. | `_rule_counts` takes per-scene token **runs**; windows never cross a scene. Cross-scene recycling of a whole 4-gram is still caught. |
| 4 | MEDIUM | **The evidence bar didn't check `grounding_source`.** Any string passed, so the model could cite "my knowledge of SCP-096" as the conflicting source — the single thing the prompt's grounding section forbids — and the claim would force `overall_pass=false` and drive a repair. | Validated against `GROUNDING_SOURCES` (the three artifacts actually supplied). No prompt change: it already documented this enum. |
| 5 | LOW | **`_clip` collapsed the newlines out of `critic_feedback`**, while `_aggregate_critic` joins per-scene feedback with newlines and the UI renders the field `whitespace-pre-wrap` — an eight-scene critique arrived as one paragraph. (`test_sse.py`'s own fixture assumes a newline is possible there.) | `_clip_lines`: same 2000-char bound, line structure preserved. |
| 6 | LOW | UI summary read `상투구 {slop_phrase_hits.length}` — the number of (scene, phrase) entries, not occurrences, under-reporting a phrase used 3× in one scene as "1". Plus: File List omitted `test_e2e_stub_run.py` / `test_sse.py` / `test-summary.md`; `state.py`'s `aggregate` comment said "not summed per scene" when two of its four counts are exactly that. | Sum `count`; File List and comment corrected. |

**Verified, not just claimed:** 2242 backend passed / 1 skipped before the review (story said
2238), 117 frontend (story said 114) — both drifted up, not down; the numbers below are
re-measured post-fix: **2251 passed / 1 skipped / 0 failed**, ruff clean, **117 frontend passed**, `tsc -b` + `vite build` clean (+9 backend tests for the fixes). `_stub_chain` fixtures, gate/SSE/artifact compatibility, clearing, and
the two `test_e2e_stub_run.py` cases that drive the real `scenario_node` were all re-read
rather than trusted — they are genuine, and the e2e pair is the reason findings 1–4 are the
only substantive gaps in a large change.

**Left for Jay (unchanged from the dev's note):** no live LLM run has exercised the
`grounded_contradictions` path. Finding 1 makes that far less risky — the worst case is now
a dropped claim and a log line rather than a failed run — but whether Gemini emits
well-evidenced contradictions at a useful rate is still an open live question. One
`--profile smoke --scp-id SCP-049` run from the main tree would answer it.

### Change Log

| Date | Change | Why |
|------|--------|-----|
| 2026-08-06 | `domain/state.py`: added the `ScenarioQuality` contract (`RuleCounts`, `SceneRuleCounts`, `RepeatedPhrase`, `SlopPhraseHit`, `RuleMetrics`, `GroundedContradiction`, `ReviewIssue`, `ScenarioWarning`) and `PipelineState.scenario_quality` as `NotRequired`. | The verdict has to survive a checkpoint, an `interrupt()` value and a JSON response; stdlib TypedDicts keep it plain-serializable and pre-12.3 checkpoints loadable. |
| 2026-08-06 | `scenario_chain.py`: added `compute_rule_metrics` + `_metric_text` / `_sentence_key` / `_rule_counts`, `KOREAN_SLOP_PHRASES`, `SLOP_VOCABULARY_VERSION`. | Repetition and slop are exactly what an LLM judge is worst at scoring and code is best at. NFKC + `Counter` + the existing `split_sentences()`, no new dependency. |
| 2026-08-06 | `scenario_chain.py`: `review_step` gained keyword-only `entity_sheet`; added `_validate_grounded_contradictions` / `_apply_grounded_contradictions`; `_aggregate_review` merges + stamps `grounded_contradictions`. | Review could not catch narration contradicting the entity roster because it never saw it. Keyword-only keeps ~15 existing positional call sites valid; the stamp is required because per-scene calls all self-report `scene_num: 1`. |
| 2026-08-06 | `prompts/scenario/review.md`: Entity Sheet grounding section, checklist §9 evidence rules, `grounded_contradictions[]` YAML schema, `grounded_contradiction` added to the issue-type enum. Seeded to `production`. | The parser now rejects unevidenced claims, so the prompt has to state the evidence bar and the "omit rather than guess" instruction. |
| 2026-08-06 | `scenario.py`: added `_build_quality` / `_bounded` / `_clip`, wired `entity_sheet` into both `review_step` call sites, returned `scenario_quality`. | Closes the defect: pass-2's verdicts were computed, overwritten and never read. Bounding/whitelisting keeps an unbounded model string out of the checkpoint. |
| 2026-08-06 | `gates.py`: the scenario interrupt value carries `scenario_quality` when present. | AD-10 — a degraded script must not reach the human gate looking identical to a clean one. Scoped to one gate so the other four stay byte-compatible. |
| 2026-08-06 | `run_service.py`: forward the context in `gate_pending`; `scenario_quality` in scenario artifacts; cleared in `_nullify("scenario", …)` and `_initial_state`. | SSE is acceleration, the checkpoint is the authority. Clearing is scenario-only: a downstream retry does not invalidate the scenario review. |
| 2026-08-06 | Frontend: `ScenarioQuality` types, `ProgressEventData.scenario_quality`, `ScenarioQualityWarning` block above the gate controls, explicit `artifactRefresh` on scenario `gate_pending`. | The operator has to see the evidence at the decision point — hence in-flow (not a toast/new page), `role="alert"` + `aria-live`, and icon **and** text rather than colour alone. |
| 2026-08-06 | Tests: +62 backend, +12 frontend across metrics, contradiction evidence, all four retry_scope branches, gate/SSE/artifact compatibility, clearing, and reload. | The regressions worth guarding are "the warning appears when it shouldn't", "it doesn't when it should", and "a stale one mislabels the next draft". |
| 2026-08-07 | Review fixes: `_validate_grounded_contradictions(strict=)` + per-scene `_make_parse()`; validated list written back in `_apply_grounded_contradictions`; `_rule_counts` takes per-scene token runs; `grounding_source` enum enforced; `_clip_lines` for `critic_feedback`; UI sums slop occurrences. +9 backend tests. | Findings 1–6 in the Senior Developer Review above. The theme: a diagnostic added on top of a working pipeline must degrade, not fail — and evidence shown at a human gate has to actually exist in the script. |
