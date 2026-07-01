---
baseline_commit: 8486f5cc5843b324dab1ce3abe9727e3f55368c9
---

# Story 4.2: Evaluation Service (LLM-as-Judge + Rule-Based)

Status: done

<!-- Ultimate context engine analysis completed — comprehensive developer guide created -->

## Story

As Jay,
I want the A/B evaluation service to score both runs using the OQ-1 rubric and OQ-6 pairwise method,
so that the comparison is automated and reproducible without manual scoring.

## Acceptance Criteria

1. Given two completed runs linked by `ab_pair_id`, when `eval_service.evaluate_ab(run_a_id, run_b_id)` runs, then LLM-as-judge scores each run on 3 axes (Atmosphere, Narrative coherence, Article fidelity) with integer 1–5 scores; each axis evaluated 3 times and averaged. [Source: `_bmad-output/planning-artifacts/epics.md#Story-4.2`]

2. Given both runs scored, when rule-based evaluation runs, then structural metrics computed: scene count match rate, avg subtitle sync error (seconds/word), audio duration variance (% per scene). [Source: `_bmad-output/planning-artifacts/epics.md#Story-4.2`]

3. Given pairwise LLM comparison, when position bias mitigation runs, then A→B order and B→A order both evaluated; contradictory results trigger a 3rd tiebreaker run. [Source: `_bmad-output/planning-artifacts/epics.md#Story-4.2`; `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#OQ-6`]

4. Given either run scores < 2/5 on any axis, when winner determination runs, then that run is flagged as below quality floor; if both fail, result is `{"winner": null, "reason": "both_below_floor"}`. [Source: `_bmad-output/planning-artifacts/epics.md#Story-4.2`; `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#OQ-6`]

5. Given `eval_service.evaluate_ab()` is called, when it runs, then total execution completes in ≤5 minutes; each individual LLM judge call has a 30-second timeout with retry-once on timeout. [Source: `_bmad-output/planning-artifacts/epics.md#Story-4.2`]

6. Given `evaluate_ab()` completes, when results are persisted, then a Langfuse trace is created containing both runs' axis scores, rule-based scores, pairwise result, and determined winner as observations under a parent trace identified by the `ab_pair_id`. [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#FR-21`; `_bmad-output/planning-artifacts/epics.md#Story-4.3` — cross-story awareness: Story 4.3 owns the API exposure of results; this story owns the evaluation computation and Langfuse persistence]

7. Given either run's LangGraph checkpoint is inaccessible or state is malformed, when `evaluate_ab()` is called, then raises a clear `ValueError` identifying the run_id and missing/malformed field before any LLM scoring begins.

## Tasks / Subtasks

- [x] Implement `src/yt_flow/services/eval_service.py` — the evaluation orchestrator (AC: 1, 2, 3, 4, 5, 6, 7)
  - [x] Define evaluation data types as TypedDicts or dataclasses: `EvalAxisScores` (3 axes × 3 runs), `RuleBasedMetrics`, `PairwiseResult`, `EvaluationResult`
  - [x] Implement `evaluate_ab(run_a_id: str, run_b_id: str) -> EvaluationResult` as the top-level entry point
  - [x] Load both runs' `PipelineState` from LangGraph `AsyncSqliteSaver` checkpoints — read `scenes`, `video_path`, `scp_text` for each run_id
  - [x] Validate precondition: both runs must exist, have `status == "complete"`, and share the same `ab_pair_id`; raise `ValueError` with specific detail on mismatch
  - [x] Run LLM-as-judge scoring (3 axes × 3 runs = 9 LLM calls per run, 18 total minimum) in parallel where possible; each call must have a 30-second timeout with one retry on timeout
  - [x] Run rule-based evaluation (pure Python, no LLM needed) comparing both runs' structural metrics
  - [x] Execute pairwise comparison: A→B and B→A order, with 3rd tiebreaker if contradictory
  - [x] Apply quality floor check: any axis score < 2 disqualifies the run; both disqualified → `winner: null, reason: "both_below_floor"`
  - [x] Persist full evaluation trace to Langfuse as a span tree under a parent trace keyed by `ab_pair_id`
  - [x] Return `EvaluationResult` with all scores, pairwise result, rule-based metrics, and winner

