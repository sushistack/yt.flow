# Story 3.8: 컨트롤 UI 결함 수리 (Control UI Defect Fixes)

Status: ready-for-dev

<!-- Context: E2E baseline 2026-07-06 (run 272b05a4). Root causes below were investigated
     and verified against the actual code during story creation — D9's live-session gap was
     reproduced with a failing page-level Vitest test (details in Dev Notes). -->

## Story

As Jay,
I want the four control-UI defects found in the 2026-07-06 Playwright E2E baseline fixed (dead retry button on failed runs, broken SPA deep links, stale run status after gate approval, wrong subtitle count),
so that the browser control surface tells the truth and every recovery action works without falling back to raw API calls.

## Acceptance Criteria

**AC1 — D9 (major, frontend): retry works on a failed stage, including on a live page**

1. **Given** the Run Detail page is open while a run executes, **when** a `run_failed` SSE event arrives carrying `stage` (e.g. `{"run_id":"...","stage":"image","error":"..."}`), **then** that stage's gate state flips to `failed` in the sidebar and panel header (실패 badge) and the "재시도" button renders in the panel header — without a page reload.
2. **Given** the failed stage's panel (artifacts GET may 404 → empty state "아직 실행되지 않은 스테이지입니다."), **when** the user clicks "재시도" and then "확인", **then** exactly one `POST /runs/{id}/stages/{stage}/retry` request fires and the stage resets to running via the existing `onRetryStart` path.
3. **Given** a failed run loaded fresh (DB `gate_states` already contains `"failed"` for the stage), **when** the user clicks "재시도" → "확인", **then** the retry POST fires (regression guard — this path already works today and must not break).

**AC2 — D4 (minor, backend): SPA deep links serve index.html**

4. **Given** a built SPA in `frontend/dist`, **when** the browser requests `GET /app/runs/{id}` (or any `/app/*` path that is not an existing file), **then** the server responds 200 with `index.html` content (`text/html`) instead of `{"detail":"Not Found"}`, and the client router renders the Run Detail page.
5. **Given** real static assets (e.g. `/app/assets/*.js`) and non-`/app` API routes, **when** requested, **then** they behave exactly as before (assets served as files; unknown API routes still return JSON 404).

**AC3 — D7 (minor, backend): run status is truthful after gate approval resumes the graph**

6. **Given** a run in `awaiting_approval` paused at a gate, **when** `POST /runs/{id}/stages/{stage}/gate` with `{"action":"approve"}` returns 202 and the graph resumes, **then** `GET /runs/{id}` returns `status="running"` for the duration of the next stage's execution — not the stale `awaiting_approval` (parity with the retry path, which already reports `running` correctly).
7. **Given** a rejected non-scenario gate (stage loops back and re-runs), **when** the resume starts, **then** `GET /runs/{id}` likewise reports `status="running"`; terminal writes by `_consume` (awaiting/failed/complete) still land at the next barrier as today.

**AC4 — D14 (minor, frontend): subtitle count matches rendered content**

8. **Given** a subtitle stage whose artifacts are `.ass` files (Story 7.5 kinetic subtitles — `Dialogue:` event lines, no `-->` arrows), **when** the panel renders, **then** the count line shows the number of dialogue events (e.g. "자막 42개"), not "자막 0개".
9. **Given** legacy/fallback `.srt` content (`-->` cue arrows), **when** the panel renders, **then** the cue count remains correct (both formats counted).

## Tasks / Subtasks

- [ ] **Task 1 [frontend]: Fix D9 — wire `run_failed` stage into client gate state (AC: 1, 2, 3)**
  - [ ] In `frontend/src/pages/RunDetail.tsx:96-98`, change `onRunFailed` to consume the event's `stage` field: set `status: "failed"`, `error`, `current_stage: stage`, and merge `gate_states[stage] = "failed"` (reuse `setStageGateState` or extend it — note `setStageGateState` currently forces `status` only for `"pending"`, so a small dedicated updater is fine).
  - [ ] Confirm the handler payload type already carries `stage` (`useRunProgress.ts` `ProgressEventData` has `stage?` — no hook change needed).
  - [ ] Add the page-level regression test from Dev Notes ("Red test for D9") to `frontend/src/pages/RunDetail.test.tsx` using its existing `MockEventSource` pattern (lines 6-22): emit `run_failed` with `stage:"image"` on a live run → assert 실패 badge + "재시도" button appear → click 재시도 → 확인 → assert `fetch` called with `POST /runs/r1/stages/image/retry`.
  - [ ] Add the fresh-load regression test (run fetched with `gate_states` containing `"image":"failed"`, artifacts GET 404) → retry click → confirm → assert POST fires. (Verified passing today; guards against regression.)
  - [ ] Do NOT change the UX-DR13 confirm flow (inline `role="alert"` confirmation, 5s auto-dismiss) — see Saved Questions Q1.
