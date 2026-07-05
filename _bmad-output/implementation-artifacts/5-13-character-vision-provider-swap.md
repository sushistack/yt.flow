---
created: 2026-07-05
baseline_commit: 8eb6ea2d52a7096c3538cb0246a9e8a4d4d79618
story_key: 5-13-character-vision-provider-swap
story_id: "5.13"
epic: 5
previous_story: 5-12-character-prompt-content-repair
depends_on:
  - 5-12-character-prompt-content-repair
---

# Story 5.13: 캐릭터 Vision LLM 프로바이더 교체 (DeepSeek → Qwen-VL)

Status: done

## Story

As Jay,
I want `CharacterService.enrich_descriptor_from_references`'s Vision LLM call to actually succeed against a real vision-capable model,
so that automatically-provisioned characters get a real text `visual_descriptor` instead of always failing and falling back to IPAdapter-only image conditioning.

## Context

Story 5.12 wired `enrich_descriptor_from_references` into `run_service._ensure_character_reference` (previously it was fully implemented but never called) and fixed the Langfuse prompt brace bug for `character-generation`/`character-angle-selection`. Its live re-validation (2026-07-05, fresh `SCP-682`) confirmed the wiring fires correctly — but the underlying Vision LLM HTTP call itself failed with a real `400 Bad Request`:

```
{"error":{"message":"Failed to deserialize the JSON body into the target type: messages[0]: unknown variant `image_url`, expected `text` at line 1 column 265","type":"invalid_request_error", ...}}
```

Root cause, confirmed live by calling the account's `/models` endpoint directly: the configured DeepSeek account only has two models available, `deepseek-v4-flash` and `deepseek-v4-pro`, and **both are text-only**. DeepSeek's official hosted API (`api.deepseek.com`) does not offer a vision/multimodal chat endpoint at all — this isn't a wrong model *name*, it's a provider that cannot do this job, at any model choice. `enrich_descriptor_from_references` has therefore never successfully produced a descriptor since Story 1.11 shipped it — every automatically- or manually-provisioned character has always fallen through to `None` (non-fatally, per AD-10, which is exactly why this went unnoticed for 4 stories).

The project already holds a DashScope (Alibaba Cloud Model Studio) account/key for Qwen TTS (`YTFLOW_QWEN_TTS_API_KEY`, see `config.py`'s `qwen_tts_*` settings and `character_image_provider.py`'s `QwenCharacterProvider`, which already calls `https://dashscope-intl.aliyuncs.com` for Qwen image generation). DashScope also exposes an OpenAI-compatible chat-completions endpoint that serves Qwen-VL vision models, confirmed via Alibaba Cloud's own docs: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions`, model `qwen-vl-plus` (or `qwen-vl-max`), request/response shape identical to what `enrich_descriptor_from_references` already builds (`messages: [{role, content: [{type: "text", ...}, {type: "image_url", image_url: {url: ...}}]}]`). This means the fix is a provider/endpoint/model swap, not a prompt or logic change — the existing message-building code (base64 data-URI construction, `image_url` content blocks) should not need to change shape, only the target host/model/auth.

This story does **not** touch: the ComfyUI/IPAdapter character-generation path (`character_image_provider.py`, `comfyui_client.py`, the multi-angle workflow JSON — all validated by Story 5.10), `run_service._ensure_character_reference`'s wiring or non-fatal/rollback contract (done in 5.12, must not regress), or the Langfuse `character-generation`/`character-angle-selection` prompt content (fixed in 5.12). It is scoped entirely to `CharacterService.enrich_descriptor_from_references`'s HTTP call and the config settings it reads.

## Acceptance Criteria