- [x] Implement LLM-as-judge scoring module (AC: 1, 3, 5)
  - [x] Create `_judge_axis(run_scp_text: str, run_artifacts: dict, axis: str) -> list[int]` — calls DeepSeek V4 as judge 3 times per axis
  - [x] Each judge call must: (a) fetch the judge prompt from Langfuse Prompt Hub (prompt name: `evaluation/judge`), (b) compile with `scp_text`, `axis`, and relevant artifact content, (c) require chain-of-thought reasoning before the integer score, (d) parse the 1–5 integer from the response
  - [x] Axis definitions per OQ-1:
    - **Atmosphere** — SCP clinical-horror register; tone, dread, clinical detachment
    - **Narrative coherence** — scene flow, entity consistency, logical progression
    - **Article fidelity** — factual accuracy to source SCP article (object class, containment procedures, key events)
  - [x] Handle malformed LLM responses: if parsing fails after retry, log the raw response and raise `EvalJudgeError` with the axis and attempt number
  - [x] Use `@observe` decorator on the per-axis judge function so each call appears as a Langfuse span

- [x] Implement rule-based evaluation module (AC: 2)
  - [x] Create `_compute_rule_metrics(state_a: PipelineState, state_b: PipelineState) -> tuple[RuleBasedMetrics, RuleBasedMetrics]`
  - [x] Compute scene count match rate: `1.0 - abs(len(a.scenes) - len(b.scenes)) / max(len(a.scenes), len(b.scenes))`
  - [x] Compute avg subtitle sync error: for each scene with `word_timings`, average the absolute delta between each word's `end_sec` and next word's `start_sec` beyond expected gap (if aligner provides word-level timings); fall back to scene count of subtitle entries vs narration word count if timing data is sparse
  - [x] Compute audio duration variance: `stddev(scene.audio_duration for scene in scenes) / mean(audio_duration)` expressed as percentage per scene
  - [x] Return metrics as structured data; this is pure computation — no LLM, no I/O

- [x] Implement pairwise comparison logic (AC: 3, 4)
  - [x] Create `_pairwise_compare(scores_a: EvalAxisScores, scores_b: EvalAxisScores, metrics_a: RuleBasedMetrics, metrics_b: RuleBasedMetrics) -> PairwiseResult`
  - [x] Run A→B comparison: LLM judge sees A first, then B, picks winner or tie
  - [x] Run B→A comparison: LLM judge sees B first, then A (position bias mitigation)
  - [x] If both agree → that run wins. If both say tie → rule-based tiebreaker. If contradictory → 3rd LLM tiebreaker run
  - [x] Rule-based tiebreaker (OQ-6): compare (a) scene count match to expected/article count, (b) subtitle sync ≤0.5s/word, (c) audio duration variance ≤10%. Best-of-3 on these metrics wins; if still tied → `"tie"`
  - [x] Apply quality floor: any axis score < 2 in a run → that run cannot win; if both below floor → `winner: null, reason: "both_below_floor"`

- [x] Implement Langfuse trace persistence (AC: 6)
  - [x] Create a parent trace with `name="ab-evaluation"` and `user_id=ab_pair_id`
  - [x] Each judge call, rule-based computation, and pairwise comparison creates a child span or generation under the parent trace
  - [x] Final evaluation result (winner, all scores, all metrics) stored as trace output/metadata
  - [x] Use `langfuse` SDK v4.x `@observe` decorator or explicit span context manager; ensure trace tree is inspectable in Langfuse UI
  - [x] Langfuse write failures are non-fatal to evaluation — log error and continue; the `EvaluationResult` return value is the authoritative output

- [x] Write tests (AC: 1, 2, 3, 4, 5, 7)
  - [x] Unit test `_compute_rule_metrics` with known PipelineState fixtures — no LLM dependency
  - [x] Unit test `_pairwise_compare` with mock `EvalAxisScores` and `RuleBasedMetrics` — verify quality floor, tiebreaker, and 2/3 majority logic
  - [x] Unit test precondition validation: missing run_id, non-complete status, mismatched ab_pair_id
  - [x] Unit test `evaluate_ab` with mock LangGraph state loader + mock LLM judge — verify the orchestration flow
  - [x] Integration test marker or skip: real `evaluate_ab` requires completed runs in the DB; use `@pytest.mark.integration` or `YTFLOW_EVAL_LIVE_TESTS=true` env guard
  - [x] Verify no test requires live DeepSeek V4 or live Langfuse unless explicitly opted in

