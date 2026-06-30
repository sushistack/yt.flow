# Story 3.3: Dashboard + SCP Picker Dialog

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Jay,
I want the Dashboard run list and SCP Picker dialog working end-to-end,
so that I can see all my runs at a glance and start a new run by selecting an SCP.

## Acceptance Criteria

1. Given runs exist in the API, when the dashboard loads at `/`, then runs are listed sorted by `started_at` desc with `awaiting_approval` runs floating to the top (FR-37, UX-DR7).
2. Given no runs exist, when the dashboard loads, then centered copy displays "실행 없음. 새 실행을 시작하세요." with a primary CTA (UX-DR7).
3. Given the API is unreachable, when the dashboard loads, then a top banner displays "서버에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인하세요." (UX-DR7).
4. Given "+ 새 실행" is clicked, when the SCP Picker Dialog opens, then the search input is focused; the list is loaded from `GET /scps` sorted by `rating` desc; rows show SCP ID (mono), nickname, object_class, and rating (tabular-nums, right-aligned) (UX-DR8).
5. Given the user types `"096"` with 200 ms debounce, when filtering completes, then only SCPs whose numeric ID includes `"096"` appear (UX-DR8).
6. Given the user navigates with Up/Down and presses Enter, when SCP-096 is confirmed, then `POST /runs` is called; the dialog closes; a new run row appears at the top with "실행 중" badge (UX-DR8).
7. Given an SCP list with 2000 items, when the dialog renders, then the list is virtualized and off-screen rows are not present as DOM nodes (UX-DR8).

## Tasks / Subtasks

- [ ] Implement dashboard API client contracts (AC: 1, 3, 4, 6)
  - [ ] Add or extend a frontend API module for `GET /runs`, `GET /scps`, and `POST /runs`.
  - [ ] Keep response parsing centralized; components should not assemble URLs or parse response blobs ad hoc.
  - [ ] Treat `gate_states` from `Run` as an API projection string if Epic 2 returns it that way; parse once into a typed frontend shape.
- [ ] Build Dashboard surface at `/` (AC: 1, 2, 3)
  - [ ] Render the persistent top nav: wordmark `yt.flow` and "+ 새 실행" CTA, 52px height.
  - [ ] Render four loading skeleton rows while `GET /runs` is pending.
  - [ ] Render API-down top banner with the exact Korean copy in AC 3.
  - [ ] Render empty state with the exact Korean copy in AC 2 and primary CTA.
  - [ ] Render runs as full-width `CardRow` list items; whole row click navigates to `/runs/{id}`.
  - [ ] Do not add nested row action buttons; any "열기" affordance must not create a second interactive target inside the row.
- [ ] Implement run sorting and row display (AC: 1)
  - [ ] Sort `awaiting_approval` rows ahead of all others, then sort each group by `started_at` desc.
  - [ ] Show SCP ID in monospace, run status badge, current stage token in monospace, and timestamp in tabular nums.
  - [ ] Map run statuses to Korean badges: `running` -> "실행 중", `awaiting_approval` -> "승인 대기", `complete` -> "완료", `failed` -> "실패".
  - [ ] Use semantic status badge colors from the Zinc token set; do not use status colors for decorative accents.
- [ ] Build SCP Picker Dialog (AC: 4, 5, 6, 7)
  - [ ] Use shadcn `Dialog`; input must focus every time the dialog opens.
  - [ ] Fetch `GET /scps` on first open or via a shared query cache; do not read `data/scps.json` from the frontend.
  - [ ] Default-sort SCPs by numeric `rating` desc before filtering.
  - [ ] Render row fields exactly: SCP ID (mono), nickname, object_class, rating right-aligned with tabular nums.
  - [ ] Search must debounce 200 ms and match numeric ID (`096`), full ID (`SCP-096`), and nickname/descriptive tag text.
  - [ ] Exclude meta/admin tags from nickname matching/display if the API includes tags: `_licensebox`, `scp`, `_cc`, `featured`, `illustrated`, `rewrite`, `co-authored`, `audio`.
  - [ ] Selecting an SCP posts `{"scp_id": "...", "scp_text": "..."}` when `scp_text` is available from the SCP API shape; if `GET /scps` only returns summary fields, fail visibly and document the API gap instead of sending fake text.
- [ ] Implement virtualization and keyboard accessibility (AC: 5, 6, 7)
  - [ ] Use a proven virtualizer such as `@tanstack/react-virtual`; do not hand-roll windowing math.
  - [ ] Keep DOM focus on the search input or listbox while using `aria-activedescendant` for the active option.
  - [ ] Results container must expose `role="listbox"` and each visible row `role="option"`.
  - [ ] Search input must have `aria-label="SCP 검색"`.
  - [ ] Up/Down updates the active option; Enter confirms it; pointer click confirms it.
  - [ ] When keyboard navigation moves the active option, scroll the virtualizer so the active row is visible.
