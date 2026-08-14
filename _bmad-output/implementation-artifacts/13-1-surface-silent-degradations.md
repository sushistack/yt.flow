---
story_key: 13-1-surface-silent-degradations
epic: 13
story: 1
status: done
created: 2026-08-03
updated: 2026-08-14
baseline_revision: a4a583e6d735dc30b4d2c1fa0348274e840f9e38
final_revision: 3a8045280af585573caf509c40f0e45ed2765960
review_loop_iteration: 0
followup_review_recommended: true
depends_on:
  - 12-3-pass2-verdict-grounded-gate
---

# Story 13.1: Surface Silent Degradations at Human Gates

Status: done

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

- [x] Task 1: Define the warning state contract and deterministic merge behavior (AC: 1, 3, 6)
  - [x] Add `RunWarningCode`/`RunWarning` to `src/yt_flow/domain/state.py`; add `run_warnings: NotRequired[list[RunWarning]]` to `PipelineState`.
  - [x] Add a small pure domain helper (recommended: `src/yt_flow/domain/warnings.py`) that merges immutable lists, preserves first-seen order, and deduplicates by stable code/stage/identifier context.
  - [x] Use only JSON-safe primitives in context. Bound exception details; do not store exception objects, paths containing secrets, arbitrary provider response bodies, or unbounded payloads.
  - [x] Update the exact type-shape/import guard tests in `tests/domain/test_state_imports.py`.

- [x] Task 2: Seed and merge service-side provisioning warnings (AC: 1, 2, 3, 6)
  - [x] Add an optional bounded diagnostic/warning collector seam to `CharacterService.enrich_descriptor_from_references()` and thread it through `generate_cards_from_descriptor()` without breaking existing `str | None` callers. This reports failed/empty enrichment even when the method returns an existing descriptor and card generation succeeds.
  - [x] Change `_ensure_character_reference()` to collect/return warnings for missing enrichment/provisioning outcomes while preserving its best-effort envelope and empty-stub rollback. Seed those warnings through `_initial_state()` in `start_run()`.
  - [x] Change `_ensure_special_pose_cards()` and `_ensure_derived_entity_cards()` to return structured cap/generation warnings naming every skipped/failed key. The derived-entity path passes the collector through `generate_cards_from_descriptor()` so a swallowed enrichment failure is not lost merely because image generation succeeds.
  - [x] In `resume_run()` scenario approval, merge provisioning warnings into the paused checkpoint/resume update through the existing service-owned graph seam. Verify the pending interrupt and next-node behavior using the real pinned LangGraph package, not only a fake graph.
  - [x] Keep A/B start, failure resume, retry, and full restart behavior aligned; initialize/reset warning state deliberately.

- [x] Task 3: Instrument current pipeline fallback branches (AC: 1, 2, 3)
  - [x] `image_node`: record plate-missing/resolver-unavailable/resolution-failed warnings while retaining generated-background fallback. Emit one deterministic warning per affected shot; identity includes code + stage + scene + shot + location, so the lookup remains cached without dropping affected-shot evidence.
  - [x] `subtitle_node`: record a warning on real WhisperX-to-provisional fallback; `qwen_tts_mock=True` remains an intentional INFO-only path.
  - [x] `video_node`: compare declared cast with resolved cards to surface missing rows/assets; translate resolver failure, malformed results, returned angle/pose fallback metadata, relight failed counts, resolver failure, and invalid/unreadable relit substitution into warnings while preserving background/original-card rendering.
  - [x] Extend `precompute_relights()` diagnostics so every Tier-3 eligible pair/shot that falls back is accounted for: failed render, unverified location/card asset, unsafe/malformed metadata, or another skipped pair. Keep orchestration single-sourced; return bounded identifiers plus computed/failed/skipped counts for `video_node` to translate into warnings.
  - [x] Keep existing logger warnings and trace counters where useful; structured state is additive and is the gate-facing authority.

- [x] Task 4: Expose warnings through gates, SSE, and artifact DTOs (AC: 4, 6)
  - [x] Extend `gates._gate()` interrupt payload with accumulated warnings/count while preserving the existing scenario-only `scenario_quality` field. Do not mutate warning state immediately before `interrupt()`; the gate only reads persisted collections.
  - [x] Extend `_consume()`'s existing `gate_pending` payload rather than adding an event type.
  - [x] Add `warnings` to every `get_stage_artifacts()` response and every frontend `StageArtifacts` variant/shared base.
  - [x] Preserve the four-event SSE convention and avoid changes to `Run`, database models, migrations, or `RunRead` unless implementation proves the existing artifact/gate path cannot meet the AC (escalate rather than silently creating dual authority).

