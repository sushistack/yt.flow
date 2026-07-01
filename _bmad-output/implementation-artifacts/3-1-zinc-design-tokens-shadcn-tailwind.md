---
baseline_commit: 04634e41ebcaedeab0c5a9879219fcda2971e665
---

# Story 3.1: Zinc Design Tokens + shadcn/ui + Tailwind

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Jay,
I want the React project bootstrapped with Zinc System design tokens and shadcn/ui configured,
so that all subsequent UI components use a consistent, spec-compliant visual foundation.

## Acceptance Criteria

1. Given `frontend/` initialized with React 18, Tailwind CSS, and shadcn/ui, when `npm run build` runs from `frontend/`, then the build succeeds and output lands in `frontend/dist/`; FastAPI serves the static SPA at `/app`.
2. Given `DESIGN.md` dark-mode color tokens, when CSS custom properties are defined in `globals.css`, then `--background: #1C1C1E`, `--card: #2C2C2E`, and `--primary: #0A84FF` are present; `prefers-color-scheme: light` triggers `--background: #F2F2F7`, `--card: #FFFFFF`, and `--primary: #007AFF`.
3. Given status color token pairs, when inspecting CSS, then all four semantic pairs exist: running `#FF9F0A` / `rgba(255,159,10,0.18)`, awaiting `#BF5AF2` / `rgba(191,90,242,0.18)`, approved `#30D158` / `rgba(48,209,88,0.18)`, failed `#FF453A` / `rgba(255,69,58,0.18)`.
4. Given typography tokens in `globals.css`, when body text renders, then body font is `system-ui, -apple-system` at `13px`, weight `400`, line-height `1.4`; the Tailwind `font-mono` class resolves to `'Courier New', Consolas, Menlo`.

## Tasks / Subtasks

- [x] Bootstrap `frontend/` as a Vite React 18 TypeScript SPA. (AC: 1)
  - [x] Create `frontend/package.json`, Vite config, TypeScript config, `index.html`, and `src/` entry files.
  - [x] Pin React to latest React 18 patch (`18.3.1`) instead of upgrading to React 19, because architecture explicitly requires React 18.x.
  - [x] Configure build output to `frontend/dist/`.
- [x] Install and configure Tailwind CSS and shadcn/ui for Vite. (AC: 1, 2, 3, 4)
  - [x] Use Tailwind v4 Vite integration (`tailwindcss` + `@tailwindcss/vite`) unless dependency conflicts force the official shadcn fallback path.
  - [x] Add shadcn `components.json`, `@/` alias, `src/lib/utils.ts`, and baseline styles in `src/globals.css`.
  - [x] Keep shadcn defaults for unlisted components; only apply the yt.flow brand-layer token delta.
- [x] Implement Zinc System CSS variables and Tailwind mappings. (AC: 2, 3, 4)
  - [x] Define dark-first CSS variables for ground, surfaces, border, foreground, muted foreground, subtle foreground, primary, and primary foreground.
  - [x] Add `@media (prefers-color-scheme: light)` swaps for light background, card, border, foreground, muted foreground, and primary.
  - [x] Define semantic status foreground/background variables and ensure they are not used as decorative accent tokens.
  - [x] Configure `font-sans` and `font-mono` so SCP IDs and stage tokens can use the required monospace stack in later stories.
- [x] Add a minimal foundation screen only for build and visual smoke testing. (AC: 1, 2, 3, 4)
  - [x] Render a small app shell using Korean UI copy and technical stage tokens in monospace.
  - [x] Avoid implementing Dashboard, SCP Picker, Run Detail, gate controls, retry, editor, SSE, or A/B UI in this story; those belong to stories 3.2-3.6.
- [x] Serve `frontend/dist/` from FastAPI at `/app`. (AC: 1)
  - [x] If Epic 2 / Story 2.1 API files exist, update `src/yt_flow/api/main.py` to mount the static build at `/app`.
  - [x] If the FastAPI app file does not exist yet, create the static-mount implementation in the architecture-approved location and avoid importing pipeline code directly.
  - [x] Ensure SPA fallback behavior does not break API routes.