- [ ] Wire successful run creation (AC: 6)
  - [ ] On successful `POST /runs`, close the dialog, clear the query, and place the returned run at the top with a "실행 중" badge.
  - [ ] Prefer invalidating/refetching `GET /runs` after optimistic insertion so server ordering wins.
  - [ ] On `POST /runs` failure, keep the dialog open and show an inline error near the picker list.
- [ ] Add tests and verification (AC: 1-7)
  - [ ] Unit-test run sorting: `awaiting_approval` first, then `started_at` desc.
  - [ ] Unit-test SCP search: numeric ID, full ID, nickname/tag normalization, meta tag exclusion, debounce behavior.
  - [ ] Component-test empty, loading skeleton, API-down banner, and list states.
  - [ ] Component-test dialog focus on open, keyboard Up/Down/Enter, `aria-label`, `role=listbox`, `aria-activedescendant`, and virtualized DOM count.
  - [ ] Integration-test `POST /runs` success and failure using the repo's frontend test runner.
  - [ ] Build verification: `npm run build` or the package manager command established by Story 3.1.

## Dev Notes

### Scope Boundary

This story owns the Dashboard and SCP Picker only. Do not implement Run Detail, artifact panels, gate controls, retry, inline editor, SSE progress, image lightbox, A/B comparison, FastAPI route internals, or Prompt Hub/LangGraph behavior here. Those belong to Stories 3.4, 3.5, 3.6, Epic 2, and Epic 1.

Story 3.3 depends on Story 3.1 for `frontend/`, React 18, Tailwind, shadcn/ui, Zinc tokens, and `/app` static serving. It depends on Story 3.2 for `StatusBadge` and `CardRow`. If those story files are not present in `_bmad-output/implementation-artifacts/`, create only the minimum missing pieces needed for this story and keep them compatible with the Story 3.1/3.2 ACs; do not redesign the visual system.

### Architecture Guardrails

- Frontend is a React SPA served by FastAPI static build under `/app`; no separate web server in production. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F7-Web-UI-React-SPA`]
- Frontend talks to API over HTTP only. It must not import Python modules, read SQLite, read LangGraph checkpoints, or read `data/scps.json` directly. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Design-Paradigm`]
- `GET /runs` returns run metadata with `status`, `current_stage`, and `gate_states`; dashboard is a read-only projection except for creating a new run. [Source: `_bmad-output/planning-artifacts/epics.md#Story-2.1-FastAPI-app-SQLModel-basic-Run-CRUD`]
- `GET /scps` returns `id`, `nickname`, `object_class`, and `rating` from `app.state.scps`; no per-request file I/O is expected server-side. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency-Conventions`]
- `POST /runs` accepts `scp_id`, `scp_text`, and optional `extra`; v1 is SCP-specific and `extra` is reserved. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F5-API-Interface-FastAPI`]

### UI/UX Requirements

- Use the Zinc design system from Story 3.1: background `#1C1C1E`, card `#2C2C2E`, hover `#323234`, border `rgba(255,255,255,0.07)`, foreground `#F2F2F7`, muted foreground `#8E8E93`, primary `#0A84FF`. Light mode swaps must remain intact. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md#Colors`]
- Dashboard layout is top nav plus scrollable single-column run list. No marketing hero, explanatory panel, persistent sidebar, decorative gradients, or nested cards. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Information-Architecture`]
- `CardRow` behavior: full-row click navigates; hover uses card-hover; hairline bottom border; no nested action buttons. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md#Components`]
- `StatusBadge` must include text and color; color alone is never the status indicator. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Accessibility-Floor`]
- Korean UI strings throughout. Stage tokens (`scenario`, `image`, `tts`, `subtitle`, `video`) and SCP IDs use monospace. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Voice-and-Tone`]
- Mockup reference for spacing and composition: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/mockups/dashboard.html`.

### Data Contracts

Expected frontend types should align to the Epic 2 API projection:

```ts
type RunStatus = "running" | "awaiting_approval" | "complete" | "failed";

type Run = {
  id: string;
  scp_id: string;
  status: RunStatus;
  current_stage: "scenario" | "image" | "tts" | "subtitle" | "video" | null;
  gate_states: string | Record<string, string> | null;
  prompt_variant?: string | null;
  ab_pair_id?: string | null;
  error?: string | null;
  started_at: string;
  updated_at: string;
  langfuse_trace_url?: string | null;
};

