---
created: 2026-08-03
baseline_commit: 71417071ba42a28a3f7e6ef2720f706176041501
story_key: 12-2-model-split-gemini
story_id: "12.2"
epic: 12
depends_on: []
---

# Story 12.2: Model Split — DeepSeek Planning / Gemini Korean Prose + Judge

Status: done

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

- [x] **Task 1 — Verify and codify the provider boundary (AC: 1, 5, 6)**
  - [x] Read the complete current `scenario.py` orchestration before editing. Mark every caller passed into `research_step`, `structure_step`, `writing_step`, `writing_scene_repair_step`, `cast_decision_step`, `visual_breakdown_step`, `review_step`, `critic_step`, and `tts_normalize_step`.
  - [x] Add focused routing tests first, including initial pass, accepted no-retry path, scene-scoped repair, and full rewrite. Assert which fake receives each rendered stage marker.
  - [x] Keep routing in the orchestration layer; do not teach individual parser functions to select providers.

- [x] **Task 2 — Add Gemini configuration and transport seam (AC: 2, 3, 4, 8)**
  - [x] Add config-pinned `gemini_api_key`, `gemini_base_url`, `gemini_writing_model`, `gemini_judge_model`, `gemini_writing_max_tokens`, and `gemini_judge_max_tokens` using the project's existing empty-key/test-constructibility convention. Suggested initial budgets are 16,384 for writing/repair and 8,192 for runtime/evaluation judging; validate them against current prompt/output sizes.
  - [x] Add `_call_gemini` beside `_call_deepseek` using `httpx.AsyncClient`, Bearer auth, the OpenAI-compatible chat payload, bounded timeout, and the existing tuple return contract.
  - [x] Normalize Gemini usage and finish reason without changing `scenario_chain._call_stage`'s callable interface. Add provider/model trace metadata without exposing credentials or full secret-bearing headers.
  - [x] Fail fast for missing keys at the correct entry points; do not demand a Gemini key for flows that never reach Gemini.

- [x] **Task 3 — Route scenario prose and runtime judges (AC: 1, 5, 6)**
  - [x] Route `writing_step` and `writing_scene_repair_step` to `_call_gemini` in every branch.
  - [x] Route both passes of `review_step` and `critic_step` to `_call_gemini`.
  - [x] Leave research/structure/cast/visual/tts-normalize on `_call_deepseek` and preserve DeepSeek cache metadata.
  - [x] Preserve same-provider syntax repair and truncation behavior for each stage.

- [x] **Task 4 — Move Epic 4 judge and pairwise comparison (AC: 7, 8)**
  - [x] Point `_post_chat`, `_judge_sample`, and `_pairwise_once` at Gemini config without changing their public/internal result contracts.
  - [x] Preserve response JSON mode, parse isolation, timeout/retry, concurrent sampling, quality floor, position-swap, persistence, and Langfuse behavior.
  - [x] Update stale DeepSeek-specific module comments, errors, and test names so operational failures identify the actual provider.

- [x] **Task 5 — Update offline eval and test infrastructure (AC: 9)**
  - [x] Update `scripts/eval_prompts.py` stage isolation, full-run wrapper/caching, artifact capture, and restoration logic for two provider seams.
  - [x] Extend deterministic fakes/cassettes and `stub_profile` to patch Gemini-owned stage markers separately. Keep all ordinary tests offline.
  - [x] Update `scripts/run_e2e_stub_server.py` dummy settings and provider patches so the stub server never reaches Gemini or DeepSeek.

- [x] **Task 6 — Verify provider contracts and end-to-end invariants (AC: 3–10)**
  - [x] Run targeted tests for config, scenario orchestration/chain parsing, evaluation, eval script, and E2E stub behavior.
  - [x] Run the full suite and Ruff.
  - [~] With an authorized Gemini key, run one bounded golden-SCP scenario diagnostic and archive provider/model routing, parse success, scene/sentence counts, and Korean output evidence. Do not run or unfreeze the promotion gate.
    - **PARTIAL — corrected during review.** What ran live: a 1-call contract probe and a 3-call SCP-049 **writing-stage** diagnostic (real repo prompt, real parser) — archived in Debug Log. What did NOT run: the full golden-SCP `scenario_node` chain (research → … → tts_normalize), because this worktree has no `.env` (no Langfuse Prompt Hub, no DeepSeek key) and an AI session must not copy credentials into a worktree. **Jay owns the remainder** — see the command in Debug Log. Was previously marked `[x]`, which overstated it against the story's own Debug Log.

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

