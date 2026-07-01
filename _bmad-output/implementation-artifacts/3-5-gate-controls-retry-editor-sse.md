---
baseline_commit: 8486f5cc5843b324dab1ce3abe9727e3f55368c9
---

# Story 3.5: Gate Controls, Retry, Inline Editor & SSE Client

Status: in-progress

<!-- Completion note: Ultimate context engine analysis completed - comprehensive developer guide created. -->

## Story

As Jay,
I want stage approval controls, retry, and inline text editing wired to the API,
so that I can fully control pipeline progression from the browser.

## Acceptance Criteria

1. Given stage `gate_state === "pending"`, when the artifact panel footer renders, then "승인" (primary) and "반려" (outline destructive) buttons are visible. (FR-40, UX-DR12)
2. Given "승인" or "반려" is clicked, when the API call is in flight, then both buttons are disabled with a spinner; on success buttons are replaced by a state label; on API failure buttons re-enable with an inline error below. (UX-DR12)
3. Given stage `gate_state === "approved"` or `"rejected"`, when the panel header renders, then a "재시도" outline button is visible. (FR-41, UX-DR13)
4. Given "재시도" is clicked, when inline confirmation appears below the button, then it shows "이 스테이지를 다시 실행합니까? 확인 / 취소" with `role="alert"` and auto-dismisses after 5 seconds of no action. (UX-DR13)
5. Given a `scenario` or `subtitle` stage panel, when "편집" is clicked, then a textarea replaces the read view; "저장" calls `PATCH /runs/{id}/stages/{stage}/artifact` and returns to read mode with updated text; "취소" reverts without saving. (FR-44, UX-DR14)
6. Given unsaved edits in the panel, when the user navigates to another stage, then `window.confirm("저장하지 않은 변경사항이 있습니다. 계속하시겠습니까?")` fires. (UX-DR14)
7. Given a Langfuse trace link, when clicked, then it opens in a new browser tab. (FR-43)
8. Given an active Run Detail page, when `/runs/{id}/progress` emits `stage_entry`, `stage_exit`, `gate_pending`, or `run_failed`, then the sidebar and active artifact panel update without page reload. (FR-38, FR-32, UX-DR15)

## Tasks / Subtasks

- [x] Confirm frontend prerequisites from Stories 3.1-3.4 before editing runtime UI. (AC: 1-8)
  - [x] Reuse the existing React app under `frontend/`; do not create a second frontend root.
  - [x] Reuse shared components from Story 3.2: `StatusBadge`, `StageSidebarItem`, `Button`, spinner/loading affordance, and existing shadcn/ui styling.
  - [x] Reuse the Run Detail layout and artifact panel structure from Story 3.4; this story wires behavior into that surface.
- [x] Add or update API client functions for stage control. (AC: 2, 4, 5)
  - [x] Implement `approveGate(runId, stage)` and `rejectGate(runId, stage)` using `POST /runs/{id}/stages/{stage}/gate` with body `{"action":"approve"}` or `{"action":"reject"}`.
  - [x] Implement `retryStage(runId, stage)` using `POST /runs/{id}/stages/{stage}/retry`.
  - [x] Implement `patchStageArtifact(runId, stage, text)` using `PATCH /runs/{id}/stages/{stage}/artifact`; allow only `scenario` and `subtitle` in the UI.
  - [x] Preserve FastAPI error shape: read `detail` when present and show Korean inline error copy.
- [x] Implement gate controls in the artifact panel footer. (AC: 1, 2)
  - [x] Render gate controls only when selected stage `gate_state === "pending"`.
  - [x] Use Korean labels exactly: `승인`, `반려`.
  - [x] Disable both buttons and show spinner while the mutation is pending.
  - [x] On success, set local stage state to the returned/expected state label immediately, then let SSE confirmation reconcile.
  - [x] On failure, re-enable buttons and render an inline error below the controls.
