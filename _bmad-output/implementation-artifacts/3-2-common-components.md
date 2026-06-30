# Story 3.2: Common Components (StatusBadge, CardRow, StageSidebarItem)

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Jay,
I want the core shared components built and spec-verified,
so that every screen renders consistently without per-screen duplication.

## Acceptance Criteria

1. Given `<StatusBadge status="running" />`, when rendered, then amber foreground on amber-tinted background; 11px/500; 6px border-radius; badge text is present and status is not communicated by color alone. (UX-DR4, UX-DR17)
2. Given `<CardRow>` item on hover, when pointer enters, then background transitions to `#323234`; hairline `rgba(255,255,255,0.07)` bottom border is visible. (UX-DR5)
3. Given `<StageSidebarItem stage="image" gateState="pending" />`, when rendered, then it has a 2px `#BF5AF2` left border and a text/icon indicator for the pending gate. (UX-DR6, UX-DR17)
4. Given `<StageSidebarItem stage="scenario" active={true} />`, when rendered, then it has a 2px `#0A84FF` left border and `aria-current="true"`. (UX-DR6, UX-DR17)
5. Given a stage not yet reached, when `<StageSidebarItem>` renders, then the item is muted, not clickable, and cannot trigger navigation. (UX-DR6)

## Tasks / Subtasks

- [ ] Confirm Story 3.1 frontend foundation is present before implementation (AC: 1-5)
  - [ ] Verify `frontend/` exists with React 18, TypeScript, Vite, Tailwind, shadcn/ui, `components.json`, and global Zinc tokens.
  - [ ] If `frontend/` is still absent, implement Story 3.1 first or keep this story blocked; do not create a second competing frontend setup from this story.
- [ ] Define shared UI contracts and types (AC: 1-5)
  - [ ] Create or extend `frontend/src/lib/types.ts` with shared literals: `RunStatus`, `GateState`, and `StageName`.
  - [ ] Use exact stage literals: `scenario`, `image`, `tts`, `subtitle`, `video`.
  - [ ] Use exact run statuses expected by the API/UI: `running`, `awaiting_approval`, `complete`, `failed`.
  - [ ] Use exact gate states: `pending`, `approved`, `rejected`, `n/a`.
- [ ] Implement `StatusBadge` (AC: 1)
  - [ ] Create `frontend/src/components/common/status-badge.tsx`.
  - [ ] Map statuses to Korean labels: `running` -> `실행 중`, `awaiting_approval` -> `승인 대기`, `complete` -> `완료`, `failed` -> `실패`.
  - [ ] Include a visible status glyph or text prefix in addition to color; color alone is not sufficient.
  - [ ] Apply token-backed classes for foreground/background pairs: running amber, awaiting purple, complete/approved green, failed red.
  - [ ] Use 11px/500 text, 6px radius, and `3px 8px` padding.
- [ ] Implement `CardRow` (AC: 2)
  - [ ] Create `frontend/src/components/common/card-row.tsx`.
  - [ ] Render a row-like interactive container that can be used as a full-row dashboard navigation target.
  - [ ] Use card background, card-hover on hover, and hairline bottom border from design tokens.
  - [ ] Support `asChild` or a typed wrapper pattern if shadcn/Radix composition is already present; otherwise expose a simple `button`/`div` variant without introducing new dependencies.
  - [ ] Do not embed nested action buttons inside this component; dashboard row actions belong to later Story 3.3.
- [ ] Implement `StageSidebarItem` (AC: 3, 4, 5)
  - [ ] Create `frontend/src/components/common/stage-sidebar-item.tsx`.
  - [ ] Render semantic list-item-friendly content for use inside a future `<ul>/<li>` sidebar.
  - [ ] Display the stage token in English monospace.
  - [ ] Active state: 2px primary blue left border, card background, `aria-current="true"`.
  - [ ] Pending gate state: 2px awaiting purple left border and visible pending text/icon.
  - [ ] Approved/rejected states: visible text/icon and semantic color pairing, without using color as the only signal.
  - [ ] Not-yet-reached state: muted styling, `aria-disabled="true"`, and no click handler.