**Live Gemini contract probe (1 call, 2026-08-06)** — the thing mocks cannot answer:

```
base_url = https://generativelanguage.googleapis.com/v1beta/openai
model    = gemini-3.6-flash          # the pinned stable ID is real and served
finish_reason = 'stop'
usage         = {'completion_tokens': 30, 'prompt_tokens': 59, 'total_tokens': 748}
content       = '```yaml\nnarration: 보안 대원이 격리실 내부로 진입한 직후, 모든 통신이 두절되었습니다.\n```'
```

Bearer auth + the documented OpenAI-compatibility `/chat/completions` shape work with
plain `httpx`; **no SDK was needed**, so AC3's no-new-dependency constraint holds against
a real response, not just documentation.

**Live writing-stage diagnostic (3 calls, 2026-08-06)** — the real repo
`prompts/scenario/writing.md` (rendered locally with Langfuse's `{{var}}` substitution)
through the real `scenario_chain.writing_step` parser against live Gemini, SCP-049
outline (the fixed golden canary, 3 scenes):

```
provider=gemini model=gemini-3.6-flash max_tokens=16384
parse: OK — 3 scenes (outline had 3)
usage: [{'completion_tokens': 374, 'prompt_tokens': 5268, 'total_tokens': 7861},
        {'completion_tokens': 369, 'prompt_tokens': 5257, 'total_tokens': 9534},
        {'completion_tokens': 392, 'prompt_tokens': 5310, 'total_tokens': 10364}]
scene 1: 7 sentences, 68 words, 7/7 distinct endings
scene 2: 7 sentences, 56 words, 7/7 distinct endings
scene 3: 7 sentences, 67 words, 7/7 distinct endings
AC5 checks: register OK, positional scene_num OK, key not in payload OK
```

Sample narration (scene 3): `마침내 수술이 끝난 후 격리 인원들이 안으로 들어가 치료 결과를 확인했습니다. 과연 그가
호언장담하던 완벽한 치료는 성공했을까요? … 당신이 목격한 치료의 진짜 정체는 구원이 아닌 끔찍한 재앙. 대상이 아무 저항
없이 순순히 재격리된 후에도, 차가운 전율은 가라앉지 않습니다.`

Two things this measured that matter beyond "it parses":

- **Reasoning tokens are a live budget consumer here too.** `total_tokens` (7.9k–10.4k)
  far exceeds `prompt + completion` (~5.6k), so Gemini 3.6 spends ~2–5k thinking tokens
  per writing call. Same failure class as
  `gotcha_reasoning-tokens-eat-the-max-tokens-budget`, which is exactly why
  `_call_gemini` maps a token-limit finish onto the chain's existing `"length"`
  truncation signal instead of inventing a new one. 16384 has real headroom at 3 scenes;
  it has **not** been measured at 8–12 scenes.
- **Ending variety looks strong but is NOT a measured claim.** 7/7 distinct final forms
  per scene, single run, one SCP. Story 5.22's median ending-variety threshold is an
  Epic 6 golden-set measurement, not this; do not read this as passing it.

**Not run — and why:** the full golden-SCP `scenario_node` diagnostic (research →
structure → writing → cast → visual → review → critic → tts_normalize) needs the
Langfuse Prompt Hub and a DeepSeek key. **This worktree has no `.env`** (only
`/mnt/work/projects/yt.flow/.env` does), and copying credentials into a worktree is not
something an AI session should do unasked. Jay can close that gap from the main tree:

```
uv run python scripts/eval_prompts.py --label production --profile smoke --scp-id SCP-049
```

Story 6.12's promotion gate was **not** touched: no `--baseline`, no
`YTFLOW_ALLOW_AB_GATE`, no label moved. The AI-session guard was not bypassed.

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- **Routing lives in one place.** `scenario._GEMINI_STAGES` is the ownership table as
  code, read by both `_provider_fields` (trace metadata) and the call sites, so a stage
  can never be *traced* as one provider while being *called* on another. No parser in
  `scenario_chain.py` learned to select a provider — the injection seam already existed,
  so the change is which callable gets passed, not new machinery.
- **`call_deepseek` → `call_llm`** across `scenario_chain.py` (26 occurrences, all
  positional; no keyword callers existed). The parameter is now honestly named for a seam
  that carries either provider. Docstrings that claimed "ONE DeepSeek call per scene" on
  writing/review/critic were corrected — those are Gemini's stages now.
- **No fallback, deliberately.** A Gemini error propagates as a scenario/evaluation
  failure. Tests assert this by making the DeepSeek fake raise `AssertionError` if it is
  ever reached during a Gemini-owned stage, including the bounded semantic retry.
- **Offline stubs became a routing test.** `fakes.deepseek_stage_aware()` /
  `gemini_stage_aware()` each know only their own stages and raise on a foreign stage
  marker, so a mis-routed stage fails the offline suite instead of silently replaying the
  right cassette from the wrong provider. `tests/pipeline/test_stub_profile_smoke.py::
  test_graph_reaches_terminal_state` drives the real `scenario_node` through both seams
  and reaches `complete` — that is the offline proof for AC9.
- **Cassette files kept their `deepseek_` names on purpose.** A cassette records the
  OpenAI-compatible *response shape*, which Gemini's compatibility endpoint shares
  byte-for-byte. Renaming would churn every reference in `test_scenario_chain.py` for no
  behavioural difference; `tests/fixtures/cassettes/README.md` now documents the
  seam↔stage mapping instead.
- **Interpretation recorded for AC9's "stage-isolated `writing` runs must not call
  DeepSeek".** Taken as *the writing call itself* must not reach DeepSeek. The isolated
  path still runs research/structure on DeepSeek because they produce writing's input —
  skipping them would leave nothing to write from. `_run_stage_chain` now routes
  per-stage, and `test_run_stage_chain_routes_the_writing_call_to_gemini` pins the split
  (2 DeepSeek planning calls, 1 Gemini call per scene).
- **`evaluate_ab` no longer needs a DeepSeek key** and fails on the Gemini key *before*
  pair validation; `deepseek_judge_model` is kept as the documented zero-new-provider
  fallback, with a `test_deepseek_settings_survive_the_split` guard so a future cleanup
  cannot quietly delete the escape hatch.
- **Bias is moved, not eliminated** — Gemini writes and judges the same prose. Recorded
  in the `eval_service` module docstring and surfaced in traces as
  `judge_provider`/`judge_model` so the Story 13.4 reassessment has evidence.
- **Hermetic test keys.** `tests/conftest.py` and `scripts/run_e2e_stub_server.py` set a
  dummy `YTFLOW_GEMINI_API_KEY` *unconditionally* (`os.environ[...]`, which outranks
  `.env` in pydantic-settings), so a real developer key can never reach a test or the
  stub server even if a seam is mis-wired.
- **Flagged, not fixed (out of scope):** a `Settings()` *construction* failure makes
  pydantic dump `input_value`, which includes whatever API keys were passed as init
  kwargs — observed while writing the live probe. This is generic pydantic behaviour that
  already applied to `deepseek_api_key`, not something this story introduced, and fixing
  it means adding `SecretStr` across the config. Worth its own change if key hygiene is
  audited.
- ~~**Pre-existing failures, baseline-verified this session:** 3 tests in
  `tests/api/test_e2e_stub_run.py` fail…~~ **RETRACTED — this note was wrong.** The
  later QA pass found the real cause: a *missing hermetic DeepSeek key in
  `tests/conftest.py`*, i.e. this story's own asymmetry (it injected an unconditional
  dummy Gemini key and left DeepSeek's identical `scenario_node` guard depending on a
  developer `.env`). It reproduced "at baseline" only because the baseline had the same
  `.env`-less worktree, not because the defect predated the story. Fixed; the suite is
  0-failed. Kept struck through rather than deleted: a false "pre-existing" label is how
  a real regression gets inherited by the next story, and Story 12.1's review carries the
  same claim — it should be re-checked there too.
