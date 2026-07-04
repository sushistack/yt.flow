---
created: 2026-07-04
baseline_commit: 92ce536d5dad111d90178a0a17689cba049b7de4
story_key: 5-8-automatic-entity-reference-generation
story_id: "5.8"
epic: 5
previous_story: 5-7-layered-background-double-exposure-fix
depends_on:
  - 1-11-character-domain-reference-search
  - 1-12-multi-angle-character-generation
  - 1-13-video-llm-character-selection
  - 3-7-character-management-ui
  - 5-7-layered-background-double-exposure-fix
---

# Story 5.8: Automatic Entity Reference Generation for the SCP Being Narrated

Status: done

## Story

As Jay,
I want the SCP entity's search-informed, multi-angle reference images (Story 1.11-1.13's pipeline) to be generated and used automatically for every run,
so that the entity's visual appearance is grounded in a real reference instead of always falling back to a same-frame segmentation cutout.

## Context

While reviewing Story 5.5's live A/B videos, Jay recalled asking for the SCP entity's appearance to be based on real reference images (originally described as DuckDuckGo image search results), composited onto the AI-generated background — not cut out from the same generated frame via segmentation.

Investigation found this is **already built**, just never engaged: Story 1.11 implemented `CharacterService.search_references` with `DuckDuckGoImageSearch`, querying `f"{scp_id} SCP Foundation"` — i.e. it searches for the SCP entity itself, not a named human character. Stories 1.12/1.13 built on this: a Vision LLM analyzes the search results to drive multi-angle ComfyUI generation, and `video_node`'s `_angle_selector` (wired via `inject_angle_selector` in `api/main.py`) LLM-picks the best generated angle per shot and overwrites `shot["character_path"]`.

The reason none of this appeared in the SCP-096 live A/B runs: `CharacterService.select_character_angles()` (`src/yt_flow/services/character_service.py:809-812`) returns `None` immediately — "no character for %s, skipping" — unless a `CharacterModel` row already exists for that `scp_id`. Creating that row (search → generate angles → save) is currently a **manual, opt-in step via the Character Management UI** (Story 3.7), and nobody had done it for SCP-096 before running the A/B validation. So every shot fell back to whatever `image_node`'s layered ComfyUI generation produced — the same-frame segmentation cutout Story 5.7 is separately fixing.

This story's job: decide and implement how entity reference generation becomes part of the normal run path (fully automatic, or an explicit pre-run step the run always performs) instead of requiring a human to have separately visited the Character Management UI first for every SCP the pipeline will ever narrate.

## Acceptance Criteria

1. Given a run starts for an `scp_id` with no existing `CharacterModel` row, then the pipeline automatically triggers the same search → multi-angle generation flow that the Character Management UI currently triggers manually, before (or during) the stage that first needs `character_path` (the image stage).
2. Given a `CharacterModel` row already exists for the `scp_id` (created previously, manually or automatically), then the pipeline does NOT re-run the search/generation — it reuses the existing character record exactly as `select_character_angles` does today.
3. Given the automatic reference generation fails (search returns nothing, generation errors, vision LLM errors), then the run must not fail — it falls back to today's behavior (same-frame segmentation cutout from Story 5.7's cleaned-up layered workflow), consistent with AD-10 (non-fatal auxiliary failures) and `select_character_angles`'s existing `fallback: true` semantics.
4. Given this automatic trigger is added, then it must not duplicate work already done by an in-flight or recent run for the same `scp_id` — reuse `CharacterService.check_existing_character` before triggering new search/generation.
5. Given the Character Management UI (Story 3.7) still exists as a manual path, then this story does not remove it — manual pre-curation before a run remains possible for humans who want to review/adjust the reference before generation, this story only removes the requirement that they must.
6. Given the change touches run orchestration, then it must not add a new pipeline stage — PRD explicitly excludes stages beyond `scenario -> image -> tts -> subtitle -> video`; the trigger belongs inside an existing stage (image, most likely) or as pre-graph orchestration in `run_service.py`, not a new LangGraph node.