- [x] Task 5: Replace the stale layered-fallback frontend warning with generic gate warnings (AC: 3, 5)
  - [x] Add the shared `RunWarning` TypeScript type in `frontend/src/lib/api.ts` or `frontend/src/lib/types.ts` and remove stale `layered_fallback` DTO dependence. Render the backend's short Korean `message`; never promote raw exception/provider detail to primary UI text.
  - [x] Add a reusable warning summary inside `ArtifactPanel`: `⚠ 경고 N건`, short messages, identifiers, accessible semantics, existing status tokens, no icon package. Keep the existing `ScenarioQualityWarning` component and render both when both contracts are present.
  - [x] Ensure `RunDetail` refetches artifacts after `gate_pending`; change logic only if the existing `run` state update does not already trigger the fetch.
  - [x] Preserve all current gate, retry, editor, media, and lightbox behavior.

- [x] Task 6: Add cross-layer regression evidence (AC: 7)
  - [x] Domain/gate: warning shape, JSON serialization, legacy state, additive interrupt payload with `scenario_quality` preservation, deterministic merge/dedupe.
  - [x] Service: enrichment, special-pose/derived caps and failures, scenario-approval checkpoint merge, artifact DTO exposure, retry persistence, restart reset.
  - [x] Pipeline: stock plate hit/miss/error, WhisperX success/fallback/mock, cast resolver success/failure/missing/malformed/fallback, relight success/failure/invalid output, hard RGBA failure unchanged.
  - [x] Frontend: zero/one/multiple warnings, accessible Korean badge/list, controls remain functional, gate-pending refresh.
  - [x] Run `PYTHONPATH=$PWD/src uv run pytest tests/`, `uv run ruff check src tests`, `npm test`, and `npm run build` from `frontend/`; report actual results without claiming unavailable GPU validation.

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

**Implementation addition (2026-08-14).** This story was written 2026-08-03; four
degradation paths landed after it and are live today, so they carry codes in the same
naming style and the same stage-ownership rule. The vocabulary above plus these four is
the complete `RunWarningCode` `Literal`:

| Code | Producer | Stage ownership |
|---|---|---|
| `special_pose_guide_unapplied` | Story 10.5 `generate_special_pose_card` (guide unresolved / non-openpose `control_type` / missing guide workflow) **and** `ComfyUICharacterProvider.generate` (guide read/upload failure) | `scenario` |
| `derived_entity_look_unauthored` | Story 10.6 `_ensure_derived_entity_cards` unauthored-key skip | `scenario` |
| `character_card_i2i_fallback` | `ComfyUICharacterProvider.generate` i2i → t2i fallback (identity anchor lost) | `scenario` |
| `background_guard_unscreened` | Story 10.2 `image_node` guard: key missing while enabled / breaker tripped / ladder exhausted | `image` |

The two provider-side conditions are reported through `last_pose_guide_applied` /
`last_i2i_fallback` flags the provider sets per `generate()` call and the service reads
immediately after: both degradations return a perfectly valid PNG, so nothing in the
bytes or the return type can distinguish them, and the provider must not learn about
runs or state to say so.

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

- Story creation (2026-08-03): OpenAI Codex (GPT-5)
- Implementation (2026-08-14): Claude Opus 5

### Debug Log References

- Story creation analysis only; implementation verification is pending `dev-story`.
- Implementation verification (2026-08-14), all local, no GPU and no live run:
  - `uv run ruff check src/ scripts/ tests/` → `All checks passed!`
  - `PYTHONPATH=$PWD/src uv run pytest tests/` → `2740 passed, 1 skipped, 1 warning` (baseline before this story on the same tree: `2691 passed, 1 skipped`)
  - `npm test` (frontend) → `Test Files 17 passed (17) / Tests 126 passed (126)`
  - `npm run build` (frontend) → `✓ built`
- Adversarial-review patch pass (2026-08-14), same conditions, no GPU and no live run:
  - `uv run ruff check src/ scripts/ tests/` → `All checks passed!`
  - `PYTHONPATH=$PWD/src uv run pytest tests/` → `2782 passed, 1 skipped, 1 warning`
    (+42 tests, no regression from the 2740 above)
  - `npm test` (frontend) → `Test Files 17 passed (17) / Tests 128 passed (128)`
  - `npm run build` (frontend) → `✓ built`

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created.
- Derived formal story and BDD acceptance criteria from the Epic 13 draft, which had no detailed ACs.
- Corrected stale scope: segmentation/layered fallback was retired by Story 8.3 and must not be reintroduced.
- Confirmed warning authority belongs in LangGraph checkpoint state and the existing gate/artifact path; no DB migration or new service is required.
- Included active producer inventory, retry/idempotency rules, UI/accessibility constraints, exact update files, regression tests, prior-story lessons, git patterns, and current pinned versions.

