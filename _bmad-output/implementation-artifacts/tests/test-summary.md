# Test Automation Summary

## Generated Tests

### E2E Tests

- [x] `e2e/dashboard-run-gate-artifacts.spec.ts` — SYS-E2E-002 (P0), Journey 1: dashboard → SCP search/select → create run → SSE-observed gate progression → approve all 5 stage gates → per-stage artifact panel (scenario text / image grid / tts audio / subtitle text / video) → completion.
- [x] `e2e/gate-reject-retry-edit-concurrency.spec.ts` — Journey 2 (P1): scenario inline edit + approve → image approve → explicit `재시도` retry trigger with B-1 concurrency-guard probes (API 409 + UI control hiding) → tts approve → subtitle gate reject (implicit backend retry loop) → subtitle inline edit + re-approve → video approve/download confirms the downstream stage re-runs cleanly → completion.
- [x] `e2e/character-management.spec.ts` — SYS-E2E-003 (P0), Journey 3: character list → "새 캐릭터" create → reference image search (thumbnail grid) → multi-angle candidate generation (4 angles, polling to `완료`) → finalize → angle gallery populated. Related stories: 3.7 (Character Management UI), 1.11 (Character Domain + Reference Search), 1.12 (Multi-Angle Character Generation).

Config changes:
- `playwright.config.ts`'s `webServer.command` now boots `scripts/run_e2e_stub_server.py` instead of the real app (from Journey 1) — both journeys drive real gate/pipeline transitions and must not hit DeepSeek/Qwen/ComfyUI/ffmpeg for real.
- `playwright.config.ts`: `workers` pinned to `1` everywhere (was `undefined` locally). With two full-pipeline journey specs now sharing one stub-server process, default parallel workers reliably raced each other (SQLite writes, in-process LangGraph `_configs`), timing out unrelated requests. Confirmed via repeated runs before/after.
- `scripts/run_e2e_stub_server.py`: added a 0.5s artificial delay to the image-stage ComfyUI fake (E2E-only; `tests/stubs/fakes.py` itself is untouched so `pytest` stays fast). The stub pipeline re-executes a stage faster than two sequential real HTTP round-trips from Playwright, so without this the B-1 `run.status == "running"` window was unobservable over real HTTP even though it exists — confirmed by probing it directly (raced 2/3 attempts without the delay, 0/6+ with it).
- `e2e/support/helpers.ts` (new): extracted `stageSidebarButton`/`artifactSection`/`approveStage`/`createRun` shared across both specs. While extracting, hardened `createRun`: it now opens Run Detail via the SPA's own client-side `pushState`/`popstate` (mirroring `frontend/src/lib/navigate.ts`) instead of clicking the new dashboard row by SCP-label regex. The row-click was silently flaky — `Dashboard.tsx`'s `onCreated()` optimistically prepends the new run then fires an unawaited `getRuns()` refetch that can reorder the list before the click lands, so `.first()` could resolve to an older same-SCP row from a prior run instead of the new one. Confirmed directly: captured `runId` from the creation response diverged from `page.url()`'s actual run id under this exact race. This affected Journey 1 too (pre-existing, just never triggered before a second full-pipeline spec existed to expose it under repeat local runs).
- `tests/stubs/fakes.py` + `scripts/run_e2e_stub_server.py` (Journey 3): added `fake_image_search` (`DuckDuckGoImageSearch.search`) and `fake_download_reference_image` (`CharacterService._download_reference_image`). Neither Story 1.11's reference search nor its download step was in the existing 5-seam stub profile — without these two, Journey 3 would hit real `duckduckgo.com` over the network. `pytest`'s own coverage of this path only ever exercises the empty-results branch (`mock_search.return_value = []`), which is how the bug below went uncaught.

Product code changes (found while wiring Journey 3 — see Findings; user approved fixing all three in-session rather than deferring):
- `src/yt_flow/services/character_service.py:305` — `result.url` → `result["url"]`. `SearchResult` is a `TypedDict` (plain dict at runtime); the attribute access always raised `AttributeError`, silently swallowed by the surrounding `except Exception: continue`, so reference image search downloaded 0 images regardless of search results. Untested path (see above) — 0 regressions, 46 passed.
- `src/yt_flow/api/routes/characters.py` (`_generate_all`) — after marking a candidate `ready`, now also calls `svc_gen.select_candidate(scp_id, candidate_num=1, angle=angle)`. Only one candidate is ever generated per angle (no regenerate/multi-candidate UI exists), so auto-selecting is behavior-preserving; without it, `Character.angle_*_path` never populates and `finalize_character` always 409s regardless of how many candidates are `ready`.
- `frontend/src/pages/CharacterDetailPage.tsx` (`handleCandidatesRefresh`) — now also calls `load()`. `finalize()` updates `angle_*_path` server-side, but the page's `char` state was never refetched after it, so the angle gallery stayed showing "이미지 없음" placeholders even after a successful finalize.