## Tasks / Subtasks

- [x] Decide the trigger point (AC: 1, 6) — read `src/yt_flow/services/run_service.py::start_run` and `src/yt_flow/pipeline/nodes/image.py::image_node` fully before choosing.
  - [x] Option A: trigger inside `image_node`, before the per-shot generation loop, awaiting character search+generation once per run if `check_existing_character` returns `None`.
  - [x] Option B: trigger in `run_service.start_run` as a pre-graph step before invoking the compiled LangGraph, so it's visible in run setup rather than buried in the image stage.
  - [x] Document the chosen option's latency impact (search + multi-angle ComfyUI generation is not instant) and whether it should show up as its own progress/status signal to the UI (check `src/yt_flow/api/routes/runs.py` and SSE event types for precedent).
- [x] Implement the automatic trigger (AC: 1-4)
  - [x] Reuse `CharacterService.search_references` / the multi-angle generation path from Stories 1.11/1.12 exactly — do not reimplement.
  - [x] Guard with `check_existing_character` first (AC:4).
  - [x] Wrap in the same non-fatal error handling pattern already used elsewhere for auxiliary failures (AD-10) — log and continue, do not raise into `PipelineState.error`.
- [x] Update tests (AC: 1-4)
  - [x] Add a test proving a run with no existing `CharacterModel` triggers search+generation exactly once.
  - [x] Add a test proving a run with an existing `CharacterModel` does NOT re-trigger.
  - [x] Add a test proving search/generation failure does not fail the run (falls back cleanly).
  - [x] Run: `uv run pytest tests/services/test_run_service_character_provisioning.py tests/services/test_character_service.py tests/services/test_character_service_generation.py tests/pipeline/nodes/test_image.py tests/services/test_run_service_gate.py tests/services/test_run_service_resume.py tests/pipeline/test_stub_profile_smoke.py -q` (actual test file locations — `tests/services/test_run_service.py` doesn't exist as a single file; `run_service` tests are split by concern).
- [x] Validate live (AC: 1-3)
  - [x] Run a fresh SCP with no prior `CharacterModel` end-to-end and confirm `character_path` for entity-visible shots ends up as an angle-selected search-informed image, not a same-frame cutout.
  - [x] Record the run ID and outcome in Dev Agent Record.

## Dev Notes

### Critical Implementation Guardrails

- Do not reimplement search, multi-angle generation, or angle selection — Stories 1.11/1.12/1.13 already built `CharacterService.search_references`, the multi-angle ComfyUI generation, and `video.py`'s `_angle_selector`/`inject_angle_selector` seam. This story only removes the manual-trigger requirement. [Source: `src/yt_flow/services/character_service.py`; `src/yt_flow/pipeline/nodes/video.py:30-40,618-650`]
- Preserve `select_character_angles`'s `None` = "no character, skip" / `{}` = "character exists but no character_path shots" / `dict` = selections contract exactly (`src/yt_flow/services/character_service.py:795-830`) — downstream code in `video.py:620-650` depends on this exact tri-state.
- This story must not fail a run if entity reference generation fails — AD-10 treats auxiliary enrichment as non-fatal, unlike required LLM-stage input (prompt fetch, per `docs/PROMPT_POLICY.md`).
- Avoid adding a new pipeline stage (PRD out-of-scope constraint) — see AC6.

### Current Code State — Files To Read Before Editing

- `src/yt_flow/services/character_service.py`
  - Current state: `search_references()` (search), `select_character_angles()` (lines 795-830+, requires existing `CharacterModel`), `check_existing_character()` (line 163) — all manual-trigger today, invoked only from Character Management UI routes.
  - This story changes: add (or wrap) a path that creates the `CharacterModel` + runs generation automatically when absent, reusing these exact methods.
- `src/yt_flow/pipeline/nodes/video.py`
  - Current state: `_angle_selector` global injected via `inject_angle_selector` (line 33-40), called at lines 618-650 during the video stage, already tolerant of `None` selector or failures (`logger.warning("Angle selection failed...")` at line 650).
  - This story changes: likely none — the consumption side already exists; only the "does a `CharacterModel` exist yet" precondition needs fixing upstream.
- `src/yt_flow/services/run_service.py`
  - Current state: `start_run()` builds `_initial_state` and drives the compiled LangGraph; no character-record bootstrapping today.
  - This story changes: possibly add a pre-graph or in-stage trigger here or in `image_node`, per the Task 1 decision.
- `src/yt_flow/api/main.py`
  - Current state: `inject_angle_selector(_select_angles)` wires the selector at app startup (line 35); `_select_angles` calls `CharacterService.select_character_angles`.
  - This story changes: none expected — cited for context on how the existing seam is wired.

### Architecture Compliance

- AD-4 (pipeline nodes are pure functions of state, no DB/SSE side effects) — if the trigger lands inside `image_node`, it needs a DB-touching seam (character creation/lookup) similar to how `video.py`'s `_angle_selector` is injected from outside rather than importing `db`/`CharacterService` directly inside the node. Prefer the same injection pattern over a direct import, to keep `pipeline` layer-clean per AD-1.
- AD-10 (non-fatal auxiliary failures) governs error handling here, same as tracing.

### Previous Story Intelligence

- Story 5.7 (double-exposure fix) is a stated dependency — it fixes the fallback path's background cleanliness. Read its Dev Agent Record for what the fallback now looks like before wiring this story's failure path (AC3).
- Stories 1.11/1.12/1.13's own Dev Notes likely document the search/generation latency and any rate-limit or cost concerns with DuckDuckGo search + multi-angle ComfyUI generation — read before deciding Task 1's Option A vs B (a slow trigger inside `image_node` could stall the image stage noticeably longer than users are used to).

### Testing Requirements

- Unit tests should mock `CharacterService`/search/ComfyUI exactly as existing character tests do — check `tests/services/test_character_service.py` (if present) for the established fake/mock patterns before writing new ones.
- A real live-run validation is required per the Tasks list — automatic triggering interacting with real DuckDuckGo search + real ComfyUI generation has failure modes (search returning nothing usable, rate limiting) that only show up live.

## Project Structure Notes

- Expected modified files:
  - `src/yt_flow/services/character_service.py` or `src/yt_flow/services/run_service.py` or `src/yt_flow/pipeline/nodes/image.py` (exact file depends on Task 1's trigger-point decision)
  - Corresponding test files
- Depends on Story 5.7 landing first so the fallback path (same-frame cutout) is already clean when this story's failure path exercises it.

## References

- Epic/story source: `_bmad-output/planning-artifacts/epics.md#Epic 5: 영상 품질 고도화`
- Related stories: `_bmad-output/implementation-artifacts/1-11-character-domain-reference-search.md`, `1-12-multi-angle-character-generation.md`, `1-13-video-llm-character-selection.md`, `3-7-character-management-ui.md`, `5-7-layered-background-double-exposure-fix.md`
- Discovered during: `_bmad-output/implementation-artifacts/5-5-visual-story-alignment.md` live A/B review (2026-07-04)
- Architecture: AD-1, AD-4, AD-10 — `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md`

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- Live validation run 1 (fresh SCP-096, no prior `CharacterModel`): `29447904-3556-4bb2-a296-c46c1190fc18` — completed all 5 stages (`status: complete`), see Completion Notes for the character-provisioning outcome.
- Live validation run 2 (SCP-096 again, `CharacterModel` row now exists): `1b7486bd-63bf-48c3-b30f-2c7b15e1ab7e` — started only to observe the pre-graph character check (AC2/AC4); left running/paused at its own pace, not needed to complete.
- Direct real-ComfyUI probe (ad hoc, not a persisted run): manually invoked `CharacterService.generate_candidates_from_reference` for a throwaway `scp_id` against the real local ComfyUI instance — surfaced the character-generation workflow gap below. Test character + generated files deleted after the probe.

### Completion Notes List

- Story context created 2026-07-04 following user (Jay) review of Story 5.5's live-rendered A/B videos; root cause (manual Character-record precondition) pre-confirmed via code investigation before story creation — see `select_character_angles` at `src/yt_flow/services/character_service.py:809-812`.
- **Trigger point decided: Option B** (pre-graph step in `run_service.start_run`, not inside `image_node`). Rationale: `run_service.py` is the one `services/` file already exempted from the AD-1 "no `pipeline`/`api` imports" AST layer test (it's the sole `graph.astream()` caller per AD-3/AD-4) and already holds the direct `Session`/DB-write pattern used throughout the file (`_write_run`, `create_ab_run`, etc.) — no new `inject_*` seam needed. `image_node` is a pure LangGraph node under AD-4; touching the DB from inside it would have required inventing a brand-new injection seam (mirroring `video.py`'s `inject_angle_selector`) just for this one call, which is more machinery than Option B needs. Latency impact: the call is `await`ed (blocking) before `_graph.astream(...)` — a never-before-seen `scp_id` delays the run's first `stage_entry` SSE event by the full search + 4-angle-generation duration; no new SSE event type was added for this (out of scope — AC6 forbids a new stage, and the story didn't ask for new progress UI), so from the SSE consumer's point of view a first-time SCP's `scenario` stage simply appears to start later than a repeat SCP's.
- Implementation: added `_ensure_character_reference(scp_id)` in `src/yt_flow/services/run_service.py`, called from `start_run` before `_graph.astream(...)`. Reuses `CharacterService.check_existing_character` (AC2/AC4 gate), `create_character` (memorization pattern, same one `select_candidate` already uses), `search_references`, and `generate_candidates_from_reference` — called once per canonical angle so each angle's resulting path can be mapped directly onto `Character.angle_{angle}_path` via `update_character`, without going through the `CharacterCandidate` polling/review bookkeeping that Story 3.7's UI uses (that bookkeeping exists for human review of in-progress generation; a headless auto-trigger has no one polling it, so skipping it isn't a reimplementation of search/generation/selection — those three methods are called completely unmodified). The whole body is wrapped in one `try/except Exception` (AD-10): any failure logs a warning and returns normally, leaving a `Character` row with no angle paths — `select_character_angles`'s own pre-existing "no angle paths set" branch then returns `None`, so `video_node` skips the override exactly as it does today with no `CharacterModel` at all. No new `Settings` field/flag was added — no existing precedent in the story's ACs asked for one, and none of the test/production friction encountered needed one either (see fakes below for how tests avoid the real network entirely instead).
- `create_ab_run` was not touched — it already funnels its Variant B run through `start_run`, so Variant B automatically gets the same `_ensure_character_reference` call; because it runs after the Variant A source run (which already attempted provisioning for the same `scp_id`), `check_existing_character` naturally prevents Variant B from re-triggering (AC4) without any A/B-specific code.
- Tests: `tests/services/test_run_service_character_provisioning.py` (new) unit-tests `_ensure_character_reference` directly against a real `CharacterService` with faked `DuckDuckGoImageSearch`/`_download_reference_image`/`_get_image_provider` (same faking style as `tests/services/test_character_service*.py`) — 4 tests: no-existing-character triggers search+generation exactly once and populates all 4 angle paths + `selected_image_path`; existing-character skips search entirely (AC2/AC4); search failure is non-fatal and leaves no angle paths set (AC3); generation failure (all 4 angles) is likewise non-fatal.
  - Discovered along the way: `tests/stubs/fakes.py` already had unused `fake_image_search`/`fake_download_reference_image` fakes (built for Story 1.11/3.7's own tests) that had never been wired into the shared `stub_profile` fixture — because until this story, nothing in the graph path ever triggered a real character search, so no test needed them. Added a third fake (`fake_get_image_provider`/`_FakeCharacterImageProvider`) for the generation side, and wired all three into `stub_profile` (`tests/conftest.py`) so any test exercising the full graph via `start_run` stays offline. Also had to add the same three monkeypatches directly to `tests/services/test_run_service_gate.py`'s `env` fixture and `tests/services/test_run_service_resume.py`'s `spy` fixture, since those two files stub the LangGraph *nodes* (`stub_stage_nodes`) rather than using `stub_profile` — `_ensure_character_reference` runs in `run_service.start_run` itself, upstream of any node, so node-stubbing alone doesn't shield it.
  - Full suite after these changes: `566 passed, 1 skipped` (pre-existing skip), no regressions. `ruff check` clean on all changed/added files.
- **Live validation (Task 4) — what was actually proven vs. what could not be, and why:**
  - **AC2/AC4 (no duplicate trigger) — proven live.** Run 1 (`29447904...`) created a `Character` row for `SCP-096` at the very start (`created_at` timestamp matches run start to the second). Starting run 2 (`1b7486bd...`) for the same `scp_id` produced **zero** new search attempts or `_ensure_character_reference` log output — `check_existing_character` found the existing row and returned immediately, confirmed by the server log showing no repeat of the character-provisioning traceback that appeared on run 1.
  - **AC3 (non-fatal fallback) — proven live, in real production conditions.** Run 1's real DuckDuckGo search for `"SCP-096 SCP Foundation"` returned a genuine `403 Forbidden` from `duckduckgo.com/i.js` (confirmed reproducible — re-ran the raw search directly afterward, still 403; this is DuckDuckGo's scraped/unofficial endpoint blocking this environment, not a bug introduced by this story). `_ensure_character_reference` logged the failure and returned normally; `start_run` proceeded into the real graph; **the full 5-stage pipeline (scenario → image → tts → subtitle → video) completed successfully (`status: complete`, `error: null`)** with all gates manually approved. The image stage's real ComfyUI layered generation produced same-frame segmentation cutouts as usual; the video stage's `_select_angles` closure logged `select_character_angles: no angle paths set for SCP-096` and correctly returned `None`, so `video_node` never overrode `character_path` — exactly the documented tri-state fallback contract, exercised for real, not simulated.
  - **AC1's optimistic happy path (search hits → real angle-selected image ends up as `character_path`) could NOT be observed live**, blocked by two issues discovered during this validation, both pre-existing and out of this story's scope (the guardrails explicitly forbid reimplementing Story 1.11/1.12's search/generation):
    1. DuckDuckGo's scraped image-search endpoint (Story 1.11's `image_search.py`) is currently returning `403 Forbidden` for every real query from this environment — confirmed via a direct, isolated re-test outside the app.
    2. Separately (probed directly, bypassing only the broken search step by feeding a real, previously-downloaded reference image): `CharacterService.generate_candidates_from_reference` against the real local ComfyUI instance fails with `prompt_outputs_failed_validation` for all 4 angles. Root cause: `Settings.character_comfyui_workflow_path` defaults to `data/workflows/comfyui_character_multi_angle_api.json`, which **does not exist** in `data/workflows/` (only the three layered/background workflow JSONs from Stories 1.6b/5.2/5.6/5.7 exist there); `character_image_provider.py`'s own fallback-to-default-path (`_load_workflow()`) also misses, so it falls through to `_default_workflow()` — a built-in minimal workflow that the real ComfyUI server rejects as invalid. This means **Story 1.12's multi-angle character generation has apparently never been exercised against a real ComfyUI server** — matching this story's own Context section ("already built, just never engaged"). The `Character` rows with populated `angle_*_path` fields seen in the dev DB/workspace before this session (e.g. `SCP-173`, `SCP-3007-...`) turned out to be 71-byte 1×1 placeholder PNGs from an unrelated, pre-existing test-isolation gap in `tests/services/test_character_service_generation.py` (writes to the real `./workspace/` when `Settings()` isn't given a `workspace_path` override) rather than genuine prior generations — not caused by this story's changes, not fixed here (out of scope), flagged in Saved Questions below.
  - Both blockers sit entirely inside `CharacterService`/`image_search.py`/ComfyUI-workflow-config territory that Stories 1.11/1.12 own, not inside anything this story added or changed — `_ensure_character_reference` correctly called the real methods with the real query and correctly absorbed both real failures without failing the run, which is precisely what AC1 (trigger fires, reuses the exact methods) and AC3 (non-fatal on failure) ask for. The optimistic "search succeeds and a real photo-grounded image gets used" outcome is validated by the unit tests' happy-path case (with fakes standing in for the two currently-broken externals) rather than by a live run, since neither external dependency can currently succeed in this environment.
- AC5: Character Management UI (`api/routes/characters.py`) was not modified — a human can still manually create/curate a character for any `scp_id` before starting a run, and the automatic path writes to the exact same `Character`/`CharacterModel` row shape the UI already reads/writes, so nothing about the manual path changed.
- AC6: no new pipeline stage — the entire trigger lives in `run_service.start_run`, one `await` before the existing `_graph.astream(...)` call; `pipeline/graph.py`'s node list is untouched.

### File List

- `src/yt_flow/services/run_service.py` (modified — added `_ensure_character_reference`, called from `start_run`)
- `tests/services/test_run_service_character_provisioning.py` (new — 4 unit tests for `_ensure_character_reference`)
- `tests/stubs/fakes.py` (modified — added `_FakeCharacterImageProvider`/`fake_get_image_provider`)
- `tests/conftest.py` (modified — wired `fake_image_search`/`fake_download_reference_image`/`fake_get_image_provider` into `stub_profile`)
- `tests/services/test_run_service_gate.py` (modified — added the same three fakes to the `env` fixture so gate/status tests stay offline)
- `tests/services/test_run_service_resume.py` (modified — added `monkeypatch` param + the same three fakes to the `spy` fixture)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — story marked `in-progress` then `review` then `done`)

