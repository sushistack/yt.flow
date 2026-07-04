---
baseline_commit: 8946828
---

# Story 6.2: Golden Set + Offline Prompt Regression Eval Runner

Status: review

## Story

As Jay,
I want a fixed golden set of SCP inputs and a cheap offline eval runner that scores a prompt label without running the full pipeline,
so that prompt promotions are gated on no regression across known inputs, not on one lucky A/B run.

## Context

Story 6.1 made prompt A/B real: `prompt_variant="B"` now maps to Langfuse label `candidate`, while `None`/`"A"` stays on production. This story turns the policy rule "golden-set regression before promotion" into a repeatable script.

For this creative pipeline, the golden set is not expected-output snapshots. There is no canonical "right video." The durable contract is fixed inputs + a stable rubric + score trends. Run only the `scenario` stage: it is where prompt changes have the strongest quality signal and avoids image/TTS/video cost, DB run creation, LangGraph gates, and full workspace artifacts.

## Acceptance Criteria

1. **Given** Langfuse Datasets, **Then** a `golden-scps` dataset exists with deterministic items for 2-3 committed SCP inputs, starting with `SCP-096`, `SCP-173`, and `SCP-049` from `data/scps.json`.
2. **Given** `uv run python scripts/eval_prompts.py --label candidate`, **When** it runs, **Then** it fetches the golden set and executes `scenario_node` only for each item with `prompt_variant="B"`; no DB `Run` row, graph invocation, gate, image, TTS, subtitle, or video work is created.
3. **Given** a label of `production`, **Then** the runner executes the same scenario path with `prompt_variant=None` or `"A"` so existing production prompt-fetch behavior is preserved.
4. **Given** a scenario output, **Then** it is scored with the existing Epic 4 LLM-as-judge axes (`atmosphere`, `narrative_coherence`, `article_fidelity`) and scenario-applicable rule metrics only; do not invent a second evaluation rubric.
5. **Given** Langfuse dataset runs, **Then** every item result records output and scores in Langfuse so label/run trends are comparable in the Langfuse UI.
6. **Given** `--label candidate --baseline production`, **Then** the script evaluates both labels against the same golden set and prints a comparison table with per-axis deltas, total delta, failures, and pass/fail promotion verdict.
7. **Given** a scenario failure for one item, **Then** that item is recorded as failed, the script continues with remaining items, and any item failure makes the final verdict fail.
8. **Given** the runner implementation, **Then** it remains a pure script/helper layer; do not add eval-only branches to pipeline nodes, services, FastAPI routes, or LangGraph graph topology.
9. **Given** `docs/PROMPT_POLICY.md`, **Then** the golden-set section is updated with the command, required pass criteria, and the rule that promotion is blocked unless candidate has no axis regression and total score is greater than or equal to baseline.

## Tasks / Subtasks

- [x] Add `scripts/eval_prompts.py` with CLI options `--label`, `--baseline`, `--dataset golden-scps`, `--seed`, and optional `--max-concurrency` (AC: 1, 2, 3, 6, 7)
- [x] Implement idempotent dataset seeding from `data/scps.json`; use stable dataset item ids so repeated `--seed` does not duplicate items (AC: 1)
- [x] Execute `scenario_node` directly with a minimal `PipelineState` per item and label mapping: `candidate` -> `prompt_variant="B"`, `production` -> `prompt_variant=None`; reject any non-`production`/`candidate` label unless explicitly supported by policy (AC: 2, 3, 8)
- [x] Reuse `yt_flow.services.eval_service` scoring primitives for LLM judge scores; reuse only scenario-applicable rule metrics such as scene count and shot/narration structural checks (AC: 4)
- [x] Record dataset run outputs and item scores through Langfuse v4 dataset/experiment APIs; ensure scores include item id, label, prompt label metadata, and failure state (AC: 5, 7)
- [x] Implement baseline comparison mode and terminal table; verdict fails on any item failure, any candidate axis below baseline, or candidate total below baseline (AC: 6)
- [x] Update `docs/PROMPT_POLICY.md` with golden-set commands and pass criteria (AC: 9)
- [x] Add tests with fake Langfuse client, fake `scenario_node`, and fake judge calls; no live network, no DB writes, no pipeline graph invocation (AC: 1-8)