**Implementation notes (2026-08-14):**

- **The producer with no consumer is now consumed.** `resolve_cast_cards` has computed
  `fallback` / `angle_fallback` / `asset_fallback` / `fallback_reason` per card since
  Story 8.3, and the only reader was `video.py`'s single Langfuse integer
  `fallback_used` — which could say neither *which shot* nor *which lever*.
  `video._cast_warnings()` now compares declared cast against resolved cards per shot
  and emits `cast_card_missing` / `cast_card_fallback` carrying `scene_num`, `shot_id`,
  `card_key` and `fallback_reason`. The aggregate trace field is untouched.
- **Task 5 confirmation.** The stale Story 5.11 `layered_fallback` indicator *was* still
  present and has been removed: `frontend/src/lib/api.ts:100` (DTO field),
  `ArtifactPanel.tsx:389,414` (`⚠ 플랫 폴백` badge), and four fixture rows in
  `ArtifactPanel.test.tsx`. The backend has emitted no such field since Story 8.3, so it
  could never have rendered. Its test was replaced by an assertion that the dead
  indicator is gone, and the generic `RunWarningList` is what surfaces degradation now.
- **`background_person_guard_attempts = 0` decision: NOT warned (AC2 "intentionally
  non-applicable" applies).** Evidence from the code: `config.py:291` declares
  `background_person_guard_attempts: int = Field(0, ge=0, le=MAX)` with the comment "0
  (default) disables the guard entirely; enable with
  `YTFLOW_BACKGROUND_PERSON_GUARD_ATTEMPTS=2`… Off by default like every other new path
  in this epic (`stock_plate_substitution_enabled`, `shot_recompose_enabled`)" — an
  operator-set knob at its shipped value, exactly like `composite_harmonization_tier < 3`
  and `stock_plate_substitution_enabled=False`, which the story itself names as
  warning-free. Warning on it would fire on literally every production run and train the
  operator to ignore the badge. What IS warned is the guard being *asked for and not
  delivered*, which is a runtime degradation: `attempts >= 1` with no
  `character_vision_api_key` (run-level, one record), the undecidable-verdict breaker
  tripping mid-run (run-level, one record), and a shot whose seed ladder was exhausted so
  a known-populated background was kept (per shot, `scene_num` + `shot_id`). The same
  rule is applied to `stock_plate_substitution_enabled=False` (silent) vs. substitution
  on with no resolver injected (`stock_plate_resolver_unavailable`), and to
  `composite_harmonization_tier < 3` (silent) vs. tier 3 with no relight resolver
  (`relight_resolver_unavailable`).
- **Post-2026-08-03 producers added** (see the vocabulary addition table above):
  `special_pose_guide_unapplied` (10.5, both the service-side rejection reasons and the
  provider-side guide upload failure), `derived_entity_look_unauthored` (10.6),
  `character_card_i2i_fallback` (provider i2i→t2i), `background_guard_unscreened` (10.2).
  The `special_pose_max_per_run` cap already had a code; it now names **every** skipped
  `(card_key, pose_hint)` pair rather than logging a list.
- **Collector seam shape.** `CharacterService(..., warnings=[])` is one optional sink on
  the instance instead of a `warnings=` parameter threaded through
  `enrich_descriptor_from_references` → `generate_candidates_from_reference` →
  `generate_cards_from_descriptor` → `generate_special_pose_card`. Same reach, four fewer
  signature changes, and no existing caller changes: `None` (the Character UI, scripts,
  most tests) keeps today's log-only behaviour. The AC's real requirement — that a
  swallowed enrichment failure survives successful card generation — is covered, because
  the sink is shared by every method on the instance.
- **Ordering/dedupe.** `domain/warnings.merge()` concatenates `existing + new`, keeps
  first-seen order, and dedupes on `(code, stage, sorted(context minus "detail"))`.
  `detail` is the one free-text field (bounded to 200 chars) and is excluded from
  identity because two attempts at the same defect produce two different exception
  strings. Every producer returns the whole merged list — no `Annotated[..., operator.add]`
  reducer anywhere, per the architecture spine.
- **Scenario-approval merge against real LangGraph.** Provisioning runs *after* the
  scenario gate opens, so its warnings are written with
  `aupdate_state(config, {"run_warnings": …}, as_node="scenario")` while the graph is
  paused — the same seam and reasoning as `resume_run`'s existing reject branch.
  `test_scenario_approval_provisioning_merges_into_the_paused_checkpoint` proves against
  the pinned LangGraph that `next` stays `("gate_scenario",)` before the resume and
  becomes `("gate_image",)` after, that the scenario node runs exactly once (no repeated
  pre-interrupt side effect), and that the warning surfaces at the image gate and in the
  scenario artifact DTO.
- **Gate/DTO scope: run-wide, not stage-filtered.** Each record names its own stage, and
  provisioning warnings are produced after the scenario gate has already been answered —
  stage-filtering would make them reach no gate at all. `warnings`/`warning_count` are
  omitted from the interrupt payload when empty, so a clean run's gate frame stays
  byte-identical to a pre-13.1 one (12.3's `scenario_quality` discipline).
  `get_stage_artifacts()` always returns `warnings`, `[]` for a legacy checkpoint.
- **Relight diagnostics.** `precompute_relights()` now counts every eligible pair that
  falls back (`location_asset_unverified`, `card_asset_unverified`, `unsafe_location_key`,
  `unsafe_card_variant`, metadata errors) and returns bounded `skipped_details` /
  `failed_details` samples (12 max) alongside exact counts. A free-text background
  (no `location_key`) is *not* recorded — it was never eligible. `skipped`/`*_details`
  appear only when non-empty, so a clean Tier-3 run returns the byte-identical
  `{computed, failed}` its existing callers read.
- **Test updates to pre-existing tests, and why:** four `test_composite_harmonization`
  assertions on the exact `stats` dict now assert the new skip/fail diagnostics (that is
  the Task 3 evidence); `test_stage_artifacts::test_video_artifacts` gains `"warnings": []`
  (AC4 requires it on every DTO); two provisioning test doubles now return `[]` since both
  helpers return their warnings. **Superseded by the review pass:** the two
  `test_run_service_gate` "omits quality" assertions were briefly weakened to
  `"scenario_quality" not in data` on the theory that the fixture's provisioning
  legitimately varies by environment. It does not *legitimately* — it was making a live
  DashScope call whenever a developer `.env` carried the vision key.
  `patch_character_reference_seams` now stubs enrichment too, and both assertions are
  exact dicts again: that is the only guard that a clean run's gate frame gained no keys.
- **Honest limitation — 8 of the 21 codes cannot fire at the shipped config.** Each
  individual "config-disabled is not a degradation" decision above is deliberate and
  argued (AC2), but the aggregate was not stated anywhere and both the epics line and
  the sprint-status entry read as though the whole surface is live today. It is not.
  Verified against `Settings()` on this tree, with no `.env` pin shadowing any of them
  (`grep -niE "stock_plate|guard|harmonization|tier" .env` matches only a comment):

  | Dormant code(s) | Gating flag | Shipped value |
  |---|---|---|
  | `stock_plate_resolver_unavailable`, `stock_plate_missing`, `stock_plate_resolution_failed` | `stock_plate_substitution_enabled` | `False` (`config.py:282`) |
  | `background_guard_unscreened` | `background_person_guard_attempts` | `0` (`config.py:291`) |
  | `relight_resolver_unavailable`, `relight_pair_skipped`, `relight_failed`, `relit_sprite_invalid` | `composite_harmonization_tier` | `1`, needs `>= 3` (`config.py:317`) |

  All 8 activate the moment their flag is turned on — each is tested against its enabled
  path (`test_image.py`, `test_video_harmonization.py`), so this is dormancy, not
  absence. The 13 codes live at the shipped config are the provisioning family
  (`vision_enrichment_failed`, `character_provisioning_failed`, the four
  special-pose/derived cap+failure codes, `special_pose_guide_unapplied`,
  `derived_entity_look_unauthored`, `character_card_i2i_fallback`),
  `subtitle_alignment_fallback`, and the three cast codes.
- **Not done / out of scope, deliberately:** no live or GPU validation was run and none
  is claimed — this story is plumbing, and the warning surface is proven end to end by
  `tests/services/test_run_warnings_gate.py` driving the real compiled graph. Partially
  provisioned angle sets (2 of 4 angles) are not warned separately; the resulting
  degradation surfaces downstream as `cast_card_fallback` with the shot named.

**Adversarial-review fixes applied (2026-08-14), all 18 findings:**

- **The pose_hint miss was invisible and now is not (highest-value finding).**
  `resolve_cast_cards` logged "no special-pose card … falling back to base pose" and
  then returned `fallback=False`, so Story 8.4/10.5's whole question — did the *pose* or
  the *angle* fall back? — was still unanswerable downstream. Fixed in the producer, not
  in `video.py` (AD-1: `pipeline/` must not import `services/`): the card's existing
  `fallback` / `fallback_reason` now carry a `pose_hint` component, `"+"`-joined with
  the pre-existing `angle` / `asset` ones whose spelling is unchanged.
- **Isolation restored in `precompute_relights`.** The identifier binding had moved
  above the `try` that guards all shot-dict access, so one non-dict shot raised
  `AttributeError` out of the function and cost the whole run its Tier-3 relights —
  exactly the guarantee the docstring makes. Bound inside the `try`, as two statements
  rather than a tuple assignment so a raising `shot.get` still leaves `scene_num`
  reportable.
- **`subtitle_node`'s error path no longer drops warnings**, matching `image_node` and
  `video_node`: `warnings` is declared outside the `try` and merged on both returns.
- **One row per lost cast member.** `_cast_warnings` emitted `cast_card_missing` from
  both the member loop and the card loop for a single malformed card; different context
  meant `merge()` kept both and `warning_count` inflated. The member loop now owns the
  outcome and distinguishes `reason="malformed_card"` from a never-resolved member.
- **The per-shot families are bounded.** `domain/warnings.MAX_SAMPLE_RECORDS` (the value
  `composite_harmonization` already used) plus `cap_samples()` is now the one policy:
  named rows stop at 12 per code, one aggregate row carries the true total, and a
  producer that already rolled up its own count is left alone. Applied at both node
  returns in `image.py` and `video.py`.
- **Dedupe identity ignores per-attempt counters.** `_VOLATILE_CONTEXT_KEYS` grew the
  undecidable streak/total and every `*_count` key, so a retry with a different tally
  converges on the row already in the checkpoint (AC1/AC6) instead of appending a
  near-duplicate. The counts stay in `context` and stay on screen.
- **Import-time catalog check is a `raise`, not an `assert`** — `python -O` strips the
  assert and degraded it into a `KeyError` thrown out of a best-effort `except` block.
- **The approve path is AD-10-enveloped.** `aupdate_state` on the scenario-approve seam
  is wrapped: a failed warning merge costs the record, never the operator's decision.
- **`_consume` reads `warning_count` from the gate** instead of recomputing it — the
  gate writes both keys or neither.
- **Frontend.** `IDENTIFIER_LABELS` gained `fallback_reason` (the field the whole story
  produces), `pose`, `angle`, `card_variant`, `cap`, `attempts`, `total_count`;
  `detail` stays excluded. `RunWarningList` is a labelled region rather than a
  contradictory `role="alert"` + `aria-live="polite"` pair — it is statically rendered
  and the header badge already announces the count. `RunDetail` refreshes only when the
  `gate_pending` names the stage on screen, and the artifacts effect no longer depends
  on the whole `run` object, so an unrelated gate-state tweak cannot null the panel
  mid-edit (12.3's explicit `artifactRefresh` signal is what does the refreshing, which
  is why it was made explicit in the first place).
- **Tests.** The `ArtifactPanel` fixture now uses the shape `_cast_warnings` really
  emits (`fallback_reason`, not `reason`) and asserts it renders. The two
  `test_run_service_gate` frames are exact dicts again, made honest by stubbing vision
  enrichment in `patch_character_reference_seams` — those unit tests were reaching a
  live DashScope endpoint whenever a developer `.env` carried
  `YTFLOW_CHARACTER_VISION_API_KEY`. The full-restart test's no-op monkeypatch is gone;
  it now asserts what actually guarantees the reset (`full_restart_run` never
  provisions). And the 11 untested emission sites are covered: all four
  `background_guard_unscreened` causes, both `character_card_i2i_fallback` sites, both
  `special_pose_guide_unapplied` sites, both `relit_sprite_invalid` sites, both
  `relight_resolver_unavailable` sites, plus the `last_i2i_fallback` /
  `last_pose_guide_applied` provider flags themselves. 2740 → 2782 backend tests.
- **Two findings deferred** to `_bmad-output/implementation-artifacts/deferred-work.md`:
  the over-wide stock-plate `try` (a copy/depth failure is reported as a plate-lookup
  failure — pre-existing width, newly operator-facing) and stale `scene_num`/`shot_id`
  on warnings that survive a scenario retry (spec-conformant per AC6, but the
  identifiers describe a discarded draft).

### File List

**Backend (source)**

- `src/yt_flow/domain/state.py` — `RunWarningCode` / `RunWarning`, `PipelineState.run_warnings`
- `src/yt_flow/domain/warnings.py` **(new)** — catalog, `make_warning()`, `merge()`
- `src/yt_flow/pipeline/gates.py` — warnings/count on the interrupt payload
- `src/yt_flow/pipeline/nodes/image.py` — plate + background-guard warnings
- `src/yt_flow/pipeline/nodes/subtitle.py` — WhisperX fallback warning
- `src/yt_flow/pipeline/nodes/video.py` — `_cast_warnings()`, `_relight_warnings()`, relit-sprite warnings
- `src/yt_flow/pipeline/nodes/composite_harmonization.py` — bounded skip/fail relight diagnostics
- `src/yt_flow/services/run_service.py` — provisioning warnings, `_initial_state` seed, paused-checkpoint merge, `gate_pending` + artifact DTO exposure
- `src/yt_flow/services/character_service.py` — collector seam, enrichment/pose/i2i warnings
- `src/yt_flow/services/character_image_provider.py` — `last_i2i_fallback` / `last_pose_guide_applied` flags

**Frontend**

- `frontend/src/lib/api.ts` — `RunWarning` type, `warnings` on every stage DTO, `layered_fallback` removed
- `frontend/src/components/ArtifactPanel.tsx` — header badge, `RunWarningList`, stale indicator removed
- `frontend/src/pages/RunDetail.tsx` — artifact refetch on every `gate_pending`

**Tests**

- `tests/domain/test_run_warnings.py` **(new)**
- `tests/services/test_run_warnings_gate.py` **(new)** — end-to-end producer → gate → artifact DTO
- `tests/domain/test_state_imports.py`
- `tests/pipeline/test_gates.py`
- `tests/pipeline/nodes/test_image.py`
- `tests/pipeline/nodes/test_subtitle.py`
- `tests/pipeline/nodes/test_video.py`
- `tests/pipeline/nodes/test_composite_harmonization.py`
- `tests/services/test_run_service_character_provisioning.py`
- `tests/services/test_run_service_gate.py`
- `tests/api/test_stage_artifacts.py`
- `frontend/src/components/ArtifactPanel.test.tsx`
- `frontend/src/pages/RunDetail.test.tsx`

**Planning artifacts**

- `_bmad-output/implementation-artifacts/13-1-surface-silent-degradations.md`
- `_bmad-output/planning-artifacts/epics.md` (13-1 line only)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (13-1 entry only)
- `_bmad-output/implementation-artifacts/deferred-work.md` (two 13.1 entries appended)

**Added by the adversarial-review patch pass (2026-08-14)**

- `tests/stubs/fakes.py` — `patch_character_reference_seams` also stubs vision enrichment
- `tests/services/test_character_angle_selector.py` — pose-hint fallback metadata
- `tests/services/test_character_service_generation.py` — provider-flag degradations + the flags themselves
- `tests/pipeline/nodes/test_video_harmonization.py` — relight/relit-sprite warnings

## Review Triage Log

### 2026-08-14 — Review pass

- intent_gap: 0
- bad_spec: 0
- patch: 18: (high 2, medium 10, low 6)
- defer: 2: (high 0, medium 1, low 1)
- reject: 6
- addressed_findings:
  - `[high]` `[patch]` P3 — a `pose_hint` miss produced no warning at all: `resolve_cast_cards` logged "falling back to base pose" and then returned `fallback=False`, so the one lever Story 8.4/10.5 exists for was invisible at the gate. Fixed in the producer (`pipeline/` may not import `services/`): the miss now folds into `fallback`/`fallback_reason` as a `pose_hint` component, which `_cast_warnings` picks up for free.
  - `[high]` `[patch]` P7 — the UI dropped the identifiers that answer the story's question: `IDENTIFIER_LABELS` had no `fallback_reason`, `pose`, `angle`, `card_variant`, `cap`, `attempts`. Added with Korean labels in fixed order; `detail` stays excluded.
  - `[medium]` `[patch]` P1 — `subtitle_node`'s error return dropped every warning already accumulated; now merges like `image_node`/`video_node`.
  - `[medium]` `[patch]` P2 — the new identifier binding in `precompute_relights` sat above the `try`, so a malformed shot raised out of the function and disabled Tier 3 for the whole run; moved back inside, as two statements so a raising `shot.get` cannot also discard `scene_num`.
  - `[medium]` `[patch]` P4 — one undrawable card emitted two contradictory `cast_card_missing` rows (member loop + card loop), inflating `warning_count`; now exactly one row per lost member.
  - `[medium]` `[patch]` P5 — the per-shot cast/plate families were unbounded while relight was capped at 12; a 155-shot resolver outage would have written hundreds of rows into the checkpoint, every interrupt payload, every artifact response, and the list above the Approve button. One shared `MAX_SAMPLE_RECORDS`/`cap_samples()` policy with an aggregate total row.
  - `[medium]` `[patch]` P6 — dedupe identity included per-attempt counters (`undecidable_streak`/`_total`, `*_count`), so a retry with a different tally appended a near-duplicate; identity now ignores them while the counts stay on screen.
  - `[medium]` `[patch]` P8 — the new `ArtifactPanel` fixture used a `context` shape the backend never emits (`reason` instead of `fallback_reason`), certifying a path that cannot occur; replaced with real `_cast_warnings` output. Same fixture-bug class as the 13.2 review.
  - `[medium]` `[patch]` P12 — the scenario-approve `aupdate_state` was unguarded, so a failed warning merge would 500 the approve after provisioning had already run; wrapped in the AD-10 envelope every other seam in that file uses.
  - `[medium]` `[patch]` P13 — refreshing artifacts on every `gate_pending` discarded an in-progress narration edit when another stage's gate opened; now only for the stage on screen, and the artifacts effect no longer depends on the whole `run` object (which made the guard unobservable).
  - `[medium]` `[patch]` P14 — two `gate_pending` compatibility assertions had been weakened to `"scenario_quality" not in data` because the fixture reached a live DashScope endpoint from a unit test; the seam is now stubbed and both assertions restored to exact dicts.
  - `[medium]` `[patch]` P15 — 11 of 21 emission sites had no test against AC7, including the `last_i2i_fallback`/`last_pose_guide_applied` provider-flag mechanism the "invisible in the returned bytes" argument rests on; +42 backend tests covering every named code.
  - `[low]` `[patch]` P9 — module-level `assert` for catalog completeness is stripped under `python -O`, degrading into a `KeyError` thrown from inside a best-effort `except`; now an explicit `raise`.
  - `[low]` `[patch]` P10 — File List cited the wrong `sprint-status.yaml` path.
  - `[low]` `[patch]` P11 — `role="alert"` + `aria-live="polite"` on a statically rendered region re-announced the whole history on every stage switch; now a labelled region.
  - `[low]` `[patch]` P16 — `value.get("warning_count", len(warnings))` was a second source of truth for a number the gate always writes.
  - `[low]` `[patch]` P17 — the full-restart test's monkeypatch was a no-op (`full_restart_run` never calls it) and the assertion was true by construction; now asserts what actually guarantees the reset.
  - `[low]` `[patch]` P18 — recorded the unstated aggregate: at shipped config defaults 8 of 21 codes are dormant (`stock_plate_substitution_enabled=False`, `background_person_guard_attempts=0`, `composite_harmonization_tier=1`), each tested against its enabled path.

Deferred (see `deferred-work.md`): `image_node`'s over-wide stock-plate `try` misattributes copy/depth failures to plate resolution; scenario retry leaves `scene_num`/`shot_id` identifiers pointing at the discarded draft.

Rejected as noise or spec-conformant: retry not clearing a stage's warnings (AC6 mandates survival and the UI copy states it); the `gate_pending` warning payload having no frontend consumer (the artifact endpoint is the authority, exactly as 12.3 does with `scenario_quality`); `NaN`/`inf` in context (no producer emits floats); `LookupError` on an unreached stage hiding provisioning warnings (the `run_failed` path carries the error); English `reason` tokens in the monospace diagnostic line (primary copy is Korean, per AC5); the `len(details) < count` dedupe nuance in `_relight_warnings`.

## Change Log

- 2026-08-03: Story 13.1 created and marked ready-for-dev after exhaustive artifact, code, history, UX, architecture, and official LangGraph documentation analysis.
- 2026-08-14: Implemented Tasks 1–6. `run_warnings` is checkpoint-owned and reaches every gate, the `gate_pending` frame, all five artifact DTOs, and a neutral-token warning badge/list in the Artifact Panel. Vocabulary extended with four post-2026-08-03 producers; `background_person_guard_attempts=0` decided warning-free with reasoning recorded above. Stale `layered_fallback` frontend indicator confirmed present and removed. Status → in-review.
- 2026-08-14: Adversarial-review patch pass — all 18 findings applied (see Completion
  Notes). Behaviour changes worth naming: the pose_hint miss now sets `fallback` /
  `fallback_reason` on the resolved card; `precompute_relights`'s per-shot isolation is
  restored; per-shot warning families are capped at one shared policy with an aggregate
  total row; dedupe identity ignores per-attempt counters; the scenario-approve
  checkpoint write is AD-10-enveloped; the warning list is a labelled region rather than
  an alert; `RunDetail` refreshes only for the stage on screen. Two findings deferred to
  `deferred-work.md`. Status stays in-review.

## Auto Run Result

Status: done. Baseline `a4a583e`. No live/GPU validation was run and none is claimed.

### What was implemented

`PipelineState.run_warnings` is the single authority for non-fatal degradation, carried
along Story 12.3's delivery spine and kept semantically separate from `scenario_quality`:
checkpoint → gate `interrupt()` (`warnings`/`warning_count`, keys omitted when empty so a
clean run's payload is byte-identical to a pre-13.1 one) → the existing `gate_pending` SSE
frame (no fifth event type) → all five stage-artifact DTOs (`[]` on a legacy checkpoint) →
a neutral-Zinc `⚠ 경고 N건` badge and list in `ArtifactPanel`. No DB column, no migration,
no reducer, no new dependency. `run_warnings` is `NotRequired` and every reader defaults it,
so pre-13.1 checkpoints stay readable.

The substance is not new instrumentation but connecting a producer that had no consumer:
`resolve_cast_cards` has computed `fallback`/`angle_fallback`/`asset_fallback`/
`fallback_reason` per card since Story 8.3, and its only reader was one Langfuse integer
(`fallback_used`) that could name neither the shot nor the lever. That is now per-shot
`cast_card_missing`/`cast_card_fallback`. Review then found the producer itself was also
lying: a `pose_hint` miss logged "falling back to base pose" and reported `fallback=False`,
so the single lever Stories 8.4/10.5 exist for was invisible — fixed in the producer.

Four codes were added for degradation paths that landed after the story was written
(2026-08-03): `special_pose_guide_unapplied` (10.5), `derived_entity_look_unauthored`
(10.6), `character_card_i2i_fallback` (i2i→t2i identity loss), `background_guard_unscreened`
(10.2). Config-disabled states are deliberately warning-free (AC2); "asked for and not
delivered" warns.

### Files changed

Production — `domain/state.py` (`RunWarningCode`/`RunWarning`/`run_warnings`),
NEW `domain/warnings.py` (catalog + `make_warning`/`merge`/`cap_samples`),
`services/run_service.py` (seed, merge at scenario approval, artifact DTOs, SSE),
`services/character_service.py` (collector seam, pose-hint fallback metadata),
`services/character_image_provider.py` (`last_i2i_fallback`/`last_pose_guide_applied`),
`pipeline/gates.py` (read-only interrupt payload), `pipeline/nodes/image.py`,
`subtitle.py`, `video.py`, `composite_harmonization.py` (bounded pair/skip diagnostics),
`frontend/src/lib/api.ts`, `components/ArtifactPanel.tsx` (badge + list, stale
`layered_fallback` removed), `pages/RunDetail.tsx` (targeted refetch).
Tests — 2 new files plus 12 updated suites; +91 tests over baseline.

### Review findings

18 patches applied (2 high, 10 medium, 6 low), 2 deferred, 6 rejected, 0 intent_gap,
0 bad_spec, 0 repair loopbacks. Detail in `## Review Triage Log`.

### Verification

- `uv run ruff check src/ scripts/ tests/` → `All checks passed!`
- `PYTHONPATH=$PWD/src uv run pytest tests/` → `2782 passed, 1 skipped, 1 warning`
  (baseline 2691 passed / 1 skipped; implementation 2740; review pass 2782)
- `npm test` → `Test Files 17 passed (17)` / `Tests 128 passed (128)`
- `npm run build` → `✓ built in 134ms`

All four were re-run independently after the review patches, not taken on report.

### Residual risks

- **8 of 21 codes are dormant at shipped defaults** (`stock_plate_*` ×3 behind
  `stock_plate_substitution_enabled=False`, `background_guard_unscreened` behind
  `background_person_guard_attempts=0`, relight ×4 behind `composite_harmonization_tier=1`).
  Each per-flag decision is correct; the aggregate is now stated rather than implied.
- No live run has exercised the surface. Every path is covered by forced-failure tests
  including one end-to-end (service fallback → gate pause → artifact DTO), but the first
  real run is the first time an operator sees the badge.
- Two deferred items in `deferred-work.md`: the over-wide stock-plate `try` misattributes
  copy/depth failures, and scenario retry leaves shot identifiers pointing at a discarded
  draft (AC6 mandates the survival, so resolving it is a contract change).
- `followup_review_recommended: true` — the patch pass changed a producer contract
  (`resolve_cast_cards` fallback metadata, which also shifts the Langfuse `fallback_used`
  count) and a frontend effect dependency, across 18 findings.
