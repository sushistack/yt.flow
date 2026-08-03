---
created: 2026-08-03
baseline_commit: 71417071ba42a28a3f7e6ef2720f706176041501
story_key: 12-2-model-split-gemini
story_id: "12.2"
epic: 12
depends_on: []
---

# Story 12.2: Model Split — DeepSeek Planning / Gemini Korean Prose + Judge

Status: ready-for-dev

## Story

As Jay,
I want the scenario pipeline to keep DeepSeek for planning-oriented work while routing final Korean prose and judging to Gemini,
so that narration quality is no longer capped by DeepSeek's Korean surface-writing weakness while the existing planning, schema, cache, and evaluation contracts remain intact.

## Context and Scope Decision

The scenario chain is already a mature multi-stage pipeline with bounded YAML repair, scene-scoped rewrite, prompt versioning, and per-stage tracing. This story changes provider ownership inside that chain; it does **not** redesign the chain or add a top-level pipeline stage.

The binding 2026-08-03 product decision is a two-provider split:

| Provider | Owned calls after this story | Reason |
| --- | --- | --- |
| DeepSeek | `research`, `structure`, `cast_decision`, `visual_breakdown`, `tts_normalize` | Preserve planning/schema behavior, 6.3 context-cache assets, visual metadata behavior, and the Qwen-TTS-specific pronunciation normalization contract. |
| Gemini | `writing`, `writing_scene_repair`, runtime `review`, runtime `critic_agent`, Epic 4 axis judge, Epic 4 pairwise judge | Gemini owns every prose-producing/revising call and every call that judges that prose. Scene-scoped repair must not silently revert repaired narration to DeepSeek. |

`tts_normalize` stays on DeepSeek deliberately. It is a mechanical pronunciation pass over already-final prose, not the authoring pass; keeping it stable minimizes risk to Story 5.4/5.18's narration/display dual-track and sentence-count invariants. The Gemini-authored text remains canonical as `display_narration`, while DeepSeek's narrowly normalized form becomes spoken `narration`. This means DeepSeek technically performs the last spoken-text transformation, but it must not re-author style or meaning. If a later listening test proves this boundary limits spoken quality, move it in a separate, evidence-backed change.

The accepted tradeoff must remain explicit: Gemini writes and judges the same prose, so self-preference bias is **not eliminated**; it moves from DeepSeek to Gemini. If evaluation results become suspect, the zero-new-provider fallback is to keep Gemini writing but route runtime review/critic and Epic 4 evaluation back to DeepSeek. Revisit this at Story 13.4 before the promotion gate is unfrozen.

## Acceptance Criteria

1. **Explicit stage routing**
   - **Given** any normal, scene-repair, or full-rewrite scenario path, **when** an LLM substage runs, **then** it uses the provider in the ownership table above.
   - Both the initial `writing_step` and `writing_scene_repair_step` use Gemini. Both first-pass and second-pass `review_step`/`critic_step` use Gemini. The same provider handles a stage's bounded syntax-repair retry.
   - No code path silently falls back from Gemini to DeepSeek or vice versa after a provider error.

2. **Config-pinned Gemini integration**
   - Add `YTFLOW_` settings for a shared Gemini API key/base URL plus independently pinned prose model, judge model, prose output-token limit, and judge output-token limit. Keep all existing DeepSeek settings and defaults, including the dormant DeepSeek judge setting needed by the documented fallback.
   - Use exact stable model IDs, not `latest`, preview, or experimental aliases. At story creation time the default is `gemini-3.6-flash`; operators can change the pinned model through config without a code change.
   - A missing Gemini key fails fast with a readable provider-specific error before the first Gemini-owned scenario or evaluation call. The key is never logged, traced, committed, or sent to the client UI.

3. **Reuse the existing OpenAI-compatible transport contract**
   - Use the existing async `httpx` pattern against Gemini's documented OpenAI-compatible `/chat/completions` REST endpoint. Do not add `openai`, `google-genai`, or another SDK unless live contract verification proves the documented REST compatibility insufficient.
   - The Gemini adapter returns the existing `(content, usage, finish_reason)` tuple consumed by `scenario_chain._call_stage`; do not leak provider SDK/HTTP response objects into `scenario_chain.py`.
   - Preserve the current prompt text, Langfuse fetch/label behavior, YAML parsers, truncation detection, bounded repair, domain data shapes, and exception propagation. Provider errors are visible failures, not empty-success responses.