1. **Given** `enrich_descriptor_from_references` is called with valid reference image paths, **when** it builds the Vision LLM request, **then** the request targets a DashScope Qwen-VL model (e.g. `qwen-vl-plus`) via the DashScope OpenAI-compatible endpoint instead of `api.deepseek.com`, using a distinct, config-pinned API key/model (not hardcoded) — mirroring the existing `character_qwen_model`/`character_qwen_api_key` naming convention already used for Qwen image generation in `config.py`.
2. **Given** a real reference image and a valid DashScope vision API key, **when** `enrich_descriptor_from_references` runs live, **then** it returns a non-empty descriptor string (not `None`, not a 400) — this is the live-validation gap Story 5.12 could not close.
3. **Given** the API key is missing, the call fails (HTTP error, timeout, malformed response), or the response is empty, **when** enrichment runs, **then** it returns `None` exactly as today (AC2 of Story 5.12 must keep holding) — no change to the non-fatal contract, no new exception types escape `enrich_descriptor_from_references`.
4. **Given** the existing message-building logic (base64 data-URI image parts, `max 3 images`, text+image content blocks), **when** the provider swap lands, **then** that logic is reused as-is — only the target host, model name, and auth header source change. Do not rewrite the multimodal message construction.
5. **Given** `tests/services/test_character_service_generation.py::TestVisionLLMEnrichment` currently asserts against `service._settings.deepseek_api_key` and DeepSeek-shaped mocks, **when** the provider swap lands, **then** these tests are updated to the new config fields/endpoint and continue to cover: no images → `None`, no API key → `None`, missing image file skipped, successful enrichment returns descriptor, HTTP failure → `None`, existing-descriptor fallback on failure, empty response → `None`.
6. **Given** Story 5.12's non-fatal wiring in `run_service._ensure_character_reference` (separate inner `try/except` around the enrichment call, isolated from the search/generation rollback logic), **when** this story's changes land, **then** that wiring, the rollback contract, and the concurrent-creation dedup guard all continue to behave exactly as before — verified by the existing `tests/services/test_run_service_character_provisioning.py` suite staying green unmodified.
7. **Given** a full regression run, **when** this story is complete, **then** `uv run pytest tests/services/test_character_service.py tests/services/test_character_service_generation.py tests/services/test_run_service_character_provisioning.py tests/pipeline/nodes/test_image.py -q` and the full suite (`uv run pytest -q`) both stay green.

## Tasks / Subtasks