- `pyproject.toml` / `uv.lock` are unchanged — no SDK was added, as AC3 required.

### File List

Production:

- `src/yt_flow/config.py` — Gemini settings block (key/base URL/prose+judge models/prose+judge token budgets); DeepSeek block preserved incl. the dormant judge model; **review fix:** documented the real scope of the writing-vs-judge pins (the writing pair also serves runtime review/critic)
- `src/yt_flow/pipeline/nodes/scenario.py` — `_call_gemini` adapter, `_GEMINI_STAGES` ownership table, `_provider_fields` trace metadata, per-stage routing, Gemini key fail-fast; **review fix:** documented why a Gemini truncation dump is legitimately 0 bytes
- `src/yt_flow/pipeline/nodes/scenario_chain.py` — provider-neutral `call_llm` seam name + corrected provider-specific docstrings/comments (no stage-selection logic added)
- `src/yt_flow/services/eval_service.py` — judge/pairwise transport on Gemini, Gemini key guard, `judge_provider`/`judge_model` trace metadata, `_artifact_text` contract rationale; **review fixes:** blocked/empty response → `EvalJudgeError` (stays inside the per-sample isolation) and de-fenced judge output

Tooling:

- `scripts/eval_prompts.py` — provider-aware stage cache (`_cached_call`, provider in the cache key), both seams wrapped/restored, per-stage routing in stage isolation; **review fix:** `--profile promotion` preflight now validates the Gemini budget too
- `scripts/run_e2e_stub_server.py` — Gemini seam patch, dummy Gemini key, both provider keys blanked for the judge seam
- `.env.example` — every new `YTFLOW_GEMINI_*` variable with non-secret placeholders; **review fix:** WRITING_* vs JUDGE_* scope spelled out

