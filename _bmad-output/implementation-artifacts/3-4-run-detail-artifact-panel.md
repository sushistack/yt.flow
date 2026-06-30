# Story 3.4: Run Detail Layout + Artifact Panel

Status: ready-for-dev

<!-- Completion note: Ultimate context engine analysis completed - comprehensive developer guide created -->

## Story

As Jay,
I want the Run Detail page with sidebar navigation and per-stage artifact panels,
so that I can inspect generated content for any pipeline stage.

## Acceptance Criteria

1. Given navigating to `/runs/{id}`, when the page loads, then the page renders a two-column layout with a 240px fixed sidebar, flex-1 main panel, persistent top nav, and semantic `<nav>`, `<main>`, and `<aside>` elements. [Source: `_bmad-output/planning-artifacts/epics.md#Story 3.4`; `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run Detail`]
2. Given `scenario` stage is selected in the sidebar, when the artifact panel renders, then it shows scrollable Korean prose at approximately 65ch line width and 1.6 line-height. [Source: `_bmad-output/planning-artifacts/epics.md#Story 3.4`; `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run Detail -- artifact panel by stage`]
3. Given `image` stage is selected, when the artifact panel renders, then it shows a 2-column scene image grid with image count label, and clicking any image opens a fullscreen lightbox. [Source: `_bmad-output/planning-artifacts/epics.md#Story 3.4`; `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run Detail -- artifact panel by stage`]
4. Given the image lightbox is open, when the left or right arrow key is pressed, then it navigates between scene images; when Esc is pressed, then the lightbox closes. [Source: `_bmad-output/planning-artifacts/epics.md#Story 3.4`; `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Image Lightbox`]
5. Given `tts` stage is selected, when the artifact panel renders, then it shows per-scene native `<audio controls>` with scene index and duration, sorted by scene number. [Source: `_bmad-output/planning-artifacts/epics.md#Story 3.4`; `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run Detail -- artifact panel by stage`]
6. Given `subtitle` stage is selected, when the artifact panel renders, then it shows SRT text in a monospace scroll area with a subtitle count label. [Source: `_bmad-output/planning-artifacts/epics.md#FR-39`; `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run Detail -- artifact panel by stage`]
7. Given `video` stage is selected, when the artifact panel renders, then it shows a full-width native `<video controls>` player and a download link below. [Source: `_bmad-output/planning-artifacts/epics.md#Story 3.4`; `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run Detail -- artifact panel by stage`]
8. Given a stage has not yet been reached, when its sidebar item renders, then it is muted and not clickable; when selected panel content is unavailable, then the panel shows `아직 실행되지 않은 스테이지입니다.`. [Source: `_bmad-output/planning-artifacts/epics.md#Story 3.4`; `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#State Patterns`]
9. Given an active SSE connection on `/runs/{id}/progress`, when a `stage_entry` event fires, then the sidebar item state updates in real time without page reload. [Source: `_bmad-output/planning-artifacts/epics.md#Story 3.4`; `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#SSE Progress`]

## Tasks / Subtasks

- [ ] Create Run Detail route and page shell (AC: 1)
  - [ ] Add `/runs/:id` route in the React app using the router pattern established by Story 3.3.
  - [ ] Render persistent top nav with wordmark dashboard navigation, run crumb, run-level status badge, and Langfuse trace link when available.
  - [ ] Use semantic `<nav>`, `<aside>`, and `<main>` and preserve focus-visible behavior from shadcn/Tailwind defaults.
- [ ] Implement stage sidebar behavior (AC: 1, 8, 9)
  - [ ] Reuse `StageSidebarItem` from Story 3.2; do not duplicate status color, active border, muted, or `aria-current` logic.
  - [ ] Render stages in fixed order: `scenario`, `image`, `tts`, `subtitle`, `video`.
  - [ ] Derive reached/clickable state from API run detail, stage artifacts, `current_stage`, and `gate_states`; not-yet-reached stages must be muted and non-interactive.
  - [ ] Selecting a reachable stage changes the active panel and scrolls the main panel to top without pushing browser history.