## Dev Notes

### Source Context

- Epic 6 goal: prompt changes must move through version + label + evaluation-gated promotion, using Langfuse labels and Datasets rather than custom infra. [Source: `_bmad-output/planning-artifacts/epics.md#Epic 6: Prompt Ops — 프롬프트 버저닝·평가 정책`]
- Story 6.2 foundation: seed 2-3 fixed SCPs as a Langfuse Dataset, run only the scenario chain, score with Epic 4 axes, and compare `candidate` against `production`. [Source: `_bmad-output/planning-artifacts/epics.md#Story 6.2: 골든셋 + 오프라인 프롬프트 회귀 평가 러너`]
- PRD F4 defines the evaluation axes: LLM-as-judge for atmosphere, narrative coherence, article fidelity; rule-based structural metrics; results recorded in Langfuse. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#F4 — A/B Testing & Evaluation`]
- Architecture AD-6 says A/B variants are independent runs, not graph branches. For this offline script, preserve that spirit by running independent scenario-only evaluations, not by branching the graph. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-6 — A/B testing is two independent runs linked by ab_pair_id`]
- Architecture AD-10 says Langfuse tracing failures are non-fatal for pipeline execution. For the eval runner, scenario generation failure is a failed item, while Langfuse score/write failure should fail the script because the requested artifact is the dataset run. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10 — Operational envelope`]

### Files To Create Or Update

- `scripts/eval_prompts.py` (new): CLI orchestration, dataset seeding, label/baseline loop, terminal comparison.
- `docs/PROMPT_POLICY.md` (update): add golden-set command and promotion criteria.
- `tests/test_eval_prompts.py` or `tests/scripts/test_eval_prompts.py` (new): fake Langfuse + fake scenario/eval seams.
- Optional helper extraction in `src/yt_flow/services/eval_service.py` only if needed to avoid duplication. Keep it small and general, not golden-set specific.

### Existing Code To Reuse

- `scenario_node` already contains correct label wiring: line 135 maps `prompt_variant="B"` to `candidate`; lines 136-158 pass that label into format guide and every scenario chain step; line 162 returns `scenes` without requiring the rest of the pipeline. [Source: `src/yt_flow/pipeline/nodes/scenario.py#L125`]
- `prompt_service.get_prompt_with_fallback()` logs a warning when a candidate prompt is missing and falls back to production. Do not bypass this by fetching prompts directly in the eval script. [Source: `src/yt_flow/services/prompt_service.py#L50`]
- `eval_service.AXES`, `_score_run()`, `_artifact_text()`, `AxisScores`, and parsing/timeout behavior already implement the Story 4 judge semantics. Reuse them rather than creating another judge client. [Source: `src/yt_flow/services/eval_service.py#L36`]
- `eval_service.determine_winner()` and `store_evaluation_results()` are pairwise A/B DB-oriented helpers. Do not call them directly for dataset runs unless refactored; the golden-set runner needs per-item/per-label trend scores, not `runs.ab_result`. [Source: `src/yt_flow/services/eval_service.py#L454`]
- Golden inputs already live in `data/scps.json`; start with `SCP-096`, `SCP-173`, and `SCP-049`. [Source: `data/scps.json#L1`]

### Langfuse v4 Dataset / Experiment API