4. **DeepSeek assets remain intact**
   - DeepSeek-owned stages continue using `deepseek_model`, `deepseek_max_tokens`, and the existing cache-friendly prompt layout.
   - Existing DeepSeek usage fields (`prompt_tokens`, `completion_tokens`, `prompt_cache_hit_tokens`, `prompt_cache_miss_tokens`) remain correct. Gemini usage is normalized to common prompt/completion token fields; absent DeepSeek cache metrics remain zero/absent rather than fabricated.

5. **Scenario output contracts are preserved**
   - Gemini writing and scene repair produce the same YAML structures currently parsed by `writing_step` and `writing_scene_repair_step`, including scene count/identity requirements.
   - Existing Korean voice rules remain enforced: documentary `-습니다` register, varied endings, no banmal sentence endings, and role-based names for non-lead people.
   - `tts_normalize` still preserves one output scene per input scene, one sentence per source sentence, Gemini-authored `display_narration` with original notation, and minimally normalized `narration` for TTS. It may adjust pronunciation, spacing/breathing, numbers, and abbreviations, but must not change style, facts, sequence, or meaning. Shot sentence indices and all downstream image/TTS/subtitle/video behavior remain valid.

6. **Runtime review/critic behavior is preserved while moving to Gemini**
   - Review output still exposes `overall_pass` and issue records; critic output still exposes `verdict`, feedback, and scene notes in their existing schemas.
   - The first negative verdict still triggers exactly one scoped/full repair under current rules. This story does not implement Story 12.3's pass-2 surfacing or change bounded-retry policy.

7. **Epic 4 evaluation moves wholly to Gemini**
   - Axis sampling and pairwise comparisons use the configured Gemini judge model/key/endpoint.
   - Preserve `_artifact_text`'s current input contract unless a separately justified regression demands otherwise: Gemini evaluates the delivered spoken `narration`, which includes the bounded DeepSeek TTS-normalization pass, rather than silently switching evaluation to display text.
   - Preserve the existing three axes, three samples per axis, 1–5 parsing, minimum two valid samples, quality floor, A→B/B→A position-bias mitigation, third-call tiebreak, rule-based fallback, 30-second timeout, and bounded retry behavior.
   - `evaluate_ab` no longer requires a DeepSeek key solely to judge; it requires the Gemini key. Database and Langfuse result shapes stay backward-compatible.

8. **Observability identifies the split**
   - Scenario and evaluation traces identify provider and configured model for each LLM-owned operation, in addition to latency, finish reason, usage, pass index, and retry scope already captured.
   - Tracing remains non-fatal per AD-10. A tracing outage cannot change provider routing or pipeline success.

9. **Offline tooling and test profiles follow production routing**
   - `scripts/eval_prompts.py` uses Gemini for writing/review/critic and judge paths while retaining DeepSeek for planning/visual/normalization paths. Stage-isolated `writing` runs must not call DeepSeek.
   - If the Story 6.13 local stage-call cache is generalized for Gemini, its key includes provider, exact model, rendered prompt, and max-token setting so entries can never collide across providers. Both wrappers are restored in `finally` paths after a run.
   - The offline E2E stub profile patches both provider seams, remains network-free, and supplies non-secret dummy settings.

10. **Verification and regressions**
    - Unit tests prove every stage-to-provider mapping across normal, scoped-repair, and full-rewrite paths; assert Gemini URL/auth/model/payload/response mapping; cover missing key, timeout, HTTP error, malformed response, usage normalization, and finish reason.
    - Evaluation tests prove Gemini ownership without weakening all current sampling, retry, pairwise, floor, persistence, or tracing assertions.
    - Run targeted scenario/evaluation/config/eval-script tests, then `uv run pytest -q` and `uv run ruff check .`.
    - Perform a bounded live smoke test with one fixed golden SCP: Gemini-owned calls return parseable outputs, the completed scenario survives `tts_normalize`, and no real provider call uses the wrong endpoint. Because Story 6.12 intentionally freezes the candidate-vs-production promotion gate, do not bypass `YTFLOW_ALLOW_AB_GATE` or AI-session guards; record this smoke as diagnostic evidence, not promotion authority.