- [ ] Load run metadata and per-stage artifacts through existing Epic 2 API contracts (AC: 1-9)
  - [ ] Fetch `GET /runs/{id}` for run status, current stage, gate states, and `langfuse_trace_url`.
  - [ ] Fetch `GET /runs/{id}/stages/{stage}/artifacts` when a reachable stage becomes active.
  - [ ] Treat stage artifact data as an API DTO; do not read workspace files directly from the frontend.
  - [ ] Handle 404 for not-yet-reached stage artifacts as the muted empty state, not as a full-page error.
- [ ] Build `ArtifactPanel` variants for all five stages (AC: 2, 3, 5, 6, 7, 8)
  - [ ] Scenario: scrollable Korean prose, max width near 65ch, line-height 1.6.
  - [ ] Image: 2-column image grid, stable aspect ratios, scene labels, image count label.
  - [ ] TTS: sorted per-scene native audio controls with scene index and duration.
  - [ ] Subtitle: monospace SRT scroll area with count label.
  - [ ] Video: full-width native video player plus download link to `GET /runs/{id}/artifact` or the backend-provided URL.
  - [ ] Running and not-yet-reached states use the exact Korean strings from UX where specified.
- [ ] Implement image lightbox (AC: 3, 4)
  - [ ] Use shadcn Dialog for fullscreen lightbox; no nested dialog patterns.
  - [ ] Support click-to-open, left/right keyboard navigation, Esc close, and focus restoration.
  - [ ] Keep image order stable by scene number and image index.
- [ ] Wire SSE progress updates for sidebar state (AC: 9)
  - [ ] Open a hidden `EventSource` to `/runs/{id}/progress` for the run detail page lifecycle.
  - [ ] On `stage_entry`, `stage_exit`, `gate_pending`, and `run_failed`, update local run/stage state in place.
  - [ ] Close the EventSource on unmount and avoid duplicate connections after route changes or React StrictMode re-mounts.
- [ ] Add focused tests and visual verification (AC: 1-9)
  - [ ] Component tests for each panel variant and not-yet-reached state.
  - [ ] Interaction tests for stage selection and lightbox keyboard controls.
  - [ ] SSE/EventSource mock test proving `stage_entry` changes sidebar state without reload.
  - [ ] Build verification with the repo's frontend command, expected to be `npm run build` once Story 3.1 creates `frontend/`.

## Dev Notes

### Epic Context

Epic 3 is the React SPA control surface for the local yt.flow pipeline. Stories 3.1 and 3.2 establish the visual system and shared components; Story 3.3 creates the Dashboard and SCP Picker; Story 3.4 creates the Run Detail review surface; Story 3.5 later adds gate controls, retry, inline editing, and richer SSE client behavior; Story 3.6 adds A/B comparison and accessibility completion. Keep Story 3.4 focused on layout, artifact preview, navigation, lightbox, and live progress sidebar state. [Source: `_bmad-output/planning-artifacts/epics.md#Epic 3: React SPA -- Pipeline Control UI`]

### API Contracts To Consume

- `GET /runs/{id}` returns run metadata including `status`, `current_stage`, `gate_states`, and `langfuse_trace_url`. [Source: `_bmad-output/planning-artifacts/epics.md#Story 2.1`]
- `GET /runs/{id}/stages/{stage}/artifacts` returns intermediate artifacts for completed stages by reading LangGraph state, not the `runs` table. [Source: `_bmad-output/planning-artifacts/epics.md#Story 2.5`; `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-7 -- Single SQLite file; no scenes table; AsyncSqliteSaver`]
- `GET /runs/{id}/artifact` returns the output video as a file download for completed runs. Use this for the video download link unless the stage artifact DTO already provides a canonical download URL. [Source: `_bmad-output/planning-artifacts/epics.md#Story 2.1`]
- `GET /runs/{id}/progress` is SSE and emits `stage_entry`, `stage_exit`, `gate_pending`, and `run_failed`. [Source: `_bmad-output/planning-artifacts/epics.md#Story 2.2`; `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency Conventions`]

### Expected Artifact Shapes

The exact TypeScript DTOs should be taken from the API client/types created by prior Epic 3 stories or generated from the FastAPI contract if present. If no frontend API types exist yet, create narrowly scoped types in the frontend API module and keep them aligned to these semantic shapes:

