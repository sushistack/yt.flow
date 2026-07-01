---
baseline_commit: b86472055d91fc8863dc86364ae39074183550c5
---

# Story 4.3: Results Storage + API Retrieval + Auto Winner Determination

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Jay,
I want A/B evaluation results stored in Langfuse and retrievable via API with an automatic winner,
So that I can query the outcome programmatically and from the UI without any manual scoring step.

## Acceptance Criteria

1. **Langfuse trace storage:** Given `eval_service` produces scores and pairwise result, when results are saved, then a Langfuse trace is created with both runs' scores as individual NUMERIC score observations — one per axis per variant (6 total axis scores), plus pairwise winner as a CATEGORICAL score, plus rule-based metrics as NUMERIC scores (FR-21).

2. **API response enrichment — A/B pair:** Given `GET /runs/{id}` where `{id}` is part of an A/B pair and evaluation has completed, when called, then response includes `ab_result` object containing: `axis_scores` (per-variant per-axis LLM-as-judge scores with 3-run averages), `pairwise_winner` (raw pairwise result), `rule_based_scores` (structural metrics per variant), `winner` (determined winner: `"A"`, `"B"`, `"tie"`, or `null`), and `langfuse_eval_trace_url` (FR-22).

3. **API response — non-A/B run:** Given `GET /runs/{id}` where the run is not part of an A/B pair, when called, then `ab_result` is `null` (not present, or explicitly null) — no breaking change to existing response schema.

4. **API response — evaluation not yet complete:** Given `GET /runs/{id}` where the run is part of an A/B pair but evaluation has not yet been triggered, when called, then `ab_result` is `null`.

5. **Auto winner — clear winner:** Given pairwise yields a clear winner (2/3 majority or rule-based tiebreak after position-bias mitigation), when `GET /runs/{id}` is called, then `ab_result.winner` is `"A"` or `"B"` — no manual input required (FR-23).

6. **Auto winner — tie:** Given both runs pass quality floor but pairwise and rule-based tiebreak both result in equality, when result is stored, then `ab_result.winner` is `"tie"` — system reports the result rather than forcing a verdict.

7. **Auto winner — both below floor:** Given either run scores < 2/5 on any single axis (after 3-run average), when winner determination runs, then that run is flagged as below quality floor; if both fail, `ab_result.winner` is `null` with `ab_result.reason` = `"both_below_floor"` (OQ-6).

8. **Idempotent re-evaluation:** Given `POST /runs/{id}/ab` is called on a run that already has `ab_result` populated, when the re-evaluation completes, then the existing `ab_result` and Langfuse scores are updated (not duplicated) — use idempotency keys based on `{run_id}-{score_name}` for Langfuse scores (score_id parameter).

## Tasks / Subtasks

- [x] Extend `Run` SQLModel with `ab_result` field (AC: 2)
  - [x] Add `ab_result: str | None = None` (JSON blob) to `src/yt_flow/db/models.py`.
  - [x] SQLModel.metadata.create_all() handles the new column automatically (no Alembic migration needed for SQLite auto-create).
  - [x] The JSON blob stores: `axis_scores`, `pairwise_winner`, `rule_based_scores`, `winner`, `reason`, `langfuse_eval_trace_url`, `evaluated_at`.

- [x] Implement result storage in `eval_service.py` (AC: 1, 6, 7)
  - [x] Add `async def store_evaluation_results(run_a_id: str, run_b_id: str, llm_judge_scores: dict, rule_based_scores: dict, pairwise_result: dict)` to `src/yt_flow/services/eval_service.py`.
  - [x] Compute structured `ab_result` dict: axis scores per variant, pairwise winner, rule-based scores, determined winner, reason (if any).
  - [x] Persist `ab_result` as JSON string to both A and B runs' `ab_result` field via DB update.
  - [x] Create Langfuse trace for evaluation: `langfuse.create_score()` per axis per variant (6 NUMERIC scores), 1 CATEGORICAL score for `pairwise_winner`, rule-based metrics as NUMERIC scores (6 more). Use `score_id` = `"{run_id}-{score_name}"` for idempotency.
  - [x] Store `langfuse_eval_trace_url` in `ab_result` JSON for API response.
  - [x] Ensure Langfuse score creation failure is non-fatal (AD-10): log error, continue, `ab_result` still persisted to DB.