- [x] Implement retry affordance in the panel header. (AC: 3, 4)
  - [x] Render `재시도` only for stages whose gate state is `approved`, `rejected`, or failed/error state.
  - [x] Show inline confirmation below the button, not a Dialog.
  - [x] Confirmation content must have `role="alert"` and buttons `확인` / `취소`.
  - [x] Auto-dismiss confirmation after 5 seconds of no action; clear the timer on unmount or when the selected stage changes.
  - [x] On confirm, call retry endpoint, reset panel/sidebar state to running, and wait for SSE to move it back to pending or failed.
- [x] Implement inline text editor for `scenario` and `subtitle`. (AC: 5, 6)
  - [x] Show `편집` only on `scenario` and `subtitle` stages once text artifact content exists.
  - [x] Replace read view with a textarea in edit mode; keep scenario prose readable and subtitle text monospace.
  - [x] `저장` calls PATCH and updates the read-mode content from the API response or submitted value.
  - [x] `취소` exits edit mode and restores the original text without saving.
  - [x] If text is dirty and the user selects another stage, call `window.confirm("저장하지 않은 변경사항이 있습니다. 계속하시겠습니까?")`; cancel navigation when it returns `false`.
  - [x] Saving must not approve or advance the stage; gate approval remains a separate action.
- [x] Implement or harden the Run Detail SSE client. (AC: 8)
  - [x] Create or update a focused hook such as `useRunProgress(runId, handlers)` inside the frontend source.
  - [x] Open `new EventSource("/runs/{id}/progress")` only while Run Detail is mounted for that run.
  - [x] Register named listeners for `stage_entry`, `stage_exit`, `gate_pending`, and `run_failed`; parse JSON `event.data`.
  - [x] Update only local run/stage UI state; do not show toast notifications for progress.
  - [x] Close the EventSource in `useEffect` cleanup to avoid duplicate streams, including React Strict Mode's development setup/cleanup cycle.
  - [x] Treat `EventSource.onerror` as connection-state feedback; do not mark a run failed unless a `run_failed` event arrives.
- [x] Wire Langfuse trace link in Run Detail. (AC: 7)
  - [x] Use `langfuse_trace_url` from `GET /runs/{id}`.
  - [x] Open in a new tab with `target="_blank"` and `rel="noreferrer"`.
  - [x] Disable or hide the link if no trace URL exists yet.
- [x] Add tests. (AC: 1-8)
  - [x] Component tests for gate controls visibility, pending disabled state, success label, and inline API error.
  - [x] Component tests for retry confirmation, `role="alert"`, confirm/cancel behavior, and 5-second auto-dismiss with fake timers.
  - [x] Component tests for scenario/subtitle edit mode, PATCH call, cancel behavior, and dirty navigation `window.confirm`.
  - [x] Hook/page test for SSE event handling using a mock `EventSource`; assert `close()` is called on unmount and run id change.
  - [x] Accessibility checks for focusable buttons, semantic `role="alert"`, and no color-only status indication.
- [ ] Verify locally. (AC: 1-8)
  - [x] Run frontend unit tests.
  - [x] Run frontend build.
  - [ ] If the API stories are implemented, run FastAPI and manually exercise gate, retry, edit, SSE, and trace link flows from `/runs/{id}`.

## Dev Notes

### Scope Boundary

This story is a UI wiring story for the Run Detail page. It should not create backend endpoints; it consumes the Epic 2 API:

- `POST /runs/{id}/stages/{stage}/gate` from Story 2.3.
- `POST /runs/{id}/stages/{stage}/retry` from Story 2.4.
- `PATCH /runs/{id}/stages/{stage}/artifact` from Story 2.4.
- `GET /runs/{id}/progress` from Story 2.2.
- `GET /runs/{id}` from Story 2.1 for `langfuse_trace_url`.
- `GET /runs/{id}/stages/{stage}/artifacts` from Story 2.5 / Story 3.4 for displayed artifact content.

Do not implement A/B comparison in this story; that is Story 3.6. Do not add WebSockets; PRD and UX specify SSE.

### Epic 3 Context