- Installed SDK is `langfuse==4.12.0`; local inspection confirms `Langfuse.create_dataset`, `create_dataset_item`, `get_dataset`, `run_experiment`, `create_score(..., dataset_run_id=...)`, and `flush()` exist. [Source: `pyproject.toml#L10`]
- Current Langfuse docs recommend `dataset.run_experiment(...)` / experiment runner for hosted datasets; it automatically creates dataset runs, isolates item failures, and exposes comparison in the UI. If the project wrapper uses `Langfuse.run_experiment(...)` directly, pass hosted dataset items and keep the same visible dataset-run behavior. [Source: https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk]
- Dataset creation supports `create_dataset(name=..., description=..., metadata=...)`, and item creation supports `create_dataset_item(dataset_name=..., input=..., expected_output=..., metadata=..., id=...)`; provide stable ids to dedupe. [Source: https://langfuse.com/docs/evaluation/experiments/datasets]
- Dataset item `expected_output` may be omitted or used for rubric metadata; do not store a fixed expected scenario script.

### Suggested Implementation Shape

Use a few small pure helpers so tests can exercise behavior without live Langfuse or DeepSeek:

```python
GOLDEN_IDS = ("SCP-096", "SCP-173", "SCP-049")

def prompt_variant_for_label(label: str) -> str | None:
    if label == "candidate":
        return "B"
    if label == "production":
        return None
    raise ValueError("Only production/candidate labels are supported by Prompt Policy")
```

For each dataset item, build a minimal state:

```python
state = {
    "run_id": f"offline-eval-{label}-{scp_id}",
    "scp_id": scp_id,
    "scp_text": scp_text,
    "scenes": [],
    "video_path": None,
    "current_stage": "scenario",
    "gate_states": {},
    "prompt_variant": prompt_variant_for_label(label),
    "error": None,
}
```

Call `await scenario_node(state)`. If `out["error"]` is present or `out["scenes"]` is missing/empty, record a failed item and continue. For successful items, construct a `PipelineState`-like value with `scp_text` and `scenes`, then feed narration text to `_score_run(scp_text, _artifact_text(state), settings)`.

### Scenario-Applicable Rule Metrics

Epic 4's subtitle sync and audio duration metrics require downstream stages and are out of scope for scenario-only evaluation. The runner may include:

- `scene_count`
- total shot count
- empty narration count (should be zero)
- empty image prompt count (should be zero after `build_scenes`)
- average shots per scene

Keep these separate from the LLM judge axes. Do not pretend subtitle/audio metrics were measured.

### Baseline Comparison Criteria

For each SCP item and each axis:

- Candidate axis score must be greater than or equal to production axis score.
- Candidate total must be greater than or equal to production total.
- Candidate must not fail generation or scoring.
- If production fails, print the failure and mark the comparison inconclusive/failing; a broken baseline cannot justify promotion.

The script exit code should be `0` only when all compared items pass. Use non-zero for regression, item failure, invalid label, or Langfuse dataset write failure.

### Test Requirements

- Dataset seeding is idempotent: repeated seed calls use the same ids and do not create duplicate logical items.
- `--label candidate` builds states with `prompt_variant="B"`; `--label production` builds `prompt_variant=None`.
- Runner calls `scenario_node` directly and never calls `run_service`, `graph`, DB init/session, or FastAPI routes.
- One failed scenario item does not stop the loop, but final verdict/exit status fails.
- Baseline comparison fails when any candidate axis or total is lower than production.
- Langfuse APIs are faked; DeepSeek/judge calls are faked via `eval_service._score_run` or `_post_chat` seams. Follow existing offline cassette style where useful. [Source: `tests/fixtures/cassettes/README.md`]

### Previous Story Intelligence

- Story 6.1 already documented and implemented `candidate` fallback behavior. If the runner appears to produce identical production/candidate outputs, check warnings from `get_prompt_with_fallback()` before blaming scoring.
- Story 6.1 full regression was green at `uv run pytest -q` with 495 passed, 1 skipped. Keep new tests additive; avoid changing existing scenario tests unless there is a real contract change.
- Recent relevant commits:
  - `8946828` added prompt policy and Story 6.1 record.
  - `13640bc` wired variant B to candidate label with production fallback.
  - `3d413b6` added Epic 6 prompt policy + golden-set planning.

### Out Of Scope

- Full pipeline golden runs with image/TTS/subtitle/video.
- Automatic production-label promotion.
- New prompt labels beyond `production` and `candidate`.
- UI changes.
- Adding a new LLM provider or SDK; use installed `httpx`/Langfuse patterns.

## Dev Agent Record

### Agent Model Used

claude-sonnet-5

### Debug Log References

- `uv run pytest -q tests/test_eval_prompts.py` → 19 passed (new test file).
- `uv run pytest -q` (full suite) → 553 passed, 1 skipped, 0 failed.
- `uv run ruff check scripts/eval_prompts.py tests/test_eval_prompts.py` → clean.

### Completion Notes List

- `scripts/eval_prompts.py` uses `Langfuse.Dataset.run_experiment(task=..., evaluators=[...])` (SDK v4.12.0) instead of hand-rolling dataset-run/score bookkeeping: the SDK creates the dataset run, links each item's trace, and posts every `Evaluation` returned by the evaluator as a Langfuse score automatically (AC5) — the script only supplies the task (run `scenario_node`) and the evaluator (score it). `dataset.run_experiment()` is a plain sync call (it wraps its own event loop internally via `run_async_safely`), so `main()` stays fully synchronous with no `asyncio.run()` of its own.
- Task function (`_run_scenario`) builds a minimal `PipelineState` per dataset item exactly as sketched in Dev Notes and calls `scenario_node` directly — never `run_service`, the LangGraph graph, DB session, or a FastAPI route.
- `_score_evaluator` reuses `eval_service.AXES`/`_score_run` unchanged for the judge axes (import + call the module's own name, patched the same way `test_scenario.py` patches `scenario.py`'s bound names, so tests monkeypatch `eval_prompts._score_run`). Scenario-applicable rule metrics (`scene_count`, `shot_count`, `empty_narration_count`, `empty_image_prompt_count`, `avg_shots_per_scene`) are computed by a small pure `_rule_metrics()` helper, kept separate from the judge axes per Dev Notes.
- Item failure handling: `scenario_node` never raises (it already returns `{"error": ...}` internally per AD-10), so the evaluator just checks `output.get("error")` and returns a `failed` marker Evaluation instead of scoring — the loop always produces one result per dataset item (AC7). Verified with a dedicated test that a scenario failure on every item still returns all N results, each marked failed.
- Dataset seeding (`seed_dataset`) relies on the SDK's own documented upsert semantics: `create_dataset` upserts by name, `create_dataset_item(..., id=scp_id)` upserts by id — no extra existence-check code needed for idempotency (AC1).
- `compare()` implements the Dev Notes' Baseline Comparison Criteria exactly: any item failure (candidate or baseline) fails the verdict; otherwise any per-axis or total regression fails it. Exit code is `0` only when every item passes.
- `docs/PROMPT_POLICY.md` updated: new "Golden-set regression" section with commands + pass criteria, and change-protocol step 4 now points at `eval_prompts.py --baseline` instead of "eyeball the gate output" (AC9).
- Tests (`tests/test_eval_prompts.py`, following the `tests/test_prompt_migration.py` sys.path-insert-scripts-dir convention): fake Langfuse client (`create_dataset`/`create_dataset_item`/`get_dataset`) and a `FakeDataset.run_experiment` that mirrors the real SDK's task/evaluator calling convention (`task(item=item)`, `evaluator(input=, output=, expected_output=, metadata=)`, both awaited if async) — no live network, no DB, no pipeline graph. 19 new tests covering: label mapping, idempotent seeding, variant wiring per label, rule metrics, item-failure continuation, comparison pass/fail/regression/item-failure cases, and CLI exit codes.

### File List

- `scripts/eval_prompts.py` (new)
- `tests/test_eval_prompts.py` (new)
- `docs/PROMPT_POLICY.md` (modified — golden-set regression section + change-protocol step 4)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — story status in-progress)

## Change Log

- 2026-07-04: Implemented `scripts/eval_prompts.py` golden-set offline eval runner (AC1-9) using Langfuse `Dataset.run_experiment`; updated `docs/PROMPT_POLICY.md`; full regression green (553 passed, 1 skipped).