- [x] Implement winner determination logic (AC: 5, 6, 7)
  - [x] Add `def determine_winner(llm_judge_scores: dict, rule_based_scores: dict, pairwise_result: dict) -> tuple[str | None, str | None]` to `src/yt_flow/services/eval_service.py`.
  - [x] Quality floor check (OQ-6): if any axis score < 2 for a variant after 3-run average → that variant is below floor. If both below floor → return `(None, "both_below_floor")`.
  - [x] Pairwise winner check (OQ-6): if majority_winner is "A" or "B" → return it.
  - [x] Rule-based tiebreaker (OQ-6): scene count match rate closest to 100% wins; if still tied, subtitle sync error lower wins; if still tied, audio duration variance lower wins.
  - [x] If tiebreaker also tied → return `("tie", None)`.
  - [x] This is a pure function — no side effects, no DB or Langfuse calls.

- [x] Wire `store_evaluation_results` into `evaluate_ab` flow (AC: 1)
  - [x] In `eval_service.evaluate_ab()`, after LLM-as-judge and rule-based evaluation complete, call `determine_winner()` then `store_evaluation_results()`.
  - [x] Evaluation flow: run evaluation → determine winner → store results → return.
  - [x] Dataclass-to-dict conversion helpers (`_axis_scores_to_dict`, `_rule_metrics_to_dict`, `_pairwise_to_dict`) added for clean wiring.

- [x] Extend `GET /runs/{id}` response with `ab_result` (AC: 2, 3, 4)
  - [x] Added `ab_result` field to `RunRead` Pydantic schema with `@field_validator` to parse JSON string → dict.
  - [x] If `ab_result` is `None`, return `"ab_result": null` in JSON.
  - [x] If the run has `ab_pair_id` set but `ab_result` is null (evaluation not yet done), still return `"ab_result": null`.

- [x] Add tests (AC: 1-8)
  - [x] Test `determine_winner()`: clear A winner, B winner, tie, both below floor, A below floor (B wins), B below floor (A wins), rule-based tiebreaks (scene count, subtitle sync, audio variance).
  - [x] Test `store_evaluation_results()`: both runs get `ab_result` JSON; Langfuse scores with correct names and idempotency keys; Langfuse failure is non-fatal.
  - [x] Test `GET /runs/{id}`: ab_result as dict when complete; ab_result null for non-A/B; ab_result null when evaluation not yet done; list includes ab_result.

- [x] Verify locally (AC: 1-5)
  - [x] All 59 story-specific tests pass (eval_service + runs API).
  - [x] Full regression: 440 passed, 2 pre-existing failures (unrelated — `test_create_ab_run_copies_state`, `test_retry_resets_gate_to_pending_in_db`).
  - [x] No regressions introduced by this story.

## Dev Notes

### Scope Boundary

This story implements the **storage and retrieval layer** for A/B evaluation results. It does NOT implement the evaluation logic itself (LLM-as-judge scoring, rule-based metric computation, pairwise comparison) — those belong to story 4.2. This story provides:

1. **Result storage** — Persist evaluation output to both the `runs` table (`ab_result` JSON) and Langfuse (individual score observations).
2. **Winner determination** — Pure-function algorithm implementing OQ-6 pairwise + rule-based tiebreaker logic.
3. **API enrichment** — Extend `GET /runs/{id}` to surface `ab_result` when the run is part of an A/B pair.

