"""services/eval_service.py — A/B evaluation orchestrator (Story 4.2 + 4.3).

Story 4.2: Scores two completed runs against the OQ-1 3-axis rubric
(LLM-as-judge) plus rule-based structural metrics, then determines a winner
with OQ-6 pairwise position-bias mitigation. Reads each run's ``PipelineState``
directly from its LangGraph checkpoint (AD-2); the ``runs`` table is consulted
only to validate status + ``ab_pair_id`` (AD-6).

Story 4.3: Persists evaluation results to the runs table (``ab_result`` JSON)
and Langfuse (individual score observations with idempotency keys). Provides
``determine_winner()`` as a standalone pure function implementing the OQ-6
algorithm (quality floor, pairwise majority, rule-based tiebreaker).

DeepSeek is OpenAI-compatible, so the judge uses the already-installed ``httpx``
client — same pattern as ``scenario_node`` — instead of adding the ``openai`` SDK.
Judge/pairwise prompts live in Langfuse Prompt Hub (``evaluation/judge``,
``evaluation/pairwise``), never hardcoded here.
"""

import asyncio
import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from langfuse import get_client, observe

from yt_flow.config import Settings
from yt_flow.domain.state import PipelineState, SceneState
from yt_flow.services.prompt_service import get_prompt

logger = logging.getLogger(__name__)

AXES = ("atmosphere", "narrative_coherence", "article_fidelity")
REPS_PER_AXIS = 3            # OQ-1: each axis scored 3 times, then averaged
QUALITY_FLOOR = 2.0         # OQ-6: any axis average < 2 disqualifies a run
JUDGE_TIMEOUT_SEC = 30.0    # AC5: per-call timeout, retry-once on timeout
JUDGE_PROMPT = "evaluation/judge"
PAIRWISE_PROMPT = "evaluation/pairwise"


class EvalJudgeError(RuntimeError):
    """A judge response could not be parsed into a valid 1–5 score."""


@dataclass
class AxisScores:
    atmosphere: float          # average of REPS_PER_AXIS judge runs
    narrative_coherence: float
    article_fidelity: float
    total: float               # sum of the 3 axis averages (3.0–15.0)

    def below_floor(self) -> bool:
        return min(self.atmosphere, self.narrative_coherence, self.article_fidelity) < QUALITY_FLOOR


@dataclass
class RuleBasedMetrics:
    scene_count: int
    scene_count_match_rate: float       # 0.0–1.0 (symmetric across the pair)
    avg_subtitle_sync_error: float      # seconds between consecutive words
    audio_duration_variance_pct: float  # stddev/mean across scenes, %


@dataclass
class PairwiseResult:
    a_to_b_winner: str | None    # "A" | "B" | "tie" | None (not run)
    b_to_a_winner: str | None
    tiebreaker_winner: str | None
    final_winner: str | None     # "A" | "B" | "tie" | None
    below_floor: list[str] = field(default_factory=list)  # run_ids below quality floor


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
    winner: str | None            # "A" | "B" | "tie" | None
    winner_run_id: str | None
    reason: str | None
    langfuse_trace_url: str | None


def _settings() -> Settings:
    # ponytail: one seam so unit tests inject fake settings without a real .env.
    return Settings()


# ── LLM judge (OQ-1 axis scoring) ──────────────────────────────────────────


