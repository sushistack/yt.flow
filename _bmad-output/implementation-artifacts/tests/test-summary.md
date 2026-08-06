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
- `tests/stubs/fakes.py` + `scripts/run_e2e_stub_server.py` (Journey 3): added `fake_image_search` (`DuckDuckGoImageSearch.search`) and `fake_download_reference_image` (`CharacterService._download_reference_image`). Neither Story 1.11's reference search nor its download step was in the existing 5-seam stub profile — without these two, Journey 3 would hit real `duckduckgo.com` over the network. `pytest`'s own coverage of this path only ever exercises the empty-results branch (`mock_search.return_value = []`), which is how the first bug below went uncaught.

Product code changes (all found while wiring/hardening Journey 3; user approved fixing every one in-session rather than deferring — see `deferred-work.md`, which now has nothing open from this session):
- `src/yt_flow/services/character_service.py:305` — `result.url` → `result["url"]`. `SearchResult` is a `TypedDict` (plain dict at runtime); the attribute access always raised `AttributeError`, silently swallowed by the surrounding `except Exception: continue`, so reference image search downloaded 0 images regardless of search results. Untested path — regression test added (`test_search_references_downloads_and_persists_results`), verified it fails against the old code.
- `src/yt_flow/api/routes/characters.py` (`_generate_all`) — after marking a candidate `ready`, now also calls `svc_gen.select_candidate(scp_id, candidate_num=1, angle=angle)`. Without it, `Character.angle_*_path` never populates and `finalize_character` always 409s regardless of how many candidates are `ready`.
- `frontend/src/pages/CharacterDetailPage.tsx` (`handleCandidatesRefresh`) — now also calls `load()`. `finalize()` updates `angle_*_path` server-side, but the page's `char` state was never refetched after it, so the angle gallery stayed showing "이미지 없음" placeholders even after a successful finalize.
- **SCP Picker integration (AC6)** — `SCPPickerDialog.tsx` gained optional `onSelect`/`title`/`confirmLabel` props (it was hard-coupled to creating a run via `createRun()`); `CharacterFormDialog.tsx`'s SCP ID field now opens it on focus and fills the field from the picked SCP instead of free-text entry. ~50 lines across 2 files, no backend changes.
- **Angle-scoped regenerate (AC4)** — `POST /{id}/generate` now accepts an optional `?angle=` query param (validated against `CharacterService.CANONICAL_ANGLES`); `CandidatePanel.tsx` shows a "재시도" button on a `failed` candidate that calls it for just that angle. `generateCandidates()` in `api.ts` gained the same optional param.
- **Duplicate candidate rows on regenerate (found while implementing the above)** — `create_candidate_batch` unconditionally inserted new rows with no check for an existing `(scp_id, angle)` row; the table has no real unique constraint (`__table_args__`'s `sqlite_on_conflict_unique` is a no-op — there's no accompanying `UniqueConstraint`, confirmed by reading `db/models.py`). Fixed by deleting any existing row(s) for the target angle(s) before inserting. Regression tests added (`test_generate_candidates_regenerate_does_not_duplicate_rows`, plus two more for the scoping itself); verified the dedup test fails against the old code.
- **`delete_character()` orphaning candidates instead of deleting them** — found by the *new* SCP-096 E2E flow itself: it only nulled a candidate's `character_id` FK ("nullable FK — set NULL for surviving records"), but `list_candidates()`/the `/{id}` detail route both look candidates up by the **scp_id string**, not `character_id`. A deleted character's old (possibly `ready`) candidates would resurface and get silently "adopted" by the next character created for the same `scp_id` — exactly what my test's `beforeEach`/`afterEach` cleanup does between runs, which is how this surfaced as ~50% E2E flakiness (`finalize` 409ing with all 4 angles "missing" despite the UI showing `완료` for all of them, because the "ready" candidates it saw were orphaned leftovers from the *previous* run, not this run's real generation). Fixed to actually delete the rows. Regression test added (`test_delete_cascades_candidates_not_just_orphans_them`); verified it fails against the old code, and confirmed 5/5 clean E2E runs after the fix (was ~50% failure rate before).

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

