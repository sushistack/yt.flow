---
story_key: 13-1-surface-silent-degradations
epic: 13
story: 1
status: ready-for-dev
created: 2026-08-03
updated: 2026-08-08
depends_on:
  - 12-3-pass2-verdict-grounded-gate
---

# Story 13.1: Surface Silent Degradations at Human Gates

Status: ready-for-dev

## Story

As the **yt.flow operator (Jay)**,
I want every non-fatal quality degradation recorded on the run and shown at human gates,
so that I can distinguish a clean result from a fallback result before approving the pipeline without turning best-effort subsystems into run failures.

## Acceptance Criteria

1. **Checkpoint-owned warning contract**
   - Given a best-effort path degrades instead of failing, when its producer returns or the service updates the paused graph, then a JSON-serializable `RunWarning` is appended to `PipelineState.run_warnings`.
   - `RunWarning` has a stable closed `code`, `stage`, short Korean operator-readable `message`, and optional bounded `context` containing identifiers such as `scene_num`, `shot_id`, `card_key`, `location_key`, `pose_hint`, or `failed_count`. Raw provider/exception text is diagnostic context only and is not rendered as primary UI copy.
   - `run_warnings` is `NotRequired` and all readers use `state.get("run_warnings", [])`, so pre-13.1 checkpoints remain readable.
   - Warning order is deterministic. Repeated execution of the same gate/retry path does not create duplicates; identity is based on stable code + stage + identifying context, not exception text.

2. **Active degradation producers are covered**
   - Given one of the following active runtime paths occurs, when the run reaches its next gate, then at least one specific warning is present while the existing fallback output is preserved:
     - character reference/vision enrichment cannot provide a descriptor or provisioning fails;
     - `special_pose_max_per_run` or `derived_entity_max_per_run` skips requested cards, or their generation fails;
     - declared cast members cannot be resolved, a resolver fails wholesale, a card record is malformed, or angle/pose resolution uses fallback metadata;
     - a requested stock `location_key` has no approved plate, the resolver is unavailable/not injected, or plate resolution/copy fails and image generation is used instead;
     - Tier-3 relight precomputation reports failures/skips, the resolver is unavailable/not injected or raises, an eligible card/location asset fails verification, or a relit sprite is invalid/unreadable and the original sprite is used;
     - WhisperX alignment fails/reconciliation returns no usable alignment and subtitle timing falls back to provisional timings.
   - Records include the narrowest identifiers available. Aggregate-only sources such as relight stats include counts; per-shot/per-card sources include scene, shot, and card identifiers.
   - Intentional non-applicability is warning-free: no `location_key`, harmonization tier below 3, the explicit `qwen_tts_mock` alignment bypass, or a special/derived provisioning bypass that exists only because `comfyui_mock=True` is not itself a degradation. Do not globally suppress plate/cast warnings merely because a run uses `comfyui_mock`; genuine downstream missing/fallback outcomes still warn.

3. **Non-fatal and fatal contracts remain distinct**
   - Given any covered degradation, when processing continues, then run/stage status, fallback output, gate topology, and retry behavior remain unchanged; warnings never populate `PipelineState.error` and never convert the run to `failed`.
   - Existing hard failures remain hard failures, including missing required stage assets and opaque/non-RGBA character cards that violate the compositing contract.
   - Story 5.11's segmentation/`layered_fallback` path is historical only: Story 8.3 retired layered image generation and removed that runtime path. This story must not reintroduce segmentation, `background_path`, `character_path`, or `layered_fallback`. The stale frontend-only `layered_fallback` DTO/indicator is removed or replaced by the generic run-warning UI.

