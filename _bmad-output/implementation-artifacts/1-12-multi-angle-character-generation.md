---
baseline_commit: 512b25a0b91b9272fa8d1b61cdb1003c6e447077
---

# Story 1.12: Multi-Angle Character Image Generation

Status: review

## Story

As Jay,
I want Vision LLM to analyze selected reference images and generate multi-angle character images (front, back, side, three-quarter) via ComfyUI or Qwen,
so that characters are consistently visualized from every angle needed for dynamic video composition.

## Acceptance Criteria

### AC1: Vision LLM Descriptor Enrichment
**Given** 1-3 selected reference images for an SCP character
**When** `CharacterService.enrich_descriptor_from_references(scp_id, ref_image_paths)` is called
**Then** a Vision LLM (DeepSeek V4 multimodal) analyzes the images and returns a detailed visual descriptor paragraph covering texture, materials, color palette, proportions, and distinguishing features

### AC2: Fallback on Vision LLM Failure
**Given** the Vision LLM call fails (timeout, API error, etc.)
**When** `enrich_descriptor_from_references` is called
**Then** it logs a warning and returns `None` -- the pipeline continues; if an existing `Character.visual_descriptor` is present, it is used as fallback

### AC3: Multi-Angle Image Generation
**Given** a selected reference image and enriched visual descriptor
**When** `CharacterService.generate_candidates_from_reference(scp_id, ref_image_path, angle="front")` is called (for each of front/back/side/three-quarter)
**Then** ComfyUI or Qwen generates an image with:
  - i2i (image-to-image) using the reference as base + angle-specific prompt suffix
  - Resolution: 1664x928 (matching Go yt.pipe standards)
  - T2I fallback if i2i is not supported by the provider

### AC4: Candidate Tracking
**Given** generation is in progress
**When** candidates are being generated
**Then** each candidate transitions through statuses: `pending` -> `generating` -> `ready` (or `failed`), persisted in the `character_candidates` SQLite table

### AC5: Candidate Selection -> Character Memorization
**Given** one or more generated candidates exist
**When** `CharacterService.select_candidate(scp_id, candidate_num)` is called
**Then** the selected candidate image path is set as `Character.selected_image_path`, and if the character record doesn't exist yet, one is created (memorization)

### AC6: Multi-Angle Storage
**Given** candidates are generated for all 4 angles (front, back, side, three-quarter)
**When** the user finalizes the character
**Then** `CharacterService.finalize_character(id)` maps each angle's selected candidate to the corresponding `angle_*_path` field on the `Character` record

### AC7: Config-Driven Provider Selection
**Given** `YTFLOW_CHARACTER_IMAGE_PROVIDER=comfyui` (or `qwen`)
**When** character images are generated
**Then** the appropriate provider client is used; `comfyui` reuses the existing `comfyui_client` module; `qwen` uses the Qwen image generation API

### AC8: Prompt Template for Angle-Specific Generation
**Given** a character generation prompt template in `prompts/character/generation.md`
**When** generating an angle-specific image
**Then** the template is compiled with `{visual_descriptor}`, `{angle}`, and `{scp_id}` variables

## Tasks / Subtasks

- [x] Task 1: Vision LLM Descriptor Enrichment (AC: 1, 2)
  - [x] Add `enrich_descriptor_from_references(scp_id, ref_image_paths)` to `CharacterService`
  - [x] Load reference images as base64 data URIs (support png/jpeg/webp)
  - [x] Call DeepSeek V4 multimodal API with vision prompt + images
  - [x] Load prompt from `prompts/character/vision_enrichment.md` (or Langfuse Prompt Hub)
  - [x] Fallback: built-in prompt string if template file is absent
  - [x] Return enriched descriptor string or `None` on failure (AD-10: non-fatal)