- [ ] **Task 2 [backend]: Fix D4 — SPA fallback for `/app/*` (AC: 4, 5)**
  - [ ] In `src/yt_flow/api/main.py` (`mount_static_spa`, lines 45-52), subclass `StaticFiles` overriding `get_response`: on 404 `HTTPException` for a non-file path, return `index.html` instead (Starlette raises `HTTPException(404)` from `StaticFiles.get_response` when the file is missing). Keep the mount at `/app` only; keep the "skip when dist absent" guard.
  - [ ] Add TestClient tests in `tests/api/test_static_spa.py` (file exists): `GET /app/runs/some-id` → 200 + `text/html`; existing asset path still served; `GET /nonexistent` outside `/app` still JSON 404.
- [ ] **Task 3 [backend]: Fix D7 — pre-stream status write in `resume_run` (AC: 6, 7)**
  - [ ] In `src/yt_flow/services/run_service.py` `resume_run` (lines 486-494), before `await _run(...)`, add `await asyncio.to_thread(_write_run, run_id, status="running")` — the exact pattern `retry_stage` (line 606) and `resume_run_from_failure` (line 510) already use. Must go through `asyncio.to_thread` (see `_consume` docstring, lines 238-245 — an inline sync sqlite write blocks the loop and starves the checkpointer into "database is locked").
  - [ ] Do not change `_consume` barrier writes; the next interrupt/failure/completion overwrites status as today.
  - [ ] Add a TestClient/asyncio test (alongside `tests/api/test_gate.py` conventions) asserting: after gate approve 202, the run row reads `status="running"` while the resumed graph is in flight (stub graph — see existing gate tests for the stub-run pattern).
  - [ ] Optional (should, not must): also set `current_stage` to the successor stage and publish a `stage_entry` SSE pre-stream, mirroring `retry_stage` lines 606-608 (approve at stage *i* → `_STAGES[i+1]`; reject → same stage re-runs). If skipped, record why in the Dev Agent Record — see Saved Questions Q3.
- [ ] **Task 4 [frontend]: Fix D14 — count ASS dialogue events (AC: 8, 9)**
  - [ ] In `frontend/src/components/ArtifactPanel.tsx` `SubtitlePanel` (line 373), extend the cue count to cover both formats, e.g. `const cueCount = (text.match(/-->/g) ?? []).length + (text.match(/^Dialogue:/gm) ?? []).length`.
  - [ ] Extend the existing subtitle test (`ArtifactPanel.test.tsx:113-121`, currently SRT-only) with an `.ass` fixture (header + N `Dialogue:` lines) asserting "자막 N개".
- [ ] **Task 5: Regression verification (AC: all)**
  - [ ] `cd frontend && npm test` (Vitest, jsdom) and `npm run build` (tsc -b + vite build) pass.
  - [ ] `uv run pytest tests/api/test_static_spa.py tests/api/test_gate.py tests/api/test_stages.py tests/api/test_sse.py` pass.
  - [ ] Preserved behavior spot-checks: gate 승인/반려 flow unchanged; retry API contract unchanged (202, `{"status":"retrying"}` body); SSE listeners for all four event names still update sidebar/panel; `/files` mount and `/runs/*` API routes unshadowed.

## Dev Notes

**Context: E2E baseline 2026-07-06 (run 272b05a4, SCP-049)** — four defects found via real Playwright user simulation, recorded in `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md` (D4, D7, D9, D14 entries). This story is defect repair only: no new features, no UX redesign, no new dependencies.

### Root cause per defect (investigated during story creation — verified against code)