type ScpEntry = {
  id: string;           // "SCP-096"
  nickname: string;     // display text from API or derived descriptive tag
  object_class: string; // "Euclid", etc.
  rating: number;
  scp_text?: string;    // required by POST /runs unless API layer provides lookup by scp_id
  tags?: string[];
};
```

Important API gap to verify before implementation: Story 2.5's `GET /scps` AC only promises summary fields, while `POST /runs` requires `scp_text`. The dev agent must inspect the implemented API. If `scp_text` is unavailable, either extend `GET /scps` or add a detail endpoint in the API story path before wiring real run creation. Do not send placeholder SCP text.

### Search Rules

Normalize the query and searchable text by lowercasing and treating spaces/hyphens as equivalent. Examples:

- `"096"` matches `SCP-096`.
- `"SCP-096"` matches `SCP-096`.
- `"shy guy"` matches nickname/tag `shy-guy`.
- `"plague-doctor"` matches nickname/tag `plague doctor`.

Default empty-query list is all SCPs sorted by `rating` desc. Filtering must preserve rating-desc order among matches unless the implementation explicitly adds deterministic relevance scoring that still keeps exact ID matches first.

### Latest Technical Notes

- React 18 apps should mount a single app root with `createRoot(domNode).render(<App />)`. [Source: https://react.dev/reference/react-dom/client/createRoot]
- For shadcn/ui on Vite, use the official Vite installation path and generated component conventions from Story 3.1; avoid mixing another UI framework. [Source: https://ui.shadcn.com/docs/installation/vite]
- For 2000-row virtualization, `@tanstack/react-virtual` provides `useVirtualizer` for element-scoped virtual lists. Use it instead of custom scroll math. [Source: https://tanstack.com/virtual/latest/docs/framework/react/react-virtual]
- WAI-ARIA listbox guidance supports `aria-activedescendant` for composite keyboard focus. If the listbox scrolls, code must ensure the active option remains visible. [Source: https://www.w3.org/WAI/ARIA/apg/patterns/listbox/]

### File Structure Requirements

Expected files depend on what Story 3.1/3.2 create. Use existing project names if they differ:

- `frontend/src/main.tsx` or existing app entry (update only if routing setup is needed)
- `frontend/src/App.tsx` or route config (update to render Dashboard at `/`)
- `frontend/src/pages/Dashboard.tsx` or equivalent (new/update)
- `frontend/src/components/SCPPickerDialog.tsx` (new)
- `frontend/src/components/RunRow.tsx` (new or reuse `CardRow`)
- `frontend/src/components/StatusBadge.tsx` (reuse from Story 3.2; update only if missing statuses)
- `frontend/src/lib/api.ts` (new/update centralized HTTP client)
- `frontend/src/lib/runSorting.ts` and `frontend/src/lib/scpSearch.ts` if extracting pure helpers improves tests
- `frontend/src/types.ts` or domain-specific type module (new/update)
- Tests beside components or under `frontend/src/__tests__/`, matching the Story 3.1 test setup

Do not create a second frontend root, second design token file, or duplicate component library. Extend the existing frontend substrate.

### Testing Requirements

Use the test tooling established by Story 3.1. If it is not established, prefer Vitest + React Testing Library for unit/component tests and keep Playwright optional for browser-level smoke checks.

Minimum tests:

- `sortRuns()` puts `awaiting_approval` first and sorts by `started_at` desc inside groups.
- `filterScps()` matches numeric ID, full ID, nickname/tag, hyphen/space normalization, and excludes meta tags.
- Dashboard shows skeletons, empty state, API error banner, and populated rows.
- SCP Picker focuses input on open, exposes listbox roles, updates `aria-activedescendant`, supports Up/Down/Enter, and keeps active virtual row visible.
- Virtualization test asserts rendered option count is far below the full 2000-item dataset.
- Run creation success calls `POST /runs`, closes dialog, clears search, and updates/refetches run list.
- Run creation failure leaves dialog open and shows inline error.

### Previous Story Intelligence

No Epic 3 story files exist yet in `_bmad-output/implementation-artifacts/` at story creation time. Treat `3.1` and `3.2` as prerequisites from `epics.md`, not as implemented facts. Recent git history is planning-only documentation; no committed `frontend/`, `src/`, `tests/`, `pyproject.toml`, or package manager files were detected during analysis. If implementation starts before Epic 2 APIs exist, use mocked API responses only in tests/dev fixtures and document that the real end-to-end flow is blocked by Epic 2.

Recent commits:

```text
2390ead chore: init sprint status tracking (24 stories across 4 epics)
4be98ee docs: add epic breakdown and implementation readiness report
6db2416 docs: add UX design specs and HTML mockups
ca2fb1d docs: add architecture design and review docs
b9dc0b0 docs: add PRD for yt.flow
```

### References

- Story source: `_bmad-output/planning-artifacts/epics.md#Story-3.3-Dashboard-SCP-Picker-Dialog`
- PRD F7 and API requirements: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F7-Web-UI-React-SPA`
- Architecture spine: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`
- UX design: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md`
- UX behavior: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md`
- Dashboard mockup: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/mockups/dashboard.html`

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.

### File List