**Do NOT implement in this story:**
- LLM-as-judge evaluation (DeepSeek V4 calls, 3-axis rubric, 3-run averaging) → Story 4.2
- Rule-based metric computation (scene count match rate, subtitle sync error, audio duration variance) → Story 4.2
- Pairwise comparison with position-bias mitigation (A→B, B→A order reversal) → Story 4.2
- `POST /runs/{id}/ab` endpoint (A/B run creation) → Story 4.1
- A/B comparison UI (side-by-side artifact display, scores, winner indicator) → Epic 3 (Story 3.6)
- Run completion detection trigger for auto-evaluation → Story 4.1/4.2

**This story assumes the following are already implemented:**
- Story 2.1: FastAPI app, `Run` SQLModel with `ab_pair_id` field, `api/routes/runs.py` with `GET /runs/{id}`
- Story 4.1: `POST /runs/{id}/ab` creates variant B run with same `scp_text` and linked `ab_pair_id`
- Story 4.2: `eval_service.evaluate_ab()` produces `llm_judge_scores`, `rule_based_scores`, and `pairwise_result` dicts
- Epic 1: All 10 stories — pipeline fully functional for both A and B variant runs

**Stub contract with story 4.2:** `eval_service.evaluate_ab(run_a_id, run_b_id)` must return a dict with this shape:
```python
{
    "llm_judge_scores": {
        "A": {"atmosphere": 4.0, "narrative_coherence": 3.7, "article_fidelity": 4.3},
        "B": {"atmosphere": 3.3, "narrative_coherence": 4.0, "article_fidelity": 3.7}
    },
    "rule_based_scores": {
        "A": {"scene_count_match_rate": 1.0, "subtitle_sync_error": 0.12, "audio_duration_variance": 0.08},
        "B": {"scene_count_match_rate": 0.8, "subtitle_sync_error": 0.15, "audio_duration_variance": 0.11}
    },
    "pairwise_result": {
        "run_1_order": "A_vs_B",   # first comparison order
        "run_1_winner": "A",
        "run_2_order": "B_vs_A",   # position-bias reversal
        "run_2_winner": "A",
        "run_3_order": "A_vs_B",   # tiebreaker if needed
        "run_3_winner": "A",
        "majority_winner": "A",
        "majority_count": 3,
        "total_runs": 3
    }
}
```

If story 4.2 is not yet implemented, create this stub return in `eval_service.py` for testing this story independently.

### Architecture Guardrails

#### AD-6 — A/B testing is two independent runs linked by `ab_pair_id`

**Rule:** `POST /runs/{id}/ab` creates a second independent run with the same `scp_text`, `prompt_variant="B"`, and `ab_pair_id` pointing to the originating run. Evaluation reads both LangGraph states after both complete. No graph-level branching.

[Source: `ARCHITECTURE-SPINE.md#AD-6`]

**Impact on this story:** When storing results, both runs (A and B) get the same `ab_result` JSON written to their respective rows. Either run's `GET /runs/{id}` returns the full `ab_result`. The `winner` field indicates which variant won — `"A"` means the originating run, `"B"` means the variant run. The `langfuse_eval_trace_url` is the same for both runs.

#### AD-2 — LangGraph state is the single source of truth

**Rule:** The `runs` table is a read-optimised API projection only. All in-flight pipeline data lives in `PipelineState`. `services/` updates `runs` table from LangGraph events — never independently.

[Source: `ARCHITECTURE-SPINE.md#AD-2`]

**Impact on this story:** `ab_result` is stored in the `runs` table because it's an API projection — evaluation results are not pipeline state (they're post-pipeline metadata). This is consistent: the `runs` table already holds `ab_pair_id`, `status`, and other API projection fields. Evaluation results are not written to `PipelineState`.

#### AD-10 — Langfuse tracing failures are non-fatal

**Rule:** Langfuse tracing failures are non-fatal — log the error and continue; pipeline must not fail due to observability unavailability.

[Source: `ARCHITECTURE-SPINE.md#AD-10`]

**Impact on this story:** `store_evaluation_results()` must wrap Langfuse score creation in try/except. If `langfuse.create_score()` raises, log the error and continue — `ab_result` must still be persisted to the `runs` table. The evaluation result is authoritative in the DB; Langfuse scores are an observability convenience.