Epic 3 delivers the React SPA control surface: dashboard, SCP picker, Run Detail, artifact review, stage approval, retry, inline editing, trace link, and later A/B comparison. Story 3.5 depends on Story 3.4's Run Detail layout and artifact panels. If Story 3.5 is implemented before 3.1-3.4, first create the frontend foundation and Run Detail primitives or stop and implement the prerequisite stories. [Source: `_bmad-output/planning-artifacts/epics.md#Epic 3: React SPA — Pipeline Control UI`]

### Current Project State Observed During Story Creation

- Repository scan found planning artifacts and story files, but no committed `frontend/`, `src/`, `package.json`, or tests yet.
- No Epic 3 story file exists yet, so there is no previous Epic 3 Dev Agent Record to reuse.
- `sprint-status.yaml` shows Epic 3 and Stories 3.1-3.4 still in `backlog` at creation time; this story file was explicitly requested out of sequence.
- Recent commits are documentation/tracking only; no runtime frontend code pattern supersedes the architecture spine.

### Architecture Guardrails

- Frontend talks to FastAPI over HTTP only; React SPA is served by FastAPI static build under `/app`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Design-Paradigm`]
- API routes own HTTP request validation, but `services/` owns LangGraph calls and SSE fan-out. The UI must not assume DB writes happen before LangGraph confirmation; after gate/retry calls, reconcile with SSE. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-4 — services/ owns DB sync and SSE fan-out`]
- `gate_states` is a flat JSON dict with stage literals as keys and string values: `pending`, `approved`, `rejected`, or `n/a`. Preserve stage literals exactly: `scenario`, `image`, `tts`, `subtitle`, `video`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency-Conventions`]
- Stage retry must reuse the original run/checkpoint thread; the frontend should treat retry as "same run, selected stage returns to running", not as a new run. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-9 — Stage retry rewinds via graph.update_state() + re-invoke`]
- Local-only, single-operator app: no auth or multi-user locking required. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#Non-Functional Requirements`]

### UX Guardrails

- Use Korean UI strings throughout. Stage tokens remain English monospace identifiers. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Voice-and-Tone`]
- Gate controls live in the artifact panel footer and appear only for `gate_state === "pending"`. Labels: `승인`, `반려`. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Component-Patterns`]
- Retry confirmation is inline below the button, not a modal. It uses `role="alert"` and auto-dismisses after 5 seconds. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Interaction-Primitives`]
- SSE updates are encoded in the sidebar and panel state only. Do not add progress toasts or push notifications. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Component-Patterns`]
- Accessibility floor: focus ring on all interactive elements; gate state must not be color-only; retry confirmation must be announced with `role="alert"`; active stage sidebar item uses `aria-current="true"`. [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Accessibility-Floor`]

### Expected Frontend Data Contracts

Use actual types created by earlier Epic 3 stories if they exist. If not, define them once in the frontend API/types layer and share them.

```ts
type StageName = "scenario" | "image" | "tts" | "subtitle" | "video";
type GateState = "pending" | "approved" | "rejected" | "n/a" | "failed";
type RunStatus = "running" | "awaiting_approval" | "complete" | "failed";

interface RunRead {
  id: string;
  scp_id: string;
  status: RunStatus;
  current_stage: StageName | null;
  gate_states: string | Record<StageName, GateState> | null;
  langfuse_trace_url?: string | null;
  error?: string | null;
}

interface ProgressEventData {
  run_id: string;
  stage?: StageName;
  error?: string;
}
```

If the backend returns `gate_states` as a JSON blob string from SQLModel, parse it once in the API client. UI components should receive normalized objects, not raw JSON strings.

### API Interaction Details

- Gate approve: `POST /runs/{id}/stages/{stage}/gate` with `{"action":"approve"}`.
- Gate reject: `POST /runs/{id}/stages/{stage}/gate` with `{"action":"reject"}`.
- Retry: `POST /runs/{id}/stages/{stage}/retry` with no required body unless the backend story defines one.
- Text edit: `PATCH /runs/{id}/stages/{stage}/artifact` with edited text body. Accept whichever body shape Story 2.4 implements; if undecided, prefer a JSON object such as `{"text":"..."}` for clarity and test it against the backend.
- Backend success for gate/retry may return `202 Accepted`. Do not assume the returned body contains final stage state; SSE is the confirmation channel.
- Backend conflict cases such as retrying a pending/not-yet-run stage should show inline Korean error and leave current UI state unchanged.

### SSE Client Guidance

- Implement SSE as a small custom hook so Strict Mode setup/cleanup behavior is isolated and tested.
- React `useEffect` is the correct place to synchronize with an external connection; return cleanup that disconnects the old connection before reconnecting or unmounting. [Source: React `useEffect` docs: https://react.dev/reference/react/useEffect]
- `EventSource` keeps a persistent server connection open until `.close()` is called. Always call `close()` in cleanup. [Source: MDN EventSource: https://developer.mozilla.org/en-US/docs/Web/API/EventSource]
- Named backend events should be handled with `addEventListener("stage_entry", ...)` etc.; generic `message` is not enough because the backend contract names four event types. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Consistency-Conventions`]
- Browsers may retry dropped SSE connections automatically. Do not display a failure state purely from `error`; only `run_failed` carries authoritative pipeline failure. [Source: MDN Using server-sent events: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events]