- `scenario`: readable text content, preferably `{ stage: "scenario", text: string }`.
- `image`: scene-indexed image entries with stable ordering, preferably `{ stage: "image", images: Array<{ scene_num: number; label?: string; url: string; path?: string }> }`.
- `tts`: per-scene audio entries, preferably `{ stage: "tts", audio: Array<{ scene_num: number; duration_sec?: number; url: string; path?: string }> }`.
- `subtitle`: SRT text content, preferably `{ stage: "subtitle", text: string; subtitle_count?: number }`.
- `video`: video URL or path plus optional download URL, preferably `{ stage: "video", url: string; download_url?: string }`.

Do not add frontend behavior that assumes artifact paths live in the SQLModel `runs` table. Artifact paths live in `PipelineState`; the backend stage-artifacts endpoint is the boundary. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-2 -- LangGraph state is the single source of truth`; `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-7 -- Single SQLite file; no scenes table; AsyncSqliteSaver`]

### UX And Visual Guardrails

- This is a workbench, not a landing page. Keep the first viewport as the usable Run Detail screen; no marketing copy, hero layout, decorative gradients, or explanatory panels. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md#Brand & Style`]
- Dark-first Zinc System: background `#1C1C1E`, card `#2C2C2E`, card hover `#323234`, border `rgba(255,255,255,0.07)`, foreground `#F2F2F7`, primary `#0A84FF`. Light mode swaps must continue to work if Story 3.1 implemented them. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md#Colors`]
- Status colors are semantic only: running amber, awaiting purple, approved green, failed red. Do not use purple as decoration; purple means operator action is needed. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md#Colors`]
- UI strings are Korean. Stage tokens remain English monospace: `scenario`, `image`, `tts`, `subtitle`, `video`. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Voice and Tone`]
- Top nav is the only persistent chrome. No persistent app sidebar beyond the Run Detail stage sidebar. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Information Architecture`]
- Run Detail layout requirement from epics says the sidebar is 240px. The static mockup uses `--sidebar-w: 220px`; the epic/UX requirement wins for implementation. [Source: `_bmad-output/planning-artifacts/epics.md#UX Design Requirements`; `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/mockups/run-detail.html`]

### Accessibility Guardrails

- Use `<nav>` for the top navigation, `<aside>` for stage navigation, and `<main>` for the artifact panel.
- Render the stage list as `<ul>`/`<li>` or an equivalent accessible list structure.
- Apply `aria-current="true"` to the active stage item via the shared `StageSidebarItem`.
- Color must never be the only state signal; keep text labels and icons for stage/gate states.
- Use native `<audio controls>` and `<video controls>` for media.
- The image lightbox must close with Esc and support keyboard navigation. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Accessibility Floor`]

### Architecture Compliance

- Frontend talks only to the HTTP/SSE API. It must not import backend Python modules, read `workspace/`, or infer LangGraph checkpoint structure directly.
- FastAPI serves the static React build under `/app`; keep asset paths compatible with that deployment shape. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#Non-Functional Requirements`]
- Dependency direction remains `frontend -> HTTP API -> api -> services -> (pipeline | db) -> domain`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Design Paradigm`]
- SSE is required for real-time progress; do not replace it with WebSockets or polling. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#Non-Functional Requirements`]

### Boundaries For This Story

- Do not implement gate approval/reject calls; those belong to Story 3.5. This story may display existing gate state in the sidebar/footer only where needed for preview context.
- Do not implement retry API calls or inline scenario/subtitle editing; those belong to Story 3.5.
- Do not implement A/B comparison; that belongs to Story 3.6.
- Do not create backend endpoints unless Story 2.5 left a missing contract that blocks this story; prefer adapting the frontend to the already implemented API.
- Do not duplicate shared components from Story 3.2. Reuse `StatusBadge`, `CardRow` where relevant, and especially `StageSidebarItem`.

### Existing Code State At Story Creation

At story creation time, the repository contains planning artifacts and BMAD files only. No `frontend/`, `src/`, or `tests/` source tree is present in the local scan, and no Epic 3 story files exist under `_bmad-output/implementation-artifacts/`. If Stories 3.1-3.3 are implemented before this story is developed, inspect their actual frontend structure and component APIs before editing. The story should follow the implemented local patterns over any speculative filenames in this document.