**D9 — retry button no-op on failed run (major, frontend).**
Root cause pinned and *reproduced with a failing test*: `RunDetail.tsx:96-98` `onRunFailed` discards the `stage` field of the `run_failed` SSE payload:

```ts
onRunFailed: ({ error: err }: { error?: string }) => {
  setRun((r) => (r ? { ...r, status: "failed", error: err } : r))
},
```

The backend *does* send the failing stage — `run_service.py:265-266` (stage-error branch: `{"run_id", "stage", "error"}`) and `run_service.py:364` (astream-exception branch). Because the handler ignores it, on a page that was open when the run failed, the client's `gate_states[failedStage]` stays `"n/a"` → `ArtifactPanel.tsx:68` `canRetry` is false → **the 재시도 button never renders for the failed stage** until a manual reload. This is exactly the E2E session shape: the tester watched the image stage live, the ROCm crash failed the run mid-stage, and the only network traffic was the artifacts GET 404 (the image stage was incomplete → `get_stage_artifacts` raises `LookupError` → 404 → `getStageArtifacts` returns null → empty state, `api.ts:83-93`).

Empirical verification (page-level Vitest, jsdom, done at story-creation time):
- Fresh-load path (run fetched with `gate_states: {"scenario":"approved","image":"failed"}`, artifacts 404): 재시도 renders, 재시도→확인 fires `POST /runs/r1/stages/image/retry`. **PASSES today** — the click→fetch wiring itself is correct (`ArtifactPanel.tsx:57-66` → `api.ts:134-135`).
- Live path (run fetched as `running`, then `MockEventSource.emit("run_failed", {stage:"image", ...})`): panel shows the empty state with **no badge and no 재시도 button**. **FAILS today** — this is the fix target and the red test to check in.

Secondary trap (do not "fix", but know it): retry is a two-step flow — clicking 재시도 only opens an inline confirmation (`role="alert"`) that auto-dismisses after 5 seconds with no action (`ArtifactPanel.tsx:51-55`, per UX-DR13 / Story 3.5 AC4). A single click never produces a network request by design, and slow interaction (>5s between 재시도 and 확인 — typical for agent-driven browsers taking snapshots) silently loses the confirmation. This plausibly compounds the observed "click → zero requests" capture. Keep the UX as specified; the real fix is the SSE gap above.

**D4 — SPA deep-link 404 (minor, backend).**
`src/yt_flow/api/main.py:45-52` mounts `StaticFiles(directory=dist_dir, html=True)` at `/app`. `html=True` only maps directory paths to `index.html` for paths that *exist on disk*; a client-side route like `/app/runs/{id}` matches no file, Starlette's `StaticFiles.get_response` raises `HTTPException(404)`, and FastAPI renders `{"detail":"Not Found"}`. Fix at the mount (standard pattern):

```python
class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise
```

The frontend router already parses `location.pathname` under `/app` (see `frontend/src/lib/navigate.ts` / `App.tsx` routing from Story 3.3/3.4), so once index.html is served the deep link renders with no frontend change. Existing test file: `tests/api/test_static_spa.py`.

**D7 — stale `awaiting_approval` during post-approval stage (minor, backend).**
Root cause is an asymmetry in `src/yt_flow/services/run_service.py`:
- `retry_stage` writes `status="running", current_stage=stage` *before* spawning the stream (line 606) and even publishes a manual `stage_entry` (line 608) → the E2E baseline confirmed retry shows "running image" correctly.
- `resume_run_from_failure` also pre-writes `status="running"` (line 510).
- **`resume_run` (lines 486-494, the gate-approval path called from `routes/runs.py:129-130`) writes nothing before streaming.** The DB keeps `status="awaiting_approval"` / `current_stage=<gated stage>` (written at the interrupt, `_consume` lines 249-254) until the *next* update event arrives — and with `stream_mode="updates"` a stage node's event is emitted only when the node **completes** (`_consume` lines 255-271; note `stage_entry` and `stage_exit` are published back-to-back after completion). For a long stage (image ≈ 30-40 min GPU) the API lies for the whole duration.

Minimal fix (ponytail): one pre-stream `await asyncio.to_thread(_write_run, run_id, status="running")` in `resume_run`, mirroring the retry path. The `asyncio.to_thread` wrapper is mandatory — see the `_consume` docstring (lines 238-245): unwrapped sync sqlite writes while the async checkpointer holds the same file caused real "database is locked" failures.