async def _post_chat(rendered: str, model: str, s: Settings, *, timeout: float = JUDGE_TIMEOUT_SEC) -> str:
    """POST a JSON-mode chat completion; retry ONCE on timeout only (AC5).

    Parse failures are not retried here — the caller raises ``EvalJudgeError``
    immediately so a persistently malformed judge can't burn the time budget.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": rendered}],
        "response_format": {"type": "json_object"},
        "max_tokens": s.deepseek_max_tokens,
    }
    for attempt in range(2):  # initial try + one retry on timeout
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                resp = await client.post(
                    f"{s.deepseek_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {s.deepseek_api_key}"},
                    json=payload,
                )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            if attempt == 1:  # second (final) attempt also timed out
                raise
    raise AssertionError("unreachable")  # loop always returns or raises


def _parse_score(raw: str, axis: str) -> int:
    """Extract a 1–5 integer from a judge response. Raise on any deviation."""
    try:
        data = json.loads(raw)
        score = data["score"]
        # bool is an int subclass; reject it so True/False can't pose as a score.
        if isinstance(score, bool):
            raise TypeError
        score = int(round(float(score)))  # tolerate "4" / 4.0 from the model
    except (ValueError, TypeError, KeyError) as exc:
        raise EvalJudgeError(f"axis={axis}: unparseable judge response: {raw!r}") from exc
    if not 1 <= score <= 5:
        raise EvalJudgeError(f"axis={axis}: score {score} outside 1–5")
    return score


@observe(name="judge-axis")
async def _judge_axis(scp_text: str, artifact_text: str, axis: str, s: Settings) -> list[int]:
    """Score one axis REPS_PER_AXIS times (concurrent) and return the raw integers."""
    rendered = get_prompt(JUDGE_PROMPT).compile(
        scp_text=scp_text, artifact_content=artifact_text, axis=axis,
    )
    raws = await asyncio.gather(
        *(_post_chat(rendered, s.deepseek_judge_model, s) for _ in range(REPS_PER_AXIS))
    )
    return [_parse_score(raw, axis) for raw in raws]


async def _score_run(scp_text: str, artifact_text: str, s: Settings) -> AxisScores:
    """Run all axes concurrently → averaged AxisScores (AC1)."""
    per_axis = await asyncio.gather(
        *(_judge_axis(scp_text, artifact_text, axis, s) for axis in AXES)
    )
    avgs = {axis: statistics.fmean(scores) for axis, scores in zip(AXES, per_axis)}
    return AxisScores(
        atmosphere=avgs["atmosphere"],
        narrative_coherence=avgs["narrative_coherence"],
        article_fidelity=avgs["article_fidelity"],
        total=sum(avgs.values()),
    )


def _artifact_text(state: PipelineState) -> str:
    """The text a judge can actually read: scene narrations joined in order.

    A text LLM can't watch the video or hear the audio, so narration is the
    faithful stand-in for the run's content. ponytail: narration-only judge input;
    add image-prompt/OCR context here if judgments prove too coarse.
    """
    return "\n\n".join(sc["narration"] for sc in state["scenes"])


# ── Rule-based structural metrics (AC2, pure computation) ──────────────────


def _scene_count_match_rate(a: int, b: int) -> float:
    hi = max(a, b)
    return 1.0 if hi == 0 else 1.0 - abs(a - b) / hi


def _avg_subtitle_sync_error(scenes: list[SceneState]) -> float:
    """Mean gap (seconds) between consecutive words across all scenes.

    Uses word_timings when present. ponytail: falls back to 0.0 when timing data
    is absent rather than re-parsing SRT files off disk — a rule metric stays pure
    (no I/O); wire the subtitle-entry-vs-word-count fallback here if a run ever
    ships without word timings and the metric matters.
    """
    gaps: list[float] = []
    for sc in scenes:
        wt = sc.get("word_timings") or []
        gaps.extend(abs(wt[i + 1]["start_sec"] - wt[i]["end_sec"]) for i in range(len(wt) - 1))
    return statistics.fmean(gaps) if gaps else 0.0


def _audio_duration_variance_pct(scenes: list[SceneState]) -> float:
    durations = [d for sc in scenes if (d := sc.get("audio_duration")) is not None]
    if len(durations) < 2:
        return 0.0
    mean = statistics.fmean(durations)
    return 0.0 if mean == 0 else statistics.pstdev(durations) / mean * 100.0


def _compute_rule_metrics(
    state_a: PipelineState, state_b: PipelineState
) -> tuple[RuleBasedMetrics, RuleBasedMetrics]:
    scenes_a, scenes_b = state_a["scenes"], state_b["scenes"]
    match_rate = _scene_count_match_rate(len(scenes_a), len(scenes_b))  # symmetric across the pair
    return (
        RuleBasedMetrics(len(scenes_a), match_rate,
                         _avg_subtitle_sync_error(scenes_a), _audio_duration_variance_pct(scenes_a)),
        RuleBasedMetrics(len(scenes_b), match_rate,
                         _avg_subtitle_sync_error(scenes_b), _audio_duration_variance_pct(scenes_b)),
    )


# ── Pairwise comparison + winner determination (AC3, AC4) ──────────────────


async def _pairwise_once(scp_text: str, first: str, second: str, s: Settings) -> str:
    """One ordered LLM comparison. Returns "A"|"B"|"tie" (A/B are the *labels* of
    ``first``/``second``, so the caller controls ordering for bias mitigation)."""
    rendered = get_prompt(PAIRWISE_PROMPT).compile(
        scp_text=scp_text, content_first=first, content_second=second,
    )
    raw = await _post_chat(rendered, s.deepseek_judge_model, s)
    try:
        winner = json.loads(raw)["winner"]
    except (ValueError, KeyError, TypeError) as exc:
        raise EvalJudgeError(f"pairwise: unparseable response: {raw!r}") from exc
    if winner not in ("first", "second", "tie"):
        raise EvalJudgeError(f"pairwise: winner must be first|second|tie, got {winner!r}")
    return {"first": "A", "second": "B", "tie": "tie"}[winner]


def _rule_tiebreak(metrics_a: RuleBasedMetrics, metrics_b: RuleBasedMetrics) -> str:
    """OQ-6 rule-based tiebreaker: lower subtitle sync error and lower audio
    variance each score a point; best total wins, else "tie".

    ponytail: scene_count_match_rate is symmetric across the pair, so it can't
    separate A from B — the tiebreaker turns on the two per-run metrics only.
    """
    pa = pb = 0
    if metrics_a.avg_subtitle_sync_error < metrics_b.avg_subtitle_sync_error:
        pa += 1
    elif metrics_b.avg_subtitle_sync_error < metrics_a.avg_subtitle_sync_error:
        pb += 1
    if metrics_a.audio_duration_variance_pct < metrics_b.audio_duration_variance_pct:
        pa += 1
    elif metrics_b.audio_duration_variance_pct < metrics_a.audio_duration_variance_pct:
        pb += 1
    return "A" if pa > pb else "B" if pb > pa else "tie"


async def _pairwise_compare(
    scp_text: str,
    text_a: str,
    text_b: str,
    scores_a: AxisScores,
    scores_b: AxisScores,
    metrics_a: RuleBasedMetrics,
    metrics_b: RuleBasedMetrics,
    run_a_id: str,
    run_b_id: str,
    s: Settings,
) -> PairwiseResult:
    """Determine the winner with OQ-6 position-bias mitigation + quality floor.

    Quality floor is applied first: a run with any axis average < 2 cannot win.
    If both are below floor no LLM comparison runs at all.
    """
    below = [rid for rid, sc in ((run_a_id, scores_a), (run_b_id, scores_b)) if sc.below_floor()]
    if len(below) == 2:
        return PairwiseResult(None, None, None, None, below)
    if len(below) == 1:
        winner = "B" if below[0] == run_a_id else "A"
        return PairwiseResult(None, None, None, winner, below)

    # A→B then B→A order (position-bias mitigation). In the B→A call the labels
    # flip, so _pairwise_once returns from A's perspective and we invert it back.
    a_to_b = await _pairwise_once(scp_text, text_a, text_b, s)
    flipped = await _pairwise_once(scp_text, text_b, text_a, s)
    b_to_a = {"A": "B", "B": "A", "tie": "tie"}[flipped]

    if a_to_b == b_to_a and a_to_b != "tie":
        final = a_to_b                              # both orders agree on a winner
    elif a_to_b == "tie" and b_to_a == "tie":
        final = _rule_tiebreak(metrics_a, metrics_b)  # both tie → rule-based
    else:
        # Contradictory (or one tie, one decisive) → 3rd LLM tiebreaker run.
        tie = await _pairwise_once(scp_text, text_a, text_b, s)
        final = tie if tie != "tie" else _rule_tiebreak(metrics_a, metrics_b)
        return PairwiseResult(a_to_b, b_to_a, tie, final, below)

    return PairwiseResult(a_to_b, b_to_a, None, final, below)


# ── Checkpoint + run-metadata loading, precondition validation (AC7) ───────


async def _load_state(run_id: str, db_path: str) -> PipelineState:
    """Read a run's PipelineState from its LangGraph checkpoint (AD-2, AD-7).

    Raises ValueError naming the run when no checkpoint exists or required fields
    are missing/malformed — before any LLM scoring begins (AC7).
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
        tup = await saver.aget_tuple({"configurable": {"thread_id": run_id}})
    if tup is None:
        raise ValueError(f"run {run_id}: no LangGraph checkpoint found")
    values = tup.checkpoint.get("channel_values") or {}
    scenes = values.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError(f"run {run_id}: checkpoint has no 'scenes' — run incomplete or malformed")
    if not isinstance(values.get("scp_text"), str) or not values["scp_text"].strip():
        raise ValueError(f"run {run_id}: checkpoint 'scp_text' missing or empty")
    return values  # type: ignore[return-value]