Journey 3 (character management) surfaced 6 bugs total; all 6 were fixed in-session (user approved going past the original test-generation scope) — see Product code changes above and `deferred-work.md`, which has nothing open from this session. None are listed here as unfixed findings.

## Next Steps

- Consider a backend `run_complete` SSE event (or have the frontend refetch `GET /runs/{id}` after the last gate's `approveGate()` resolves) to close finding #1.
- Consider adding a catch-all route (or `StaticFiles` fallback) so `/app/*` always serves `index.html` when no static asset matches, to close finding #2.
- Decide whether finding #3 (no proactive UI disable during a run-wide B-1 guard) is worth a frontend fix, or whether the current 409-surfaces-as-inline-error behavior is acceptable for a single-operator app.
- Have Dev assess finding #4's TOCTOU window; if real, the fix is likely moving the `status="running"` write earlier (before `aupdate_state`) or holding a per-run asyncio lock across the guard-check-and-write.
- Wire all specs into a nightly CI job (not PR-blocking), per `test-design-qa.md`'s Execution Strategy — not done this session.
- Update Story 3.7's task checklist/AC6 note if desired — the SCP Picker item was previously marked done despite the code gap; it's genuinely done now.

---

# Test Automation Summary — Story 12.1 (Retention Schema)

Workflow: `bmad-qa-generate-e2e-tests` · 2026-08-06 · Story status: `review`
Appended; the Playwright journey summary above is from a prior session and is unchanged.

Story 12.1 is backend-only (AC 10 forbids any API/DB/UX/frontend change), so there is
no UI surface to drive and no Playwright spec applies. "E2E" here means the full
`scenario_node` orchestration path with the **real** `structure_step` — the widest
boundary the story actually owns.

## Framework

pytest + pytest-asyncio (existing). No new dependency, no new fixture layer, no new
test file — gaps were closed inside the three suites that already own this code.

## Gaps Found and Closed

Existing coverage was already deep (132 retention assertions). These 9 were genuinely
absent. Each was verified by mutation: break the behavior → the new test fails, and
**no pre-existing test does**.

### Validator — `tests/pipeline/nodes/test_scenario_chain.py`

| Test | Gap it closes |
|---|---|
| `test_retention_canonicalizes_enums_on_later_scenes_too` | AC 3 canonicalization was only proven on scene 1; `hook_type: "  NONE  "` at position 2 is the same model slip |
| `test_retention_rejected_outline_is_mutated_only_by_canonicalization` | The existing AC 8 sibling used already-canonical values, so it could not distinguish "writes only the two enums" from "writes nothing at all" |
| `test_retention_empty_outline_is_rejected` | `_validate_retention_outline([])` must not read as a vacuously satisfied contract |
| `test_retention_single_scene_outline_can_never_settle_its_ledger` | Pins the structural 2-scene minimum implied by AC 4's "closed in a *later* scene" |
| `test_structure_cassette_satisfies_the_retention_contract` | `deepseek_structure.json` is replayed as a *valid* reply by other tests; drift there surfaced far from the edit that caused it |
| `test_critic_step_sends_the_source_text_as_the_fact_sheet` | AC 12a wiring — the prompt-contract test only proves `{{scp_fact_sheet}}` still exists, not that the stage fills it |

### Orchestration — `tests/pipeline/nodes/test_scenario.py`

| Test | Gap it closes |
|---|---|
| `test_contract_valid_outline_runs_the_whole_chain` | The positive counterpart to the AC 7 failure test. Without it, a validator that rejected **every** outline would still pass that test |
| `test_scoped_repair_subset_degrades_to_empty_when_writing_overproduces` | `scenario.py:279`'s `idx < len(structure)` guard was untested; removing it turns a recoverable run into an `IndexError` |
| `test_both_critic_call_sites_receive_the_source_text` | AC 12a at the node boundary — the **post-repair** `critic_step` call site was unexercised |

### Fixture contract — `tests/test_eval_prompts.py`

- `test_scripted_structure_fixture_satisfies_the_retention_contract[2,3,8]`

## Two Real Defects Found (both fixed)

1. **`_valid_structure_scenes()` was only accidentally valid.** It hard-coded
   `word_budget: 90` and an interrupt on scene 1 only — correct at its default of 2
   scenes, but any call with ≥4 scenes silently breaks the interrupt cadence and ≥5
   also blows the 360 budget ceiling. Fixed to spread budget and place an interrupt
   every 3rd scene, matching `test_scenario_chain.py`'s helper.

2. **The first draft of `test_both_critic_call_sites_receive_the_source_text`
   overclaimed.** With an empty `scene_notes`, `_retry_scope` yields no indexes, so the
   run takes the **full-rewrite** path and re-enters the *initial* critic call site
   twice — the post-repair site was never reached and the injected mutation went
   undetected. Fixed to flag a specific scene; `calls["repair"] == 1` now pins the path.

## Coverage

| Surface | Status |
|---|---|
| `_validate_retention_outline` rule codes | all 20 codes asserted |
| AC 11's enumerated cases | all present |
| `structure_step` no-LLM-recall (AC 7) | failure **and** success paths |
| `scenario_node` E2E with real `structure_step` | failure **and** success paths |
| Scoped-repair structure subset (AC 9) | non-adjacent indexes + over-production degradation |
| AC 12a critic wiring | stage-level compile + both node call sites |
| Prompt/fixture contracts (AC 11, 12) | `structure.md`, both writing prompts, `critic_agent.md`, cassette, eval fixture |

## Verification

- `PYTHONPATH=$PWD/src uv run pytest tests/pipeline/nodes/test_scenario_chain.py tests/pipeline/nodes/test_scenario.py tests/test_eval_prompts.py -q` → **667 passed**
- `PYTHONPATH=$PWD/src uv run pytest -q` → **2125 passed, 1 skipped, 3 failed**
  (2113 before this workflow; +12). The 3 failures are all in
  `tests/api/test_e2e_stub_run.py`, documented as pre-existing at baseline `db2e813`
  in the story's own Debug Log, and untouched by these test-only changes.
- `uv run ruff check src tests` → **All checks passed!**
- Mutation check: 5 injected defects — critic fact sheet dropped; canonicalization
  narrowed to scene 1; over-production guard removed; post-repair `scp_text` dropped;
  validator rejects everything — **all 5 caught**. Source restored byte-identical
  (verified with `diff`).

## Checklist

| Item | |
|---|---|
| API tests generated (if applicable) | n/a — AC 10 forbids an API surface |
| E2E tests generated | ✅ full `scenario_node` path, real `structure_step`, both directions |
| Standard framework APIs | ✅ pytest / monkeypatch / parametrize only |
| Happy path covered | ✅ |
| Critical error cases covered | ✅ |
| All generated tests pass | ✅ |
| Proper locators | n/a — no UI |
| Clear descriptions | ✅ each docstring states the defect it prevents |
| No hardcoded waits/sleeps | ✅ |
| Tests independent | ✅ pass under both default random ordering and `-p no:randomly` |
| Summary includes coverage metrics | ✅ this section |

## Next Steps

- No production-code change was needed or made — the implementation held under all
  5 mutations. The two defects found were both in test-side fixtures.
- The 3 `test_e2e_stub_run.py` failures remain open and predate Story 12.1
  (`_drain_bg_tasks` timeout, per the project's recorded gotcha). Out of scope here.

---

# Story 12.2 — Model Split (DeepSeek planning / Gemini prose + judge)

Workflow: `bmad-qa-generate-e2e-tests`, 2026-08-06. Test generation only — no story
validation, no code review. All discovered gaps auto-applied per Jay's instruction.

## Generated Tests

### E2E Tests (API-driven, offline)

- [x] `tests/api/test_e2e_stub_run.py::test_scenario_substages_reach_the_provider_the_ownership_table_assigns`
  — a run created through `POST /runs` records `(stage, provider)` for every LLM call
  and checks it against the story's ownership table. The unit tests inject the seams by
  hand, so they only prove the routing helper works; this proves **production wiring
  calls it**. Also names the stages that must appear on each side, so a run that
  skipped `tts_normalize` or judged nothing can't pass by touching both providers.
- [x] `tests/api/test_e2e_stub_run.py::test_a_gemini_outage_fails_the_run_visibly_instead_of_completing_on_deepseek`
  — Gemini returns 429 `RESOURCE_EXHAUSTED`: the run reaches the API client as
  `status: "failed"`, its scenario gate refuses approval with 409, `run_failed` fans
  out for the scenario stage, and DeepSeek is confirmed to have served only
  `research`/`structure` — it never covered for the prose stage (AC1, AD-10).
- [x] `tests/test_run_e2e_stub_server.py` (new file) —
  `scripts/run_e2e_stub_server.py` had **zero** coverage despite carrying AC9's
  "the stub server reaches no provider" claim. Two tests: both provider keys are
  non-secret dummies set unconditionally, and each scenario seam replays only its own
  provider's stages (handing it the other provider's stage marker raises).

### API / service tests

- [x] `tests/services/test_eval_service.py::test_the_whole_evaluation_talks_only_to_gemini`
  — AC7 **composed** rather than per-function. Only `httpx.AsyncClient` is faked, so a
  complete `evaluate_ab` (3 axes × 3 samples × 2 runs + pairwise) is checked in
  aggregate: every request lands on Gemini's endpoint with the Gemini judge model,
  budget, bearer key and JSON mode; no request carries the DeepSeek base URL or key.
  The pre-existing Gemini tests stub `_post_chat`, which left "does some path inside
  the evaluation still reach DeepSeek?" unanswered.

## Gaps Found and Fixed

1. **The offline E2E profile was only hermetic on a machine that had a `.env`.**
   Story 12.2 gave Gemini an unconditional dummy key in `tests/conftest.py` but left
   DeepSeek's identical `scenario_node` guard to be satisfied by whatever real key
   `.env` held. On a `.env`-less checkout — fresh clone, CI, or this git worktree —
   every stub-profile run died at
   `stage=scenario: YTFLOW_DEEPSEEK_API_KEY is not configured`. Fixed by setting
   `YTFLOW_DEEPSEEK_API_KEY` unconditionally alongside Gemini's.

   This is the **actual** cause of the "3 pre-existing `test_e2e_stub_run.py`
   failures" recorded in Story 12.1's and 12.2's Dev Agent Records, and blamed there
   (and in this document's Story 12.1 section) on the `_drain_bg_tasks` timeout gotcha.
   It is neither a timeout nor a flake: with the dummy key the file goes from
   `3 failed` in 1.09s to `5 passed` in 8.6s — the earlier runs were failing instantly,
   never timing out. Confirmed by reading the run's `run_failed` SSE payload.

2. **`test_stub_profile_smoke.py::test_graph_reaches_terminal_state` was vacuous** —
   the very test the story cites as "the offline proof for AC9". It asserted only the
   final status, and approving the gate of a *failed* stage still advances the run, so
   it saw `status == "complete"` while scenario had died before either provider seam
   was reached. Added `assert run.error is None` first, which is what distinguishes
   "traversed five stages" from "failed instantly and got dragged to the end".

3. **`scripts/run_e2e_stub_server.py` required a real DeepSeek key to boot a run.**
   Same asymmetry: the module top set a Gemini dummy, and its `__main__` comment
   explicitly relied on `scenario_node`'s `Settings()` keeping "the real .env-derived
   value it needs to pass its guard" — so the script advertising "zero real network
   calls" could not run a scenario stage at all without a live credential on disk.
   Fixed with a DeepSeek dummy; the stale comment corrected.

4. **Stale provider in a test's simulated failure.**
   `test_run_service_gate.py::test_ab_eval_failure_does_not_affect_run_status` raised
   `YTFLOW_DEEPSEEK_API_KEY is not configured` as the realistic A/B-eval failure, but
   after this story that key no longer stops an evaluation — the Gemini one does
   (Task 4 asked for exactly this kind of cleanup). Updated.

## Coverage

| Surface | Before | After |
|---|---|---|
| Provider routing, E2E through `POST /runs` | none — unit-injected seams only | ✅ full ownership table |
| Gemini outage visible to an API client | none | ✅ failed run + 409 gate + no DeepSeek fallback |
| Whole `evaluate_ab` transport (not per-function) | none | ✅ every request asserted Gemini-only |
| `scripts/run_e2e_stub_server.py` | 0 tests | ✅ 2 tests |
| Offline stub profile hermetic without `.env` | ✗ DeepSeek | ✅ both providers |

## Verification

- `PYTHONPATH=$PWD/src uv run pytest -q` → **2168 passed, 1 skipped, 0 failed**
  (was 2160 passed / 3 failed: +5 new tests, and the 3 long-misdiagnosed failures now pass).
- `PYTHONPATH=$PWD/src uv run pytest -q --cov` → **92.76%**, gate 80% (was 92.51%).
- `uv run ruff check .` → **All checks passed!**
- Mutation check — 3 injected defects, **all 3 caught**, sources restored byte-identical
  (`diff` clean):
  1. `writing_step` routed back to `_call_deepseek` → both new API E2E tests fail.
  2. `_judge_sample` model back to `deepseek_judge_model` → the whole-evaluation test fails.
  3. stub server's DeepSeek dummy key removed → the new key test fails.

## Checklist

| Item | |
|---|---|
| API tests generated | ✅ `evaluate_ab` transport; run/gate contract via `POST /runs` + gate endpoint |
| E2E tests generated | ✅ 3 (2 API-driven pipeline runs + the stub-server script) |
| Standard framework APIs | ✅ pytest / pytest-asyncio / monkeypatch only |
| Happy path covered | ✅ full-ownership-table run, complete evaluation |
| Critical error cases covered | ✅ Gemini 429 outage, missing dummy key, cross-provider stage marker |
| All generated tests pass | ✅ and the full suite is green for the first time in this worktree |
| Proper locators | n/a — no UI change in this story |
| Clear descriptions | ✅ each docstring states the defect it prevents |
| No hardcoded waits/sleeps | ✅ awaits `run_service._bg_tasks`, no `sleep` |
| Tests independent | ✅ env/module mutations registered with `monkeypatch` before the script rebinds them, so nothing leaks |
| Summary includes coverage metrics | ✅ above |

## Next Steps

- **Left for Jay (unchanged by this workflow):** AC10's bounded live golden-SCP
  `scenario_node` diagnostic still needs a `.env` with a real DeepSeek key + Langfuse
  Prompt Hub reach, which this worktree does not have. Story 6.12's promotion gate was
  not run, bypassed, or unfrozen here.
- **Worth a follow-up story, not fixed here (out of test-generation scope):**
  approving the gate of a *failed* run marks it **complete**, which is what let gap #2
  hide. `run_service.resume_run` (`run_service.py:651`) has no status precondition: it
  writes `status="running"` and streams `Command(resume=…)` into a graph that a failed
  stage already routed to END, so the stream yields no updates and `_run` falls through
  to `status="complete"`. Verified directly, not inferred. The API gate endpoint does
  return 409 on a failed run (asserted by the new outage test), so the exposure is
  service-level — anything calling `resume_run` without going through the route.