#### AD-1 — Layer dependency direction

**Rule:** Import path must follow `api → services → (pipeline | db) → domain`. Cross-layer imports forbidden.

[Source: `ARCHITECTURE-SPINE.md#AD-1`]

**Impact on this story:**
- `api/routes/runs.py` imports from `services/eval_service.py` (or reads `ab_result` from DB directly — both are valid since `db/` is below `api/`)
- `services/eval_service.py` imports `langfuse` SDK and `db/models.py`
- `services/eval_service.py` never imports from `api/`

#### AD-4 — `services/` owns DB sync and SSE fan-out

**Rule:** `services/` is the only layer permitted to call `graph.astream()` or `graph.update_state()`. Pipeline nodes are pure functions.

[Source: `ARCHITECTURE-SPINE.md#AD-4`]

**Impact on this story:** `eval_service.py` is already the designated service for evaluation orchestration. `store_evaluation_results()` lives here. DB writes for `ab_result` happen through `services/` — consistent with AD-4.

### Required Data Contracts

#### Extended Run SQLModel (db/models.py)

Add to the existing `Run` model from story 2.1:

```python
# db/models.py — add to existing Run class
ab_result: str | None = Field(default=None)  # JSON blob for evaluation results
```

#### ab_result JSON Schema

```python
# Shape of ab_result when deserialized:
{
    "axis_scores": {
        "A": {
            "atmosphere": 4.0,           # float, 1.0–5.0, 3-run average
            "narrative_coherence": 3.7,
            "article_fidelity": 4.3
        },
        "B": {
            "atmosphere": 3.3,
            "narrative_coherence": 4.0,
            "article_fidelity": 3.7
        }
    },
    "pairwise_winner": {
        "majority_winner": "A",          # "A" | "B" | "tie"
        "majority_count": 3,             # int, 2 or 3
        "total_runs": 3,                 # int, always 3 (or 2 if 2/2 agree)
        "runs": [
            {"order": "A_vs_B", "winner": "A"},
            {"order": "B_vs_A", "winner": "A"},
            {"order": "A_vs_B", "winner": "A"}
        ]
    },
    "rule_based_scores": {
        "A": {
            "scene_count_match_rate": 1.0,      # float, 0.0–1.0
            "subtitle_sync_error": 0.12,         # float, seconds/word, lower=better
            "audio_duration_variance": 0.08      # float, proportion, lower=better
        },
        "B": {
            "scene_count_match_rate": 0.8,
            "subtitle_sync_error": 0.15,
            "audio_duration_variance": 0.11
        }
    },
    "winner": "A",                     # "A" | "B" | "tie" | null
    "reason": null,                    # str | null — e.g. "both_below_floor"
    "langfuse_eval_trace_url": "https://langfuse.example.com/trace/...",
    "evaluated_at": "2026-07-01T12:00:00.000Z"
}
```

#### Extended RunRead Schema (api/routes/runs.py)

```python
# api/routes/runs.py — extend existing RunRead
class RunRead(BaseModel):
    id: str
    scp_id: str
    status: str
    current_stage: str | None
    gate_states: str | None
    prompt_variant: str | None
    ab_pair_id: str | None
    ab_result: dict | None = None      # NEW — parsed from JSON blob
    error: str | None
    extra: str | None
    langfuse_trace_url: str | None
    started_at: str
    updated_at: str
```

Note: `ab_result` is returned as a parsed dict, not as a raw JSON string. The route handler must `json.loads(run.ab_result)` when building the response.

#### Winner Determination Function Signature

```python
# services/eval_service.py
def determine_winner(
    llm_judge_scores: dict,     # {"A": {axis: float}, "B": {axis: float}}
    rule_based_scores: dict,    # {"A": {metric: float}, "B": {metric: float}}
    pairwise_result: dict       # {"majority_winner": str, "majority_count": int, ...}
) -> tuple[str | None, str | None]:
    """
    Returns (winner, reason).
    winner: "A" | "B" | "tie" | None
    reason: None | "both_below_floor"
    """
```