## Tasks / Subtasks

- [ ] **Task 1 — Verify and codify the provider boundary (AC: 1, 5, 6)**
  - [ ] Read the complete current `scenario.py` orchestration before editing. Mark every caller passed into `research_step`, `structure_step`, `writing_step`, `writing_scene_repair_step`, `cast_decision_step`, `visual_breakdown_step`, `review_step`, `critic_step`, and `tts_normalize_step`.
  - [ ] Add focused routing tests first, including initial pass, accepted no-retry path, scene-scoped repair, and full rewrite. Assert which fake receives each rendered stage marker.
  - [ ] Keep routing in the orchestration layer; do not teach individual parser functions to select providers.

- [ ] **Task 2 — Add Gemini configuration and transport seam (AC: 2, 3, 4, 8)**
  - [ ] Add config-pinned `gemini_api_key`, `gemini_base_url`, `gemini_writing_model`, `gemini_judge_model`, `gemini_writing_max_tokens`, and `gemini_judge_max_tokens` using the project's existing empty-key/test-constructibility convention. Suggested initial budgets are 16,384 for writing/repair and 8,192 for runtime/evaluation judging; validate them against current prompt/output sizes.
  - [ ] Add `_call_gemini` beside `_call_deepseek` using `httpx.AsyncClient`, Bearer auth, the OpenAI-compatible chat payload, bounded timeout, and the existing tuple return contract.
  - [ ] Normalize Gemini usage and finish reason without changing `scenario_chain._call_stage`'s callable interface. Add provider/model trace metadata without exposing credentials or full secret-bearing headers.
  - [ ] Fail fast for missing keys at the correct entry points; do not demand a Gemini key for flows that never reach Gemini.

- [ ] **Task 3 — Route scenario prose and runtime judges (AC: 1, 5, 6)**
  - [ ] Route `writing_step` and `writing_scene_repair_step` to `_call_gemini` in every branch.
  - [ ] Route both passes of `review_step` and `critic_step` to `_call_gemini`.
  - [ ] Leave research/structure/cast/visual/tts-normalize on `_call_deepseek` and preserve DeepSeek cache metadata.
  - [ ] Preserve same-provider syntax repair and truncation behavior for each stage.

- [ ] **Task 4 — Move Epic 4 judge and pairwise comparison (AC: 7, 8)**
  - [ ] Point `_post_chat`, `_judge_sample`, and `_pairwise_once` at Gemini config without changing their public/internal result contracts.
  - [ ] Preserve response JSON mode, parse isolation, timeout/retry, concurrent sampling, quality floor, position-swap, persistence, and Langfuse behavior.
  - [ ] Update stale DeepSeek-specific module comments, errors, and test names so operational failures identify the actual provider.

- [ ] **Task 5 — Update offline eval and test infrastructure (AC: 9)**
  - [ ] Update `scripts/eval_prompts.py` stage isolation, full-run wrapper/caching, artifact capture, and restoration logic for two provider seams.
  - [ ] Extend deterministic fakes/cassettes and `stub_profile` to patch Gemini-owned stage markers separately. Keep all ordinary tests offline.
  - [ ] Update `scripts/run_e2e_stub_server.py` dummy settings and provider patches so the stub server never reaches Gemini or DeepSeek.

- [ ] **Task 6 — Verify provider contracts and end-to-end invariants (AC: 3–10)**
  - [ ] Run targeted tests for config, scenario orchestration/chain parsing, evaluation, eval script, and E2E stub behavior.
  - [ ] Run the full suite and Ruff.
  - [ ] With an authorized Gemini key, run one bounded golden-SCP scenario diagnostic and archive provider/model routing, parse success, scene/sentence counts, and Korean output evidence. Do not run or unfreeze the promotion gate.

## Dev Notes

### Non-Negotiable Guardrails

