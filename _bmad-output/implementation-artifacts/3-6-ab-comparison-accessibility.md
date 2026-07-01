---
baseline_commit: 8486f5cc5843b324dab1ce3abe9727e3f55368c9
---

# Story 3.6: A/B Comparison View and Accessibility Floor

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Jay,
I want the A/B comparison view and full accessibility compliance,
so that I can evaluate prompt variants visually and the tool meets keyboard and screen-reader standards.

## Acceptance Criteria

1. Given a run with a completed `ab_pair_id`, when `/runs/{id}/ab` is loaded, then side-by-side panels show Variant A and Variant B artifacts with LLM-as-judge scores, rule-based scores, and winner indicator. [Source: _bmad-output/planning-artifacts/epics.md#Story-3.6-A/B-비교-뷰-+-접근성-플로어]
2. Given any interactive element, when focused via keyboard Tab, then the shadcn default focus ring is visible. [Source: _bmad-output/planning-artifacts/epics.md#Story-3.6-A/B-비교-뷰-+-접근성-플로어]
3. Given a status badge, when rendered, then badge text and color are both used; color is never the sole indicator. [Source: _bmad-output/planning-artifacts/epics.md#Story-3.6-A/B-비교-뷰-+-접근성-플로어]
4. Given the SCP Picker dialog, when open, then the results use `role="listbox"` and `aria-activedescendant`, and the search input has `aria-label="SCP 검색"`. [Source: _bmad-output/planning-artifacts/epics.md#Story-3.6-A/B-비교-뷰-+-접근성-플로어]
5. Given retry inline confirmation, when it appears, then it has `role="alert"` so screen readers announce it. [Source: _bmad-output/planning-artifacts/epics.md#Story-3.6-A/B-비교-뷰-+-접근성-플로어]
6. Given all UI labels and buttons, when inspected, then all copy is Korean; stage tokens (`scenario`, `image`, `tts`, `subtitle`, `video`) display in English monospace. [Source: _bmad-output/planning-artifacts/epics.md#Story-3.6-A/B-비교-뷰-+-접근성-플로어]

## Tasks / Subtasks

- [x] Add the A/B comparison route and navigation entry point (AC: 1)
  - [x] Add `/runs/:id/ab` to the React router under the existing SPA served at `/app`.
  - [x] Add a Run Detail entry point, preferably an A/B tab or link, without adding persistent global sidebar navigation.
  - [x] Load the selected run with `GET /runs/{id}` and resolve its paired run using the `ab_pair_id` contract. Treat the B-run as the row whose `ab_pair_id` points to the originating A run unless Epic 4 later backfills both directions.
- [x] Build the side-by-side comparison surface (AC: 1, 6)
  - [x] Reuse the stage artifact preview/rendering logic from Story 3.4 for `scenario`, `image`, `tts`, `subtitle`, and `video` instead of creating duplicate artifact renderers.
  - [x] Render two equal-width columns labeled `Variant A` and `Variant B`; preserve stage tokens in English monospace.
  - [x] Show LLM-as-judge axes (`atmosphere`, `narrative_coherence`, `article_fidelity`), rule-based metrics (`scene_count_match`, `subtitle_sync`, `audio_duration_variance`), and winner state from `ab_result` when present.
  - [x] Provide non-success states: missing pair, pair still running, pair failed, evaluation pending, no winner because both variants are below quality floor, and tie.
- [x] Preserve design system and component contracts from Stories 3.1-3.5 (AC: 2, 3, 6)
  - [x] Use existing shadcn/ui components and Zinc tokens; do not introduce a second component library or custom visual language.
  - [x] Use existing `StatusBadge`, `CardRow`, `StageSidebarItem`, artifact panel, retry confirmation, and SCP Picker components where they exist.
  - [x] Keep Korean operator microcopy short and active; do not add explanatory marketing/help text inside the app.
- [x] Implement and verify the accessibility floor across the whole SPA (AC: 2-6)
  - [x] Ensure all buttons, links, inputs, tab triggers, image lightbox controls, dialog controls, retry confirmations, and A/B controls are keyboard reachable and show visible focus rings.
  - [x] Ensure status and gate states use text + icon/shape + color; never rely on color alone.
  - [x] Ensure Run Detail keeps semantic `<nav>`, `<main>`, and `<aside>` structure, and sidebar/SCP results use `<ul>`/`<li>` where applicable.
  - [x] Ensure SCP Picker keeps `role="listbox"`, stable option ids, `aria-activedescendant`, keyboard up/down/Enter behavior, and `aria-label="SCP 검색"`.
  - [x] Ensure retry confirmation uses `role="alert"` and auto-dismiss behavior from Story 3.5 is preserved.
- [x] Add focused tests (AC: 1-6)
  - [x] Add component or route tests for A/B rendering with completed results, pending results, missing pair, failed pair, tie, and no-winner states.
  - [x] Add accessibility tests using Testing Library role/name queries and keyboard navigation checks.
  - [x] Add a Playwright smoke test for `/runs/{id}/ab` if the frontend test harness exists by this story.
  - [x] Add an axe-core accessibility scan in Playwright or component tests if test dependencies are already present or can be added consistently with the frontend setup.

## Dev Notes

### Epic Context

Epic 3 delivers the browser control surface for the pipeline: dashboard, SCP picker, run detail, artifact review, gate approval/rejection, retry, inline editing, Langfuse trace link, and finally A/B comparison plus accessibility compliance. This story is the capstone for Epic 3 and must verify accessibility behavior introduced by Stories 3.1-3.5, not only the new A/B page. [Source: _bmad-output/planning-artifacts/epics.md#Epic-3-React-SPA--Pipeline-Control-UI]

This story covers FR-42 and UX-DR16 through UX-DR18. The A/B evaluation backend itself belongs to Epic 4: Story 4.1 creates Variant B, Story 4.2 scores both runs, and Story 4.3 exposes `ab_result` via `GET /runs/{id}`. Do not implement evaluation scoring in the frontend. The frontend consumes API data and renders clear states while Epic 4 is incomplete or evaluation is pending. [Source: _bmad-output/planning-artifacts/epics.md#Epic-4-A/B-Evaluation]

### Expected API/Data Contract

Use these contracts unless the implemented API has a stricter typed client by the time this story starts:

- `GET /runs/{id}` returns run metadata including `id`, `status`, `current_stage`, `gate_states`, `prompt_variant`, `ab_pair_id`, `langfuse_trace_url`, and, after Epic 4.3, optional `ab_result`. [Source: _bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F5--API-Interface-FastAPI]
- `GET /runs` returns all runs and can be used to locate the paired run when only one side stores `ab_pair_id`. [Source: _bmad-output/planning-artifacts/epics.md#Story-4.1-A/B-실행-생성]
- `GET /runs/{id}/stages/{stage}/artifacts` returns intermediate artifacts by reading LangGraph state, not the `runs` table. Reuse the same frontend artifact fetch/render path from Story 3.4. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-7--Single-SQLite-file-no-scenes-table-AsyncSqliteSaver]
- A/B architecture is two independent runs linked by `ab_pair_id`; do not model variants as branches inside one run. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-6--A/B-testing-is-two-independent-runs-linked-by-ab_pair_id]

Recommended `ab_result` rendering shape for frontend tolerance:

```ts
type AbResult = {
  winner: "A" | "B" | "tie" | null;
  reason?: string;
  llm_scores?: {
    A?: { atmosphere?: number; narrative_coherence?: number; article_fidelity?: number };
    B?: { atmosphere?: number; narrative_coherence?: number; article_fidelity?: number };
  };
  rule_scores?: {
    A?: { scene_count_match?: number; subtitle_sync?: number; audio_duration_variance?: number };
    B?: { scene_count_match?: number; subtitle_sync?: number; audio_duration_variance?: number };
  };
};
```

Render absent fields gracefully as Korean short labels such as `평가 대기`, `결과 없음`, or `승자 없음`; do not crash or show raw JSON.

### UX and Visual Requirements

- Surface: `/runs/{id}/ab`, reached from Run Detail to compare side-by-side variant scoring. [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Information-Architecture]
- Foundation: desktop browser, single operator, local deployment, React SPA served by FastAPI under `/app`; no mobile layout required, design target is wide viewport >= 1024px. [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Foundation]
- Visual identity: Zinc dark system, iOS blue primary actions, semantic status colors only for pipeline state; no gradients, decorative chrome, or marketing/explanatory copy. [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md#Brand--Style]
- Copy: Korean UI strings throughout. Stage tokens remain English monospace because they are technical identifiers. [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Voice-and-Tone]
- Reuse artifact panel content rules: scenario prose, image 2-col grid + lightbox, TTS native audio controls, subtitle monospace scroll area, video native player + download link. [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Run-Detail--artifact-panel-by-stage]

For the A/B page, avoid placing two large floating cards inside another card. Use an unframed route layout with two aligned columns or panes and stable responsive widths. Maintain readable density; this is an operational tool, not a landing page.

### Accessibility Guardrails

- Semantic structure: Run Detail must retain `<nav>`, `<main>`, and `<aside>`; lists should use `<ul>`/`<li>` for stage sidebar and SCP results. [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Accessibility-Floor]
- Focus visible: shadcn default focus ring must appear on every interactive element. Do not override `outline`/ring styles without replacing them with an equally visible focus state. [Source: _bmad-output/planning-artifacts/epics.md#Story-3.6-A/B-비교-뷰-+-접근성-플로어]
- Color not sole indicator: badges require text and color; gate states require left border + text label + icon. [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Accessibility-Floor]
- Native media controls: keep `<audio controls>` and `<video controls>` for keyboard accessibility; do not replace with custom controls in this story. [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Accessibility-Floor]
- SCP Picker: `role="listbox"` and `aria-activedescendant` are required for keyboard navigation. The input label must be `aria-label="SCP 검색"`. [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Accessibility-Floor]
- Retry confirmation: inline confirmation uses `role="alert"`, not a modal. [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Retry-confirmation]

### Architecture Compliance

- Frontend code belongs under `frontend/`; the built output lands in `frontend/dist/` and is served by FastAPI at `/app`. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Structural-Seed]
- Keep dependency direction intact: the frontend talks to API routes over HTTP only. Do not import Python modules or duplicate backend business logic. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Design-Paradigm]
- API routes remain nouns with verb subresources such as `/ab`; do not invent frontend-only API routes for comparison if `GET /runs/{id}` and stage artifact endpoints provide the data. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency-Conventions]
- Treat `gate_states` as a flat dict of string values: `{"scenario": "approved", "image": "pending"}`. Architecture review flagged this as a divergence risk, so frontend parsing should reject array-shaped gate states early or normalize only through a shared API client. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/reviews/review-adversary.md#HIGH-2--gate_states-JSON-blob-format-Run.gate_states-vs-PipelineState.gate_states]

### File Structure Requirements

The repository currently has planning artifacts and story files but no committed `src/` or `frontend/` implementation tree yet. By the time this story is implemented, Stories 3.1-3.5 should have created the frontend structure. Follow the established files from those stories. Expected locations, if no better local pattern exists:

- `frontend/src/routes/RunAbComparisonPage.tsx` or equivalent route module.
- `frontend/src/components/ab/` only for comparison-specific presentation.
- Shared artifact renderers, status badges, sidebar items, SCP Picker, and retry confirmation should remain in their existing shared component locations from Stories 3.2-3.5.
- `frontend/src/api/` or equivalent typed client should own HTTP calls. Keep response shape parsing in one place rather than spreading `fetch()` calls through components.
- Tests should sit beside the established frontend test pattern (`*.test.tsx`, Playwright specs, or repo convention from Story 3.1).

Do not create a second router, second styling system, second status badge, second artifact renderer, or custom dialog/listbox primitive when shadcn/Radix-based components already exist.

### Previous Story Intelligence

Stories 3.1-3.5 now exist as ready-for-dev story files in `_bmad-output/implementation-artifacts/`. Use them as the immediate implementation contract before starting this story:

- Story 3.1 provides React 18, Tailwind, shadcn/ui, Zinc tokens, build output in `frontend/dist/`, and `/app` static serving.
- Story 3.2 provides `StatusBadge`, `CardRow`, and `StageSidebarItem`; the A/B page must reuse status semantics and focus styling.
- Story 3.3 provides Dashboard and SCP Picker; this story audits its listbox and input ARIA behavior.
- Story 3.4 provides Run Detail layout and artifact renderers; the A/B page must reuse those renderers side by side.
- Story 3.5 provides gate controls, retry confirmation, inline editor, SSE client, and Langfuse trace link; this story audits focus, `role="alert"`, and Korean copy.

Important carry-forward details from Story 3.5:

- The retry confirmation contract is `이 스테이지를 다시 실행합니까? 확인 / 취소`, inline below the button, with `role="alert"` and 5-second auto-dismiss.
- The SSE client should be isolated in a hook, close `EventSource` during cleanup, and treat `run_failed` as the authoritative failure event rather than `EventSource.onerror`.
- Gate/retry/edit API calls should live behind a typed frontend API client and surface FastAPI `detail` errors as Korean inline copy.

### Git Intelligence

Recent commits are documentation/setup only: sprint status, epics/readiness report, UX specs/mockups, architecture reviews, and PRD. There is no committed implementation code to preserve yet. Current untracked implementation story files for Epic 1 and Story 2.1 appear to be user/workflow output; do not modify or revert them while implementing this story.

### Latest Technical Information

The architecture has already incorporated tech-currency review updates: React 18.x, latest stable shadcn/ui + Tailwind, FastAPI 0.115.x, SQLModel 0.0.38, LangGraph 1.2.x, `langgraph-checkpoint-sqlite` as a separate package, and langfuse Python SDK 4.x. [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Stack]

For accessibility implementation:

- shadcn/ui components are built on Radix primitives; preserve their ARIA/focus behavior rather than replacing primitives with custom div-click handlers.
- Tailwind focus styling should use existing shadcn ring utilities and `focus-visible` behavior.
- Testing Library should prefer role/name queries so tests enforce accessible names.
- Playwright plus axe-core is the recommended automated smoke check if the repo already has or accepts that test dependency by this story. Automated scans do not replace keyboard walkthroughs for Tab order, lightbox controls, listbox active descendant, or native media control behavior.

## Testing Requirements

- Run the frontend unit/component test suite established by Story 3.1.
- Run `npm run build` in `frontend/`; build must still output `frontend/dist/`.
- Add tests for:
  - `/runs/{id}/ab` happy path with completed A/B pair and scores.
  - Missing `ab_pair_id`, pair still running, pair failed, evaluation pending, `winner: "tie"`, and `winner: null` with below-floor reason.
  - Korean labels and English monospace stage tokens.
  - Visible status text for every badge state.
  - SCP Picker `aria-label`, `role="listbox"`, `aria-activedescendant`, keyboard up/down/Enter behavior.
  - Retry confirmation `role="alert"`.
  - Keyboard Tab reaches all interactive controls with visible focus.
- If Playwright exists, add a smoke spec that loads `/runs/{id}/ab` with mocked API responses and verifies the route, heading/labels, two variant columns, winner indicator, and no obvious axe violations.

## Project Structure Notes

- No implementation tree exists at story creation time, so file paths above are expected targets, not verified current files.
- This story intentionally depends on Stories 3.1-3.5 for frontend scaffold and reusable components.
- Epic 4 owns backend A/B evaluation. This story must render pending/unavailable states until Epic 4.3's `ab_result` is available.
- The implementation must leave the existing dashboard and run detail workflows intact. Accessibility fixes should be applied to existing shared components, not patched locally only on the A/B route.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story-3.6-A/B-비교-뷰-+-접근성-플로어]
- [Source: _bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F7--Web-UI-React-SPA]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-6--A/B-testing-is-two-independent-runs-linked-by-ab_pair_id]
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Structural-Seed]
- [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Accessibility-Floor]
- [Source: _bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md#Brand--Style]
- [Source: _bmad-output/planning-artifacts/implementation-readiness-report-2026-06-30.md#UX-Alignment-Assessment]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- `npm test -- RunAbComparisonPage.test.tsx` - RED failed before page implementation, then passed after route/page implementation.
- `npm test -- App.test.tsx RunDetail.test.tsx RunAbComparisonPage.test.tsx` - route and Run Detail entry point tests passed.
- `npm test -- ArtifactPanel.test.tsx` - retry alert and editor guard tests passed after test timing cleanup.
- `npm test` - full frontend suite passed: 14 files, 75 tests.
- `npm run build` - TypeScript and Vite production build passed.

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Implemented `/runs/:id/ab` route with selected-run fetch, pair resolution through `ab_pair_id`, and B-run lookup via `GET /runs`.
- Added side-by-side A/B comparison panes reusing the shared artifact panel for all pipeline stages, with score tables, winner/tie/no-winner rendering, and missing/running/failed/pending states.
- Added Run Detail A/B entry point and preserved semantic `nav`/`aside`/`main` layout, focus-visible rings, Korean operator copy, and English monospace stage tokens.
- Tightened accessibility/test coverage for status badges, stage controls, retry confirmation alert behavior, SCP Picker role/name contracts, route rendering, and A/B comparison states.
- Playwright and axe-core harness/dependencies were not present in the frontend setup, so no new dependency was added; coverage is provided through Vitest and Testing Library role/name assertions.

### File List

- `_bmad-output/implementation-artifacts/3-6-ab-comparison-accessibility.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `frontend/src/App.tsx`
- `frontend/src/App.test.tsx`
- `frontend/src/components/ArtifactPanel.test.tsx`
- `frontend/src/components/common/status-badge.tsx`
- `frontend/src/lib/types.ts`
- `frontend/src/pages/RunAbComparisonPage.tsx`
- `frontend/src/pages/RunAbComparisonPage.test.tsx`
- `frontend/src/pages/RunDetail.tsx`
- `frontend/src/pages/RunDetail.test.tsx`

### Change Log

- 2026-07-01: Added A/B comparison route, side-by-side comparison UI, accessibility verification updates, focused route/component tests, and marked story ready for review.