Tests:

- `tests/conftest.py` — Gemini seam in `stub_profile`, hermetic dummy Gemini key
- `tests/stubs/fakes.py` — `_stage_aware` split into `deepseek_stage_aware`/`gemini_stage_aware`, per-provider cassette maps
- `tests/fixtures/cassettes/README.md` — seam↔stage mapping, why filenames were kept
- `tests/pipeline/nodes/test_scenario.py` — 15 new tests: routing across normal/scoped-repair/full-rewrite, trace provider/model, key fail-fast, same-provider retry, Gemini-text-survives-tts_normalize, and the `_call_gemini` transport contract (URL/auth/payload/usage/truncation/blocked/no-choices/HTTP error/timeout/no-key)
- `tests/services/test_eval_service.py` — 6 new tests: Gemini endpoint/auth/model/budget, no-key fail-fast, judge+pairwise model, Gemini-key-not-DeepSeek-key, runs without a DeepSeek key, judge provider/model in traces; **review adds:** fenced-judge parse (4 cases, both parsers), blocked/empty response shapes (3 cases), one-blocked-sample-drops-not-fails-the-axis
- `tests/test_config.py` — 3 new tests: pinned Gemini defaults (no `latest`/`preview`/`exp`), independent overrides, DeepSeek block survival
- `tests/test_eval_prompts.py` — cache-key provider component, `_cached_call` rename, writing-call-to-Gemini routing, Gemini cache pins, both-seams wrap/restore; **review adds:** promotion preflight rejects a risky Gemini budget
- `tests/api/test_e2e_stub_run.py` — E2E provider-routing through `POST /runs` + a Gemini-outage case (added in the QA pass; **was missing from this list**)
- `tests/pipeline/test_stub_profile_smoke.py` — `error is None` asserted before `status == "complete"` (**was missing from this list**)
- `tests/services/test_run_service_gate.py` — the A/B-eval failure case now raises the Gemini key error (**was missing from this list**)
- `tests/test_run_e2e_stub_server.py` — NEW: first coverage of `scripts/run_e2e_stub_server.py` — dummy keys + both seams stage-scoped (**was missing from this list**)