def _load_run_meta(run_id: str) -> "tuple[str, str | None]":
    """Return (status, ab_pair_id) from the runs table. Raises ValueError if absent."""
    from sqlmodel import Session

    from yt_flow import db
    from yt_flow.db.models import Run

    with Session(db._engine) as session:
        run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"run {run_id}: not found in runs table")
    return run.status, run.ab_pair_id


def _validate_pair(run_a_id: str, run_b_id: str) -> str:
    """Check both runs exist, are complete, and share an ab_pair_id. Returns the pair id."""
    status_a, pair_a = _load_run_meta(run_a_id)
    status_b, pair_b = _load_run_meta(run_b_id)
    for rid, status in ((run_a_id, status_a), (run_b_id, status_b)):
        if status != "complete":
            raise ValueError(f"run {rid}: status is {status!r}, must be 'complete' to evaluate")
    if not pair_a or pair_a != pair_b:
        raise ValueError(
            f"runs are not a valid A/B pair: {run_a_id} ab_pair_id={pair_a!r}, "
            f"{run_b_id} ab_pair_id={pair_b!r}"
        )
    return pair_a


# ── Langfuse persistence (AC6, non-fatal per AD-10) ─────────────────────────


def _trace_url(client) -> str | None:
    try:
        return client.get_trace_url()
    except Exception:  # noqa: BLE001 — tracing is observability, never fatal
        return None