### Previous Story Intelligence

No previous Epic 3 implementation story file was available when this story was created. Use the Epic 3 sequence as the continuity contract:

- Story 3.1 should provide React 18, Tailwind, shadcn/ui, design tokens, build output to `frontend/dist/`, and FastAPI static serving under `/app`.
- Story 3.2 should provide shared `StatusBadge`, `CardRow`, and `StageSidebarItem` components. This story must reuse them.
- Story 3.3 should provide Dashboard routing, API client conventions, run DTO handling, and navigation from dashboard rows to `/runs/{id}`. This story must extend that routing/API style.

### Git Intelligence Summary

Recent commits are documentation and planning commits only:

- `2390ead` initialized sprint status tracking.
- `4be98ee` added epic breakdown and implementation readiness report.
- `6db2416` added UX design specs and HTML mockups.
- `ca2fb1d` added architecture spine and architecture reviews.
- `b9dc0b0` added the PRD.

No committed application code patterns exist yet in this repository snapshot. The developer should take concrete code conventions from the first implemented Epic 3 stories when they exist.

### Latest Technical Information

- Architecture pins React 18.x. Use the React 18+ root API from `react-dom/client`; `createRoot` is the supported client root API and should be used by the app bootstrap created in Story 3.1. [Source: `https://react.dev/reference/react-dom/client/createRoot`; `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Stack`]
- Tailwind's current Vite guidance uses the first-party `@tailwindcss/vite` plugin and CSS `@import "tailwindcss";`. If Story 3.1 already chose a Tailwind setup, follow it; otherwise use the official Vite plugin path. [Source: `https://tailwindcss.com/docs`; `https://tailwindcss.com/blog/tailwindcss-v4`]
- shadcn/ui's Vite installation path supports Vite projects and components styled with Tailwind. Reuse generated shadcn components from Story 3.1/3.2 instead of hand-rolling Dialog, Skeleton, or focus-ring primitives. [Source: `https://ui.shadcn.com/docs/installation/vite`; `https://ui.shadcn.com/docs/installation/manual`]
- Use `EventSource` for SSE; no extra real-time library is required by the project docs.

### Testing Requirements

- Run the frontend test/build commands established by Story 3.1. If absent, add minimal tests using the chosen React test stack rather than introducing a second test framework.
- Mock HTTP calls for `GET /runs/{id}` and `GET /runs/{id}/stages/{stage}/artifacts`.
- Mock `EventSource` to verify a `stage_entry` event updates the sidebar state without reload.
- Verify media elements use native `controls` attributes.
- Verify semantic elements and `aria-current` are present.
- Add at least one lightbox keyboard test for ArrowRight/ArrowLeft/Esc.

### Project Structure Notes

Expected frontend locations after Story 3.1 may include:

- `frontend/src/main.tsx` or `frontend/src/main.jsx`
- `frontend/src/App.tsx`
- `frontend/src/routes/` or `frontend/src/pages/`
- `frontend/src/components/`
- `frontend/src/lib/` or `frontend/src/api/`

These names are guidance only. Follow the actual structure created by earlier stories. Do not create a parallel routing/component system if one already exists.

### References

- `_bmad-output/planning-artifacts/epics.md#Story 3.4: 런 상세 레이아웃 + 아티팩트 패널`
- `_bmad-output/planning-artifacts/epics.md#Functional Requirements`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F7 -- Web UI (React SPA)`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F5 -- API Interface (FastAPI)`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-7 -- Single SQLite file; no scenes table; AsyncSqliteSaver`
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run Detail -- artifact panel by stage`
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md`
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/mockups/run-detail.html`
- `https://react.dev/reference/react-dom/client/createRoot`
- `https://tailwindcss.com/docs`
- `https://ui.shadcn.com/docs/installation/vite`

## Dev Agent Record

### Agent Model Used

TBD by dev agent.

### Debug Log References

TBD by dev agent.

### Completion Notes List

TBD by dev agent.

### File List

TBD by dev agent.