## Dev Notes

### Scope Boundary

This story builds the evaluation computation engine — `services/eval_service.py`. It owns:

- LLM-as-judge scoring against the OQ-1 3-axis rubric
- Rule-based structural metric computation
- Pairwise comparison with OQ-6 position-bias mitigation
- Langfuse trace persistence of evaluation results
- Returning `EvaluationResult` with winner determination

This story does NOT own:

- **Story 4.1**: A/B run creation (`POST /runs/{id}/ab`) — creates the second run with `prompt_variant="B"` and `ab_pair_id`
- **Story 4.3**: API endpoint exposure of results (`GET /runs/{id}` with `ab_result` field) — wraps `eval_service` output as HTTP responses
- **Story 2.1/2.2**: Run CRUD, SSE infrastructure — `evaluate_ab` reads LangGraph state directly, not via HTTP
- Pipeline nodes, gate mechanism, or UI components

### Critical Dependency Chain

```
Story 1.4 (LangGraph + AsyncSqliteSaver) → provides checkpoint reads
Story 1.5 (scenario_node) → provides scenes[].narration for judge context
Story 1.6 (image_node) → provides ShotData.image_path
Story 1.7 (tts_node) → provides audio_path + word_timings for rule-based metrics
Story 1.8 (subtitle_node) → provides subtitle_path for rule-based sync check
Story 1.9 (video_node) → provides video_path (final artifact reference)
Story 4.1 (A/B run creation) → provides ab_pair_id linking two completed runs
THIS STORY (4.2) → computes evaluation between those two runs
Story 4.3 → exposes results via API
```

**Reality check**: None of the Epic 1 pipeline stories (1.4–1.9) are implemented yet. When this story is developed, `PipelineState` will exist only as TypedDicts in `domain/state.py`. The `evaluate_ab` function must be designed to work with `PipelineState` as its input contract — it reads state via `AsyncSqliteSaver.aget_tuple(config)` and validates field presence. It does not require the pipeline to actually run; it requires well-formed checkpoint data.

For testing: construct `PipelineState` fixtures directly. For integration: manually insert checkpoints or use a pre-populated test DB.

### Architecture Compliance

- **AD-1 — Layer direction**: `eval_service.py` lives in `services/`. It may import from `domain/` (state types) and use `AsyncSqliteSaver` from `langgraph.checkpoint.sqlite.aio`. It must NOT import from `api/` or `pipeline/`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-1`]

- **AD-6 — A/B as two independent runs**: `evaluate_ab` reads both runs' LangGraph checkpoints independently. It does not create new runs, modify existing runs, or branch the graph. The `ab_pair_id` is read from the `runs` table (or passed explicitly) to validate that the two runs are a legitimate pair. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-6`]

- **AD-4 — services/ owns orchestration**: `eval_service` is the single entry point for evaluation. API routes (Story 4.3) will call `eval_service.evaluate_ab()` — they never implement evaluation logic directly. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-4`]

- **AD-2 — LangGraph state is source of truth**: `evaluate_ab` reads artifact paths, scene data, and narration text from `PipelineState` via LangGraph checkpoints. It does NOT read the `runs` table for evaluation data. The `runs` table is consulted only for metadata validation (status check, ab_pair_id). [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-2`]