- [ ] Export common components from a stable barrel (AC: 1-5)
  - [ ] Create or update `frontend/src/components/common/index.ts`.
  - [ ] Export component props types where useful for later dashboard/run-detail stories.
- [ ] Add component tests and accessibility checks (AC: 1-5)
  - [ ] Use the frontend test setup established by Story 3.1; if absent, add Vitest + React Testing Library in the frontend package only.
  - [ ] Test `StatusBadge` label, class/token mapping, and non-color status text.
  - [ ] Test `CardRow` hover class and border class.
  - [ ] Test `StageSidebarItem` active `aria-current`, pending visual/text state, and disabled/not-clickable behavior.
  - [ ] Prefer assertions on roles, text, attributes, and stable class names; avoid fragile pixel snapshot tests.
- [ ] Verify locally (AC: 1-5)
  - [ ] Run `npm run build` from `frontend/`.
  - [ ] Run the frontend test command from Story 3.1, typically `npm test` or `npm run test`.

## Dev Notes

### Scope Boundary

This story creates the shared component primitives for Epic 3. It must not implement Dashboard data loading, SCP Picker Dialog, Run Detail layout, artifact panels, gate API calls, retry behavior, inline editing, SSE, or A/B comparison. Those belong to Stories 3.3-3.6.

This story is blocked by Story 3.1 implementation output if the React project, Tailwind setup, shadcn/ui config, and Zinc design tokens are not already present. At story creation time, Story 3.1 exists as a ready-for-dev story file, but this repository still has no `frontend/` directory and no `package.json`; implementers must not create a parallel frontend architecture here. [Source: repository inspection; `_bmad-output/implementation-artifacts/3-1-zinc-design-tokens-shadcn-tailwind.md`; `_bmad-output/planning-artifacts/epics.md#Story-3.1-Zinc-design-tokens--shadcnui--Tailwind`]

### Architecture Guardrails

- FastAPI serves the React static build under `/app`; no separate production web server. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#Non-Functional-Requirements`]
- Frontend communicates only through HTTP/SSE APIs. It must not import Python modules or duplicate pipeline business logic. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Design-Paradigm`]
- Keep shared UI code under `frontend/src/components/common/` and shared literals/helpers under `frontend/src/lib/`. This keeps later Epic 3 screens from redefining component-specific copies.
- Stage names are technical identifiers and must remain English monospace in UI: `scenario`, `image`, `tts`, `subtitle`, `video`. Korean labels are used for operator-facing status strings. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Voice-and-Tone`]

### UX Requirements

- Zinc System is a restrained tool UI, not a marketing surface: dark-first, system blue for primary actions, semantic colors only for state. No gradients or decorative chrome. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md#Brand--Style`]
- `StatusBadge`: foreground from `status-*`, background from `status-*-bg`, 11px/500, 6px radius, `3px 8px` padding. Text must be present. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md#Components`]
- `CardRow`: card background, card-hover on hover, hairline bottom border, full-row click target, no nested action buttons. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Interaction-Primitives`]
- `StageSidebarItem`: active uses 2px primary left border, awaiting uses 2px purple left border, unreached is muted and not clickable. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md#Components`]
- Accessibility floor: status requires text plus color, focus ring on all interactive elements, `aria-current="true"` for the active stage, and semantic future usage inside `<aside>` and `<ul>/<li>`. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Accessibility-Floor`]

### Component API Guidance

Recommended component signatures:

```tsx
type RunStatus = "running" | "awaiting_approval" | "complete" | "failed";
type GateState = "pending" | "approved" | "rejected" | "n/a";
type StageName = "scenario" | "image" | "tts" | "subtitle" | "video";

type StatusBadgeProps = {
  status: RunStatus | GateState;
  className?: string;
};

type CardRowProps = {
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
  disabled?: boolean;
};