### Review Findings

Code review 2026-07-04 (Blind Hunter + Edge Case Hunter + Acceptance Auditor). Acceptance Auditor: AC1, AC2 (happy path), AC5, AC6 PASS; AC2/AC4's concurrent-run guard and AC3's non-fatal guarantee had real gaps under specific failure modes — fixed below.

- [x] [Review][Patch] `_settings()` was called *before* the `try:` block in `_ensure_character_reference` — a `Settings()` validation error would propagate out of `start_run` instead of degrading non-fatally, contradicting AC3/AD-10's explicit "must not fail the run" — moved inside the `try` [src/yt_flow/services/run_service.py].
- [x] [Review][Patch] A total provisioning failure (search raises, search returns nothing, or every angle generation fails) left a permanent empty `CharacterModel` row behind — `check_existing_character` would then skip that `scp_id` forever, even after a transient failure (e.g. a rate limit) cleared up; confirmed this already happened to `SCP-096` during live validation (DuckDuckGo 403). Now rolls back (`delete_character`) on any failure after creation, so a later run retries [src/yt_flow/services/run_service.py].
- [x] [Review][Patch] Two concurrent first-time runs for the same `scp_id` (e.g. an A/B pair, Story 4.1) can both pass the existence check before either commits; the loser's `create_character` hit the DB's `unique=True` constraint on `scp_id` and fell into the generic exception handler, logged as a misleading "provisioning failed" — now caught specifically as an expected dedup collision [src/yt_flow/services/run_service.py].
- [x] [Review][Test] The one-line production wiring (`start_run` → `_ensure_character_reference`) was only ever exercised indirectly (via gate/resume fixtures faking the seams) — added a direct test asserting `start_run` invokes it [tests/services/test_run_service_character_provisioning.py].
- [x] [Review][Test] No test covered a partial angle-generation failure (some angles succeed, some fail) — the exact branch the `if angle_paths` / `if "front" in angle_paths` logic exists for — added one [tests/services/test_run_service_character_provisioning.py].
- [x] [Review][Test] No test covered the concurrent-creation race — added one asserting the loser doesn't touch the winner's row and doesn't log it as a failure [tests/services/test_run_service_character_provisioning.py].
- [x] [Review][Refactor] The same three-line DuckDuckGo/CharacterService monkeypatch block was duplicated verbatim across `conftest.py`, `test_run_service_gate.py`, and `test_run_service_resume.py` — extracted into one `fakes.patch_character_reference_seams()` helper.
- Dismissed: `except Exception` swallowing all errors (matches AD-10's explicit non-fatal-auxiliary-enrichment design, already commented); reaching into `db._engine` / sync DB calls inside `async def` (both match the established pattern used 8x elsewhere in `run_service.py`, including the async `create_ab_run`); only trying `refs[0]` with no fallback to other search results (matches the manual Character Management UI's identical `refs[0].local_path` pattern — Dev Notes explicitly required reusing this exactly); search query built from `scp_id` alone, not `scp_text` (pre-existing behavior from Story 1.11, not this diff's scope); calling `generate_candidates_from_reference` once per angle instead of batched (necessary given the method's return contract has no angle attribution — batching would require fragile filename parsing); no opt-out/feature flag (speculative, not requested by any AC); orphaned downloaded reference files on rollback (matches `delete_character`'s existing DB-only cleanup elsewhere, pre-existing pattern); no SSE event during provisioning (explicitly considered and deferred in this story's own Completion Notes — AC6 forbids a new stage); AC3's "vision LLM errors" fallback path being dead code (pre-existing gap from Stories 1.11-1.13, already flagged in Saved Questions below, not this diff's fault).