- **AD-10 — Operational envelope**: Langfuse write failures during result persistence are non-fatal — log the error and return the `EvaluationResult`. The evaluation output is the return value; the Langfuse trace is observability, not the system-of-record. DeepSeek V4 timeout (30s) + retry-once prevents a stuck judge call from blocking the entire evaluation pipeline. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10`]

### OQ-1: 3-Axis Rubric (Fully Resolved)

The LLM-as-judge rubric was resolved in PRD open items. No design ambiguity remains.

| Axis | Definition | Scoring Guidance |
|------|-----------|-----------------|
| **Atmosphere** | SCP clinical-horror register — tone, dread, clinical detachment, bureaucratic horror | 1 = generic/non-SCP tone; 3 = adequate clinical register; 5 = exemplary SCP atmosphere (cold precision + creeping dread) |
| **Narrative coherence** | Scene flow, entity consistency, logical progression from containment to incident | 1 = disjointed/contradictory; 3 = coherent but flat; 5 = tight narrative with natural scene transitions and consistent entity portrayal |
| **Article fidelity** | Factual accuracy to source SCP article: object class, containment procedures, key events, entity properties | 1 = major factual errors or omissions; 3 = mostly accurate with minor deviations; 5 = article-perfect portrayal with all key facts present |

**Scoring protocol** (per OQ-1):
- Each axis scored 3 independent times, then averaged → float
- LLM must produce chain-of-thought reasoning before the integer score
- Total score = sum of 3 axis averages (range: 3.0–15.0)
- The judge prompt must be in Langfuse Prompt Hub as `evaluation/judge` — not hardcoded in `eval_service.py`

### OQ-6: Pairwise Winner Determination (Fully Resolved)

1. **Pairwise comparison**: LLM judge compares A vs B (A→B order), then B vs A (B→A order)
2. **Majority**: 2/3 required — if both orders agree, that variant wins
3. **Contradictory**: A→B says A wins, B→A says B wins → 3rd LLM tiebreaker run
4. **Rule-based tiebreaker** (if LLM cannot decide):
   - Scene count match to expected/article count
   - Subtitle sync ≤0.5s/word average error
   - Audio duration variance ≤10% across scenes
5. **Quality floor**: Every axis must score ≥2/5. If any axis < 2 in a run, that run is disqualified. Both below floor → `winner: null, reason: "both_below_floor"`
6. **Tie**: If pairwise + rule-based cannot determine → `winner: "tie"` [Source: `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#OQ-1`; `OQ-6`]

### Library / Framework Requirements

- **DeepSeek V4 as judge**: Use the same OpenAI-compatible client pattern as `scenario_node` and `image_node`. The judge LLM is DeepSeek V4 — the same model that generates the pipeline content. Use `openai` Python client pointed at DeepSeek endpoint. Configuration via `YTFLOW_DEEPSEEK_API_KEY`, `YTFLOW_DEEPSEEK_BASE_URL`, `YTFLOW_DEEPSEEK_JUDGE_MODEL` (Pydantic `BaseSettings`, prefix `YTFLOW_`). [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Stack`]

- **Langfuse SDK v4.x**: Use `langfuse` package ≥4.12.0. The `@observe` decorator creates spans automatically. For the evaluation parent trace, use `langfuse.trace()` context manager or `start_as_current_span()`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Stack`]

- **AsyncSqliteSaver**: Import from `langgraph.checkpoint.sqlite.aio`. Use `AsyncSqliteSaver.from_conn_string(db_path)` with `YTFLOW_DB_PATH`. Call `aget_tuple(config)` to read checkpoint state. [Source: `_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-7`]

- **Prompt Hub for judge prompt**: The judge prompt (`evaluation/judge`) must be fetched from Langfuse Prompt Hub via `prompt_service.get_prompt("evaluation/judge").compile(...)`. If the prompt doesn't exist in Prompt Hub yet, create it during implementation (this is part of this story, since Story 1.3 only migrates pipeline node prompts). The judge prompt must include: axis definition, scoring protocol, chain-of-thought requirement, and output format (`{"axis": "<name>", "chain_of_thought": "...", "score": <int>}`). [Source: `_bmad-output/planning-artifacts/epics.md#Story-1.3`; `_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md#FR-14,FR-15`]

- **No new dependencies**: Use only packages already in the architecture stack. Ponytail rule: no new dependency unless strictly required. [Source: `CLAUDE.md#Code-Philosophy`]

### File Structure Requirements

New files:

- `src/yt_flow/services/eval_service.py` — evaluation orchestrator entry point + LLM judge + rule-based metrics + pairwise logic
- `tests/services/test_eval_service.py` — unit tests with mock LLM and mock state loaders
- `tests/services/fixtures/eval_pipeline_states.py` — PipelineState fixtures for A/B comparison tests

Existing files potentially touched:

