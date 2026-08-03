---
created: 2026-08-03
baseline_commit: 71417071ba42a28a3f7e6ef2720f706176041501
story_key: 8-19-embedding-asset-retrieval-layer
story_id: "8.19"
epic: 8
previous_story: 8-18-cast-decision-diversity-validator
depends_on:
  - 8-6-asset-library-management
  - 8-17-location-plate-data-generation
related:
  - 8-18-cast-decision-diversity-validator
  - 13-1-surface-silent-degradations
workflow_decision: "Diagnosis first. If reuse-selection failure is confirmed, improve constrained LLM selection and add only a conservative stdlib matcher in scenario_chain.py. Embeddings and asset_retrieval_service.py remain a separately justified escalation, never default scope."
completion_note: "Ultimate context engine analysis completed - comprehensive developer guide created"
---

# Story 8.19: Asset-Reuse Selection — stdlib/LLM First, Embeddings Last

Status: ready-for-dev

## Story

> The epic entry is a draft and contains no verbatim user-story statement. The following is a faithful synthesis of its intent.

As Jay,
I want STOCK character and location reuse decisions to be evidence-backed and constrained to known asset keys, with a safe free-generation outcome,
so that narration and imagery stay aligned without adding an embedding stack unless simpler matching is demonstrably insufficient.

## Context and Decision Ladder

Image–narration mismatch continued to be observed after Story 5.5, but the proposed cause—incorrect STOCK-reuse versus free-generation selection—is explicitly a hypothesis, not a confirmed diagnosis. The epic requires this ladder:

1. **Stage 0 — prove the cause:** trace 3–5 recent mismatches end-to-end before changing code.
2. **Stage 1 — no new dependency:** give the LLM explicit key/description choices plus `None`, validate the structured result, and use conservative stdlib text matching only where the evidence requires it.
3. **Stage 2 — conditional escalation:** only measured residual semantic misses after Stage 1 may open a separate decision to add a local embedding implementation.

The current checkout cannot complete Stage 0: `yt_flow.db` has no `run` rows and `workspace/` contains no per-run scenario/image/video artifacts. Historical evidence identifies other root causes: Story 8.11 found that a whole scene displayed only its first shot; iteration 1 had ten empty-background shots because `SCP-049-2` cards were missing; and all `location_key` values in that run were `None` because the prompt was not live. Do not reuse those cases as proof of this story's hypothesis.

## Acceptance Criteria