4. **Warnings reach the human gate through existing contracts**
   - Given warnings exist in checkpoint state, when a gate calls `interrupt()`, then its JSON-serializable payload includes `{"stage": stage, "warnings": [...], "warning_count": N}`.
   - Story 12.3 already adds `scenario_quality` to the scenario-gate payload when final review remains unresolved. The generic warning keys are additive: `gate_scenario` preserves `scenario_quality`, and gates with no existing stage-specific context retain only the base stage/warning keys.
   - The existing `gate_pending` SSE data uses the same `warnings` and `warning_count` keys, but no fifth SSE event type is introduced.
   - `GET /runs/{id}/stages/{stage}/artifacts` includes `warnings: RunWarning[]` for every stage DTO, returning `[]` for legacy/no-warning states. Scenario artifacts continue returning `scenario_quality` independently.
   - No `Run` SQLModel column, migration, warning table, or second persistence source is added. The `runs` table remains a status/gate projection; LangGraph checkpoint state remains authoritative.

5. **Gate UI makes degradation visible and actionable**
   - Given an artifact response has one or more warnings, when the Artifact Panel is shown, then its header displays a compact Korean badge such as `⚠ 경고 N건` and a scannable list with the warning message and available scene/shot/card identifiers.
   - The warning treatment uses neutral Zinc tokens (`border-border`, `bg-card`, `text-foreground`) plus icon + text + count (never color alone), no new icon dependency, and short Korean operator microcopy. Do not repurpose `status-running`, `status-awaiting`, `status-approved`, or `status-failed`; those colors retain their existing state meanings.
   - The badge/list is additive: the existing Story 12.3 `2차 검토 경고`, pending Approve/Reject controls, retry, editing, lightbox/media rendering, sidebar gate state, focus behavior, and `aria-current` remain unchanged. A run warning is not a new gate state and does not replace scenario-review evidence or pending/approved/rejected/failed styling.
   - On `gate_pending`, the current artifact data refreshes so warnings written by the just-completed stage appear without a manual page reload.

6. **Resume, retry, and restart semantics are explicit**
   - Warnings survive checkpoint persistence, normal gate resume, and stage retry as a run-wide degradation history.
   - Repeated paths are deduplicated rather than appended again. The UI copy makes clear these warnings occurred during the run, not necessarily in every retry attempt.
   - Full restart creates a fresh `run_warnings` collection together with the existing fresh graph state. No warning from the deleted checkpoint leaks into the restarted attempt.
   - Adding warnings while the scenario gate is paused uses the service-owned LangGraph state/resume mechanism and is verified against the pinned LangGraph version; it must not change the next node, consume the pending interrupt, or execute pre-interrupt side effects twice.

7. **Verification closes the old observability gap**
   - Backend tests force each covered degradation and assert all three facts together: fallback still succeeds, a structured warning is in checkpoint/node output, and the warning reaches gate/artifact payloads.
   - Tests cover legacy state with no `run_warnings`, deterministic ordering/deduplication, warning-free happy/config-disabled/mock paths, additive gate payload changes including `scenario_quality` preservation, and full-restart reset.
   - Frontend tests cover zero/one/multiple warnings, Korean accessible text, identifiers, gate controls remaining operable, and refresh after `gate_pending`.
   - Targeted suites, full backend regression, Ruff, frontend Vitest, and TypeScript build are green. No live GPU run is required for warning plumbing; do not fabricate live evidence. If a real existing checkpoint is used, record the command and observed warning payload.

## Tasks / Subtasks

- [ ] Task 1: Define the warning state contract and deterministic merge behavior (AC: 1, 3, 6)
  - [ ] Add `RunWarningCode`/`RunWarning` to `src/yt_flow/domain/state.py`; add `run_warnings: NotRequired[list[RunWarning]]` to `PipelineState`.
  - [ ] Add a small pure domain helper (recommended: `src/yt_flow/domain/warnings.py`) that merges immutable lists, preserves first-seen order, and deduplicates by stable code/stage/identifier context.
  - [ ] Use only JSON-safe primitives in context. Bound exception details; do not store exception objects, paths containing secrets, arbitrary provider response bodies, or unbounded payloads.
  - [ ] Update the exact type-shape/import guard tests in `tests/domain/test_state_imports.py`.