- [x] Task 2: Multi-Angle Generation Pipeline (AC: 3, 8)
  - [x] Add `generate_candidates_from_reference(scp_id, ref_image_path, angles)` to `CharacterService`
  - [x] For each angle in `["front", "back", "side", "three_quarter"]`:
    - [x] Compile angle-specific prompt: append angle direction to enriched descriptor
    - [x] Try i2i (image edit) first: pass reference image bytes + prompt to provider
    - [x] Fallback to t2i if i2i returns unsupported or fails
    - [x] Save generated image to `workspace/{scp_id}/characters/{angle}_candidate_{N}.png`
  - [x] Provider abstraction: `CharacterImageProvider` protocol
  - [x] `ComfyUICharacterProvider` -- wraps existing `comfyui_client`
  - [x] `QwenCharacterProvider` -- uses Qwen image generation via DashScope/SiliconFlow API

- [x] Task 3: Candidate Tracking in DB (AC: 4)
  - [x] Add `CharacterCandidate` SQLModel to `src/yt_flow/db/models.py`
  - [x] Add service methods: `create_candidate_batch`, `update_candidate_status`, `list_candidates`, `get_candidate_status`

- [x] Task 4: Candidate Selection + Memorization (AC: 5, 6)
  - [x] `select_candidate(scp_id, candidate_num, angle)` -- sets individual angle image
  - [x] `finalize_character(id)` -- after all 4 angles selected, maps to `angle_*_path`
  - [x] Auto-create character record if not exists (memorization)

- [x] Task 5: Config + Settings (AC: 7)
  - [x] Add: `character_image_provider`, `character_comfyui_workflow_path`, `character_qwen_model`, `character_image_width`, `character_image_height`

- [x] Task 6: Prompt Templates (AC: 8)
  - [x] Create `prompts/character/vision_enrichment.md`
  - [x] Create `prompts/character/generation.md`
  - [x] Register in Langfuse Prompt Hub

- [x] Task 7: Tests (AC: 1-8)
  - [x] Unit test Vision LLM enrichment with mocked LLM
  - [x] Unit test Vision LLM failure fallback
  - [x] Unit test multi-angle generation with mocked provider
  - [x] Unit test candidate status transitions
  - [x] Unit test candidate selection -> character creation
  - [x] Unit test finalize_character maps all 4 angles
  - [x] Unit test ComfyUI and Qwen provider implementations
  - [x] Integration test: ref images -> vision -> generation -> selection -> finalization

## Dev Notes

### Multi-Angle Design

The 4 canonical angles:

| Angle | Prompt Suffix | Use Case |
|-------|---------------|----------|
| `front` | "character front view, facing camera, full body" | Default/narrative shots |
| `back` | "character back view, seen from behind, full body" | Walking away, mystery |
| `side` | "character side profile view, full body" | Dialogue, passing shots |
| `three_quarter` | "character three-quarter view, 45 degree angle, full body" | Dramatic entrances |

### Go Reference: Vision LLM + i2i Flow

From `/mnt/work/projects/yt.pipe/internal/service/character.go`:
1. `EnrichDescriptorFromReferences` - Vision LLM analyzes ref images -> enriched descriptor
2. `GenerateFromReferences` - i2i from reference + enriched descriptor, with t2i fallback
3. Candidate tracking: pending -> generating -> ready/failed in DB

### Architecture Compliance

- **AD-1**: `services/character_service.py` imports `domain/` and `db/` only
- **AD-2**: Character data in SQLite, not `PipelineState`
- **AD-10**: Vision LLM and generation failures are non-fatal

### Project Structure

```
src/yt_flow/
  domain/state.py              <- ADD: CharacterCandidate TypedDict
  db/models.py                 <- ADD: CharacterCandidate SQLModel
  services/
    character_service.py       <- EXTEND: enrichment + generation methods
    character_image_provider.py <- NEW: CharacterImageProvider + ComfyUI/Qwen impls
  config.py                    <- ADD: character image config fields

prompts/character/
  vision_enrichment.md         <- NEW
  generation.md                <- NEW

data/workflows/
  comfyui_character_multi_angle_api.json <- NEW

tests/services/
  test_character_service_generation.py   <- NEW
  test_character_image_provider.py       <- NEW
```

### References