- [x] Verify the foundation. (AC: 1, 2, 3, 4)
  - [x] Run `npm install` and `npm run build` from `frontend/`.
  - [x] Inspect generated CSS/source for required token values.
  - [x] If FastAPI exists, start the app and verify `/app` serves the built SPA.

## Dev Notes

### Source Context

- Epic 3 creates the browser surface for operating the pipeline end-to-end: run start, artifact review, stage approval, retry, inline editing, SSE progress, and A/B comparison. This story is only the UI foundation for that work. [Source: `_bmad-output/planning-artifacts/epics.md` §Epic 3]
- F7 requires a React SPA served by FastAPI as a static build; there is no separate web server and no authentication because the tool is local-only for a single operator. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md` §F7, §Non-Functional Requirements]
- Architecture structural seed reserves `frontend/` for the React SPA and `frontend/dist/` for the built output served at `/app`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` §Structural Seed]

### Current Repository State

- No `frontend/`, root `package.json`, `vite.config.*`, `tailwind.config.*`, `components.json`, or `src/` application files are currently present. Treat this as a greenfield frontend bootstrap.
- Existing implementation artifacts for Epic 1 and Story 2.1 are untracked in git. Do not rewrite them. If API source files are still absent during implementation, create only the minimum FastAPI static mount needed for AC1 in the architecture-approved path.
- `project-context.md` was not found in the workspace during story creation, so rely on PRD, architecture, UX, epics, and this story for implementation rules.

### Architecture Compliance

- Preserve layer direction: `api -> services -> (pipeline | db) -> domain`; frontend talks to `api` over HTTP only. Do not import Python modules into frontend code, and do not let API routes call pipeline code directly. [Source: `ARCHITECTURE-SPINE.md` §AD-1]
- FastAPI static mount belongs in `src/yt_flow/api/main.py`. The API may mount `frontend/dist` under `/app`, but API endpoints must remain available outside `/app`. [Source: `ARCHITECTURE-SPINE.md` §Structural Seed]
- UI technology is React 18.x, shadcn/ui, and Tailwind. Do not choose Next.js, Remix, WebSockets, a separate Node production server, or React 19 for this story. [Source: `ARCHITECTURE-SPINE.md` §Stack; `prd.md` §Non-Functional Requirements]
- No auth, multi-user state, or mobile layout is required. Minimum design target is desktop browser width >= 1024px. [Source: `EXPERIENCE.md` §Foundation]

### Design Token Requirements

- Dark mode is primary: `background #1C1C1E`, `card #2C2C2E`, `card-hover #323234`, `border rgba(255,255,255,0.07)`, `foreground #F2F2F7`, `muted-foreground #8E8E93`, `subtle-foreground #48484A`, `primary #0A84FF`, `primary-foreground #FFFFFF`. [Source: `DESIGN.md` frontmatter and §Colors]
- Light mode must use system preference: `background #F2F2F7`, `card #FFFFFF`, `border rgba(0,0,0,0.09)`, `foreground #1C1C1E`, `muted-foreground #6C6C70`, `primary #007AFF`. [Source: `DESIGN.md` frontmatter and §Colors]
- Status colors are semantic only: running, awaiting, approved, failed. Do not use purple/green/red/amber as section accents or brand decoration. [Source: `DESIGN.md` §Colors, §Do's and Don'ts]
- Typography: body stack is `system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`; body text is `13px`, `400`, `line-height: 1.4`; mono stack is `'Courier New', Consolas, Menlo, monospace` and is reserved for SCP IDs and stage tokens. [Source: `DESIGN.md` §Typography]
- The broader developer instruction says not to scale font size with viewport width and letter spacing must be `0`, but the approved UX spec requires body letter-spacing `-0.01em`. For this project story, preserve the approved UX spec in `DESIGN.md` for body text; keep labels at `letter-spacing: 0`.