- [ ] Task 2: Seed and merge service-side provisioning warnings (AC: 1, 2, 3, 6)
  - [ ] Add an optional bounded diagnostic/warning collector seam to `CharacterService.enrich_descriptor_from_references()` and thread it through `generate_cards_from_descriptor()` without breaking existing `str | None` callers. This reports failed/empty enrichment even when the method returns an existing descriptor and card generation succeeds.
  - [ ] Change `_ensure_character_reference()` to collect/return warnings for missing enrichment/provisioning outcomes while preserving its best-effort envelope and empty-stub rollback. Seed those warnings through `_initial_state()` in `start_run()`.
  - [ ] Change `_ensure_special_pose_cards()` and `_ensure_derived_entity_cards()` to return structured cap/generation warnings naming every skipped/failed key. The derived-entity path passes the collector through `generate_cards_from_descriptor()` so a swallowed enrichment failure is not lost merely because image generation succeeds.
  - [ ] In `resume_run()` scenario approval, merge provisioning warnings into the paused checkpoint/resume update through the existing service-owned graph seam. Verify the pending interrupt and next-node behavior using the real pinned LangGraph package, not only a fake graph.
  - [ ] Keep A/B start, failure resume, retry, and full restart behavior aligned; initialize/reset warning state deliberately.

- [ ] Task 3: Instrument current pipeline fallback branches (AC: 1, 2, 3)
  - [ ] `image_node`: record plate-missing/resolver-unavailable/resolution-failed warnings while retaining generated-background fallback. Emit one deterministic warning per affected shot; identity includes code + stage + scene + shot + location, so the lookup remains cached without dropping affected-shot evidence.
  - [ ] `subtitle_node`: record a warning on real WhisperX-to-provisional fallback; `qwen_tts_mock=True` remains an intentional INFO-only path.
  - [ ] `video_node`: compare declared cast with resolved cards to surface missing rows/assets; translate resolver failure, malformed results, returned angle/pose fallback metadata, relight failed counts, resolver failure, and invalid/unreadable relit substitution into warnings while preserving background/original-card rendering.
  - [ ] Extend `precompute_relights()` diagnostics so every Tier-3 eligible pair/shot that falls back is accounted for: failed render, unverified location/card asset, unsafe/malformed metadata, or another skipped pair. Keep orchestration single-sourced; return bounded identifiers plus computed/failed/skipped counts for `video_node` to translate into warnings.
  - [ ] Keep existing logger warnings and trace counters where useful; structured state is additive and is the gate-facing authority.

- [ ] Task 4: Expose warnings through gates, SSE, and artifact DTOs (AC: 4, 6)
  - [ ] Extend `gates._gate()` interrupt payload with accumulated warnings/count while preserving the existing scenario-only `scenario_quality` field. Do not mutate warning state immediately before `interrupt()`; the gate only reads persisted collections.
  - [ ] Extend `_consume()`'s existing `gate_pending` payload rather than adding an event type.
  - [ ] Add `warnings` to every `get_stage_artifacts()` response and every frontend `StageArtifacts` variant/shared base.
  - [ ] Preserve the four-event SSE convention and avoid changes to `Run`, database models, migrations, or `RunRead` unless implementation proves the existing artifact/gate path cannot meet the AC (escalate rather than silently creating dual authority).

- [ ] Task 5: Replace the stale layered-fallback frontend warning with generic gate warnings (AC: 3, 5)
  - [ ] Add the shared `RunWarning` TypeScript type in `frontend/src/lib/api.ts` or `frontend/src/lib/types.ts` and remove stale `layered_fallback` DTO dependence. Render the backend's short Korean `message`; never promote raw exception/provider detail to primary UI text.
  - [ ] Add a reusable warning summary inside `ArtifactPanel`: `⚠ 경고 N건`, short messages, identifiers, accessible semantics, existing status tokens, no icon package. Keep the existing `ScenarioQualityWarning` component and render both when both contracts are present.
  - [ ] Ensure `RunDetail` refetches artifacts after `gate_pending`; change logic only if the existing `run` state update does not already trigger the fetch.
  - [ ] Preserve all current gate, retry, editor, media, and lightbox behavior.