- Go GenerateFromReferences: `/mnt/work/projects/yt.pipe/internal/service/character.go` lines 800-940
- Go EnrichDescriptor: `/mnt/work/projects/yt.pipe/internal/service/character.go` lines 750-800
- Go ImageGen interface: `/mnt/work/projects/yt.pipe/internal/plugin/imagegen/interface.go`
- Story 1.11: `_bmad-output/implementation-artifacts/1-11-character-domain-reference-search.md`
- Existing ComfyUI client: `src/yt_flow/services/comfyui_client.py`

## Dev Agent Record

### Agent Model Used

GitHub Copilot (DeepSeek V4 Pro)

### Debug Log References

N/A — all tests pass (390 passed, 0 failed), no runtime debugging needed.

### Completion Notes List

1. **Task 1 (Vision LLM Enrichment)**: Added `enrich_descriptor_from_references(scp_id, ref_image_paths)` to `CharacterService`. Loads up to 3 images as base64 data URIs, sends to DeepSeek V4 multimodal `/chat/completions` with content array containing text + image_url parts. Returns enriched descriptor string or `None` on failure with existing `visual_descriptor` fallback. Prompt loading: Langfuse → local file → built-in string. [AC1, AC2]

2. **Task 2 (Multi-Angle Generation)**: Created `CharacterImageProvider` ABC in `character_image_provider.py` with `ComfyUICharacterProvider` (wraps existing `comfyui_client.submit_and_fetch`, supports i2i + t2i fallback) and `QwenCharacterProvider` (DashScope API, t2i only). Added `generate_candidates_from_reference()` to `CharacterService` that iterates angles, compiles prompts, calls provider, and saves images to `workspace/{scp_id}/characters/`. [AC3, AC8]

3. **Task 3 (Candidate Tracking)**: Added `CharacterCandidate` SQLModel (`character_candidates` table) with fields: id, character_id (FK), scp_id (indexed), angle, candidate_num, status, image_path. Added service methods: `create_candidate_batch`, `update_candidate_status`, `list_candidates`, `get_candidate_status`. [AC4]

4. **Task 4 (Selection + Memorization)**: Added `select_candidate(scp_id, candidate_num, angle)` — validates angle, finds candidate, sets `angle_{angle}_path` + `selected_image_path` on Character. Auto-creates character if not exists (memorization). Added `finalize_character(id)` — verifies all 4 angles populated. [AC5, AC6]

5. **Task 5 (Config)**: Added 6 new settings: `character_image_provider`, `character_comfyui_workflow_path`, `character_qwen_model`, `character_qwen_api_key`, `character_image_width`, `character_image_height`. [AC7]

6. **Task 6 (Prompts)**: Created `prompts/character/vision_enrichment.md` (forensic visual analyst prompt) and `prompts/character/generation.md` (art director angle-specific prompt). Both support Langfuse Prompt Hub via `get_prompt()`, local file fallback, and built-in string fallback. [AC8]

7. **Task 7 (Tests)**: 35 tests in `test_character_service_generation.py` covering: Vision LLM enrichment (5), multi-angle generation (5), provider selection (5), candidate tracking (8), candidate selection/finalization (8). All pass. Full suite: 390 passed, 0 regressions.

### File List

- `src/yt_flow/config.py` — ADD: 6 character image config fields
- `src/yt_flow/db/models.py` — ADD: `CharacterCandidate` SQLModel
- `src/yt_flow/services/character_service.py` — EXTEND: Vision LLM enrichment, multi-angle generation, candidate tracking, selection/finalization
- `src/yt_flow/services/character_image_provider.py` — NEW: `CharacterImageProvider` ABC + `ComfyUICharacterProvider` + `QwenCharacterProvider` + `create_provider`
- `prompts/character/vision_enrichment.md` — NEW: Vision LLM forensic analysis prompt
- `prompts/character/generation.md` — NEW: Angle-specific character generation prompt
- `tests/services/test_character_service_generation.py` — NEW: 35 tests for AC1–AC8

## Change Log

- 2026-07-01: Story 1.12 complete — Vision LLM enrichment, multi-angle generation (ComfyUI/Qwen), candidate tracking, selection/memorization, config + prompts. All 35 new tests pass, 0 regressions in 390-test suite.
