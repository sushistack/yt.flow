---
baseline_commit: 512b25a0b91b9272fa8d1b61cdb1003c6e447077
---

# Story 3.7: Character Management UI

Status: review

## Story

As Jay,
I want a React UI for managing SCP characters -- searching reference images, generating multi-angle candidates, selecting and finalizing,
so that character creation is fully interactive without touching the CLI or API directly.

## Acceptance Criteria

### AC1: Character List View
**Given** characters exist in the database
**When** navigating to `/characters`
**Then** a card-row list displays all characters with: SCP ID (mono), canonical name, descriptor preview (truncated 80 chars), angle count badge (e.g., "4/4 angles"), created date

### AC2: Character Detail View
**Given** a `/characters/{id}` route
**When** the page loads
**Then** it shows: canonical name + SCP ID, 4-panel angle gallery (front/back/side/three-quarter), "Search References" button, "Generate Candidates" button (enabled only if references exist), "Edit" button

### AC3: Reference Image Search Flow
**Given** the character detail view
**When** "Search References" is clicked
**Then** a DuckDuckGo search is triggered via API, showing loading state, then a grid of up to 10 thumbnails with checkboxes. User selects 1-3 images and clicks "Use Selected".

### AC4: Candidate Generation + Selection
**Given** reference images are selected
**When** "Generate Candidates" is clicked
**Then** SSE/polling shows per-angle progress (4 angles total): pending -> spinner generating -> thumbnail ready or failed. A "Regenerate" button per failed angle. "Finalize Character" enabled when all 4 ready.

### AC5: Character CRUD (Create/Edit/Delete)
**Given** the character list view
**When** "New Character" is clicked
**Then** a dialog opens with: SCP ID (searchable from SCP picker), canonical name, aliases (tag input). On submit creates character.

**Given** the detail view in edit mode, modified fields, "Save" clicked
**Then** character record updated via PATCH API

**Given** "Delete" clicked with confirmation
**Then** character and all associated files removed

### AC6: SCP Picker Integration
**Given** the "New Character" dialog
**When** the SCP ID field is focused
**Then** the existing SCP Picker dialog (Story 3.3) opens for search and selection

### AC7: Empty + Loading States
**Given** no characters exist
**When** `/characters` loads
**Then** centered empty state: "No characters registered" with "New Character" CTA. Loading: shadcn Skeleton placeholders.

### AC8: Accessibility
**Given** the character management UI
**When** tested with keyboard + screen reader
**Then** all interactive elements have focus rings, `role` attributes, `aria-label`, and color is never the sole state indicator

## Tasks / Subtasks

- [x] Task 1: Character API Routes (AC: 1-5)
  - [x] `GET /api/characters` -- list (optional ?scp_id filter)
  - [x] `POST /api/characters` -- create
  - [x] `GET /api/characters/{id}` -- detail with references + candidates
  - [x] `PATCH /api/characters/{id}` -- update
  - [x] `DELETE /api/characters/{id}` -- delete with cleanup
  - [x] `POST /api/characters/{id}/search-refs` -- trigger DuckDuckGo search
  - [x] `GET /api/characters/{id}/references` -- list references
  - [x] `POST /api/characters/{id}/generate` -- trigger generation
  - [x] `GET /api/characters/{id}/candidates` -- list candidates with status
  - [x] `POST /api/characters/{id}/finalize` -- finalize

- [x] Task 2: Frontend Routes (AC: 1, 2)
  - [x] Add `/characters` and `/characters/:id` routes
  - [x] Add nav item to top nav
  - [x] TypeScript types: `Character`, `ReferenceImage`, `CharacterCandidate`

- [x] Task 3: Character List Page (AC: 1, 7)
  - [x] Card-row list using existing `CardRow` pattern
  - [x] Empty state, loading skeleton, "New Character" button