- [ ] Task 6: Add cross-layer regression evidence (AC: 7)
  - [ ] Domain/gate: warning shape, JSON serialization, legacy state, additive interrupt payload with `scenario_quality` preservation, deterministic merge/dedupe.
  - [ ] Service: enrichment, special-pose/derived caps and failures, scenario-approval checkpoint merge, artifact DTO exposure, retry persistence, restart reset.
  - [ ] Pipeline: stock plate hit/miss/error, WhisperX success/fallback/mock, cast resolver success/failure/missing/malformed/fallback, relight success/failure/invalid output, hard RGBA failure unchanged.
  - [ ] Frontend: zero/one/multiple warnings, accessible Korean badge/list, controls remain functional, gate-pending refresh.
  - [ ] Run `PYTHONPATH=$PWD/src uv run pytest tests/`, `uv run ruff check src tests`, `npm test`, and `npm run build` from `frontend/`; report actual results without claiming unavailable GPU validation.

## Dev Notes

### Implementation Spine

`PipelineState.run_warnings` is the only warning authority:

```text
best-effort producer
  -> immutable structured warning in LangGraph checkpoint
  -> gate interrupt + existing gate_pending payload
  -> existing stage-artifact response
  -> ArtifactPanel warning badge/list
```

Do not add a warnings table, write warnings from pipeline nodes to the DB, or overload `gate_states`. Warnings describe output quality/provenance; they are not failures and not gate decisions.

This spine is parallel to, not a replacement for, Story 12.3's `scenario_quality` contract. `scenario_quality` describes final scenario review/critic evidence from generation; `run_warnings` describes runtime fallback/degradation history across stages. Both remain checkpoint-owned and may appear together at the scenario decision point.

`RunWarningCode` is the following exact `Literal` vocabulary; backend, frontend, and tests use these values without aliases:

| Code | Producer | Stage ownership |
|---|---|---|
| `vision_enrichment_failed` | pre-graph character provisioning | `scenario` |
| `character_provisioning_failed` | pre-graph character provisioning | `scenario` |
| `special_pose_cap_exceeded` / `special_pose_generation_failed` | scenario approval provisioning | `scenario` |
| `derived_entity_cap_exceeded` / `derived_entity_generation_failed` | scenario approval provisioning | `scenario` |
| `stock_plate_resolver_unavailable` / `stock_plate_missing` / `stock_plate_resolution_failed` | `image_node` | `image` |
| `subtitle_alignment_fallback` | `subtitle_node` | `subtitle` |
| `cast_resolution_failed` / `cast_card_missing` / `cast_card_fallback` | `video_node` | `video` |
| `relight_resolver_unavailable` / `relight_pair_skipped` / `relight_failed` / `relit_sprite_invalid` | `video_node` + relight diagnostics | `video` |

The `stage` is the pipeline stage that owns/operator-reviews the condition, not necessarily the Python function's layer. Provisioning warnings are assigned to `scenario` because they occur before or directly after its human decision and are not regenerated by ordinary image/video retry.

### Current Code State — UPDATE Files

- `src/yt_flow/domain/state.py`
  - Current: JSON-serializable TypedDict substrate; `PipelineState` ends with optional `ending_credit_error` and has no warning field.
  - Change: add warning types and a legacy-safe optional collection.
  - Preserve: stdlib-only domain layer and existing TypedDict field meanings.

- `src/yt_flow/services/run_service.py`
  - Current: `get_stage_artifacts()` reads the checkpoint; `_initial_state()` owns fresh state; `_consume()` converts interrupts to `gate_pending`; character/special-pose/derived provisioning logs and swallows degradation; `resume_run()` invokes post-scenario provisioning.
  - Change: seed/merge warnings, expose them in artifacts/SSE, and reset only on full restart.
  - Preserve: service-only `astream`/state-update authority, `asyncio.to_thread` around sync DB writes, gate routing, rollback of incomplete character stubs, and all non-fatal envelopes.