### Library / Framework Requirements

- npm reports latest React as `19.2.7`, but this project architecture pins React 18.x. Use React `18.3.1`, the latest React 18 patch available from npm during story creation. [Source: React npm package; npm `react` and `react@18` queries on 2026-07-01]
- Vite latest observed version is `8.1.1`; `@vitejs/plugin-react` latest observed version is `6.0.3`. Use Vite with React TypeScript template conventions, adjusting only where React 18 compatibility requires it. [Source: Vite official guide; npm queries on 2026-07-01]
- Tailwind latest observed version is `4.3.2`; official Tailwind Vite docs use `@tailwindcss/vite` and CSS `@import "tailwindcss";`. Prefer that path. [Source: Tailwind official Vite docs; npm queries on 2026-07-01]
- shadcn latest observed CLI/package version is `4.12.0`; official shadcn Vite docs support Vite setup and existing-project configuration. Use `npx shadcn@latest init` or equivalent generated files, then apply yt.flow tokens. [Source: shadcn/ui Vite docs; npm query on 2026-07-01]

### File Structure Requirements

Expected new or updated files:

- `frontend/package.json`
- `frontend/index.html`
- `frontend/vite.config.ts`
- `frontend/tsconfig.json`
- `frontend/tsconfig.node.json` or equivalent Vite TypeScript config files
- `frontend/components.json`
- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `frontend/src/globals.css`
- `frontend/src/lib/utils.ts`
- `src/yt_flow/api/main.py` only if needed to satisfy `/app` static serving

Keep component-heavy work out of this story. Story 3.2 owns `StatusBadge`, `CardRow`, and `StageSidebarItem`; Story 3.3 owns Dashboard and SCP Picker; Story 3.4 owns Run Detail and artifacts; Story 3.5 owns gate/retry/editor/SSE; Story 3.6 owns A/B and accessibility completion.

### Testing Requirements

- Build verification is mandatory: `cd frontend && npm run build`.
- Token verification is mandatory: inspect `frontend/src/globals.css` and any Tailwind theme mapping for exact hex/rgba values from AC2 and AC3.
- Font verification is mandatory: ensure rendered body uses the sans stack and `font-mono` resolves to the required mono stack.
- Static serving verification is required when FastAPI source exists: built files must be reachable at `/app`, and API routes must not be shadowed by the static mount.
- Do not claim this story implements downstream UI behavior. The foundation screen is only a smoke target for tokens and build output.

### Git Intelligence

Recent commits are planning/artifact commits only:

- `2390ead` initialized sprint status tracking.
- `4be98ee` added epic breakdown and implementation readiness report.
- `6db2416` added UX design specs and HTML mockups.
- `ca2fb1d` added architecture design and review docs.
- `b9dc0b0` added the PRD.

There is no committed frontend implementation pattern to reuse yet; follow the architecture and UX docs directly.

### References

- `_bmad-output/planning-artifacts/epics.md` §Epic 3 / Story 3.1
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md` §F7, §Non-Functional Requirements
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md` §AD-1, §Stack, §Structural Seed
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md` §Colors, §Typography, §Components, §Do's and Don'ts
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md` §Foundation, §Information Architecture, §Voice and Tone
- React versions: https://react.dev/versions
- React npm package: https://www.npmjs.com/package/react
- Vite guide: https://vite.dev/guide/
- Tailwind Vite install: https://tailwindcss.com/docs/installation/using-vite
- shadcn/ui Vite install: https://ui.shadcn.com/docs/installation/vite

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m]

### Debug Log References