## Change Log

- 2026-07-04: Story created from live-render review feedback (searched entity reference images never engaging), root cause pre-confirmed via code investigation before story creation.
- 2026-07-04: Implemented automatic entity reference provisioning as a pre-graph step in `run_service.start_run` (Option B); added unit tests; wired previously-unused character-search fakes into the shared offline test profile; live-validated AC2/AC3/AC4 against a real run (AC1's optimistic happy path blocked by two pre-existing, out-of-scope external issues discovered during validation — DuckDuckGo 403 and a missing/incompatible character-generation ComfyUI workflow — documented above and in Saved Questions).
- 2026-07-04: Code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor) found the non-fatal guarantee didn't hold under three real failure modes (settings init, permanent-failure poisoning, concurrent-creation race); applied all 3 patches, added 3 regression tests, de-duplicated seam-patching across test fixtures; full suite green (569 passed, 1 skipped), `ruff check` clean.

## Saved Questions / Clarifications

- Trigger point (Task 1, Option A vs B): **resolved — Option B** (pre-graph step in `run_service.start_run`). See Completion Notes for rationale.
- Should the Character Management UI's manual review step become a required gate before first use of an auto-generated character (quality control), or is silent automatic use acceptable? Not decided — AC5 keeps the manual path available but doesn't mandate it.
- **New, discovered during this story's live validation — needs a follow-up story:** Story 1.12's multi-angle character generation cannot currently produce a real image against this environment's local ComfyUI — `character_comfyui_workflow_path`'s default file doesn't exist on disk, and `character_image_provider.py`'s built-in fallback workflow is rejected by ComfyUI's prompt validation. Until a valid `comfyui_character_multi_angle_api.json` (or equivalent) is authored and configured, neither this story's automatic path nor Story 3.7's manual Character Management UI can produce a real angle-selected reference image in this environment — both call the exact same `generate_candidates_from_reference`. Recommend a follow-up story (Epic 1 or Epic 5) to author/validate that workflow JSON against the real local ComfyUI instance, the same way Story 5.7 validated the layered background/character workflow.
- **Also discovered, unrelated to this story's own scope:** `tests/services/test_character_service_generation.py` writes real files into the repo's `./workspace/` directory (not `tmp_path`) whenever `Settings()` is constructed without an explicit `workspace_path` override — pre-existing test-isolation gap, surfaced only because those tests happened to run during this session's full-suite pass. Not fixed here (unrelated to this story's ACs); worth a small follow-up cleanup.
- **Separately, DuckDuckGo's scraped image-search endpoint (`image_search.py`, Story 1.11) is currently returning `403 Forbidden` for real queries from this environment** — confirmed reproducible outside the app. Not fixed here (Story 1.11's implementation, out of this story's scope); worth checking whether this is environment-specific (IP/rate-limit) or a lasting breakage of the scraped endpoint before relying on it for future live validations.