- `src/yt_flow/services/character_service.py`
  - Current: `enrich_descriptor_from_references()` catches provider/HTTP failures and may return an existing descriptor or `None`; `generate_cards_from_descriptor()` consumes it, so successful card generation can hide failed enrichment from its caller.
  - Change: add an optional backward-compatible diagnostic collector and thread it through derived-card generation.
  - Preserve: existing `str | None` return contract, non-fatal enrichment semantics, database rollback behavior, and callers with no run context.

- `src/yt_flow/pipeline/gates.py`
  - Current: every gate payload contains `stage`; the scenario gate also includes `scenario_quality` when present, then validates the resumed decision and replaces the complete `gate_states` dict.
  - Change: read warnings/count into the interrupt payload without removing stage-specific context.
  - Preserve: no side effects before interrupt, decision validation, and full-dict gate-state merge.

- `src/yt_flow/pipeline/nodes/image.py`
  - Current: approved stock plate fast path; missing/error resolution logs then generates a normal background; no segmentation/layered branch exists.
  - Change: add structured warnings to those active fallback branches.
  - Preserve: deterministic SHA-256 plate selection, one lookup per location key, resume sidecars, ComfyUI health/recovery, and `image_path`-only output.

- `src/yt_flow/pipeline/nodes/subtitle.py`
  - Current: always attempts WhisperX, writes aligned or provisional timings back, logs real fallback, and records aggregate trace counts; mock audio intentionally skips alignment.
  - Change: convert only real fallback to structured warning state.
  - Preserve: alignment never fails the stage, mock skip stays warning-free, timing/cue invariants and write-back.

- `src/yt_flow/pipeline/nodes/video.py`
  - Current: cast resolution may degrade wholesale or omit cards; hard alpha validation remains fatal; Tier-3 relight failures use original sprites; final trace records cast/relight aggregates.
  - Change: produce structured warnings from existing outcomes and declared-vs-resolved comparison.
  - Preserve: per-shot cut planning, cards that survive the clip plan, original-card fallback, all FFmpeg behavior, and hard RGBA validation.

- `src/yt_flow/pipeline/nodes/composite_harmonization.py`
  - Current: per-pair render failures are isolated and summarized as `{computed, failed}`, but asset-verification and malformed/unsafe metadata skips are not counted.
  - Change: return bounded diagnostics for every eligible pair/shot that falls back, including skipped verification/metadata paths.
  - Preserve: per-pair isolation, cache safety, concurrency bound, and original-sprite fallback.

- `frontend/src/lib/api.ts`, `frontend/src/components/ArtifactPanel.tsx`, `frontend/src/pages/RunDetail.tsx`
  - Current: stage DTO union and gate panel; Story 12.3 already defines and renders `ScenarioQuality`, while a stale image-only `layered_fallback` indicator remains after backend retirement.
  - Change: shared run-warnings DTO and generic warning summary/refetch behavior; preserve the scenario-quality DTO and warning block.
  - Preserve: same-origin API client, no ad-hoc fetches, Korean UI, two-column layout, and existing control lifecycle.

### Explicitly Out of Scope

- Reintroducing layered generation, segmentation, or the Story 5.11 flat-fallback field.
- Converting warnings into failures, automatic rejection, or approval blocking.
- New pipeline stages, warning persistence tables, migrations, WebSockets, or new SSE event types.
- Solving the underlying optional-subsystem failures (generating more plates/cards, replacing providers, implementing IC-Light). This story surfaces them.
- Epic 13.2 evaluation axes, 13.3 ComfyUI provenance/workflow manifests, and 13.4 A/B gate unfreeze.
- Ending-credit errors: already exposed by the existing video artifact contract; do not duplicate them unless the generic UI can consume the existing field without changing semantics.

### Architecture Compliance

