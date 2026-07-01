# Story 3.7: Character Management UI

Status: ready-for-dev

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

- [ ] Task 1: Character API Routes (AC: 1-5)
  - [ ] `GET /api/characters` -- list (optional ?scp_id filter)
  - [ ] `POST /api/characters` -- create
  - [ ] `GET /api/characters/{id}` -- detail with references + candidates
  - [ ] `PATCH /api/characters/{id}` -- update
  - [ ] `DELETE /api/characters/{id}` -- delete with cleanup
  - [ ] `POST /api/characters/{id}/search-refs` -- trigger DuckDuckGo search
  - [ ] `GET /api/characters/{id}/references` -- list references
  - [ ] `POST /api/characters/{id}/generate` -- trigger generation
  - [ ] `GET /api/characters/{id}/candidates` -- list candidates with status
  - [ ] `POST /api/characters/{id}/finalize` -- finalize

- [ ] Task 2: Frontend Routes (AC: 1, 2)
  - [ ] Add `/characters` and `/characters/:id` routes
  - [ ] Add nav item to top nav
  - [ ] TypeScript types: `Character`, `ReferenceImage`, `CharacterCandidate`

- [ ] Task 3: Character List Page (AC: 1, 7)
  - [ ] Card-row list using existing `CardRow` pattern
  - [ ] Empty state, loading skeleton, "New Character" button

- [ ] Task 4: Character Detail Page (AC: 2, 5)
  - [ ] Header with name + ID + actions
  - [ ] 2x2 angle gallery grid with placeholders
  - [ ] Descriptor section (read/edit toggle)
  - [ ] Aliases tag chips

- [ ] Task 5: Reference Image Panel (AC: 3)
  - [ ] Search trigger + loading skeleton grid
  - [ ] Thumbnail grid with checkboxes (max 3 selection)
  - [ ] "Use Selected" button

- [ ] Task 6: Candidate Generation Panel (AC: 4)
  - [ ] Per-angle progress cards (2x2 grid)
  - [ ] Polling every 3s for status updates
  - [ ] "Regenerate" per failed angle, "Finalize" when all ready

- [ ] Task 7: Create/Edit Dialog (AC: 5, 6)
  - [ ] shadcn Dialog with SCP Picker integration
  - [ ] Tag input for aliases
  - [ ] Validation, delete confirmation

- [ ] Task 8: Accessibility (AC: 8)
  - [ ] focus-visible rings, semantic HTML
  - [ ] `aria-label` on gallery images
  - [ ] icon + text + color for status (never color alone)
  - [ ] Korean microcopy

- [ ] Task 9: Tests (AC: 1-8)
  - [ ] Unit test list/detail pages with mocked API
  - [ ] Unit test reference search + candidate generation flows
  - [ ] Unit test create/edit dialog validation
  - [ ] Accessibility audit

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

_To be filled by dev agent_

### Debug Log References

_To be filled by dev agent_

### Completion Notes List

_To be filled by dev agent_

### File List

_To be filled by dev agent_