### Library / Framework Notes

- Architecture pins React 18.x. Do not upgrade to React 19 just because current shadcn/ui supports it. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Stack`]
- shadcn/ui's current Vite docs support Vite setup and current Tailwind flows, but existing React 18 + Tailwind projects remain valid; follow the Story 3.1 setup rather than reinitializing the UI stack. [Source: shadcn/ui Vite docs: https://ui.shadcn.com/docs/installation/vite; Tailwind v4 notes: https://ui.shadcn.com/docs/tailwind-v4]
- If Story 3.3 introduced TanStack Query, use `useMutation` for gate/retry/edit server side-effects; its success/error callbacks fit the disabled/spinner/error lifecycle. [Source: TanStack Query `useMutation`: https://tanstack.com/query/latest/docs/framework/react/reference/useMutation]
- If no data library exists, a small typed fetch wrapper is enough; do not add a new dependency solely for this story.

### Expected Files to Update

Exact paths depend on Stories 3.1-3.4. Keep changes inside the established `frontend/` tree. Likely files:

- `frontend/src/pages/RunDetail.tsx` or equivalent route component: wire gate/retry/edit/SSE behaviors.
- `frontend/src/components/ArtifactPanel.tsx`: render footer controls, header retry, editor mode.
- `frontend/src/components/GateControls.tsx`: create only if it reduces duplication.
- `frontend/src/components/InlineTextEditor.tsx`: create only if scenario/subtitle panels would otherwise duplicate edit lifecycle.
- `frontend/src/hooks/useRunProgress.ts`: SSE lifecycle and event dispatch.
- `frontend/src/lib/api.ts` or equivalent: add gate/retry/artifact PATCH functions.
- `frontend/src/types.ts` or equivalent: normalize stage/gate/run/event types.
- `frontend/src/__tests__/...` or `frontend/tests/...`: add component/hook tests.

Do not add backend files for this story unless earlier stories are missing a tiny type/client fixture needed for frontend tests.

### Previous Story Intelligence

No Story 3.4 file exists at story creation time. The dev agent must inspect the actual frontend code produced by Stories 3.1-3.4 before implementing this story and adapt to those local patterns. Do not assume component names from this document if code has already established better names.

Story 2.1's context establishes that API contracts should keep route handlers thin and service-driven, and that the project may initially be scaffold-only. For this story, that translates to: keep frontend API calls behind a typed client and do not couple UI state directly to backend internals.

### Git Intelligence

Recent commits are planning/setup only:

- `2390ead` initialized sprint status tracking.
- `4be98ee` added epic breakdown and implementation readiness report.
- `6db2416` added UX design specs and HTML mockups.
- `ca2fb1d` added architecture design and review docs.
- `b9dc0b0` added the PRD.

There are no implementation commits yet, so the dev agent must follow the architecture/UX docs and any code created by earlier stories in the current working tree.

### Testing Requirements

- Use the test runner and component test stack established in Story 3.1. If none exists, add Vitest + React Testing Library only as part of the frontend foundation story, not ad hoc here.
- Mock `fetch` or the project's API client for gate/retry/edit tests.
- Mock `window.EventSource` for SSE tests:
  - capture constructor URL,
  - expose `addEventListener`,
  - dispatch named events with JSON `data`,
  - assert `close()` is called on cleanup.
- Use fake timers for retry confirmation auto-dismiss.
- Mock `window.confirm` for dirty navigation tests and restore it after each test.
- Test UI copy in Korean and stage tokens in English.

### Out of Scope

- Backend implementation of gate/retry/edit/SSE endpoints.
- Static app serving under `/app` unless Story 3.1 left a small integration gap.
- Dashboard run list sorting or SCP picker behavior.
- A/B comparison screen.
- Authentication, CORS hardening, or multi-user conflict handling.
- Prompt editing in Langfuse UI.

## Project Structure Notes

Expected code root after prerequisites:

```text
frontend/
  src/
    components/
    hooks/
    lib/
    pages/
    types.ts