1. **Blocking diagnosis gate.** Before production-code or prompt edits, document 3–5 traceable, recent image–narration mismatch cases. Each row records: run ID, scene/shot, narration sentence, `image_prompt`, emitted `cast`/`location_key`, eligible approved asset key(s), final asset source (STOCK or generated), expected decision (`key` or `None`), observed frame, and root-cause classification. Classifications distinguish at least selection failure, missing/unapproved asset, prompt/parser failure, generation noise, and downstream composition/substitution failure. Evidence must come from real artifacts/checkpoints/logs; it must not be reconstructed or invented.
2. **Honest stop condition.** If fewer than 3 traceable cases are available, or the evidence does not support reuse-selection failure as a material cause, stop without changing runtime code, prompts, dependencies, or configuration. Record the result and recommended owning story in this file's Dev Agent Record. This evidence-backed no-code outcome satisfies the story; do not implement speculative retrieval.
3. **Stage-1 scope gate.** Only if AC1 supports the hypothesis, implement the smallest affected namespace demonstrated by the evidence—location selection first unless cast selection is independently proven. Do not generalize arbitrary SCP or derived `<scp_id>-<n>` identity keys into fuzzy STOCK-character matching.
4. **Constrained LLM selection.** For each affected namespace, the relevant repo prompt receives a compact controlled catalog of allowed key plus description/aliases and requires exactly one catalog key or the existing no-reuse outcome (`None`/omission; empty cast where applicable). Returned keys remain subject to the current strict/lenient parser contracts: hallucinated or malformed keys never become asset identities and safely degrade to the existing fallback.
5. **Narrow pure matcher.** If Task 0 demonstrates that structured catalog selection alone is insufficient, add a total, deterministic pure helper with the conceptual contract `text + typed candidates -> unique best key or None`. It uses controlled aliases/keyword overlap first and may use `difflib.SequenceMatcher` only as a lexical tie aid. It never raises, never queries DB, never mutates input state, and never crosses asset namespaces.
6. **Precision-first fallback.** The matcher returns `None` for empty input/catalog, anomaly-specific environments, below-threshold scores, ambiguous ties, or insufficient winner margin. Thresholds and margin are calibrated on diagnosed positive and negative examples—not copied from a generic documentation example. A false STOCK match is worse than the existing free-generation fallback.
7. **Preservation rules.** A valid explicit catalog key and an explicit no-reuse decision are not rewritten by weak fuzzy evidence. Matcher integration is mark-targeted: unrelated shots and all non-selection fields (`image_prompt`, `negative_prompt`, cast placement/motion, camera fields, sentence indices) remain byte-identical. Existing 1:1 sentence coverage, bounded retry, `_enforce_camera_variety`, `_enforce_cast_diversity`, and derived-entity provisioning remain unchanged.
8. **Runtime consumption remains approved-only.** Scenario code does not query asset tables. `LocationService` and existing character resolution remain the authorities that expose approved assets; a missing lookup continues to warn and fall back non-fatally to normal generation. No asset lifecycle, manifest, style epoch, path, DB schema, image-node copy logic, or cleanup behavior changes.
9. **Decision evidence.** Stage-1 evaluation records, at minimum in diagnostic/test evidence and structured logs, the candidate namespace, selected key/`None`, match method, score/reason, threshold, and ambiguity result. This story does not add UI or gate-warning plumbing; Story 13.1 owns visible run-level degradation warnings.
10. **Stage-1 verification.** Automated tests cover exact key/alias, Korean controlled synonyms, keyword overlap, lexical near-match, unrelated negative, ambiguity/tie, empty input/catalog, Unicode normalization, determinism, idempotence, valid-key/no-reuse preservation, hallucinated-key fallback, and `build_scenes` integration. Existing cast, location parser, camera/cast validator, stub-profile, and free-generation tests remain green.
11. **Prompt deployment follows current policy.** Repo prompt files remain the source of truth. In current DEV MODE, any prompt change is seeded directly with `uv run python scripts/migrate_prompts.py --label production --source prompts`; no A/B, golden-set, promotion gate, `--baseline`, or `YTFLOW_ALLOW_AB_GATE` action is required or permitted as completion evidence.
12. **Embedding escalation is not part of Stage 1.** If Stage 1 resolves the diagnosed cases, `pyproject.toml`, `config.py`, and `src/yt_flow/services/asset_retrieval_service.py` do not change. Only if documented Stage-1 replay still fails on semantic paraphrase/homonym cases may the developer stop and propose Stage 2 with research covering Korean retrieval quality, commercial license, local footprint, determinism, and dependency impact. Do not install or stub an embedding model in this story without that evidence and an explicit scope decision.
13. **No graph or product-surface changes.** The LangGraph topology remains `scenario → image → tts → subtitle → video`; no new node, API, DB table, UI, asset-generation path, curation flow, compositing behavior, or paid retrieval API is added.
14. **Quality gates.** For a Stage-1 implementation, run `PYTHONPATH=$PWD/src uv run pytest tests/pipeline/nodes/test_scenario_chain.py -q`, all directly affected test files, `uv run pytest -q`, and Ruff on changed Python files. Repository coverage remains at least 80%.

## Tasks / Subtasks

- [ ] Task 0: Execute the blocking diagnosis (AC: 1, 2)
  - [ ] Obtain 3–5 recent run artifacts/checkpoints/logs from the actual runtime environment; this checkout alone is insufficient.
  - [ ] Build the evidence table with the fields and classifications in AC1.
  - [ ] Decide `SUPPORTED` or `NOT SUPPORTED`, citing every case.
  - [ ] If `NOT SUPPORTED` or evidence is unavailable, record the redirect/no-code conclusion and stop.