# ── Top-level entry point ───────────────────────────────────────────────────


async def evaluate_ab(run_a_id: str, run_b_id: str) -> EvaluationResult:
    """Evaluate two completed A/B runs and determine a winner (AC1–AC7).

    Preconditions are validated before any LLM call. LLM scoring for both runs
    runs concurrently; rule-based metrics are pure Python. All spans nest under a
    single Langfuse trace deterministically keyed by ``ab_pair_id`` (AC6); Langfuse
    failures are non-fatal — the returned EvaluationResult is authoritative (AD-10).

    Story 4.3: After evaluation, results are persisted to the runs table
    (``ab_result`` JSON) and Langfuse scores via ``store_evaluation_results()``.
    """
    s = _settings()
    if not s.deepseek_api_key:
        raise RuntimeError("YTFLOW_DEEPSEEK_API_KEY is not configured")

    ab_pair_id = _validate_pair(run_a_id, run_b_id)  # AC7: raises before any scoring
    state_a = await _load_state(run_a_id, s.db_path)
    state_b = await _load_state(run_b_id, s.db_path)
    text_a, text_b = _artifact_text(state_a), _artifact_text(state_b)

    span = _enter_trace(ab_pair_id)
    try:
        metrics_a, metrics_b = _compute_rule_metrics(state_a, state_b)
        scores_a, scores_b = await asyncio.gather(
            _score_run(state_a["scp_text"], text_a, s),
            _score_run(state_b["scp_text"], text_b, s),
        )
        pairwise = await _pairwise_compare(
            state_a["scp_text"], text_a, text_b, scores_a, scores_b,
            metrics_a, metrics_b, run_a_id, run_b_id, s,
        )
        winner, winner_run_id, reason = _resolve_winner(pairwise, run_a_id, run_b_id)
        trace_url = _finish_trace(span, ab_pair_id, winner, reason)

        # Story 4.3: Persist results to DB + Langfuse scores
        await store_evaluation_results(
            run_a_id=run_a_id,
            run_b_id=run_b_id,
            llm_judge_scores={
                "A": _axis_scores_to_dict(scores_a),
                "B": _axis_scores_to_dict(scores_b),
            },
            rule_based_scores={
                "A": _rule_metrics_to_dict(metrics_a),
                "B": _rule_metrics_to_dict(metrics_b),
            },
            pairwise_result=_pairwise_to_dict(pairwise),
            trace_url=trace_url,
        )

        return EvaluationResult(
            ab_pair_id=ab_pair_id, run_a_id=run_a_id, run_b_id=run_b_id,
            scores_a=scores_a, scores_b=scores_b, metrics_a=metrics_a, metrics_b=metrics_b,
            pairwise=pairwise, winner=winner, winner_run_id=winner_run_id,
            reason=reason, langfuse_trace_url=trace_url,
        )
    finally:
        _exit_trace(span)