- `src/yt_flow/config.py` — add `YTFLOW_DEEPSEEK_JUDGE_MODEL` field (if not already present from pipeline stories)
- `src/yt_flow/domain/state.py` — may add `EvaluationResult` TypedDict or use dataclasses in `eval_service.py` (domain/ only if shared with API story 4.3)
- `pyproject.toml` — no changes expected; all dependencies already declared

Do NOT touch:

- `src/yt_flow/api/` — Story 4.3 owns API exposure
- `src/yt_flow/pipeline/` — no pipeline graph changes
- `src/yt_flow/db/` — no schema changes needed for this story
- `frontend/` — Story 3.6 owns A/B comparison UI

### Data Types Contract

Define these in `eval_service.py` (use dataclasses for complex return types; TypedDicts only if shared with domain/):

```python
@dataclass
class AxisScores:
    atmosphere: float      # average of 3 judge runs
    narrative_coherence: float
    article_fidelity: float
    total: float           # sum of 3 axes (3.0–15.0)

@dataclass
class RuleBasedMetrics:
    scene_count: int
    scene_count_match_rate: float       # 0.0–1.0
    avg_subtitle_sync_error: float      # seconds/word
    audio_duration_variance_pct: float  # per-scene variance %

@dataclass
class PairwiseResult:
    a_to_b_winner: str | None   # "A" | "B" | "tie" | None
    b_to_a_winner: str | None
    tiebreaker_winner: str | None  # if 3rd run needed
    final_winner: str | None     # "A" | "B" | "tie" | None
    below_floor: list[str]       # run_ids below quality floor

@dataclass
class EvaluationResult:
    ab_pair_id: str
    run_a_id: str
    run_b_id: str
    scores_a: AxisScores
    scores_b: AxisScores
    metrics_a: RuleBasedMetrics
    metrics_b: RuleBasedMetrics
    pairwise: PairwiseResult
    winner: str | None           # "A" | "B" | "tie" | None
    winner_run_id: str | None    # actual run_id of winner
    reason: str | None            # human-readable explanation
    langfuse_trace_url: str | None
```

### Performance Budget

- **Total evaluation**: ≤5 minutes wall-clock [Source: `_bmad-output/planning-artifacts/epics.md#Story-4.2`]
- **Per LLM judge call**: 30-second timeout + 1 retry on timeout (not on parse failure — parse failure should raise immediately after retry)
- **LLM calls breakdown**: 3 axes × 3 runs = 9 calls per run, 18 total for two runs. Plus 2–3 pairwise calls = 20–21 total. At ~5 seconds per call (typical DeepSeek latency), 21 calls × 5s = 105s. Even with retries, the 300s budget is comfortable.
- **Parallelism**: Run A's 9 judge calls and Run B's 9 judge calls can run concurrently (independent). Pairwise calls are sequential (A→B, then B→A, then tiebreaker if needed). Rule-based metrics are pure Python (<100ms) and can run in parallel with LLM calls.
- **Rule-based metrics**: Pure computation — scene count, subtitle sync, audio variance. No LLM needed. Run in <100ms.

### Testing Requirements

- **No live DeepSeek V4 in unit tests**: Mock the OpenAI-compatible client. Use `unittest.mock` or `pytest.monkeypatch` to inject fake judge responses with known scores.
- **No live Langfuse in unit tests**: Mock the Langfuse client or use `langfuse.testing` utilities if available.
- **No live LangGraph DB in unit tests**: Mock `AsyncSqliteSaver.aget_tuple()` to return pre-built `PipelineState` fixtures.
- **Rule-based metrics**: Test with real `PipelineState` fixtures — these are pure functions with deterministic output.
- **Pairwise logic**: Test all branches: agreement, contradiction, tiebreaker trigger, quality floor disqualification, both-below-floor.
- **Precondition validation**: Test missing run_id, non-complete status (running/awaiting_approval/failed), mismatched ab_pair_id, missing/malformed state fields.
- **Integration guard**: Mark integration tests with `@pytest.mark.integration` or guard with `YTFLOW_EVAL_LIVE_TESTS=true`. Never run live LLM calls in CI.

### Previous Story Intelligence