#### Langfuse Score Creation Pattern

```python
# services/eval_service.py — within store_evaluation_results()
from langfuse import get_client

langfuse = get_client()

# Per-axis scores (6 total)
for variant in ("A", "B"):
    for axis in ("atmosphere", "narrative_coherence", "article_fidelity"):
        langfuse.create_score(
            name=f"{axis}_{variant}",
            value=float(llm_judge_scores[variant][axis]),  # 1.0–5.0
            trace_id=eval_trace_id,
            data_type="NUMERIC",
            score_id=f"{run_id}-{axis}_{variant}",  # idempotency key
            comment=f"3-run average for {axis} (variant {variant})"
        )

# Pairwise winner as categorical score
langfuse.create_score(
    name="pairwise_winner",
    value=pairwise_result["majority_winner"],
    trace_id=eval_trace_id,
    data_type="CATEGORICAL",
    score_id=f"{run_id}-pairwise_winner"
)

# Rule-based metrics
for variant in ("A", "B"):
    for metric in ("scene_count_match_rate", "subtitle_sync_error", "audio_duration_variance"):
        langfuse.create_score(
            name=f"{metric}_{variant}",
            value=float(rule_based_scores[variant][metric]),
            trace_id=eval_trace_id,
            data_type="NUMERIC",
            score_id=f"{run_id}-{metric}_{variant}"
        )
```

### Winner Determination Algorithm (OQ-6)

Pseudo-code implementing the resolved OQ-6 algorithm:

```python
def determine_winner(llm_judge_scores, rule_based_scores, pairwise_result):
    QUALITY_FLOOR = 2.0  # minimum per-axis score (1-5 scale)

    # Step 1: Quality floor check
    a_below = any(llm_judge_scores["A"][axis] < QUALITY_FLOOR for axis in ("atmosphere", "narrative_coherence", "article_fidelity"))
    b_below = any(llm_judge_scores["B"][axis] < QUALITY_FLOOR for axis in ("atmosphere", "narrative_coherence", "article_fidelity"))

    if a_below and b_below:
        return (None, "both_below_floor")
    if a_below:
        return ("B", None)
    if b_below:
        return ("A", None)

    # Step 2: Pairwise majority (2/3 required)
    winner = pairwise_result["majority_winner"]
    if winner in ("A", "B"):
        return (winner, None)

    # Step 3: Rule-based tiebreaker
    # 3a. Scene count match rate (higher = better)
    a_scene = rule_based_scores["A"]["scene_count_match_rate"]
    b_scene = rule_based_scores["B"]["scene_count_match_rate"]
    if abs(a_scene - b_scene) > 0.01:  # non-trivial difference
        return ("A" if a_scene > b_scene else "B", None)

    # 3b. Subtitle sync error (lower = better, threshold ≤0.5)
    a_sync = rule_based_scores["A"]["subtitle_sync_error"]
    b_sync = rule_based_scores["B"]["subtitle_sync_error"]
    if abs(a_sync - b_sync) > 0.01:
        return ("A" if a_sync < b_sync else "B", None)

    # 3c. Audio duration variance (lower = better, threshold ≤10%)
    a_var = rule_based_scores["A"]["audio_duration_variance"]
    b_var = rule_based_scores["B"]["audio_duration_variance"]
    if abs(a_var - b_var) > 0.01:
        return ("A" if a_var < b_var else "B", None)

    # Step 4: All tiebreakers exhausted → tie
    return ("tie", None)
```

### OQ-6 Summary (from PRD Open Items)

- **Pairwise comparison**: Position-bias mitigated via order reversal (A→B, B→A, then tiebreaker if needed). 2/3 majority required.
- **Tiebreaker hierarchy**: Scene count match rate → subtitle sync error (≤0.5s/word threshold) → audio duration variance (≤10% threshold).
- **Quality floor**: All 3 axes ≥2/5 required per variant (3-run average per axis). If one variant fails floor, the other wins automatically. If both fail, no winner declared.