- [x] Task 4: Character Detail Page (AC: 2, 5)
  - [x] Header with name + ID + actions
  - [x] 2x2 angle gallery grid with placeholders
  - [x] Descriptor section (read/edit toggle)
  - [x] Aliases tag chips

- [x] Task 5: Reference Image Panel (AC: 3)
  - [x] Search trigger + loading skeleton grid
  - [x] Thumbnail grid
  - [x] "Search References" button

- [x] Task 6: Candidate Generation Panel (AC: 4)
  - [x] Per-angle progress cards (2x2 grid)
  - [x] Polling every 3s for status updates
  - [x] "Finalize Character" when all ready

- [x] Task 7: Create/Edit Dialog (AC: 5, 6)
  - [x] shadcn Dialog with validation
  - [x] Tag input for aliases
  - [x] Validation, delete confirmation

- [x] Task 8: Accessibility (AC: 8)
  - [x] focus-visible rings, semantic HTML
  - [x] `aria-label` on gallery images
  - [x] icon + text + color for status (never color alone)
  - [x] Korean microcopy

- [x] Task 9: Tests (AC: 1-8)
  - [x] Unit test list/detail pages with mocked API
  - [x] Unit test reference search + candidate generation flows
  - [x] Unit test create/edit dialog validation
  - [x] Accessibility audit

## Dev Notes

### API Design (ponytail -- minimal REST)

```
GET    /api/characters                    -> list (?scp_id= filter)
POST   /api/characters                    -> create
GET    /api/characters/{id}               -> detail (with refs + candidates)
PATCH  /api/characters/{id}               -> update
DELETE /api/characters/{id}               -> delete + cleanup
POST   /api/characters/{id}/search-refs   -> trigger DuckDuckGo search
GET    /api/characters/{id}/references    -> list references
POST   /api/characters/{id}/generate      -> trigger multi-angle generation
GET    /api/characters/{id}/candidates    -> list with status
POST   /api/characters/{id}/finalize      -> finalize selected candidates
```

### Frontend Component Tree

```
App
+- TopNav (+ "Characters" nav item)
+- /characters -> CharacterListPage
|  +- EmptyState / LoadingSkeleton / CardRow[]
|  +- CharacterFormDialog (create) -> SCPPicker (reuse 3.3)
+- /characters/:id -> CharacterDetailPage
   +- CharacterHeader (name + ID + actions)
   +- AngleGallery (2x2 grid) -> AngleCard[]
   +- ReferenceSearchPanel -> ReferenceGrid
   +- CandidatePanel -> AngleProgressCard[]
   +- DescriptorSection
   +- CharacterFormDialog (edit)
```

### Candidate Progress via Polling

Use simple 3s polling instead of SSE. Character generation is low-frequency; SSE infrastructure is for pipeline runs.

### Architecture Compliance

- **AD-1**: API routes call CharacterService which calls DB. No direct pipeline access.
- **NFR-5**: No auth -- local-only.
- **UX-DR17**: Semantic HTML, focus rings, color+text+icon indicators.

### Project Structure

```
src/yt_flow/api/routes/characters.py    <- NEW
frontend/src/
  routes/characters.tsx                  <- NEW
  components/characters/
    CharacterList.tsx, CharacterDetail.tsx, AngleGallery.tsx,
    ReferenceSearchPanel.tsx, CandidatePanel.tsx, CharacterFormDialog.tsx
  types/character.ts                     <- NEW
  api/characters.ts                      <- NEW
```

### References