- [x] **Task 1 — Confirm the exact DashScope Qwen-VL contract before coding (AC: 1, 2)**
  - [x] Read Alibaba Cloud Model Studio's OpenAI-compatible vision docs (`https://www.alibabacloud.com/help/en/model-studio/qwen-vl-compatible-with-openai`, `https://www.alibabacloud.com/help/en/model-studio/vision`) to confirm: exact endpoint path (`/compatible-mode/v1/chat/completions` off the `qwen_tts_endpoint`-style base), whether `image_url.url` accepts a `data:image/...;base64,...` URI directly (not just a public HTTPS URL) — the current code builds base64 data URIs and this must keep working without a re-upload step — and the response shape (should be the same OpenAI `choices[0].message.content` shape DeepSeek uses, but confirm before assuming).
  - [x] Do a real, throwaway live call (same style as Story 5.12's `/models` check) against the account's DashScope key with a tiny test image to confirm a 200 response before writing any production code — do not implement against assumed behavior alone.
- [x] **Task 2 — Add config settings for the vision provider (AC: 1)**
  - [x] In `src/yt_flow/config.py`, add settings mirroring the existing `character_qwen_model`/`character_qwen_api_key` pair (near that block): a model setting (default `"qwen-vl-plus"`) and an API key setting (default `""`, same "stays constructible in tests" comment convention as `deepseek_api_key`/`qwen_tts_api_key`). Do **not** add a settings field for the endpoint URL unless Task 1 shows it needs to vary — `QwenCharacterProvider` hardcodes its DashScope endpoint as a class constant rather than a setting; follow that precedent unless there's a concrete reason not to (ponytail: no config for a value that never changes).
  - [x] Decide the exact field names during implementation (suggested: `character_vision_model`, `character_vision_api_key`) — keep them distinct from `character_qwen_api_key`/`qwen_tts_api_key` even though they may point at the same underlying DashScope account in practice, matching this codebase's existing convention of one explicit setting per call site rather than shared/inferred keys.
- [x] **Task 3 — Swap the provider in `enrich_descriptor_from_references` (AC: 1, 3, 4)**
  - [x] In `src/yt_flow/services/character_service.py` (currently lines ~475-502), change the `httpx.AsyncClient.post` call's URL, `model`, and `Authorization` header source from `s.deepseek_base_url`/`s.deepseek_api_key`/`s.deepseek_model` to the new DashScope settings/endpoint. Leave the `image_parts`/`content_parts` construction (lines ~444-473) untouched — same base64 data-URI building, same 3-image cap.
  - [x] Confirm the `except (httpx.HTTPError, ValueError, KeyError, IndexError)` failure branch and existing-descriptor fallback (lines ~495-502) still make sense against the new response shape; adjust the exception tuple only if DashScope's error surface genuinely differs (e.g. a different exception type for malformed JSON) — do not broaden it speculatively.
  - [x] Leave `_load_vision_enrichment_prompt` (the text prompt asking for a descriptor) and the `"character-vision-enrichment"` Langfuse prompt fetch completely untouched — that's prompt content, already correct (Story 5.12 confirmed it has no brace-bug exposure since it has no variables), not part of this story.
- [x] **Task 4 — Update existing unit tests (AC: 5)**
  - [x] Update `tests/services/test_character_service_generation.py::TestVisionLLMEnrichment` (7 tests) to set/assert against the new config field(s) instead of `service._settings.deepseek_api_key`, and update the mocked request/response shape only if Task 1 found the DashScope response envelope differs from DeepSeek's. Keep the same AC1/AC2 coverage intent (success, no-key, no-images, missing-file, HTTP failure, existing-descriptor fallback, empty-response).
  - [x] Do not touch `TestMultiAngleGeneration` or any other class in that file — they're unaffected (different code path, ComfyUI/Qwen image generation, not vision enrichment).
- [x] **Task 5 — Live re-validation (AC: 2, 6, 7)**
  - [x] Run `_ensure_character_reference` (or call `enrich_descriptor_from_references` directly) against a real reference image — reuse Story 5.12's `SCP-682` character (already has reference images downloaded in the dev DB/workspace from that story's live run) or a fresh `scp_id` if a clean provisioning cycle is preferred — and confirm `visual_descriptor` is populated with real, non-empty text this time.
  - [x] Confirm `run_service._ensure_character_reference`'s non-fatal wiring and rollback/dedup contract from Story 5.12 are unaffected: re-run `tests/services/test_run_service_character_provisioning.py` unmodified and confirm all 9 tests still pass (2 of which — `test_enrichment_success_persists_descriptor_before_generation`, `test_enrichment_failure_is_non_fatal_generation_still_proceeds` — mock `enrich_descriptor_from_references` entirely and are provider-agnostic by construction, so they should need zero changes).
  - [x] Run the full regression suite (`uv run pytest -q`) and record pass/fail counts plus the live descriptor text (or a preview of it) in Dev Agent Record.

### Review Findings

- [x] [Review][Patch] `enrich_descriptor_from_references`'s except tuple (`httpx.HTTPError, ValueError, KeyError, IndexError`) didn't catch `AttributeError` — a DashScope safety/moderation block returning `content: null` would raise instead of returning `None`, violating AC2/AC3's "no new exception types escape" contract [src/yt_flow/services/character_service.py:498]
- [x] [Review][Patch] No test asserted the outbound HTTP call actually targets the new DashScope endpoint/model — a regression silently reverting to the old DeepSeek URL/model would have passed every existing test [tests/services/test_character_service_generation.py:106-112]

## Dev Notes

### Critical Implementation Guardrails

- **Reuse, don't rewrite, the multimodal message construction.** `enrich_descriptor_from_references`'s image-loading/base64/content_parts logic (lines ~444-473 as of Story 5.12) is provider-agnostic already — it just builds an OpenAI-shaped `content` array. The only DeepSeek-specific pieces are the URL, the `model` field, and the `Authorization` header's key source. Changing more than that is scope creep.
- **Do not touch `run_service._ensure_character_reference`.** Story 5.12 already wired the call and hardened the non-fatal/rollback contract with a dedicated inner `try/except`. This story only changes what happens *inside* `enrich_descriptor_from_references` when it makes its HTTP call — the caller's contract (call it, persist non-`None` result, swallow any exception) does not change.
- **Do not touch the Langfuse prompt content or `docs/PROMPT_POLICY.md` protocol.** `"character-vision-enrichment"`'s prompt text has no variables and was confirmed unaffected by the Story 5.12 brace bug. Nothing about the *prompt text* needs to change here — only which HTTP endpoint renders and answers it.
- **Do not touch `character_image_provider.py`'s `QwenCharacterProvider`** (the existing Qwen *image generation* path) beyond reading it for the DashScope auth/endpoint pattern — it's a different call (`aigc/image-generation/generation`, async polling) serving a different purpose (t2i character portraits, not vision-to-text description) and is already validated.
- **AD-1** (`services/` imports `domain`/`db`, never `pipeline`/`api`) — `character_service.py` and `config.py` are already `services`-layer/config; no new cross-layer import.
- **AD-10** (non-fatal auxiliary failures) — the provider swap must not weaken this. Any DashScope failure mode (bad key, rate limit, malformed response) must still degrade to `None`, exactly as the current DeepSeek failure path does.