def _resolve_winner(
    pairwise: PairwiseResult, run_a_id: str, run_b_id: str
) -> "tuple[str | None, str | None, str | None]":
    if len(pairwise.below_floor) == 2:
        return None, None, "both_below_floor"
    winner = pairwise.final_winner
    if winner == "A":
        return "A", run_a_id, "run A preferred"
    if winner == "B":
        return "B", run_b_id, "run B preferred"
    return "tie", None, "no decisive winner"


# ── Story 4.3: Winner determination (pure function, OQ-6) ───────────────────


def determine_winner(
    llm_judge_scores: dict,     # {"A": {axis: float}, "B": {axis: float}}
    rule_based_scores: dict,    # {"A": {metric: float}, "B": {metric: float}}
    pairwise_result: dict,      # {"majority_winner": str, ...}
) -> "tuple[str | None, str | None]":
    """Pure-function OQ-6 winner determination.

    Returns (winner, reason).
    winner: "A" | "B" | "tie" | None
    reason: None | "both_below_floor"
    """
    QUALITY_FLOOR = 2.0

    # Step 1: Quality floor check
    a_below = any(
        llm_judge_scores["A"].get(axis, 0) < QUALITY_FLOOR
        for axis in ("atmosphere", "narrative_coherence", "article_fidelity")
    )
    b_below = any(
        llm_judge_scores["B"].get(axis, 0) < QUALITY_FLOOR
        for axis in ("atmosphere", "narrative_coherence", "article_fidelity")
    )

    if a_below and b_below:
        return (None, "both_below_floor")
    if a_below:
        return ("B", None)
    if b_below:
        return ("A", None)

    # Step 2: Pairwise majority (2/3 required)
    winner = pairwise_result.get("majority_winner")
    if winner in ("A", "B"):
        return (winner, None)

    # Step 3: Rule-based tiebreaker
    # 3a. Scene count match rate (higher = better)
    a_scene = rule_based_scores["A"]["scene_count_match_rate"]
    b_scene = rule_based_scores["B"]["scene_count_match_rate"]
    if abs(a_scene - b_scene) > 0.01:
        return ("A" if a_scene > b_scene else "B", None)

    # 3b. Subtitle sync error (lower = better)
    a_sync = rule_based_scores["A"]["subtitle_sync_error"]
    b_sync = rule_based_scores["B"]["subtitle_sync_error"]
    if abs(a_sync - b_sync) > 0.01:
        return ("A" if a_sync < b_sync else "B", None)

    # 3c. Audio duration variance (lower = better)
    a_var = rule_based_scores["A"]["audio_duration_variance"]
    b_var = rule_based_scores["B"]["audio_duration_variance"]
    if abs(a_var - b_var) > 0.01:
        return ("A" if a_var < b_var else "B", None)

    # Step 4: All tiebreakers exhausted → tie
    return ("tie", None)