Known deeper limitation (not this story's scope, record only): even after the fix, live-page `current_stage` and the `stage_entry` SSE still lag until node completion because `stream_mode="updates"` has no node-entry signal. The UI's own optimistic state (`RunDetail.tsx:68-74` keeps `status` unchanged after approve) also depends on that SSE. AC6 targets the `GET /runs/{id}` truth; SSE-entry parity is the optional subtask in Task 3.

**D14 — "자막 0개" while content renders (minor, frontend).**
`ArtifactPanel.tsx:373`: `const cueCount = (text.match(/-->/g) ?? []).length` counts SRT `-->` arrows. Story 7.5 (commit aed0d7d) switched the subtitle node to kinetic `.ass` output (`src/yt_flow/pipeline/nodes/subtitle.py:242, 306-311` — `.ass` when word timings are usable, `.srt` fallback otherwise). ASS files have `Dialogue:` event lines and zero `-->`, so run 272b05a4's 8 `.ass` files rendered fine but counted 0. Fix must count **both** formats since the node still emits `.srt` on the aligner fallback path.

### Preserved behavior (must not regress)

- **SSE contract**: four named events (`stage_entry`, `stage_exit`, `gate_pending`, `run_failed`) with JSON `{run_id, stage?, error?}`; `useRunProgress` cleanup/close semantics; `EventSource.onerror` stays non-authoritative (only `run_failed` marks failure).
- **Gate approve flow** (Story 3.5/2.3): footer 승인/반려 only for `pending`, optimistic `onGateStateChange`, 202 + SSE reconciliation, 409 on non-pending gate.
- **Retry API contract** (Story 2.4): `POST /runs/{id}/stages/{stage}/retry` → 202 `{"run_id","stage","status":"retrying","message":...}`; preconditions unchanged (run status ∈ `_MUTABLE_STATES`, gate state ∈ `_RETRYABLE` = approved/rejected/failed → else 409).
- **UX-DR13**: inline retry confirmation (`role="alert"`, 확인/취소, 5s auto-dismiss) stays as-is.
- **Static mounts**: `/app` never shadows API routes; `/files` workspace mount untouched; API startup without a `frontend/dist` build still works (guard in `mount_static_spa`).

### Testing standards

- **Frontend**: Vitest + RTL, jsdom (`frontend/vitest.config.ts` — separate from vite.config so `tsc -b` skips test types). Run: `cd frontend && npm test`; build gate: `npm run build`. Conventions from Story 3.2/3.5: mock `fetch` via `vi.stubGlobal`, mock `EventSource` with the `MockEventSource` class already in `RunDetail.test.tsx:6-22`, fake timers for the 5s auto-dismiss, jsdom has no `showModal` (moot here — no dialogs). D9/D14 tests must assert **fetch was called with the exact URL/method** (D9) and the rendered count text (D14).
- **Backend**: FastAPI TestClient + pytest under `tests/api/` (`conftest.py` provides app/db fixtures; `test_gate.py`, `test_stages.py`, `test_sse.py` show the stub-graph pattern for exercising resume/retry without a real pipeline). D4 → `test_static_spa.py`; D7 → assert the runs-table `status` after approve while the stubbed resumed stage is still "executing".
- Worktree gotcha (memory): if implementing in a git worktree, `PYTHONPATH=$PWD/src` — the global editable install points at the main tree.

### Red test for D9 (drop into `RunDetail.test.tsx`, adapt names)

```tsx
it("run_failed SSE flips the failed stage to retryable without reload (D9)", async () => {
  // run fetched as running/image, gate_states = {"scenario":"approved"} (JSON string)
  // artifacts GET → 404
  render(<RunDetail runId="r1" />)
  await waitFor(() => expect(screen.getByRole("navigation")).toBeInTheDocument())
  act(() => MockEventSource.instances[0].emit("run_failed",
    { run_id: "r1", stage: "image", error: "ComfyUI connection refused" }))
  const main = screen.getByRole("main")
  const retryBtn = await within(main).findByRole("button", { name: "재시도" })
  fireEvent.click(retryBtn)
  fireEvent.click(within(main).getByRole("button", { name: "확인" }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/runs/r1/stages/image/retry", expect.objectContaining({ method: "POST" })))
})
```

### Ponytail

Four surgical fixes, zero new dependencies, zero new abstractions: one SSE-handler line-group (D9), one `StaticFiles` subclass of ~7 lines (D4), one pre-stream `_write_run` call (D7), one regex addition (D14). Do not build a state-machine refactor for run status, a router library for the SPA, or a subtitle parser — count lines and move on. Mark any deliberate deferral with `# ponytail:`.

### Saved Questions

- **Q1 (D9 residual)**: The fresh-load retry path passes in jsdom, so if Jay can still reproduce a dead retry button *after a full page reload* in a real browser, there is a second cause not covered here (candidate: the 5s auto-dismiss racing slow interaction, or a pointer-interception overlay). Re-verify with Playwright after the SSE fix lands; reopen if it reproduces.
- **Q2 (D7 deeper)**: `stream_mode="updates"` emits stage events only at node completion, so `current_stage` + `stage_entry` SSE inherently lag on the approval path even after this fix. A true node-entry signal needs a different stream mode or entry callbacks — deliberately out of scope; open a follow-up story if live-page stage tracking during long stages matters.
- **Q3 (D7 optional subtask)**: Should `resume_run` also pre-write `current_stage` to the successor stage and publish a synthetic `stage_entry` (as `retry_stage` does)? Approve→`_STAGES[i+1]`, reject→same stage; video-approve has no successor. Minimal AC only requires `status="running"`; decide during dev and record.

### Project Structure Notes

- Frontend fixes stay inside the established `frontend/src/` tree (`pages/RunDetail.tsx`, `components/ArtifactPanel.tsx`, colocated `*.test.tsx`). No new components needed.
- Backend fixes stay in `src/yt_flow/api/main.py` and `src/yt_flow/services/run_service.py`; routes are untouched (AD-1/AD-4: routes thin, services own graph + DB sync + SSE fan-out).
- D4 and D7 are backend-rooted fixes shipped inside this UI story deliberately (defect batch from one E2E baseline); each task is layer-tagged.
- No changes to `sprint-status.yaml` / `epics.md` as part of implementation.

### References

- Evidence: `_bmad-output/implementation-artifacts/e2e-baseline-2026-07-06.md` (D4 at scenario-gate section; D7 + D9 at image-stage section incl. the "재시도 경로에서는 running 정상 표기" asymmetry note; D14 at subtitle-gate section)
- Draft: `_bmad-output/planning-artifacts/epics.md#Story 3.8: 컨트롤 UI 결함 수리 (2026-07-06 E2E 베이스라인 발견분)` (line 834)
- Built-the-controls story (behavior contracts to preserve): `_bmad-output/implementation-artifacts/3-5-gate-controls-retry-editor-sse.md`
- Panel/layout story: `_bmad-output/implementation-artifacts/3-4-run-detail-artifact-panel.md`
- Code, frontend: `frontend/src/pages/RunDetail.tsx:68-74, 76-83, 85-104 (96-98 = D9 fix site)`; `frontend/src/components/ArtifactPanel.tsx:43-68 (retry), 51-55 (auto-dismiss), 342-380 (373 = D14 fix site)`; `frontend/src/lib/api.ts:83-93, 134-135`; `frontend/src/hooks/useRunProgress.ts:41-49`
- Code, backend: `src/yt_flow/api/main.py:45-52, 73 (D4)`; `src/yt_flow/services/run_service.py:249-254, 255-271, 265-266, 364 (run_failed payload), 486-494 (D7 fix site), 510, 606-608`; `src/yt_flow/api/routes/runs.py:114-130`; `src/yt_flow/api/routes/stages.py:20-26`; `src/yt_flow/pipeline/nodes/subtitle.py:242, 306-311 (D14 backend context)`
- Tests: `frontend/src/pages/RunDetail.test.tsx` (MockEventSource lines 6-22), `frontend/src/components/ArtifactPanel.test.tsx:113-121, 194-207`, `tests/api/test_static_spa.py`, `tests/api/test_gate.py`, `tests/api/test_stages.py`
- Architecture: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-4` (services own DB sync + SSE), `#AD-9` (retry semantics)
- UX: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md#Interaction-Primitives` (UX-DR13 retry confirmation)

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