- AD-1: `api -> services -> (pipeline | db) -> domain`; pipeline nodes never write DB/SSE and API never imports pipeline.
- AD-2/AD-7: warnings live in `PipelineState`/AsyncSqliteSaver and are read through the existing artifact path; `runs` remains a projection.
- AD-3/AD-4: fixed five-gate topology remains; services alone drives/resumes the graph and fans out SSE.
- State mutation: return/submit full replacement warning lists; never mutate input state in place.
- The architecture spine says no reducers for this sequential graph. Do not add `Annotated[..., operator.add]`: explicit merge/dedupe is required for retry idempotency.
- NFR: no new dependency and negligible work relative to the two-hour pipeline ceiling; structured warnings must not add material observability overhead.

### Previous Story and Git Intelligence

- Story 12.3 is the direct delivery-path precedent. It added checkpoint-owned `scenario_quality`, scenario-gate interrupt context, `gate_pending` forwarding, durable scenario-artifact reload, explicit refresh on gate pending, and the accessible `2차 검토 경고` block. Reuse its checkpoint → gate/SSE → artifact → UI spine, but keep `run_warnings` semantically separate and additive.
- Story 5.11 established per-item degradation metadata, artifact DTO propagation, and frontend warning rendering. Its review found three recurring mistakes to prevent here: losing the original error, undercounting attempts, and omitting `scene_num` from ambiguous warnings.
- Story 8.3 later retired that entire segmentation/layered path. Its current architecture wins; remove stale frontend assumptions rather than resurrecting backend fields.
- Stories 8.4/8.13 show cap overflow and swallowed card generation can produce empty-room output; name every skipped key and verify required artifacts after best-effort generation.
- Story 8.5 shows optional lookup/copy boundaries must stay isolated and deterministic; retain SHA-256 selection and cache semantics.
- Story 8.7 shows per-pair relight isolation and aggregate stats already exist; reuse them.
- Story 8.15 shows a fake provider can fall into a broad `except` while the suite remains green. Require an end-to-end seam assertion that a forced provider failure reaches the gate artifact, not only `caplog`.
- Story 8.17 proves schema/service completion is not output evidence. Tests must assert the warning is actually present at the human review boundary.
- Story 11.4 already made WhisperX fallback visible in logs/traces but not the gate UI; 13.1 completes that path.
- Recent commits are story-scoped, followed by separate adversarial review fixes. Preserve unrelated untracked `.serena/` content and do not include it in this story.

### Library / Framework Requirements

