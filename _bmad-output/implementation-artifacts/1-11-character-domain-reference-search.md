# Story 1.11: Character Domain + DuckDuckGo Reference Image Search

Status: ready-for-dev

## Story

As Jay,
I want to define the Character domain model and integrate DuckDuckGo image search for reference images,
so that character definitions are persisted in SQLite and reference images are discoverable without any API key dependency.

## Acceptance Criteria

### AC1: Character Domain Model
**Given** the `Character` TypedDict and SQLModel are defined
**When** `from yt_flow.domain.state import Character` and `from yt_flow.db.models import Character` run
**Then** both import without error, and the SQLModel `Character` table is created on `db.init()`

### AC2: CharacterService CRUD
**Given** `CharacterService` is instantiated with a SQLModel `Session`
**When** `create_character(scp_id, canonical_name, aliases)` is called
**Then** a `Character` record is persisted to SQLite with a UUID v4 `id`, and the returned object contains all fields

**Given** an existing character
**When** `get_character(id)`, `list_characters(scp_id)`, `update_character(...)`, `delete_character(id)` are called
**Then** each operation reads/writes the SQLite `characters` table correctly

### AC3: DuckDuckGo Image Search
**Given** no API key or external service dependency
**When** `DuckDuckGoImageSearch.search(query="SCP-096", max_results=10)` is called
**Then** up to 10 `SearchResult` objects are returned, each with `url`, `thumbnail_url`, and `title` fields

### AC4: Reference Image Download with Safety Checks
**Given** a DuckDuckGo search result URL
**When** `CharacterService.search_references(scp_id, workspace_path, max_results=10)` is called
**Then** images are downloaded to `workspace/{scp_id}/references/ref_1.png` (etc.), saved to DB as `ReferenceImage` records, and the following safety checks are enforced:
  - Content-Type must be `image/png`, `image/jpeg`, or `image/webp`
  - Max file size <= 10 MB
  - Downloads timeout after 30 seconds
  - Private/loopback IP addresses are blocked (SSRF protection)

### AC5: Validation
**Given** invalid input to `create_character` (empty `scp_id`, empty `canonical_name`, empty-string alias)
**When** the method is called
**Then** a `ValidationError` is raised with the offending field name

### AC6: Multi-Angle Readiness
**Given** the `Character` model
**When** fields are inspected
**Then** the following are present (with `None` defaults, populated in Story 1.12):
  - `visual_descriptor: str | None`
  - `style_guide: str | None`
  - `image_prompt_base: str | None`
  - `selected_image_path: str | None`
  - `angle_front_path: str | None`
  - `angle_back_path: str | None`
  - `angle_side_path: str | None`
  - `angle_three_quarter_path: str | None`

## Tasks / Subtasks

- [ ] Task 1: Character Domain TypedDict (AC: 1, 6)
  - [ ] Add `Character` TypedDict to `src/yt_flow/domain/state.py`
  - [ ] Add `ReferenceImage` TypedDict
  - [ ] Add `SearchResult` TypedDict
  - [ ] Define `AngleName = Literal["front", "back", "side", "three_quarter"]`

- [ ] Task 2: Character SQLModel + DB Table (AC: 1, 6)
  - [ ] Add `Character` SQLModel to `src/yt_flow/db/models.py` with table=True
  - [ ] Add `ReferenceImage` SQLModel with table=True
  - [ ] Verify `db.init()` creates both tables via `SQLModel.metadata.create_all`
  - [ ] Fields: `id` (UUID v4 PK), `scp_id` (indexed), `canonical_name`, `aliases` (JSON), angle paths, `created_at`, `updated_at`

- [ ] Task 3: DuckDuckGo Image Search Plugin (AC: 3)
  - [ ] Create `src/yt_flow/services/image_search.py` with `ImageSearch` protocol/ABC
  - [ ] Implement `DuckDuckGoImageSearch` class
  - [ ] VQD token acquisition (POST to duckduckgo.com, extract from response)
  - [ ] Image search request (GET duckduckgo.com/i.js with vqd token)
  - [ ] Parse JSON response into `SearchResult` objects
  - [ ] User-Agent header (Chrome 131 Linux)
  - [ ] 30-second HTTP timeout