No previous story in Epic 4 has been implemented. Story 4.1 (`4-1-ab-run-creation`) is still `backlog` and has no story file. This means:

- The `ab_pair_id` column in the `runs` table may not exist yet. `eval_service` should validate `ab_pair_id` is non-null and matches between the two runs, but the schema is owned by Stories 2.1/4.1.
- `prompt_variant` field (`"A"` or `"B"`) in `PipelineState` may not be populated. For evaluation, the variant label is informational — evaluation compares outputs, not variant labels.
- No code patterns for evaluation exist. This story establishes the pattern for calling DeepSeek V4 as a judge (distinct from calling it as a content generator in `scenario_node`).

### Git / Repository State

All commits so far are documentation-only:

```
2390ead chore: init sprint status tracking (24 stories across 4 epics)
4be98ee docs: add epic breakdown and implementation readiness report
6db2416 docs: add UX design specs and HTML mockups
ca2fb1d docs: add architecture design and review docs
b9dc0b0 docs: add PRD for yt.flow
b3feda2 docs: add initial brainstorm & intent document
bd4ec4f chore: init project — .gitignore and CLAUDE.md
```

No source code exists yet. The `src/` tree is empty. This story may be one of the first to write production Python — follow Ponytail rules strictly:
- No interface with one implementation
- No speculative abstractions
- Stdlib first, then existing deps, then minimum code
- Mark deliberate simplifications with `# ponytail:` comment

### References