- [ ] Task 1: Define Stage-1 candidate scope from evidence (AC: 3, 8)
  - [ ] Select `location`, `cast`, or both only when separately supported.
  - [ ] Identify a runtime-safe source for compact controlled descriptions/aliases; do not import `scripts/seed_*` from production code and do not duplicate generation prompts blindly.
  - [ ] Assert catalog coverage against `LOCATION_KEYS` and/or `STOCK_CAST_KEYS` for any namespace implemented.
- [ ] Task 2: Strengthen structured LLM selection (conditional on Task 0) (AC: 4, 7, 11)
  - [ ] Update only the affected repo prompt(s) and template variables.
  - [ ] Preserve existing output counts, schemas, and explicit no-reuse semantics.
  - [ ] Seed repo prompts directly to `production` under current DEV MODE after tests pass.
- [ ] Task 3: Add the stdlib matcher only if diagnosed cases require it (conditional) (AC: 5–7)
  - [ ] Implement the narrow pure helper in `scenario_chain.py` near the existing normalization/repair helpers.
  - [ ] Normalize controlled text deterministically; apply alias/keyword logic before any `SequenceMatcher` tie aid.
  - [ ] Calibrate threshold and winner margin on the Task-0 examples plus hard negatives.
  - [ ] Preserve valid explicit keys/no-reuse outcomes unless the evidence-backed integration rule explicitly requires otherwise.
- [ ] Task 4: Add regression and integration coverage (conditional) (AC: 9, 10, 14)
  - [ ] Add the matcher, prompt-placeholder, parser, and `build_scenes` tests listed in AC10.
  - [ ] Assert unrelated selection namespaces and all non-selection fields remain unchanged.
  - [ ] Replay the diagnosed cases through Stage 1 and record before/after decisions.
- [ ] Task 5: Close or escalate honestly (AC: 12, 13)
  - [ ] If Stage 1 succeeds, verify no embedding/service/config/dependency changes exist.
  - [ ] If semantic misses remain, document them and stop with a Stage-2 proposal; do not silently broaden this implementation.

## Dev Notes

### Current State of Files Potentially Updated

- `src/yt_flow/pipeline/nodes/scenario_chain.py`
  - **Today:** `cast_decision_step` gives DeepSeek only comma-joined STOCK cast keys and strictly parses one cast list per sentence. `visual_breakdown_step` gives it only comma-joined location keys. `parse_cast` normalizes known STOCK/SCP casing while preserving derived identities; `parse_location_key` performs exact case-insensitive canonicalization and unknown keys become `None`. `build_scenes` writes both fields and then runs the existing camera/cast deterministic repairs.
  - **Conditional change:** add catalog rendering and, only if required, one stdlib-only pure matcher at the existing normalization boundary.
  - **Preserve:** 1:1 coverage, retry/error behavior, current parsers, arbitrary SCP/derived identity handling, camera/cast repairs, and every non-selection field.
- `prompts/scenario/visual_breakdown.md`
  - **Today:** asks the LLM to choose one of 14 bare `location_key` names or omit the field; it does not receive the controlled meaning/aliases of those keys.
  - **Conditional change:** provide a compact key→description/alias catalog and sharpen key-or-omit output rules.
  - **Preserve:** background-only prompt contract, populated `image_prompt`, 1:1 shot schema, cast attachment, camera rules, and anomaly-specific free generation.
- `prompts/scenario/cast_decision.md`
  - **Today:** lists the run entity and three bare STOCK cast keys, while supporting derived entity keys.
  - **Conditional change:** only if Task 0 independently proves cast-role selection failures, add controlled role descriptions/aliases.
  - **Preserve:** the run entity and derived identities as exact opaque keys; empty cast remains valid.
- `src/yt_flow/domain/state.py`
  - **Today:** owns the canonical three `STOCK_CAST_KEYS`, 14-value `LocationKey`, and `LOCATION_KEYS` tuple.
  - **Conditional change:** only if centralizing a small pure catalog here prevents key/description drift; no state schema change is expected.