### Current Code State — Files To Read Before Editing

- `src/yt_flow/services/character_service.py:424-502` (`enrich_descriptor_from_references`) — the function this story modifies. Read the full try/except structure before touching it.
- `src/yt_flow/services/character_image_provider.py:283-386` (`QwenCharacterProvider`) — existing precedent for calling DashScope from this codebase: base URL (`https://dashscope-intl.aliyuncs.com`), `Authorization: Bearer <key>` header pattern, config-pinned model name. Different endpoint family (image generation, not chat), but the auth/settings pattern is the one to mirror.
- `src/yt_flow/config.py:20-76` — see the `deepseek_*`, `qwen_tts_*`, and `character_qwen_*` blocks for the exact naming/comment conventions (`# ponytail: api_key defaults to "" so Settings() stays constructible in tests/tooling`) new settings should follow.
- `tests/services/test_character_service_generation.py:59-158` (`TestVisionLLMEnrichment`) — the 7 existing tests that need updating (Task 4).
- `tests/services/test_run_service_character_provisioning.py` — the 2 enrichment-wiring tests added in Story 5.12 (`test_enrichment_success_persists_descriptor_before_generation`, `test_enrichment_failure_is_non_fatal_generation_still_proceeds`) mock `enrich_descriptor_from_references` at the method level, so they should require no changes — read them to confirm this assumption holds before assuming it's a free pass.
- `_bmad-output/implementation-artifacts/5-12-character-prompt-content-repair.md` — Dev Agent Record documents the exact live 400 error and why this was deferred rather than fixed in-place. The follow-up `/models` check that confirmed no vision model exists on the DeepSeek account was run in the same live-investigation session but recorded in `epics.md`'s Story 5.13 backlog note (see below), not in 5.12's own Dev Agent Record — don't go looking for it there.

### Architecture Compliance

- AD-1, AD-10 — see Guardrails above.
- No new pipeline stage, no new LangGraph node, no `db/models.py` schema change, no new dependency (this is an `httpx` call to a different host, same as the existing DeepSeek call — `httpx` is already a project dependency).

### Testing Requirements

- Follow existing patterns in `test_character_service_generation.py`: `@patch("httpx.AsyncClient.post", new_callable=AsyncMock)` mocking, `MagicMock` response with `.json()`/`.raise_for_status()`. No new test infrastructure needed.
- Live verification (Task 5) is required per AC2 since this story's entire purpose is closing a live-validation gap — a green mocked unit test suite alone does not satisfy this story's intent.

## Project Structure Notes

