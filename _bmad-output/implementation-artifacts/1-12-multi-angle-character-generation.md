# Story 1.12: Multi-Angle Character Image Generation

Status: ready-for-dev

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

- [ ] Task 1: Vision LLM Descriptor Enrichment (AC: 1, 2)
  - [ ] Add `enrich_descriptor_from_references(scp_id, ref_image_paths)` to `CharacterService`
  - [ ] Load reference images as base64 data URIs (support png/jpeg/webp)
  - [ ] Call DeepSeek V4 multimodal API with vision prompt + images
  - [ ] Load prompt from `prompts/character/vision_enrichment.md` (or Langfuse Prompt Hub)
  - [ ] Fallback: built-in prompt string if template file is absent
  - [ ] Return enriched descriptor string or `None` on failure (AD-10: non-fatal)

- [ ] Task 2: Multi-Angle Generation Pipeline (AC: 3, 8)
  - [ ] Add `generate_candidates_from_reference(scp_id, ref_image_path, angles)` to `CharacterService`
  - [ ] For each angle in `["front", "back", "side", "three_quarter"]`:
    - [ ] Compile angle-specific prompt: append angle direction to enriched descriptor
    - [ ] Try i2i (image edit) first: pass reference image bytes + prompt to provider
    - [ ] Fallback to t2i if i2i returns unsupported or fails
    - [ ] Save generated image to `workspace/{scp_id}/characters/{angle}_candidate_{N}.png`
  - [ ] Provider abstraction: `CharacterImageProvider` protocol
  - [ ] `ComfyUICharacterProvider` -- wraps existing `comfyui_client`
  - [ ] `QwenCharacterProvider` -- uses Qwen image generation via DashScope/SiliconFlow API

- [ ] Task 3: Candidate Tracking in DB (AC: 4)
  - [ ] Add `CharacterCandidate` SQLModel to `src/yt_flow/db/models.py`
  - [ ] Add service methods: `create_candidate_batch`, `update_candidate_status`, `list_candidates`, `get_candidate_status`

- [ ] Task 4: Candidate Selection + Memorization (AC: 5, 6)
  - [ ] `select_candidate(scp_id, candidate_num, angle)` -- sets individual angle image
  - [ ] `finalize_character(id)` -- after all 4 angles selected, maps to `angle_*_path`
  - [ ] Auto-create character record if not exists (memorization)

- [ ] Task 5: Config + Settings (AC: 7)
  - [ ] Add: `character_image_provider`, `character_comfyui_workflow_path`, `character_qwen_model`, `character_image_width`, `character_image_height`

- [ ] Task 6: Prompt Templates (AC: 8)
  - [ ] Create `prompts/character/vision_enrichment.md`
  - [ ] Create `prompts/character/generation.md`
  - [ ] Register in Langfuse Prompt Hub

- [ ] Task 7: Tests (AC: 1-8)
  - [ ] Unit test Vision LLM enrichment with mocked LLM
  - [ ] Unit test Vision LLM failure fallback
  - [ ] Unit test multi-angle generation with mocked provider
  - [ ] Unit test candidate status transitions
  - [ ] Unit test candidate selection -> character creation
  - [ ] Unit test finalize_character maps all 4 angles
  - [ ] Unit test ComfyUI and Qwen provider implementations
  - [ ] Integration test: ref images -> vision -> generation -> selection -> finalization

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

_To be filled by dev agent_

### Debug Log References

_To be filled by dev agent_

### Completion Notes List

_To be filled by dev agent_

### File List

_To be filled by dev agent_