# ── Story 4.3: Result storage (DB + Langfuse, AD-10 non-fatal) ──────────────


def _build_trace_id(ab_pair_id: str) -> str | None:
    """Recreate the deterministic Langfuse trace id from ab_pair_id."""
    try:
        client = get_client()
        return client.create_trace_id(seed=ab_pair_id)
    except Exception:  # noqa: BLE001
        return None


async def store_evaluation_results(
    run_a_id: str,
    run_b_id: str,
    llm_judge_scores: dict,
    rule_based_scores: dict,
    pairwise_result: dict,
    trace_url: str | None = None,
) -> dict:
    """Persist A/B evaluation results to DB (both runs) and Langfuse (scores).

    Returns the ``ab_result`` dict that was persisted. Langfuse score creation
    failures are non-fatal per AD-10 — the DB write is the authoritative record.
    """
    # ── Compute ab_result ───────────────────────────────────────────────────
    winner, reason = determine_winner(llm_judge_scores, rule_based_scores, pairwise_result)
    evaluated_at = datetime.now(tz=timezone.utc).isoformat()

    ab_result: dict = {
        "axis_scores": llm_judge_scores,
        "pairwise_winner": pairwise_result,
        "rule_based_scores": rule_based_scores,
        "winner": winner,
        "reason": reason,
        "langfuse_eval_trace_url": trace_url,
        "evaluated_at": evaluated_at,
    }
    ab_result_json = json.dumps(ab_result)

    # ── Persist to runs table (both runs get the same ab_result, AD-6) ─────
    from sqlmodel import Session

    from yt_flow import db as db_module
    from yt_flow.db.models import Run

    with Session(db_module._engine) as session:
        for run_id in (run_a_id, run_b_id):
            run = session.get(Run, run_id)
            if run is not None:
                run.ab_result = ab_result_json
                run.updated_at = evaluated_at
        session.commit()

    # ── Langfuse score ingestion (non-fatal, AD-10) ─────────────────────────
    try:
        langfuse = get_client()

        # Per-axis scores (6 total: 3 axes × 2 variants)
        for variant in ("A", "B"):
            variant_run_id = run_a_id if variant == "A" else run_b_id
            for axis in ("atmosphere", "narrative_coherence", "article_fidelity"):
                value = float(llm_judge_scores[variant].get(axis, 0))
                langfuse.create_score(
                    name=f"{axis}_{variant}",
                    value=value,
                    trace_id=trace_url.rsplit("/", 1)[-1] if trace_url else _build_trace_id(pairwise_result.get("ab_pair_id", "")),
                    data_type="NUMERIC",
                    score_id=f"{variant_run_id}-{axis}_{variant}",
                    comment=f"3-run average for {axis} (variant {variant})",
                )

        # Pairwise winner as CATEGORICAL score
        majority = pairwise_result.get("majority_winner", "tie")
        langfuse.create_score(
            name="pairwise_winner",
            value=majority,
            trace_id=trace_url.rsplit("/", 1)[-1] if trace_url else _build_trace_id(pairwise_result.get("ab_pair_id", "")),
            data_type="CATEGORICAL",
            score_id=f"{run_a_id}-pairwise_winner",
        )

        # Rule-based metrics as NUMERIC scores
        for variant in ("A", "B"):
            variant_run_id = run_a_id if variant == "A" else run_b_id
            for metric in ("scene_count_match_rate", "subtitle_sync_error", "audio_duration_variance"):
                value = float(rule_based_scores[variant].get(metric, 0))
                langfuse.create_score(
                    name=f"{metric}_{variant}",
                    value=value,
                    trace_id=trace_url.rsplit("/", 1)[-1] if trace_url else _build_trace_id(pairwise_result.get("ab_pair_id", "")),
                    data_type="NUMERIC",
                    score_id=f"{variant_run_id}-{metric}_{variant}",
                )
    except Exception:
        logger.warning("Langfuse score ingestion failed — result persisted to DB only", exc_info=True)

    return ab_result