- Expected modified files:
  - `src/yt_flow/config.py` (Task 2 — new vision provider settings)
  - `src/yt_flow/services/character_service.py` (Task 3 — `enrich_descriptor_from_references`'s HTTP target)
  - `tests/services/test_character_service_generation.py` (Task 4 — `TestVisionLLMEnrichment` updates)
- No `db/models.py` schema change expected. No changes expected to `run_service.py`, `character_image_provider.py`, `comfyui_client.py`, `image_search.py`, or any `prompts/character/*.md` file.

### References

- Epic/story source: `_bmad-output/planning-artifacts/epics.md#Story 5.13`
- Direct predecessor: `_bmad-output/implementation-artifacts/5-12-character-prompt-content-repair.md` (Dev Agent Record — the live 400 error this story exists because of); the follow-up `/models` check (proving no vision model on the DeepSeek account) is recorded in `_bmad-output/planning-artifacts/epics.md#Story 5.13`, not in 5.12's own record
- Related: `1-11-character-domain-reference-search.md` (Vision LLM enrichment origin, `enrich_descriptor_from_references`'s original implementation against DeepSeek)
- Architecture: AD-1, AD-10 — `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`
- DashScope OpenAI-compatible vision API (confirmed via web search, 2026-07-05): [Alibaba Cloud Model Studio — Integrate Qwen-VL into OpenAI-Compatible Apps](https://www.alibabacloud.com/help/en/model-studio/qwen-vl-compatible-with-openai), [Alibaba Cloud Model Studio — Image and video understanding](https://www.alibabacloud.com/help/en/model-studio/vision) — endpoint `https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions`, model `qwen-vl-plus`/`qwen-vl-max`, `image_url` content blocks in the standard OpenAI chat-completions message shape. Verify the base64 data-URI acceptance detail live before relying on it (Task 1).

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- Task 1 live throwaway call, 1×1 test image → confirmed 400 is an image-size validation error, not an endpoint/auth/model problem: `{"error":{"message":"<400> InternalError.Algo.InvalidParameter: The image length and width do not meet the model restrictions. [height:1 or width:1 must be larger than 10]", ...}}`
- Task 1 live throwaway call, 64×64 solid-red test image → `HTTP 200`, response shape confirmed identical to DeepSeek's OpenAI-compatible shape: `{"choices":[{"message":{"content":"Red.","role":"assistant"},...}],"object":"chat.completion","usage":{...},"model":"qwen-vl-plus",...}`. Confirms endpoint `https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions`, model `qwen-vl-plus`, and base64 `data:image/...;base64,...` URIs all work with the existing DashScope account key (`YTFLOW_QWEN_TTS_API_KEY`) with zero re-upload step.
- Task 5 live call against real `SCP-682` reference image (`workspace/SCP-682/references/ref_1.jpg`, downloaded during Story 5.12's live run) via `CharacterService.enrich_descriptor_from_references` directly → non-empty descriptor returned, no exception, no `None`. Full text recorded in Completion Notes below.
- `uv run pytest tests/services/test_character_service_generation.py -q` → 41 passed
- `uv run pytest tests/services/test_character_service.py tests/services/test_character_service_generation.py tests/services/test_run_service_character_provisioning.py tests/pipeline/nodes/test_image.py -q` → 112 passed
- `uv run pytest tests/services/test_run_service_character_provisioning.py -q` (unmodified) → 9 passed
- `uv run pytest -q` (full suite) → 628 passed, 1 skipped (same skip as Story 5.12's baseline)

### Completion Notes List

- Root cause confirmed and fixed: the DeepSeek account has no vision-capable model at all (`deepseek-v4-flash`/`deepseek-v4-pro` are both text-only) — this was a provider swap, not a model-name or prompt fix.
- `enrich_descriptor_from_references` now calls DashScope's OpenAI-compatible endpoint (`https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions`, hardcoded as `_DASHSCOPE_VISION_ENDPOINT` — no config field for the endpoint, mirroring `QwenCharacterProvider`'s precedent per ponytail: no config for a value that never changes) with model/key sourced from two new distinct settings: `character_vision_model` (default `"qwen-vl-plus"`) and `character_vision_api_key` (default `""`).
- The `image_parts`/`content_parts` base64 data-URI construction was left completely untouched, as required — only the URL, `model`, and `Authorization` header source changed. `max_tokens` continues to reuse `s.deepseek_max_tokens` unchanged, since Task 3 scoped the change to exactly URL/model/auth and DashScope accepts the same field.
- The `except (httpx.HTTPError, ValueError, KeyError, IndexError)` branch and existing-descriptor fallback were left as-is — DashScope's error/response envelope is confirmed identical in shape to DeepSeek's (both OpenAI-compatible), so no exception-tuple change was needed.
- Live AC2 validation (2026-07-05, real `SCP-682` reference image): returned a real, non-empty, richly detailed descriptor (600+ chars covering body shape, texture, color palette, distinguishing features) — the live-validation gap Story 5.12 could not close is now closed.
- Live descriptor text (Task 5, full): "The character is a towering, grotesque entity with a massive, amorphous body that defies conventional anatomy, its silhouette resembling a decaying, bloated whale. The creature's skin is a mottled, translucent black with deep, leathery folds and patches of decayed flesh, revealing underlying layers of brown and orange hues reminiscent of rotting meat. Its disproportionately large head is fused seamlessly into the main body, lacking distinct facial features but adorned with a single, bulbous, yellowish protrusion on top. The limbs are short, stubby appendages that blend into the bulk of the torso, contributing to an overall impression of immense weight and sluggish movement. The surface texture is highly detailed, with a mix of wet, glossy areas suggesting moisture or bodily fluids, alongside rough, scaly patches that hint at a non-human origin. The color palette is dominated by dark, oppressive tones—deep blacks (#0A0A0A), muted browns (#5C4033), and sickly yellows (#FDD835)—with subtle gradients that enhance the sense of decay and otherworldliness. Distinguishing features include a series of horizontal ridges running along the back, resembling skeletal structures, and faint, glowing veins visible beneath the translucent skin. The lighting in the reference image is natural daylight, casting soft shadows that accentuate the creature's grotesque contours, while the background of a serene beach and distant mountains creates a stark contrast, amplifying the unsettling mood of the design. The art style is hyper-realistic with a touch of painterly texture, emphasizing the visceral details and creating a haunting, immersive visual experience."
- Story 5.12's non-fatal wiring, rollback, and dedup contract in `run_service._ensure_character_reference` were untouched and confirmed unaffected — `tests/services/test_run_service_character_provisioning.py` passed unmodified (9/9), including the two provider-agnostic enrichment-wiring tests.
- Added `YTFLOW_CHARACTER_VISION_API_KEY` to the local `.env` (not committed via story artifacts — operator-owned secret file) reusing the same DashScope account key already configured for Qwen TTS, per the story's own note that both settings may point at the same underlying account while staying distinct config fields.

### File List

- `src/yt_flow/config.py` — added `character_vision_model` (default `"qwen-vl-plus"`) and `character_vision_api_key` (default `""`) settings
- `src/yt_flow/services/character_service.py` — added `_DASHSCOPE_VISION_ENDPOINT` constant; swapped `enrich_descriptor_from_references`'s HTTP call from DeepSeek (`deepseek_base_url`/`deepseek_api_key`/`deepseek_model`) to DashScope Qwen-VL (`_DASHSCOPE_VISION_ENDPOINT`/`character_vision_api_key`/`character_vision_model`); updated docstring/log line from "DeepSeek" to "DashScope Qwen-VL"
- `tests/services/test_character_service_generation.py` — `TestVisionLLMEnrichment` (5 call sites) updated from `service._settings.deepseek_api_key` to `service._settings.character_vision_api_key`

## Change Log

- 2026-07-05: Story drafted via create-story workflow, from Story 5.12's live re-validation finding (Vision LLM enrichment call fires correctly but fails with a real 400 — the configured DeepSeek account has no vision-capable model at all, confirmed via a live `/models` check). Jay confirmed the fix direction in conversation: swap to Qwen-VL via the DashScope account this project already holds for Qwen TTS, scoped strictly to the one HTTP call inside `enrich_descriptor_from_references`.
- 2026-07-05: Implemented via dev-story workflow — confirmed DashScope Qwen-VL contract live (endpoint/auth/base64/response-shape all match assumptions), added `character_vision_model`/`character_vision_api_key` settings, swapped `enrich_descriptor_from_references`'s HTTP target to DashScope, updated `TestVisionLLMEnrichment`'s 5 config-field references. Live re-validation against real `SCP-682` reference image returned a real, non-empty descriptor (AC2 closed). Full regression suite green: 628 passed, 1 skipped.
- 2026-07-05: Code review (joint with Story 5.12) via bmad-code-review — 3 parallel layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor). 2 findings confirmed and fixed for this story: `enrich_descriptor_from_references`'s except tuple widened to catch `AttributeError` (a DashScope safety-block response with `content: null` would otherwise raise, violating AC2/AC3's non-fatal contract); added an assertion that the outbound POST actually targets the DashScope endpoint/model, closing a gap where reverting to the old DeepSeek URL would pass every test. Full regression suite green (628 passed, 1 pre-existing skip). Status → done.