- **No third provider and no new SDK by default.** The rejected draft used Claude for writing and Gemini for judging. The current decision uses one new external provider, Gemini. Existing `httpx` plus Google's OpenAI-compatible REST endpoint is sufficient and matches this repository's established provider pattern.
- **No silent fallback.** A Gemini outage must be visible. Falling back to DeepSeek would make a run appear compliant with the model split when it is not and would invalidate quality attribution.
- **Do not move `tts_normalize` in this story.** It is coupled to Qwen pronunciation and the dual-track display contract. Writing quality is determined before this pass.
- **Do not change prompt content or labels.** This is provider wiring. `docs/PROMPT_POLICY.md` remains authoritative; repo prompt content is not rewritten or promoted here.
- **Do not implement adjacent Epic 12 work.** Retention schema (12.1), pass-2 verdict surfacing/grounding (12.3), and archetype diversity (12.4) remain separate.
- **Do not claim bias elimination.** Gemini writer + Gemini judge retains self-preference bias. Record provider/model in evidence so the 13.4 reassessment is possible.

### Current Code State and Required Changes

- `src/yt_flow/config.py` — UPDATE. Today it has DeepSeek generation/judge settings only. Add a distinct Gemini block; preserve all existing defaults and environment naming conventions.
- `.env.example` — UPDATE. Document every new `YTFLOW_GEMINI_*` variable with non-secret placeholders. Never edit or print the real `.env`.
- `src/yt_flow/pipeline/nodes/scenario.py` — UPDATE. Today one `_call_deepseek` is injected into all scenario substages. `_write_and_review`, `_repair_and_review`, and the full-rewrite branch contain separate call sites; changing only the first `writing_step` is incomplete. Add the Gemini seam and explicit routing while preserving graph-node purity (`state` in, changed fields out).
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — likely UPDATE only for provider-neutral names/types/comments and trace metadata, not stage selection. Its `_call_stage`/`_call_stage_with_retry` injection seam, YAML parsing, truncation checks, and output builders already solve the hard problems; reuse them.
- `src/yt_flow/services/eval_service.py` — UPDATE. Today `_post_chat` always targets `deepseek_base_url`, uses `deepseek_api_key`, and callers pass `deepseek_judge_model`; `evaluate_ab` fails fast on the DeepSeek key. Change provider wiring while preserving all evaluation math and persistence.
- `scripts/eval_prompts.py` — UPDATE. It imports and wraps `_call_deepseek`, directly injects it into isolated stages, and keys its local cache with the DeepSeek model/max tokens. It must reflect production routing and avoid cross-provider cache collisions.
- `scripts/run_e2e_stub_server.py` — UPDATE. It currently patches only `_call_deepseek` and creates settings around the DeepSeek guard. Add the Gemini seam/key so offline E2E remains hermetic.
- `tests/conftest.py`, `tests/stubs/fakes.py`, relevant cassette docs/data — UPDATE. The shared stub currently patches one provider seam and maps all stage markers through a DeepSeek-named fake. Split ownership without duplicating parser fixtures unnecessarily.
- `tests/pipeline/nodes/test_scenario.py`, `tests/pipeline/nodes/test_scenario_chain.py`, `tests/services/test_eval_service.py`, `tests/test_config.py`, `tests/test_eval_prompts.py` — UPDATE/add coverage described in AC10.
- `pyproject.toml` / `uv.lock` — no change expected. Add an SDK only if Task 2 documents a verified blocker in REST compatibility; if added, pin it exactly and update the lockfile.

### Preserve These Existing Behaviors

- Scenario remains one top-level LangGraph stage followed by the existing human gate; no graph topology, checkpoint schema, API, or UI change.
- Prompt Hub runtime fetch and `production`/`candidate` label behavior remain unchanged.
- Scene-scoped repair modifies only rejected scenes; full rewrite and bounded retry rules remain unchanged.
- `build_scenes` continues preserving positional scene/shot mapping, camera/cast repair, display narration, titles/kickers, and downstream data shapes.
- Existing evaluation result JSON and Langfuse score names remain compatible with stored runs and the A/B UI.
- External LLM failures remain explicit stage/evaluation failures; Langfuse failures alone remain non-fatal.

### Architecture Compliance

- AD-1: keep dependency direction intact. Provider HTTP belongs in the existing node/service seams; no `domain` or API layer may import provider clients.
- AD-2/AD-4: no new database source of truth and no direct state mutation outside node return values.
- AD-6: evaluation persistence continues through the existing service and `runs.ab_result` contract.
- AD-10: no silent degradation. Provider errors are observable; tracing errors are non-fatal; no partial output should masquerade as success.
- Model identifiers and credentials are config-pinned (`YTFLOW_`), never prompt constants or hardcoded call-site values.