- `cd frontend && npm run build` → success; `dist/index.html` + `dist/assets/*` emitted (vite 8.1.2).
- Built-CSS token grep: all AC2/AC3 hex values present; status `-bg` rgba(...,0.18) values losslessly minified to hex8 (`#ff9f0a2e`, `0x2E/255 ≈ 0.18`) — source `globals.css` retains exact rgba forms (the AC-mandated inspection target).
- `pytest -q` → 266 passed, 1 skipped (no regressions). New `tests/api/test_static_spa.py` → 2 passed.
- Live check: `GET /app/` → 200 serving built `index.html`; `GET /app/assets/<hash>.js` → 200 (base `/app/` gives correct asset URLs); `/scps` API route unshadowed.

### Completion Notes List

- Bootstrapped `frontend/` as a hand-written Vite + React 18.3.1 + TypeScript SPA (React pinned to 18.x per architecture; Vite/plugin-react resolved 8.x/6.x).
- Tailwind v4 CSS-first integration via `@tailwindcss/vite` + `@import "tailwindcss"`; no `tailwind.config.js` needed. shadcn plumbing added (`components.json`, `@/` alias, `src/lib/utils.ts` `cn`) so stories 3.2–3.6 can `npx shadcn add` cleanly — no shadcn components implemented here.
- Zinc tokens in `src/globals.css`: dark-first `:root`, light swaps under `@media (prefers-color-scheme: light)`, semantic status tier as a separate group (not accent), sans/mono stacks and radius tokens mapped into Tailwind via `@theme inline`.
- Body set to `system-ui` 13px/400/1.4, `-0.01em` (approved UX spec preserved over the generic no-letter-spacing instruction, per Dev Notes).
- `App.tsx` is a minimal foundation smoke screen only (Korean copy, mono SCP ID + stage tokens, 4 status badges, primary CTA). No Dashboard/SCP Picker/Run Detail/gate/retry/editor/SSE/A/B UI.
- FastAPI `/app` static mount via `mount_static_spa()` in `src/yt_flow/api/main.py`; guarded on `dist` existence so the API still boots without a build, and scoped to `/app` so API routes are never shadowed (AD-1 respected: api does not import pipeline).

### File List

- `frontend/package.json` (new)
- `frontend/index.html` (new)
- `frontend/vite.config.ts` (new)
- `frontend/tsconfig.json` (new)
- `frontend/tsconfig.app.json` (new)
- `frontend/tsconfig.node.json` (new)
- `frontend/components.json` (new)
- `frontend/.gitignore` (new)
- `frontend/src/main.tsx` (new)
- `frontend/src/App.tsx` (new)
- `frontend/src/globals.css` (new)
- `frontend/src/lib/utils.ts` (new)
- `frontend/src/vite-env.d.ts` (new)
- `src/yt_flow/api/main.py` (modified — added `mount_static_spa()` + `/app` mount)
- `tests/api/test_static_spa.py` (new)

### Review Findings (2026-07-01)

Reviewed jointly with Story 3.2 (Blind Hunter + Edge Case Hunter + Acceptance Auditor). All AC2/AC3 exact hex/rgba token values, AC4 typography, and the AC1 `/app` static mount verified compliant.

- [x] [Review][Defer] Light-mode `@media` block omits `--card-hover`, `--subtle-foreground`, `--primary-foreground`, and the `--status-*` swaps, so those fall through to dark values on a light OS [frontend/src/globals.css:26-36] — deferred: DESIGN.md/AC2 enumerate only the six swaps that ARE implemented and dark mode is the primary target; correct light-mode values for the remaining tokens are not in the design spec, so fixing needs a design decision. Tracked in `deferred-work.md`.

## Change Log

| Date | Change |
|------|--------|
| 2026-07-01 | Implemented Story 3.1: bootstrapped Vite/React 18/Tailwind v4/shadcn frontend foundation, Zinc design tokens in globals.css, and FastAPI `/app` static SPA mount. All ACs verified; 266 tests + 2 new pass. Status → review. |
| 2026-07-01 | Code review (joint with 3.2): no AC violations. One light-mode token-swap gap deferred (spec-intent, dark is primary). Status → done. |