- `tests/pipeline/nodes/test_scenario_chain.py`
  - **Today:** covers prompt placeholders, cast decision parsing, `parse_location_key`, `build_scenes` location attachment, and the 8.18 deterministic repair pattern.
  - **Conditional change:** add the AC10 matrix and integration tests alongside those blocks.

Files that must remain unchanged in Stage 1 unless Task 0 exposes a separate defect: `src/yt_flow/pipeline/nodes/image.py`, `src/yt_flow/services/location_service.py`, DB models, API/frontend code, video/compositing code, `config.py`, and `pyproject.toml`.

### Implementation Shape and Guardrails

- Clone Story 8.18's proven shape: pure, total, deterministic, idempotent, mark-targeted, INFO-logged, no LLM re-call, and integration-tested through `build_scenes`.
- Keep candidate namespaces typed and separate. A location query must never return a character key; arbitrary SCP/derived character identities must never fuzzy-collapse to a `STOCK-*` key.
- Use the narrowest evidence-bearing text: current shot narration plus scene location and/or current `image_prompt`. Whole-scene narration can mention several locations and is unsafe as a single query.
- Do not compare Korean narration directly against English generation prose and call the result semantic retrieval. Controlled Korean aliases are required for Korean lexical matching.
- `SequenceMatcher.ratio()` is lexical, may depend on argument order, and is not a semantic or cross-language model. If used, fix argument ordering, normalize text, set/test `autojunk` deliberately, and calibrate on project examples.
- Precision beats recall: `None` preserves the mature, non-fatal ComfyUI generation path; a false STOCK match produces a confidently wrong frame.
- Keep observability scoped: diagnostic/log evidence belongs here; gate/UI warning transport belongs to Story 13.1.

### Architecture Compliance

- **AD-1:** import direction remains `api → services → (pipeline | db) → domain`; `scenario_chain.py` must not import DB or service catalog queries.
- **AD-2/AD-4:** scenario helpers operate on freshly constructed data and return JSON-serializable keys/`None`; they do not write DB, emit SSE, or mutate asset records.
- **AD-5:** shot remains the image-generation and matching unit; do not decide once per scene when shots can occupy different locations.
- **AD-10:** unknown, ambiguous, or unavailable reuse degrades visibly to `None`/free generation; no silent forced match.
- No new pipeline stage. Approved-only asset consumption and deterministic plate variant selection stay downstream.

### Library and Framework Requirements

- Actual project pins: Python `>=3.12,<3.13`, LangGraph `1.2.7`, FastAPI `0.138.2`, SQLModel `0.0.39`, Langfuse `4.12.0`, pytest `9.1.1`, Ruff `0.15.20`.
- Stage 1 uses only the standard library; the repository currently has no embedding/CLIP dependency and DeepSeek is used through chat completions only.
- Do not add an OpenAI-compatible embedding assumption: the configured DeepSeek path has no project embedding contract.

### Testing Requirements

- Run worktree code with `PYTHONPATH=$PWD/src`; a global editable installation may otherwise shadow it.
- Test `None` and hard negatives as first-class success cases, not only positive matches.
- Include real Korean aliases and intentionally confusable pairs; do not label a hand-written easy example as semantic retrieval proof.
- Verify current fallback end-to-end: unknown/ambiguous choice → `location_key=None` → existing image generation path, with no new exception.
- If Task 0 ends the story without code, verification is the completed evidence table plus a clean diff proving no runtime/prompt/dependency files changed.

### Previous Story Intelligence

- Story 8.18/commit `fcad36f` is the template: an inline deterministic post-LLM repair with no service, no config, no prompt re-call, and exhaustive pure/integration tests.
- Its review caught a repair that displaced a healthy later sibling. Apply the same lesson here: weak evidence must not rewrite a healthy explicit decision or unrelated shot.
- Story 8.17 proved all 42 location plates are approved and the STOCK fast path fires. Code/schema existence is not evidence of correct selection; this story must inspect actual post-8.17 decisions.
- Story 8.13 fixed the documented SCP-049-2 empty-frame mismatch. Do not misclassify missing derived-card provisioning as STOCK retrieval.