- Repository pins are authoritative: Python 3.12, LangGraph 1.2.7, `langgraph-checkpoint-sqlite` 3.1.0, FastAPI 0.138.2, SQLModel 0.0.39, Langfuse 4.12.0, React 18.3.1, Tailwind 4.3.2, Vitest 3.2.6.
- No package upgrade is required. The architecture document's older version table is superseded by `pyproject.toml`/`frontend/package.json`.
- Official LangGraph guidance confirms interrupt payloads must be JSON-serializable, state is checkpointed while paused, and a resumed node restarts from its beginning; side effects before `interrupt()` therefore must be idempotent. Gate code should only read already-persisted warnings. [Official LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- Official Graph API documentation supports reducers, but this project intentionally uses explicit whole-field replacement in a sequential graph. Follow the project invariant. [Official LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api)

### Testing Requirements

Primary files:

- `tests/domain/test_state_imports.py`
- `tests/pipeline/test_gates.py`
- `tests/api/test_stage_artifacts.py`
- `tests/pipeline/nodes/test_image.py`
- `tests/pipeline/nodes/test_subtitle.py`
- `tests/pipeline/nodes/test_video.py`
- `tests/pipeline/nodes/test_video_harmonization.py`
- `tests/services/test_run_service_character_provisioning.py`
- `tests/services/test_run_service_gate.py`
- `frontend/src/components/ArtifactPanel.test.tsx`
- `frontend/src/pages/RunDetail.test.tsx`

Do not stop at unit tests around a merge helper. At least one integration-style backend test must force a real service/node fallback, pause at a gate, read the stage artifact DTO, and assert the same structured warning is visible end-to-end.

### Project Structure Notes

Expected production changes:

- UPDATE `src/yt_flow/domain/state.py`
- NEW `src/yt_flow/domain/warnings.py` (small pure merge/dedupe helper; not a service)
- UPDATE `src/yt_flow/services/run_service.py`
- UPDATE `src/yt_flow/services/character_service.py`
- UPDATE `src/yt_flow/pipeline/gates.py`
- UPDATE `src/yt_flow/pipeline/nodes/image.py`
- UPDATE `src/yt_flow/pipeline/nodes/subtitle.py`
- UPDATE `src/yt_flow/pipeline/nodes/video.py`
- UPDATE `src/yt_flow/pipeline/nodes/composite_harmonization.py` for bounded pair/skip diagnostics
- UPDATE `frontend/src/lib/api.ts` and/or `frontend/src/lib/types.ts`
- UPDATE `frontend/src/components/ArtifactPanel.tsx`
- OPTIONAL UPDATE `frontend/src/pages/RunDetail.tsx` only if refresh testing proves necessary
- UPDATE the tests listed above

No DB model/migration, config, dependency, workflow JSON, or new service file is expected.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md:1358`] Epic 13 objective and silent-success incidents.
- [Source: `_bmad-output/planning-artifacts/epics.md:1366`] Story 13.1 source scope.
- [Source: `_bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md:320`] Gap analysis: surface silent degradations.
- [Source: `_bmad-output/planning-artifacts/research/technical-yt-flow-quality-strategy-research-2026-08-01.md:365`] Run warnings visible at gates.
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md:22`] Layering and state authority.
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md:53`] Fixed human-gate mechanism.
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md:110`] Whole-field state replacement/no reducers.
- [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md:51`] Artifact Panel and Gate Controls.
- [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md:114`] Status must use text/icon plus color.
- [Source: `_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/DESIGN.md:108`] Semantic status tokens.
- [Source: `_bmad-output/implementation-artifacts/8-3-bg-only-generation-multicard-compositing.md:68`] Layered generation/segmentation retirement.
- [Source: `_bmad-output/implementation-artifacts/5-11-segmentation-failure-shot-fallback.md`] Historical per-shot warning precedent only.
- [Source: `src/yt_flow/domain/state.py:165`] Current `PipelineState`.
- [Source: `src/yt_flow/services/run_service.py:62`] Checkpoint-backed artifact DTO seam.
- [Source: `src/yt_flow/services/run_service.py:382`] Pre-graph character provisioning fallback.
- [Source: `src/yt_flow/services/run_service.py:460`] Special-pose provisioning cap/failure.
- [Source: `src/yt_flow/services/run_service.py:513`] Derived-entity provisioning cap/failure.
- [Source: `src/yt_flow/pipeline/nodes/image.py:319`] Stock-plate fallback.
- [Source: `src/yt_flow/pipeline/nodes/subtitle.py:435`] WhisperX-to-provisional fallback.
- [Source: `src/yt_flow/pipeline/nodes/video.py:1629`] Cast resolution and background-only fallback.
- [Source: `src/yt_flow/pipeline/nodes/video.py:1670`] Relight fallback.
- [Source: `src/yt_flow/pipeline/nodes/composite_harmonization.py:354`] Existing per-pair relight statistics.

## Dev Agent Record

### Agent Model Used

OpenAI Codex (GPT-5)

### Debug Log References

- Story creation analysis only; implementation verification is pending `dev-story`.

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Derived formal story and BDD acceptance criteria from the Epic 13 draft, which had no detailed ACs.
- Corrected stale scope: segmentation/layered fallback was retired by Story 8.3 and must not be reintroduced.
- Confirmed warning authority belongs in LangGraph checkpoint state and the existing gate/artifact path; no DB migration or new service is required.
- Included active producer inventory, retry/idempotency rules, UI/accessibility constraints, exact update files, regression tests, prior-story lessons, git patterns, and current pinned versions.

### File List

- `_bmad-output/implementation-artifacts/13-1-surface-silent-degradations.md`

## Change Log

- 2026-08-03: Story 13.1 created and marked ready-for-dev after exhaustive artifact, code, history, UX, architecture, and official LangGraph documentation analysis.