### Testing Requirements

- Prefer callable-identity/stage-marker assertions over call-count-only tests; call counts vary with scene count and repair branch.
- Add a regression that makes DeepSeek and Gemini fakes return distinguishable writing text, proving the final narration comes from Gemini while `tts_normalize` still receives and preserves it according to contract.
- Exercise malformed YAML from a Gemini-owned stage and prove the repair retry stays on Gemini.
- Exercise a Gemini HTTP timeout/429/5xx and prove it does not fall back to DeepSeek. Keep the current judge-specific retry rules; do not invent broad pipeline retries.
- Assert no API key appears in caplog, exception text, trace metadata, or serialized evaluation output.
- Maintain ≥80% package coverage and the full-suite/Ruff gates already configured in `pyproject.toml`.

### Latest Technical Information (verified 2026-08-03)

- Google's official OpenAI-compatibility endpoint is `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`; it accepts Bearer API-key auth and the chat-completions request/response shape already used by this repository.
- Pin `gemini-3.6-flash`, the current stable model, rather than `gemini-flash-latest` because `latest` aliases can be hot-swapped. Preview models have shorter deprecation notice and tighter quotas.
- Gemini rate limits are project-scoped across RPM, input TPM, and RPD; 429 means `RESOURCE_EXHAUSTED`. Preserve bounded behavior and surface the failure rather than adding unbounded retries. Reject empty/blocked responses and abnormal finish reasons explicitly; normalize a token-limit finish to the chain's existing truncation signal so bounded retry remains effective.
- Google is transitioning away from unrestricted standard API keys; use an authorization/restricted key from environment/secret storage and never expose it client-side. Current official guidance says standard keys will be rejected beginning September 2026, so live verification must use a compliant key.

### Previous Story and Git Intelligence

No Story 12.1 implementation file exists yet, so there is no earlier Epic 12 developer record to inherit. Relevant proven patterns are:

- Story 5.13: provider swaps must assert the outbound URL/model, preserve message/output/error contracts, and include a live smoke because mocks can validate the wrong provider.
- Story 5.18: `display_narration` and TTS `narration` are separate tracks; sentence identity and count are downstream invariants.
- Story 5.22: prompt-only Korean style rules improved some cases but did not reliably meet the ending-variety median threshold, motivating a model-level intervention. Preserve its register/designation rules.
- Stories 6.3/6.13: DeepSeek cache metrics and offline stage caching are real assets. Provider/model/max-token identity must participate in cache keys.
- Stories 6.4/6.7/6.8: YAML syntax repair and judge-sample repair are bounded and failure-isolated. Keep those semantics.
- Story 6.12 / commit `cc82403`: promotion gating is intentionally off during development. Do not bypass it for this story.
- Commit `7141707` is the authoritative spec revision replacing the rejected three-provider design with Gemini for prose + judge and recording the accepted bias.

### Project Structure Notes

Expected production changes are confined to existing Python nodes/services/config plus offline tooling and tests. No new DB migration, API route, React component, prompt file, graph node, or GPU workflow is expected. Preserve the user's unrelated untracked `.serena/` directory.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Epic 12: 대본·나레이션 품질 — 리텐션 구조 + 모델 분리 + 접지 게이트`]
- [Source: `_bmad-output/planning-artifacts/epics.md#Story 12.2: 모델 분리 — DeepSeek 기획 / Gemini 한국어 문장 + judge`]
- [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#Functional Requirements`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Decision Index`]
- [Source: `_bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md#Area 1 — Script & Narration Quality`]
- [Source: `_bmad-output/implementation-artifacts/5-13-character-vision-provider-swap.md#Dev Notes`]
- [Source: `_bmad-output/implementation-artifacts/5-22-narration-style-designation-rules.md#Dev Agent Record`]
- [Google Gemini API — OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai)
- [Google Gemini API — Models and version naming](https://ai.google.dev/gemini-api/docs/models)
- [Google Gemini API — Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Google Gemini API — API key security](https://ai.google.dev/gemini-api/docs/api-key)

## Dev Agent Record

### Agent Model Used

GPT-5

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.

### File List