- [ ] Task 4: CharacterService (AC: 2, 4, 5)
  - [ ] Create `src/yt_flow/services/character_service.py`
  - [ ] `create_character(scp_id, canonical_name, aliases)` with validation
  - [ ] `get_character(id)`, `list_characters(scp_id)`, `list_all_characters()`
  - [ ] `update_character(id, **fields)` -- partial update
  - [ ] `delete_character(id)`
  - [ ] `check_existing_character(scp_id)` -> first character or None
  - [ ] `search_references(scp_id, workspace_path, max_results=10)`:
    - Call `DuckDuckGoImageSearch.search(query=f"{scp_id} SCP")`
    - Download each image with safety checks (content-type, size, SSRF)
    - Save to `workspace/{scp_id}/references/ref_N.ext`
    - Persist `ReferenceImage` records to DB
    - Return deduplicated: if references already exist in DB, skip search
  - [ ] `research_references(scp_id, workspace_path)` -- clear existing, fresh search
  - [ ] Private `_download_reference_image(url, refs_dir, num)` with safety checks

- [ ] Task 5: Config Integration (AC: 3)
  - [ ] Add `image_search_provider: str = "duckduckgo"` to `Settings`

- [ ] Task 6: Validation + Error Handling (AC: 5)
  - [ ] `ValidationError` exception with `field` and `message` attributes
  - [ ] Validate on create: non-empty `scp_id`, non-empty `canonical_name`
  - [ ] Validate aliases: no empty strings in list

- [ ] Task 7: Tests (AC: 1-6)
  - [ ] Unit test `Character` TypedDict + SQLModel table creation
  - [ ] Unit test `CharacterService` CRUD with in-memory SQLite
  - [ ] Unit test `CharacterService` validation errors
  - [ ] Unit test `DuckDuckGoImageSearch` with mocked HTTP responses
  - [ ] Unit test `search_references` with mocked search + download
  - [ ] Unit test SSRF protection (private IP rejection)
  - [ ] Unit test incremental build (existing refs -> skip search)
  - [ ] Layer-boundary test: `services/` does not import `api/`, `pipeline/` does not import `db/`

## Dev Notes

### Why this story exists

yt.pipe (Go) has a mature `CharacterService` (550+ lines) that manages character ID cards, reference image search via DuckDuckGo, LLM-based candidate generation, and character memorization. yt.flow's Python rewrite has none of this -- the `image_node` simply calls ComfyUI with text prompts. This story establishes the foundation: character domain model, persistence, and reference image discovery.

### Go Reference: Character Domain Model

From `/mnt/work/projects/yt.pipe/internal/domain/character.go`:
```go
type Character struct {
    ID, SCPID, CanonicalName string
    Aliases []string
    VisualDescriptor, StyleGuide, ImagePromptBase string
    SelectedImagePath string
}
```

Python equivalent adds multi-angle fields for Story 1.12 readiness.

### Go Reference: DuckDuckGo Image Search

From `/mnt/work/projects/yt.pipe/internal/plugin/imagesearch/duckduckgo.go`:
1. VQD token: POST to duckduckgo.com, extract `vqd=([0-9a-f-]+)` regex
2. Image search: GET duckduckgo.com/i.js with vqd token
3. No API key required; scraped, not official API

### Architecture Compliance

- **AD-1**: `services/character_service.py` imports from `domain/` and `db/`. Must NOT import `api/` or `pipeline/`.
- **AD-2**: Characters live in SQLite, not `PipelineState`. Long-lived configuration, not per-run state.
- **AD-7**: `Character` and `ReferenceImage` tables share `yt_flow.db`.
- **AD-10**: Image search failures are non-fatal -- log and continue.

### Project Structure

```
src/yt_flow/
  domain/state.py          <- ADD: Character, ReferenceImage, SearchResult TypedDicts, AngleName Literal
  db/models.py             <- ADD: Character, ReferenceImage SQLModel tables
  services/
    character_service.py   <- NEW
    image_search.py        <- NEW: DuckDuckGoImageSearch
  config.py                <- ADD: image_search_provider field

tests/
  domain/test_character_types.py     <- NEW
  services/test_character_service.py <- NEW
  services/test_image_search.py      <- NEW
```

### References

- Go Character domain: `/mnt/work/projects/yt.pipe/internal/domain/character.go`
- Go CharacterService: `/mnt/work/projects/yt.pipe/internal/service/character.go`
- Go DuckDuckGo search: `/mnt/work/projects/yt.pipe/internal/plugin/imagesearch/duckduckgo.go`
- Architecture spine: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`
- Existing domain types: `src/yt_flow/domain/state.py`
- Existing DB models: `src/yt_flow/db/models.py`

## Dev Agent Record

### Agent Model Used

_To be filled by dev agent_

### Debug Log References

_To be filled by dev agent_

### Completion Notes List

_To be filled by dev agent_

### File List

_To be filled by dev agent_