## Coverage

- SYS-E2E-002 baseline journey (per `test-design-qa.md`): covered.
- Journey 2 from `next-session-e2e-03-generate-tests.md` (gate reject/retry/edit + B-1 concurrency guard): covered.
- Journey 3 (character management: list → create → reference search → multi-angle generation → finalize → gallery): covered.
- Journey 4 (A/B comparison): a spec (`e2e/ab-comparison-accessibility.spec.ts`) already exists from a prior/parallel session — not touched here.

## Findings (not fixed — out of scope for test generation)

1. **No SSE signal for run completion.** `run_service._consume` only publishes `stage_entry`/`stage_exit`/`gate_pending`/`run_failed`; after the last stage's gate is approved, the run flips to `status: "complete"` in the DB with no corresponding SSE event. `RunDetail`'s header badge never updates to "완료" without a manual page reload. Both specs verify completion via `GET /runs/{id}` instead of the live UI.
2. **No SPA history-fallback for nested `/app/...` paths.** `GET /app/runs/{id}` 404s directly (confirmed via curl) — the FastAPI `StaticFiles(html=True)` mount only serves `index.html` for `/app/` itself, not for arbitrary sub-paths. Deep-linking or refreshing a Run Detail page breaks.
3. **No frontend-level concurrency guard beyond the retried stage's own controls.** The B-1 backend guard (`run.status not in {awaiting_approval, failed, complete}` → 409) is enforced server-side only. While one stage is retrying, an *already-approved, different* stage's `재시도`/`편집` controls remain visible and clickable in the UI; clicking them surfaces the same generic inline API-error text used for any other failure rather than a proactive disabled state. Journey 2's test asserts the 409 + error text (the guard *is* enforced, correctly), not a UI-level disable, since none exists.
4. **Possible TOCTOU race in `retry_stage`/`edit_artifact`'s B-1 guard.** Reading code only (not exercised by this session's tests, which target a single actor): the `run.status` guard check and the eventual `status="running"` write are separated by `await`s (`_graph.aget_state`/`aupdate_state`), so two genuinely concurrent requests for the same run could both pass the check before either commits. This is a single-operator local app (no auth/multi-user per the PRD), so real-world exposure is low, but flagging for Dev awareness since SYS-INT-004's existing pytest coverage sets up `run.status="running"` via fixture rather than firing two live concurrent requests, so it wouldn't catch this.

Journey 3 (character management) — three bugs found were fixed in-session (see Product code changes above, user approved); two more remain out of scope for test generation:

5. **`CharacterFormDialog`'s "New Character" dialog has no SCP Picker integration.** Story 3.7's AC6 ("SCP ID field focus opens the existing SCP Picker dialog from Story 3.3") and its task checklist both claim this is done, but `CharacterFormDialog.tsx` only renders a plain text `<input>` for SCP ID — no picker dialog is wired up anywhere in the component. Journey 3's test fills the field directly (`SCP-3007-{timestamp}`) rather than exercising a picker, since none exists to exercise. Spec/shipped-code drift, not something this QA session should silently paper over.
6. **No "재시도"(regenerate) control for a failed angle candidate.** AC4 specifies a per-angle regenerate button when a candidate's status is `failed`; `CandidatePanel.tsx` only renders a static "⚠ 실패" indicator with no retry action. Not exercised by Journey 3 (the stubbed ComfyUI fake never fails), and no code fix attempted — this is a missing feature, not a one-line bug like the three above.

## Next Steps

- Consider a backend `run_complete` SSE event (or have the frontend refetch `GET /runs/{id}` after the last gate's `approveGate()` resolves) to close finding #1.
- Consider adding a catch-all route (or `StaticFiles` fallback) so `/app/*` always serves `index.html` when no static asset matches, to close finding #2.
- Decide whether finding #3 (no proactive UI disable during a run-wide B-1 guard) is worth a frontend fix, or whether the current 409-surfaces-as-inline-error behavior is acceptable for a single-operator app.
- Have Dev assess finding #4's TOCTOU window; if real, the fix is likely moving the `status="running"` write earlier (before `aupdate_state`) or holding a per-run asyncio lock across the guard-check-and-write.
- Wire all specs into a nightly CI job (not PR-blocking), per `test-design-qa.md`'s Execution Strategy — not done this session.
- Decide whether finding #5 (missing SCP Picker in `CharacterFormDialog`) should be a Dev follow-up story or a doc correction to 3.7's AC6/task checklist, given the checklist already marks it done.
- Add a "재시도" control for failed angle candidates (finding #6) if AC4's regenerate-on-failure requirement is still wanted; add a Playwright probe for it once it exists (mirroring Journey 2's B-1 retry pattern).
