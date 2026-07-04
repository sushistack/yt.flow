---
created: 2026-07-04
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

Status: ready-for-dev

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

- [ ] Decide the trigger point (AC: 1, 6) — read `src/yt_flow/services/run_service.py::start_run` and `src/yt_flow/pipeline/nodes/image.py::image_node` fully before choosing.
  - [ ] Option A: trigger inside `image_node`, before the per-shot generation loop, awaiting character search+generation once per run if `check_existing_character` returns `None`.
  - [ ] Option B: trigger in `run_service.start_run` as a pre-graph step before invoking the compiled LangGraph, so it's visible in run setup rather than buried in the image stage.
  - [ ] Document the chosen option's latency impact (search + multi-angle ComfyUI generation is not instant) and whether it should show up as its own progress/status signal to the UI (check `src/yt_flow/api/routes/runs.py` and SSE event types for precedent).
- [ ] Implement the automatic trigger (AC: 1-4)
  - [ ] Reuse `CharacterService.search_references` / the multi-angle generation path from Stories 1.11/1.12 exactly — do not reimplement.
  - [ ] Guard with `check_existing_character` first (AC:4).
  - [ ] Wrap in the same non-fatal error handling pattern already used elsewhere for auxiliary failures (AD-10) — log and continue, do not raise into `PipelineState.error`.
- [ ] Update tests (AC: 1-4)
  - [ ] Add a test proving a run with no existing `CharacterModel` triggers search+generation exactly once.
  - [ ] Add a test proving a run with an existing `CharacterModel` does NOT re-trigger.
  - [ ] Add a test proving search/generation failure does not fail the run (falls back cleanly).
  - [ ] Run: `uv run pytest tests/pipeline/nodes/test_image.py tests/services/test_character_service.py tests/test_run_service.py -q` (adjust paths to actual test file locations).
- [ ] Validate live (AC: 1-3)
  - [ ] Run a fresh SCP with no prior `CharacterModel` end-to-end and confirm `character_path` for entity-visible shots ends up as an angle-selected search-informed image, not a same-frame cutout.
  - [ ] Record the run ID and outcome in Dev Agent Record.

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

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

- Story context created 2026-07-04 following user (Jay) review of Story 5.5's live-rendered A/B videos; root cause (manual Character-record precondition) pre-confirmed via code investigation before story creation — see `select_character_angles` at `src/yt_flow/services/character_service.py:809-812`.

### File List

## Change Log

- 2026-07-04: Story created from live-render review feedback (searched entity reference images never engaging), root cause pre-confirmed via code investigation before story creation.

## Saved Questions / Clarifications

- Trigger point (Task 1, Option A vs B) is not decided — needs the dev agent (or Jay) to weigh latency impact vs. visibility before implementing.
- Should the Character Management UI's manual review step become a required gate before first use of an auto-generated character (quality control), or is silent automatic use acceptable? Not decided — AC5 keeps the manual path available but doesn't mandate it.