### OQ-1 Summary (from PRD Open Items)

- **3-axis rubric**: Atmosphere (SCP clinical-horror register), Narrative coherence (scene flow + entity consistency), Article fidelity (facts, object class, containment accuracy).
- **Scoring**: Integer 1–5 per axis, 3-run average, chain-of-thought before scoring.
- **Total score**: Sum of 3 axes (3–15). Not used directly for winner determination — pairwise comparison is the authoritative method.

### File Structure

```
src/yt_flow/
├── api/routes/runs.py        # MODIFY: extend GET /runs/{id} with ab_result
├── db/models.py              # MODIFY: add ab_result field to Run
├── services/eval_service.py  # MODIFY: add store_evaluation_results(), determine_winner()
```

### Conventions

| Concern | Convention |
|---------|------------|
| Naming | `ab_result` field; `determine_winner()` function; `store_evaluation_results()` function |
| IDs | UUID v4 strings; Langfuse score_id = `"{run_id}-{score_name}"` |
| Timestamps | `datetime.utcnow().isoformat()` for `evaluated_at` |
| Error shape | `HTTPException` with `detail: str`; Langfuse errors logged, not raised |
| State mutation | `ab_result` JSON replaced wholesale on re-evaluation — no partial merge |
| Config | Langfuse credentials from `YTFLOW_LANGFUSE_*` env vars via `config.py` |
| Testing | `TestClient` + in-memory SQLite; mock Langfuse client; `determine_winner()` is pure — testable without mocks |

## Dev Agent Record

### Agent Model Used

GitHub Copilot / DeepSeek V4 Pro

### Debug Log References

No debug logs needed — all tests pass on first run.

### Completion Notes List

- **Task 1 — `ab_result` field**: Added `ab_result: str | None = None` to `Run` SQLModel in `db/models.py`. No migration needed — `SQLModel.metadata.create_all()` handles auto-add for SQLite.
- **Task 2 — `store_evaluation_results()`**: Implemented in `services/eval_service.py`. Persists `ab_result` JSON to both A and B run rows (AD-6: same blob). Creates 13 Langfuse scores (6 axis + 1 pairwise + 6 rule-based) with idempotency keys `{run_id}-{score_name}`. Langfuse failures are caught and logged (AD-10), DB write is authoritative.
- **Task 3 — `determine_winner()`**: Pure function implementing OQ-6 algorithm: quality floor check → pairwise majority → rule-based tiebreaker (scene count → subtitle sync → audio variance). Returns `(winner, reason)` tuple. 8 test cases cover all branches.
- **Task 4 — Wiring**: `evaluate_ab()` now calls `store_evaluation_results()` after `_finish_trace()`. Dataclass-to-dict conversion helpers (`_axis_scores_to_dict`, `_rule_metrics_to_dict`, `_pairwise_to_dict`) added for clean interface between the existing dataclass-based code and the new dict-based storage layer.
- **Task 5 — API enrichment**: `RunRead` schema extended with `ab_result: dict | None = None` using `@field_validator` to auto-parse JSON string → dict. Both `GET /runs/{id}` and `GET /runs` return parsed `ab_result`.
- **Task 6 — Tests**: 15 new tests added (8 `determine_winner` + 3 `store_evaluation_results` + 4 API). All 59 story-specific tests pass. Full regression: 440 pass, 2 pre-existing failures unrelated.

### File List

- `src/yt_flow/db/models.py` — added `ab_result` field to `Run`
- `src/yt_flow/services/eval_service.py` — added `determine_winner()`, `store_evaluation_results()`, conversion helpers; wired into `evaluate_ab()`
- `src/yt_flow/api/routes/runs.py` — added `ab_result` to `RunRead` with field_validator
- `tests/services/test_eval_service.py` — added 11 tests for determine_winner + store_evaluation_results
- `tests/api/test_runs.py` — added 4 tests for ab_result API enrichment

### Change Log

- 2026-07-01: Story 4.3 implementation — Results Storage API with auto winner determination