### Git Intelligence

- Relevant recent commits: `fcad36f` (Story 8.18 deterministic cast validator), `76da474` (42/42 location plates approved), `eb17118` (8.17 review fixes), `b5a2b35`/`8ae36a6` (real plate generation and labeling).
- `scenario_chain.py`, its tests, and `sprint-status.yaml` are recurring edit hotspots. Preserve unrelated worktree changes and stage status edits surgically.

### Latest Technical Information

- Python 3.12 `difflib.SequenceMatcher` returns a lexical ratio in `[0,1]`; it is not guaranteed symmetric by argument order, and `autojunk` can alter matching for long repetitive sequences. The documentation's `0.6` example is illustrative, not a project threshold.
- Animate-A-Story (arXiv:2307.06940) retrieves video motion structures from text and uses them to guide synthesis. It supports retrieval-guided storytelling directionally, but it is not evidence that this project needs CLIP-based static asset matching.
- No embedding-model research is needed unless Stage-1 replay demonstrates residual semantic failures. At that point, research must be a visible escalation decision, not an implementation side effect.

### Project Structure Notes

- Stage-1 production code stays in `src/yt_flow/pipeline/nodes/scenario_chain.py` plus affected repo prompt(s) and tests.
- A new `src/yt_flow/services/asset_retrieval_service.py`, service tests, model configuration, and dependency changes belong only to an explicitly approved Stage 2.
- No UX changes: the existing scenario gate exposes `location_key`, and image review/retry already exists.

### References

- [Source: _bmad-output/planning-artifacts/epics.md:1187] — Epic 8 objective and architecture transition
- [Source: _bmad-output/planning-artifacts/epics.md:1213] — asset library identity, approval, provenance, and lifecycle
- [Source: _bmad-output/planning-artifacts/epics.md:1256] — real location-plate data generation
- [Source: _bmad-output/planning-artifacts/epics.md:1264] — Story 8.19 hypothesis and Stage 0→1→2 ladder
- [Source: _bmad-output/implementation-artifacts/epic-8-context.md:31] — Epic 8 constraints and technical decisions
- [Source: _bmad-output/implementation-artifacts/8-18-cast-decision-diversity-validator.md:29] — deterministic-repair precedent and review lessons
- [Source: _bmad-output/implementation-artifacts/e2e-iteration1-2026-07-09.md:14] — historical mismatch and non-retrieval causes
- [Source: _bmad-output/implementation-artifacts/8-11-per-shot-cut-assembly.md:39] — first-shot-only mismatch root cause
- [Source: _bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md:37] — dependency direction and state-purity invariants
- [Source: src/yt_flow/domain/state.py:38] — canonical STOCK and location vocabularies
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:97] — current key normalization and deterministic repair helpers
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:924] — current cast-decision call and bare-key catalog input
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:999] — current visual-breakdown call and bare location keys
- [Source: src/yt_flow/pipeline/nodes/scenario_chain.py:1251] — `build_scenes` integration boundary
- [Source: prompts/scenario/cast_decision.md:7] — current cast vocabulary contract
- [Source: prompts/scenario/visual_breakdown.md:205] — current location-key selection contract
- [Source: src/yt_flow/services/location_service.py:30] — approved-only plate lookup
- [Source: docs/PROMPT_POLICY.md:5] — current DEV MODE direct-production prompt workflow
- [Source: pyproject.toml:1] — actual dependency pins and coverage gate
- [Python 3.12 difflib documentation](https://docs.python.org/3.12/library/difflib.html)
- [Animate-A-Story, arXiv:2307.06940](https://arxiv.org/abs/2307.06940)

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Diagnostic Evidence and Gate Decision

<!-- Task 0 owner: add the 3–5-case table and SUPPORTED / NOT SUPPORTED decision here. -->

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created

### File List

## Change Log

- 2026-08-03: Story context created; status set to ready-for-dev. Scope fixed as diagnosis-first, stdlib/LLM Stage 1 only when supported, embeddings as a separately justified last resort.