- [PRD OQ-1 & OQ-6](_bmad-output/planning-artifacts/prds/prd-yt.flow-2026-06-30/prd.md) — 3-axis rubric and pairwise method, fully resolved
- [Epic 4 Stories](_bmad-output/planning-artifacts/epics.md#Epic-4) — story requirements and acceptance criteria
- [Architecture AD-6](_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-6) — A/B as two independent runs
- [Architecture AD-4](_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-4) — services/ owns orchestration
- [Architecture AD-2](_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-2) — LangGraph state is source of truth
- [Architecture AD-7](_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-7) — AsyncSqliteSaver, single SQLite file
- [Architecture AD-10](_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#AD-10) — Langfuse failures non-fatal
- [Architecture Stack](_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Stack) — Python 3.12, LangGraph 1.2.6, Langfuse SDK 4.x, DeepSeek V4
- [Architecture Structural Seed](_bmad-output/planning-artifacts/architecture/architecture-yt.flow-2026-06-30/ARCHITECTURE-SPINE.md#Structural-Seed) — `src/yt_flow/services/eval_service.py`
- [CLAUDE.md](../../../CLAUDE.md) — Ponytail code philosophy (YAGNI, stdlib-first, deletion over addition)
- [UX A/B Comparison](_bmad-output/planning-artifacts/ux-designs/ux-yt.flow-2026-06-30/EXPERIENCE.md) — A/B view at `/runs/{id}/ab` with side-by-side scores

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (BMad dev-story workflow)

### Debug Log References

- `uv run pytest tests/api/test_ab_run.py tests/services/test_eval_service.py` → 46 passed
- Full suite: `uv run pytest` → 320 passed, 1 skipped, no regressions
- `uv run ruff check` on all Story 4.1/4.2 touched files → clean

### Completion Notes List

Implemented the A/B evaluation engine per OQ-1 (3-axis judge) and OQ-6 (pairwise
+ quality floor). Deviations from the story spec, all deliberate:

- **httpx, not the `openai` SDK.** The story's Library Requirements named the
  `openai` client, but the codebase already calls DeepSeek's OpenAI-compatible
  endpoint with `httpx` (`scenario_node`). Reused that pattern — Ponytail: no new
  dependency for what an installed one already does.
- **`PipelineState` / `runs` table exist.** The story's Dev Notes ("no source code
  yet", "Epic 1 not implemented") were stale. Built against the real `PipelineState`
  TypedDict and the real `runs` table (which already has `status` + `ab_pair_id`).
- **Second prompt `evaluation/pairwise` added.** AC3 requires an *ordered* LLM
  comparison (A→B vs B→A) to mitigate position bias — that needs its own prompt, not
  the per-axis `evaluation/judge`. Both prompts live in `prompts/evaluation/` and are
  pushed by `scripts/seed_eval_prompts.py` (they are new to yt.flow, so the yt.pipe-
  sourced `migrate_prompts.py` can't seed them). eval_service only *fetches* them
  from Prompt Hub — no prompt text hardcoded (FR-16).
- **`_pairwise_compare` signature extended** with run contents + run_ids beyond the
  scores/metrics the task listed, because the ordered LLM comparison needs the actual
  narration text. Quality floor is applied first: a below-floor run can't win, and if
  both are below floor no LLM comparison runs at all.
- **Subtitle-sync SRT fallback skipped.** `_avg_subtitle_sync_error` computes the mean
  inter-word gap from `word_timings`; when timings are absent it returns 0.0 rather
  than re-parsing SRT files off disk — a rule metric stays pure (no I/O). Marked with a
  `# ponytail:` comment naming the upgrade path.
- **Langfuse trace** keyed deterministically by `ab_pair_id` via
  `create_trace_id(seed=...)` (same pattern as `run_service._trace_cm`). langfuse v4
  has no `update_current_trace`, so the parent span is enriched via
  `update_current_span`. Review tightened AC6 so the span output now includes the full
  `EvaluationResult` payload: axis scores, rule metrics, pairwise result, winner, and
  run IDs. All trace calls are guarded — a Langfuse failure is non-fatal and the
  returned `EvaluationResult` is authoritative (AD-10).
- **A/B pair validation follows Story 4.1's directional link.** Variant B points at
  source A via `ab_pair_id`; source A usually has `ab_pair_id=None`. `evaluate_ab()`
  accepts either order where one run points at the other and uses the source run id as
  the evaluation trace/result `ab_pair_id`.
- **Judge parsing tightened during review.** Scores must be integer 1-5 values (or
  stringified integers); fractional numeric values are malformed. Malformed judge
  responses are logged and retried once before `EvalJudgeError`.
- **Checkpoint validation tightened during review.** `_load_state()` validates
  `scp_text`, non-empty `scenes`, per-scene narration, and `video_path` before any LLM
  scoring begins.

`YTFLOW_DEEPSEEK_JUDGE_MODEL` added to `config.py` (defaults to the content model).

### File List

- `src/yt_flow/services/eval_service.py` (new) — evaluation orchestrator: data types,
  LLM axis judge, rule-based metrics, pairwise + winner logic, Langfuse persistence
- `src/yt_flow/config.py` (modified) — added `deepseek_judge_model`
- `prompts/evaluation/judge.md` (new) — OQ-1 axis judge prompt (Prompt Hub source)
- `prompts/evaluation/pairwise.md` (new) — OQ-6 pairwise comparison prompt (Prompt Hub source)
- `scripts/seed_eval_prompts.py` (new) — pushes the two evaluation prompts to Langfuse
- `tests/services/test_eval_service.py` (new) — 37 unit tests (no live LLM/Langfuse/DB)
- `tests/services/fixtures/__init__.py` (new)
- `tests/services/fixtures/eval_pipeline_states.py` (new) — deterministic A/B fixtures

## Review Findings

- [x] [Review][Patch] Valid Story 4.1-created A/B pairs failed `_validate_pair()` because only Variant B stores `ab_pair_id` — fixed by accepting directional source/variant linkage.
- [x] [Review][Patch] Langfuse trace output omitted scores, metrics, and pairwise result required by AC6 — fixed by persisting the full `EvaluationResult` payload.
- [x] [Review][Patch] Malformed judge responses were not retried/logged and fractional scores were rounded — fixed with parse-aware retry, logging, and integer-only score parsing.
- [x] [Review][Patch] Checkpoint validation did not verify `video_path` or scene narration shape before scoring — fixed with explicit `ValueError` validation before LLM calls.
- [x] [Review][Patch] Rule-based tiebreaker omitted the scene-count criterion and OQ-6 thresholds — fixed with best-of-3 threshold scoring for scene-count consistency, subtitle sync, and audio variance.

## Change Log

- 2026-07-01: Implemented Story 4.2 A/B Evaluation Service (LLM-as-judge + rule-based +
  pairwise winner determination + Langfuse persistence). 32 tests added; full suite green.
- 2026-07-01: Code review findings fixed; status → done.