# ── Dataclass → dict conversion helpers (Story 4.3 wire-up) ──────────────────


def _axis_scores_to_dict(scores: AxisScores) -> dict:
    return {
        "atmosphere": scores.atmosphere,
        "narrative_coherence": scores.narrative_coherence,
        "article_fidelity": scores.article_fidelity,
    }


def _rule_metrics_to_dict(metrics: RuleBasedMetrics) -> dict:
    return {
        "scene_count_match_rate": metrics.scene_count_match_rate,
        "subtitle_sync_error": metrics.avg_subtitle_sync_error,
        "audio_duration_variance": metrics.audio_duration_variance_pct / 100.0,
    }


def _pairwise_to_dict(pairwise: PairwiseResult) -> dict:
    """Convert PairwiseResult to the ab_result pairwise_winner shape."""
    runs = []
    if pairwise.a_to_b_winner is not None:
        runs.append({"order": "A_vs_B", "winner": pairwise.a_to_b_winner})
    if pairwise.b_to_a_winner is not None:
        runs.append({"order": "B_vs_A", "winner": pairwise.b_to_a_winner})
    if pairwise.tiebreaker_winner is not None:
        runs.append({"order": "A_vs_B", "winner": pairwise.tiebreaker_winner})

    # Determine majority_count and total_runs
    total_runs = len(runs)
    final = pairwise.final_winner
    if final and final != "tie":
        # Count how many runs agree with the final winner
        majority_count = sum(1 for r in runs if r["winner"] == final)
        if majority_count < 2:
            majority_count = max(majority_count, 1)
    else:
        majority_count = 0

    return {
        "majority_winner": final,
        "majority_count": majority_count,
        "total_runs": total_runs,
        "runs": runs,
    }


# ── Trace lifecycle helpers (all guarded — tracing is non-fatal, AD-10) ─────


def _enter_trace(ab_pair_id: str):
    """Open a parent span keyed deterministically by ab_pair_id so every judge
    @observe span nests under one inspectable trace (AC6). Returns None on failure."""
    try:
        client = get_client()
        span = client.start_as_current_observation(
            name="ab-evaluation", as_type="chain",
            trace_context={"trace_id": client.create_trace_id(seed=ab_pair_id)},
        )
        span.__enter__()
        return span
    except Exception:  # noqa: BLE001
        return None


def _finish_trace(span, ab_pair_id: str, winner: str | None, reason: str | None) -> str | None:
    if span is None:
        return None
    try:
        client = get_client()
        # The parent span IS the trace root; enrich it (langfuse v4 has no
        # update_current_trace). ab_pair_id already keys the trace via the id seed.
        client.update_current_span(
            output={"winner": winner, "reason": reason},
            metadata={"ab_pair_id": ab_pair_id},
        )
        return _trace_url(client)
    except Exception:  # noqa: BLE001
        return None


def _exit_trace(span) -> None:
    if span is not None:
        try:
            span.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