type StageSidebarItemProps = {
  stage: StageName;
  active?: boolean;
  gateState?: GateState;
  reached?: boolean;
  onSelect?: (stage: StageName) => void;
  className?: string;
};
```

The exact prop names may change to match existing Story 3.1 conventions, but the behavior must remain stable for Stories 3.3-3.5.

### Latest Technical Notes

- Architecture pins React 18.x. As of 2026-07-01, npm reports the latest React 18 release as `18.3.1`, while the current latest React major is `19.2.7`. Use React 18.x unless the architecture is deliberately updated. [Source: `npm view react@18 version --json`; `npm view react version`]
- Tailwind CSS latest is `4.3.2` by npm lookup. Tailwind v4 uses CSS theme variables via `@theme`; regular CSS variables remain appropriate for shadcn-compatible tokens that should not generate utilities. [Source: `npm view tailwindcss version`; `https://tailwindcss.com/docs/theme`]
- shadcn/ui supports Tailwind v4, including `@theme` / `@theme inline`; current docs note updated components with `data-slot` attributes. Do not hand-copy old Tailwind v3 shadcn patterns if Story 3.1 initialized v4. [Source: `https://ui.shadcn.com/docs/tailwind-v4`]
- For Vite React projects, shadcn's current guide installs `tailwindcss` and `@tailwindcss/vite`, uses `@/*` path aliases, and expects Tailwind v4 setup. [Source: `https://ui.shadcn.com/docs/installation/vite`]
- `components.json` for Tailwind v4 should leave the Tailwind config path blank; the CSS entry should point at the global Tailwind import file. [Source: `https://ui.shadcn.com/docs/components-json`]

### Previous Story Intelligence

Story 3.1 is ready-for-dev and defines the frontend foundation this story depends on. Its key implementation guidance:

- Bootstrap `frontend/` as a Vite React 18 TypeScript SPA.
- Pin React to `18.3.1` rather than upgrading to React 19.
- Use Tailwind v4 Vite integration (`tailwindcss` + `@tailwindcss/vite`) unless dependency conflicts force the official shadcn fallback.
- Add shadcn `components.json`, `@/` alias, `src/lib/utils.ts`, and `src/globals.css`.
- Keep Dashboard, SCP Picker, Run Detail, gate controls, retry, editor, SSE, and A/B UI out of Story 3.1; those remain downstream responsibilities.

At story creation time, no frontend files exist in the repository, so Story 3.2 implementers should consume the files created by Story 3.1 if it has been dev-completed before them; otherwise implement Story 3.1 first. [Source: `_bmad-output/implementation-artifacts/3-1-zinc-design-tokens-shadcn-tailwind.md`]

Story 3.4 also exists as ready-for-dev and explicitly requires reuse of `StageSidebarItem` from Story 3.2. Keep the component API stable enough for that later Run Detail page to consume. [Source: `_bmad-output/implementation-artifacts/3-4-run-detail-artifact-panel.md`]

Recent git history contains documentation/planning commits only:

```text
2390ead chore: init sprint status tracking (24 stories across 4 epics)
4be98ee docs: add epic breakdown and implementation readiness report
6db2416 docs: add UX design specs and HTML mockups
ca2fb1d docs: add architecture design and review docs
b9dc0b0 docs: add PRD for yt.flow
```

This means component conventions are not yet established in committed code. The dev agent should follow Story 3.1's resulting structure if it is implemented before this story; otherwise stop and implement Story 3.1 first.

### Project Structure Notes

Expected files for this story after Story 3.1 exists:

- `frontend/src/components/common/status-badge.tsx`
- `frontend/src/components/common/card-row.tsx`
- `frontend/src/components/common/stage-sidebar-item.tsx`
- `frontend/src/components/common/index.ts`
- `frontend/src/lib/types.ts` or the existing Story 3.1 shared types file
- Component tests under the frontend test convention, for example `frontend/src/components/common/*.test.tsx`

Detected variance at story creation: `frontend/` is absent. This is expected only if Story 3.1 has not been implemented yet.

### References

- Epic 3 story source: `_bmad-output/planning-artifacts/epics.md#Story-3.2-공통-컴포넌트-StatusBadge-CardRow-StageSidebarItem`
- PRD F7 Web UI: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F7--Web-UI-React-SPA`
- Architecture Spine: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`
- UX Design: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md`
- UX Experience: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md`

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.

### File List