```

Current repository inspection found no `frontend/` tree yet. Implement Stories 3.1-3.4 first if those files are still absent when dev work starts.

## References

- `_bmad-output/planning-artifacts/epics.md#Story 3.5: 게이트 컨트롤 + 재시도 + 인라인 에디터 + SSE 클라이언트`
- `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F7 — Web UI (React SPA)`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-4 — services/ owns DB sync and SSE fan-out`
- `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-9 — Stage retry rewinds via graph.update_state() + re-invoke`
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md`
- `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md`
- React `useEffect`: https://react.dev/reference/react/useEffect
- MDN EventSource: https://developer.mozilla.org/en-US/docs/Web/API/EventSource
- MDN Using server-sent events: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
- shadcn/ui Vite docs: https://ui.shadcn.com/docs/installation/vite
- shadcn/ui Tailwind v4 notes: https://ui.shadcn.com/docs/tailwind-v4
- TanStack Query `useMutation`: https://tanstack.com/query/latest/docs/framework/react/reference/useMutation

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- `npm test` - 75 frontend tests passed.
- `npm run build` - TypeScript and Vite production build passed.
- `uv run pytest tests/api/test_gate.py tests/api/test_stages.py tests/api/test_sse.py tests/api/test_stage_artifacts.py` - 46 related API contract tests passed.

### Completion Notes List

- Reused the existing React app, Run Detail layout, ArtifactPanel, StatusBadge, and StageSidebarItem surfaces.
- Added stage control API client functions for gate approval/rejection, retry, and text artifact patching; preserved FastAPI `detail` errors for inline Korean copy.
- Implemented pending gate footer controls, retry header confirmation with `role="alert"` and 5-second auto-dismiss, and separate scenario/subtitle inline editing.
- Extracted Run Detail SSE handling into `useRunProgress`, with named event listeners, cleanup on unmount/run change, local state updates, and non-authoritative connection-error handling.
- Preserved Langfuse trace link behavior with new-tab `target="_blank"` and `rel="noreferrer"`.
- Verified backend stage-control contract through API tests; browser manual flow is still pending because no local DB/run existed to exercise `/runs/{id}` live.

### File List

- frontend/src/components/ArtifactPanel.tsx
- frontend/src/components/ArtifactPanel.test.tsx
- frontend/src/components/common/stage-sidebar-item.tsx
- frontend/src/hooks/useRunProgress.ts
- frontend/src/lib/api.ts
- frontend/src/lib/types.ts
- frontend/src/pages/RunAbComparisonPage.tsx
- frontend/src/pages/RunDetail.tsx
- frontend/src/pages/RunDetail.test.tsx

### Change Log

- 2026-07-01: Implemented gate controls, retry confirmation, inline artifact editor, Run Detail SSE hook wiring, and coverage for Story 3.5.