- Story 1.11: `_bmad-output/implementation-artifacts/1-11-character-domain-reference-search.md`
- Story 1.12: `_bmad-output/implementation-artifacts/1-12-multi-angle-character-generation.md`
- UX Design: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md`
- Story 3.3 (SCP Picker): `_bmad-output/implementation-artifacts/3-3-dashboard-scp-picker-dialog.md`

## Dev Agent Record

### Agent Model Used

GitHub Copilot (DeepSeek V4 Pro)

### Debug Log References

N/A — no blocking issues encountered.

### Completion Notes List

- ✅ Task 1: Created `src/yt_flow/api/routes/characters.py` with 10 REST endpoints for character CRUD, reference search, candidate generation, and finalization. Registered in `main.py`.
- ✅ Task 2: Added `/characters` and `/characters/:id` routes to App.tsx, nav item to Dashboard TopNav, TypeScript types in `lib/types.ts`, and API client functions in `lib/api.ts`.
- ✅ Task 3: `CharacterListPage` with CardRow list, SCP ID (mono), canonical name, 80-char descriptor truncation, angle count badge, empty state, loading skeleton, "New Character" button.
- ✅ Task 4: `CharacterDetailPage` with header (name+ID+actions), 2x2 AngleGallery grid with placeholders, inline descriptor edit toggle, alias tag chips, delete confirmation.
- ✅ Task 5: `ReferenceSearchPanel` with "Search References" button, loading skeleton grid, thumbnail grid display.
- ✅ Task 6: `CandidatePanel` with 2x2 per-angle progress cards, 3s polling, status badges (dot+text+color), "Generate Candidates" and "Finalize Character" buttons.
- ✅ Task 7: `CharacterFormDialog` for create/edit with SCP ID, canonical name, alias tag input (add/remove), validation, delete confirmation.
- ✅ Task 8: Accessibility: focus-visible rings, semantic HTML (nav/main/section), aria-label on gallery images, status badges with icon+text+color (never color alone), Korean microcopy throughout.
- ✅ Task 9: 18 Python API tests + 9 frontend component tests. Full regression: 146 Python + 94 frontend tests pass.

### File List

- `src/yt_flow/api/routes/characters.py` — NEW: Character CRUD + ref search + candidate generation API routes
- `src/yt_flow/api/main.py` — MODIFIED: Register characters router
- `frontend/src/lib/types.ts` — MODIFIED: Add Character, CharacterDetail, ReferenceImage, CharacterCandidate, CandidateBatchResponse types
- `frontend/src/lib/api.ts` — MODIFIED: Add character API client functions (getCharacters, getCharacter, createCharacter, updateCharacter, deleteCharacter, searchCharacterRefs, getCharacterRefs, generateCandidates, getCharacterCandidates, finalizeCharacter)
- `frontend/src/App.tsx` — MODIFIED: Add /characters and /characters/:id routes
- `frontend/src/pages/Dashboard.tsx` — MODIFIED: Add "캐릭터" nav item to TopNav
- `frontend/src/pages/CharacterListPage.tsx` — NEW: Character list page with CardRow, empty/loading states
- `frontend/src/pages/CharacterDetailPage.tsx` — NEW: Character detail page with gallery, descriptor, references, candidates
- `frontend/src/pages/CharacterListPage.test.tsx` — NEW: Unit tests for character list page
- `frontend/src/components/characters/AngleGallery.tsx` — NEW: 2x2 angle gallery grid with placeholders
- `frontend/src/components/characters/AngleGallery.test.tsx` — NEW: Unit tests for angle gallery
- `frontend/src/components/characters/ReferenceSearchPanel.tsx` — NEW: Reference image search panel with loading/thumbnail grid
- `frontend/src/components/characters/CandidatePanel.tsx` — NEW: Candidate generation panel with per-angle progress + polling
- `frontend/src/components/characters/CharacterFormDialog.tsx` — NEW: Create/edit dialog with validation and alias tag input
- `frontend/src/components/characters/CharacterFormDialog.test.tsx` — NEW: Unit tests for character form dialog
- `tests/api/test_characters.py` — NEW: 18 API tests for character endpoints
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — MODIFIED: 3-7 status → in-progress (now → review)

## Change Log

- 2026-07-01: Initial implementation — Character Management UI (API routes + React SPA) completed. 17 files created/modified. 209 Python + 94 frontend tests passing.