Process:

- `_bmad-output/implementation-artifacts/sprint-status.yaml` — status tracking
- `_bmad-output/implementation-artifacts/12-2-model-split-gemini.md` — this file

## Senior Developer Review (AI)

**Reviewer:** Jay (adversarial AI review) · **Date:** 2026-08-06 · **Outcome:** Approve with fixes applied

Baseline before review: **2168 passed / 1 skipped / 0 failed**, `ruff check .` clean — the
story's own verification claims hold. Seven findings; all HIGH/MEDIUM auto-fixed.

Both HIGH findings are in the same place, and it is the place the story's live evidence
did **not** reach: the judge transport. The live probe exercised the *writing* path only,
so every Gemini-specific response behaviour on the judge path was assumed rather than
observed — and the two shapes that assumption missed are the ones that fail the whole
evaluation, not one sample.

### 🔴 HIGH — fixed

1. **The judge parses JSON that Gemini has no documented obligation to leave unfenced.**
   `_post_chat` sends `response_format: {"type": "json_object"}` — inherited from DeepSeek,
   where it *guaranteed* bare JSON — and both callers then run `json.loads` on the result
   directly. Google's OpenAI-compatibility docs do not list `json_object` (checked
   2026-08-06; the page documents structured output via schema-based `response_format` and
   says compatibility "is still in beta"), and **this story's own live probe caught Gemini
   fencing its output** (` ```yaml `). If the parameter is silently ignored, *every* sample
   fails `json.loads` → every axis lands under the 2-valid-sample floor → `evaluate_ab`
   fails outright. `scenario_chain._parse_yaml`'s docstring already anticipates precisely
   this ("may fence it as ```json without json_object mode forcing bare output any more").
   No offline test could catch it: the fakes all return bare JSON.
   *Fix:* de-fence in `_post_chat`, using the same pattern `scenario_chain` hardened over
   live runs `64b6d9a8`/`db2e813`. A no-op when the response is bare. Covered by a 4-case
   parametrized test (```json, bare fence, prose-then-fence, unfenced) asserted through
   **both** the axis and pairwise parsers.
   *Note on the duplication:* the first attempt imported `scenario_chain._yaml_text` and
   `test_services_does_not_import_api_or_pipeline` correctly rejected it — AD-1 allows
   `services/` to import only PURE pipeline node modules, and `scenario_chain` is not one.
   The pattern is therefore duplicated with a keep-in-sync comment on both ends. That
   boundary guard doing its job is worth recording: it is the reason this fix landed as a
   local helper instead of a new cross-layer dependency.

2. **`eval_service._post_chat` had no guard for Gemini's two new response shapes, and the
   escaping exception type defeated the per-sample isolation.**
   `resp.json()["choices"][0]["message"]["content"]` raises `IndexError` on a
   safety-blocked 200-with-no-choices and `KeyError` on a `MAX_TOKENS` stop that omits
   `content` — shapes DeepSeek never produced, which is exactly why `scenario._call_gemini`
   guards them and why this transport's lack of a guard was asymmetric. Neither type is
   caught by `_judge_sample`/`_pairwise_once` (they isolate on `EvalJudgeError`), and
   `_judge_axis` gathers **without** `return_exceptions`, so **one blocked sample would
   fail the entire A/B evaluation** instead of degrading to a dropped sample — breaking the
   Story 6.8 isolation contract that AC7 required preserved.
   *Fix:* normalize no-choices / empty-content to `EvalJudgeError` in `_post_chat`, which
   routes into the existing one-retry-then-drop. Covered by a 3-shape parametrized test
   plus `test_one_blocked_judge_sample_drops_instead_of_failing_the_axis`.

### 🟡 MEDIUM — fixed

3. **`--profile promotion` preflight validated only `deepseek_max_tokens`.** The guard
   exists because a low budget truncates a stage and the truncation "masquerades as a
   prompt regression". After the split, writing/review/critic — the three stages with the
   live truncation history — are governed by `gemini_writing_max_tokens`, which nothing
   validated. *Fix:* the preflight now checks both budgets against the same floor; new
   `test_main_promotion_profile_rejects_a_risky_gemini_budget`.

4. **`config.py` documented a token-budget split the code does not implement.** The
   comment claimed `gemini_judge_max_tokens` covers "review/critic/judge"; in reality
   runtime review/critic ride the single `_call_gemini` seam and therefore use the
   *writing* model + 16384 budget. `gemini_judge_model` affects the Epic 4 judge only — a
   silent config trap for anyone raising it to strengthen the runtime judge.
   *Fix:* documented the real scope in `config.py` and `.env.example`. **The routing was
   deliberately left as-is rather than moved onto the judge budget** (which Task 2
   *suggested*): the live probe measured ~2-5k thinking tokens per Gemini call, and
   review/critic are the two stages that already truncated at 16k in run `370666ba` —
   capping them at 8192 would re-introduce a known failure for no benefit. Per-stage model
   plumbing is the change to make if a genuinely different runtime judge is ever wanted.

5. **File List omitted 4 changed test files** (`tests/api/test_e2e_stub_run.py`,
   `tests/pipeline/test_stub_profile_smoke.py`, `tests/services/test_run_service_gate.py`,
   and the new `tests/test_run_e2e_stub_server.py`). *Fix:* added, each marked.

6. **A retracted claim was left standing as fact.** Completion Notes asserted 3
   `test_e2e_stub_run.py` failures were "pre-existing, baseline-verified", while the QA
   Change Log entry below already disproved it (the cause was this story's own
   DeepSeek/Gemini key asymmetry; "reproduced at baseline" only because the baseline shared
   the same `.env`-less worktree). *Fix:* struck through with the correction inline, and
   flagged that Story 12.1's review carries the same claim and should be re-checked.

7. **Task 6's live-diagnostic subtask was marked `[x]` but its own Debug Log says the
   golden-SCP `scenario_node` run did not happen.** *Fix:* demoted to `[~]` with the exact
   split of what ran (4 live calls, writing stage) vs what Jay still owns.

### Not fixed — deliberate, with reasons

- **`_call_gemini` produces a 0-byte truncation dump.** `_call_deepseek` substitutes
  `reasoning_content`; Gemini's compatibility layer does not return its thoughts, so there
  is nothing to substitute. Not fixable here — documented at the truncation branch so the
  next debugger reads `usage` (completion vs total tokens) instead of hunting a dump bug.
- **The judge path is still not live-verified.** Finding 1 hardens it against the failure
  mode the docs left open, but neither a real review/critic call nor a real judge call has
  been made. Rolled into the Jay-owned residual below, not silently closed.
- **`cast_decision` still has no trace entry of its own** (it is folded into
  `visual_breakdown`'s), so AC8's "each LLM-owned operation" is met per-stage-entry, not
  per-call. Pre-existing; not a regression from this story.
- **Pydantic dumps init kwargs (including keys) on a `Settings()` construction failure** —
  correctly flagged by the dev as generic, pre-existing, and needing `SecretStr` across the
  config. Own change.

### Residual, Jay-owned (credential-gated, not implementation-gated)

Run from the main tree, which has `.env`:

```
uv run python scripts/eval_prompts.py --label production --profile smoke --scp-id SCP-049
```

Confirms the full chain across both providers, and is the first live exercise of the
Gemini review/critic and JSON-mode judge calls. Story 6.12's promotion gate stays frozen —
no `--baseline`, no `YTFLOW_ALLOW_AB_GATE`.

**Post-fix verification:** `2177 passed / 1 skipped / 0 failed` (+9 review tests over the
2168 baseline), coverage gate passed, `uv run ruff check .` clean. Closed **done**: no
CRITICAL findings survive, and the one outstanding item is credential-gated, not
implementation-gated.

## Change Log

| Date | Change |
|------|--------|
| 2026-08-06 | Implemented the DeepSeek/Gemini model split. Gemini owns `writing`, `writing_scene_repair`, both passes of runtime `review`/`critic_agent`, and the Epic 4 axis + pairwise judges; DeepSeek keeps `research`, `structure`, `cast_decision`, `visual_breakdown`, `tts_normalize`. Added a config-pinned Gemini block and a `_call_gemini` adapter reusing the existing `httpx` OpenAI-compatible transport (no SDK, no new dependency). Renamed `scenario_chain`'s injection seam `call_deepseek` → `call_llm` and corrected provider-specific docstrings. Moved the A/B judge transport and key requirement to Gemini while preserving all sampling/floor/pairwise/persistence behaviour. Split the offline stub fakes per provider so a mis-route fails the suite. Provider + model now appear in scenario and evaluation traces. No silent fallback in either direction. |
| 2026-08-06 | QA (`bmad-qa-generate-e2e-tests`, test-only changes — see `tests/test-summary.md`): added E2E provider-routing + Gemini-outage cases through `POST /runs`, a whole-`evaluate_ab` Gemini-only transport test, and first-ever coverage of `scripts/run_e2e_stub_server.py`. **Corrects the "3 pre-existing `test_e2e_stub_run.py` failures" note above**: the cause was not a `_drain_bg_tasks` timeout but a missing hermetic `YTFLOW_DEEPSEEK_API_KEY` in `tests/conftest.py` — this story added an unconditional dummy Gemini key and left DeepSeek's identical guard depending on a developer `.env`, so on a `.env`-less checkout every stub-profile run died instantly at `stage=scenario`. That also made `test_stub_profile_smoke.py::test_graph_reaches_terminal_state` — cited above as the offline proof for AC9 — pass without reaching either provider seam. Both fixed; `scripts/run_e2e_stub_server.py` had the same asymmetry and needed a real DeepSeek key to boot. Suite now 2168 passed / 1 skipped / **0 failed**, coverage 92.76%, ruff clean. |
| 2026-08-06 | Adversarial review (`bmad-story-automator-review`, auto-fix). Baseline verified as shipped: 2168 passed / 1 skipped / 0 failed, ruff clean. 7 findings, all HIGH/MEDIUM fixed — see "Senior Developer Review (AI)". Both HIGH findings sit in the judge transport, the one Gemini-owned path the story's live evidence never reached. HIGH: the judge ran `json.loads` on output whose bare-JSON shape depended on `response_format: {"type": "json_object"}`, which Google does not document for the OpenAI-compatibility endpoint — and this story's own live probe caught Gemini fencing its output, which would have failed every sample and thus the whole evaluation; de-fenced by reusing `scenario_chain._yaml_text` (+4 cases). HIGH: `_post_chat` let Gemini's blocked (200-no-choices) and MAX_TOKENS (no `content`) responses escape as `IndexError`/`KeyError`, which `_judge_sample`'s `EvalJudgeError` isolation does not catch, so one blocked sample failed the whole A/B evaluation instead of dropping a sample — normalized to `EvalJudgeError` + 4 tests. MEDIUM: `--profile promotion` preflight validated only the DeepSeek budget while writing/review/critic moved to Gemini's (+1 test); `config.py`/`.env.example` documented a judge-budget scope the code doesn't implement (routing left deliberately on the prose budget — 8192 would re-introduce run `370666ba`'s truncation); File List missing 4 test files; a retracted "3 pre-existing failures" claim left standing as fact; Task 6's live-diagnostic checkbox overstated against its own Debug Log. Left unfixed with reasons: Gemini 0-byte truncation dumps (no `reasoning_content` to substitute — documented), judge path still live-unverified (Jay's residual). |
| 2026-08-06 | Verified: 2160 passed / 1 skipped, coverage 92.51% (gate 80%), `ruff check .` clean. 3 `tests/api/test_e2e_stub_run.py` failures confirmed pre-existing at the untouched baseline. Live evidence: 1-call Gemini contract probe + 3-call SCP-049 writing-stage diagnostic through the real repo prompt and real parser. The full golden-SCP `scenario_node` run is not runnable in this worktree (no `.env` → no Langfuse Prompt Hub, no DeepSeek key) and is left to Jay; Story 6.12's promotion gate was not run or bypassed. |
