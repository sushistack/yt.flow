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

Story 12.2: the judge moved from DeepSeek to Gemini, which owns every call that
judges prose. Gemini's OpenAI-compatibility endpoint takes the same request shape,
so the judge still uses the already-installed ``httpx`` client — same pattern as
``scenario_node`` — instead of adding the ``openai`` SDK. Judge/pairwise prompts
live in Langfuse Prompt Hub (``evaluation/judge``, ``evaluation/pairwise``), never
hardcoded here.

Accepted tradeoff, recorded so it is not mistaken for a fix: Gemini now both
writes and judges the narration, so self-preference bias is *moved*, not
eliminated. The zero-new-provider fallback is to point the judge back at
``deepseek_judge_model`` (still configured for exactly this reason). Revisit at
Story 13.4 before the promotion gate is unfrozen.

Story 13.2 added four rule metrics in two deliberately asymmetric classes, and
unified the two tiebreak implementations that could previously disagree:

* **motion** (``motion_archetype_coverage``, ``motion_repeat_ratio``) — pure
  functions of checkpoint state, always computable, so they *are* tiebreak inputs.
* **visual** (``unreadable_rate``, ``mean_dsg_score``) — need a paid VLM pass over
  rendered frames (``scripts/score_shot_narration.py --dsg``), so they exist only
  when someone ran it. Recorded in ``ab_result``/Langfuse/UI and **record-only,
  excluded from winner selection pending Story 13.4** — a winner that silently
  depended on their presence would be a trap.

No libcom composite-quality axis is present, and that absence is deliberate:
Story 8-16 is ``backlog`` and ``libcom`` is nowhere in the repo, so there is
nothing to calibrate a threshold against. When 8-16 lands, its axis drops into
the five wiring points 13.2 built (dataclass → dict → Langfuse tuple → tiebreak
table → frontend) — no stub, flag, config field or reserved key is kept for it.
"""

import asyncio
import json
import logging
import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from yt_flow.observability import get_client, observe

from yt_flow.config import Settings
from yt_flow.domain.state import CAMERA_ARCHETYPES, PipelineState, SceneState, ShotData
from yt_flow.pipeline.nodes.shot_timing import plan_shot_clips  # services→nodes: run_service precedent
from yt_flow.services.prompt_service import get_prompt

logger = logging.getLogger(__name__)

AXES = ("atmosphere", "narrative_coherence", "article_fidelity")
REPS_PER_AXIS = 3            # OQ-1: each axis scored 3 times, then averaged
QUALITY_FLOOR = 2.0         # OQ-6: any axis average < 2 disqualifies a run
JUDGE_TIMEOUT_SEC = 30.0    # AC5: per-call timeout, retry-once on timeout

# Same pattern as ``scenario_chain._YAML_FENCE_RE``, deliberately duplicated rather than
# imported: AD-1 bars services/ from importing pipeline/ (enforced by
# test_services_does_not_import_api_or_pipeline, which allows only PURE node modules, and
# scenario_chain is not one). MULTILINE so the fence may open after prose; the ``\Z``
# branch takes everything after an unterminated fence instead of failing to match.
# Keep the two in sync — see ``_post_chat`` for why the judge needs it at all.
_FENCE_RE = re.compile(r"^```[a-zA-Z]*[ \t]*\n(.*?)(?:\n?[ \t]*```|\Z)", re.DOTALL | re.MULTILINE)


def _defence(raw: str) -> str:
    """Strip one markdown code fence, if present. A no-op on bare output."""
    text = raw.strip()
    match = _FENCE_RE.search(text)
    return match.group(1) if match else text
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
    # None == no word timings to check, which is NOT the same as "perfectly aligned"
    # (Story 13.2 — it became a tiebreak input, and 0.0-means-both would have let the
    # less-measured run win position 2). See _cut_alignment_error.
    cut_alignment_error: float | None   # seconds, cut boundary vs nearest word boundary (Story 11.4)
    # Story 13.2. Motion pair: always computable from state, tiebreak inputs.
    motion_archetype_coverage: float = 0.0   # 0.0–1.0, higher is better
    motion_repeat_ratio: float = 0.0         # 0.0–1.0, lower is better
    # Visual pair: None == the offline visual scorer never ran for this run. NOT
    # 0.0 — a defaulted unreadable_rate of 0.0 would read as perfect readability.
    unreadable_rate: float | None = None     # 0.0–1.0, lower is better
    mean_dsg_score: float | None = None      # 0.0–1.0, higher is better


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
    """POST a JSON-mode chat completion to Gemini; retry ONCE on timeout only (AC5).

    Parse failures are not retried here — the caller raises ``EvalJudgeError``
    immediately so a persistently malformed judge can't burn the time budget.

    Story 12.2: Gemini's OpenAI-compatibility endpoint, so only the base URL, key,
    model and token budget changed — the retry/timeout/parse contract is untouched.
    Never falls back to DeepSeek: a judge served by the wrong provider would make
    the whole comparison uninterpretable. A blocked/empty Gemini response is raised
    as ``EvalJudgeError`` so it stays inside the per-sample isolation (see below).
    """
    if not s.gemini_api_key:
        raise RuntimeError("YTFLOW_GEMINI_API_KEY is not configured")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": rendered}],
        "response_format": {"type": "json_object"},
        "max_tokens": s.gemini_judge_max_tokens,
    }
    for attempt in range(2):  # initial try + one retry on timeout
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                resp = await client.post(
                    f"{s.gemini_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {s.gemini_api_key}"},
                    json=payload,
                )
            resp.raise_for_status()
            # Gemini answers a safety-blocked prompt 200-with-no-choices, and omits
            # `content` entirely on a MAX_TOKENS stop — two shapes DeepSeek never
            # produced. Indexing them raw raised IndexError/KeyError, which is NOT
            # what `_judge_sample`/`_pairwise_once` isolate on, so ONE blocked sample
            # escaped `asyncio.gather` and failed the whole evaluation instead of
            # degrading to a dropped sample (Story 6.8's isolation contract, AC7).
            # Normalize to EvalJudgeError: the caller's existing one-retry-then-drop.
            choices = resp.json().get("choices") or []
            if not choices:
                raise EvalJudgeError(f"judge: response carried no choices (model={model})")
            content = (choices[0].get("message") or {}).get("content")
            if not content:
                raise EvalJudgeError(
                    f"judge: empty content (model={model}, "
                    f"finish_reason={choices[0].get('finish_reason')!r})"
                )
            # De-fence before the callers' json.loads. `response_format:
            # {"type": "json_object"}` above is what USED to guarantee bare JSON, but
            # Google does not document `json_object` for the OpenAI-compatibility
            # endpoint (checked 2026-08-06) — and Story 12.2's own live probe caught
            # Gemini fencing its output as ```yaml. If the parameter is silently
            # ignored, every fenced sample fails json.loads, every axis lands under
            # the 2-valid-sample floor, and the whole A/B evaluation fails. Reuses
            # the same fence pattern scenario_chain hardened over live runs 64b6d9a8 /
            # db2e813 (duplicated, not imported — see `_FENCE_RE`); a no-op on bare JSON.
            return _defence(content)
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
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise EvalJudgeError(f"axis={axis}: unparseable judge response: {raw!r}") from exc
    if not 1 <= score <= 5:
        raise EvalJudgeError(f"axis={axis}: score {score} outside 1–5")
    return score


async def _judge_sample(rendered: str, axis: str, s: Settings) -> int | None:
    """One judge sample: exactly one bounded retry on a parse failure (Story 6.8).

    Timeouts are not retried here — ``_post_chat`` already retries those once
    and a persistent timeout should still fail the sample. Returns None if both
    the original call and the retry fail to parse, so the caller can drop this
    one sample without losing the other REPS_PER_AXIS-1 already-sampled calls.
    """
    for attempt in range(2):  # initial try + one retry on parse failure
        try:
            raw = await _post_chat(rendered, s.gemini_judge_model, s)
            return _parse_score(raw, axis)
        except EvalJudgeError:
            if attempt == 1:
                return None
    raise AssertionError("unreachable")  # loop always returns


@observe(name="judge-axis")
async def _judge_axis(scp_text: str, artifact_text: str, axis: str, s: Settings) -> list[int]:
    """Score one axis REPS_PER_AXIS times (concurrent) and return the raw integers.

    Each sample is retried once on a parse failure, isolated from the other
    concurrent samples (a dropped sample never raises out of ``asyncio.gather``,
    so it can't cancel or fail the others). One permanently-failed sample
    degrades to a REPS_PER_AXIS-1 average; two or more still fail the axis, same
    as before this story (Story 6.8, AC1/AC2).
    """
    rendered = get_prompt(JUDGE_PROMPT).compile(
        scp_text=scp_text, artifact_content=artifact_text, axis=axis,
    )
    samples = await asyncio.gather(
        *(_judge_sample(rendered, axis, s) for _ in range(REPS_PER_AXIS))
    )
    scores = [score for score in samples if score is not None]
    if len(scores) < REPS_PER_AXIS:
        logger.warning(
            "axis=%s: %d/%d judge samples parsed (rest failed retry)", axis, len(scores), REPS_PER_AXIS
        )
    if len(scores) < 2:
        raise EvalJudgeError(f"axis={axis}: fewer than 2 of {REPS_PER_AXIS} judge samples parsed")
    return scores


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

    Story 12.2 deliberately did NOT switch this to ``display_narration``: the judge
    reads the text actually delivered as speech, which includes the bounded DeepSeek
    tts_normalize pass. Judging display text instead would score something the
    viewer never hears — a silent contract change, not a provider change.
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

    MEANING INVERTED by Story 11.4: tts's provisional timings are gap-free uniform
    splits, so this was always ~0. Real WhisperX timings have inter-word silence —
    a NONZERO value is now normal, not a regression. Known distortion: the tiebreak
    (lower=better) weakly prefers a run that FELL BACK to provisional (=degraded)
    timings over a properly aligned one. **MITIGATED BY DEMOTION IN STORY 13.2, NOT
    REMOVED**: the unified ``_TIEBREAK_CHAIN`` now puts ``cut_alignment_error`` —
    the only timing metric whose meaning is not inverted — ahead of this one, so
    the distorted comparison is only reached when the un-inverted one ties. The
    metric itself still means the wrong thing; treat a delta here as uninterpretable.
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


def _cut_alignment_error(scenes: list[SceneState], min_shot_clip_sec: float) -> float | None:
    """Mean |deviation| (seconds) between each internal shot-cut boundary and the
    nearest word boundary (any word's start/end), across all scenes. [Story 11.4 AC:6]

    Recomputes ``plan_shot_clips`` (pure — shots/word_timings/narration/
    audio_duration all live in state). Internal boundaries only: the first clip's
    start and last clip's end are pinned to 0/audio_duration, not cut decisions.
    ~0 when cuts derive from a clean 1:1 word-timing mapping; > 0 exactly when
    sentence_windows' count-mismatch apportion degrade fired — i.e. the
    uniform-split regression Story 11.4 eliminates. Scenes with < 2 clips contribute
    nothing.

    PROMOTED TO A TIEBREAK INPUT BY STORY 13.2 (11.4's "regression-detection record
    ONLY" line is gone, deliberately). It sits at position 2 of ``_TIEBREAK_CHAIN``,
    ahead of ``subtitle_sync_error``, because it is the only timing metric 11.4 did
    not invert the meaning of — putting it first *is* the redesign 11.4 deferred.

    **RETURNS ``None``, NOT 0.0, WITH NO DATA — changed by 13.2, and the promotion is
    exactly why.** Under 11.4's "0.0 with no data" convention the value 0.0 meant both
    "every cut lands on a word boundary" and "there were no word timings to check",
    which is harmless for a record but not for a *winner input*: lower-is-better at
    position 2 would have handed the top-priority tiebreak to whichever run had LESS
    timing data (WhisperX fell back → no timings → 0.0 → beats a properly aligned run
    scoring 0.09). ``None`` is omitted from ``_rule_metrics_to_dict``, and
    ``_rule_tiebreak_from_dicts`` skips a step it cannot compare — so an unmeasured
    run neither wins nor loses on this axis. Relocating that ambiguity instead of
    fixing it would have reproduced, at higher priority, the distortion demoting
    ``subtitle_sync_error`` was meant to mitigate.
    """
    deviations: list[float] = []
    for sc in scenes:
        timings = sc.get("word_timings") or []
        narration = sc.get("narration") or ""
        duration = sc.get("audio_duration")
        if not timings or not narration or duration is None:
            continue
        clips = plan_shot_clips(sc.get("shots") or [], timings, narration, duration,
                                min_shot_clip_sec=min_shot_clip_sec)
        if len(clips) < 2:
            continue
        bounds = sorted({t["start_sec"] for t in timings} | {t["end_sec"] for t in timings})
        deviations.extend(min(abs(clip.start - b) for b in bounds) for clip in clips[1:])
    return statistics.fmean(deviations) if deviations else None


# ── Motion metrics (Story 13.2, pure — no I/O, no Settings) ─────────────────


def _motion_key(shot: ShotData) -> str:
    """This shot's camera archetype, or the single ``"unmapped"`` bucket.

    Read straight off ``ShotData.camera_movement`` (Story 11.2's closed enum).
    Deliberately NOT through ``pipeline/nodes/video.select_effect``: that collapses
    ``push_in`` and ``shake`` both to ``"in-center"``, so measuring there would
    count *direction* diversity instead of *archetype* diversity — and Story 11.3
    lays separate fBm noise on ``shake``, so the two really do render differently.
    A legacy free-text hint or ``None`` is not an archetype and shares one bucket:
    those shots are actually driven by ``select_effect``'s ``_DIRECTION_POOL``
    round-robin, which carries no archetype at all.
    """
    movement = shot.get("camera_movement")
    return movement if movement in CAMERA_ARCHETYPES else "unmapped"


def _motion_archetype_coverage(scenes: list[SceneState]) -> float:
    """Distinct ``CAMERA_ARCHETYPES`` actually used ÷ 5 (higher is better).

    ``"unmapped"`` shots never contribute to the numerator, so a run whose
    ``camera_movement`` values are all ``None``/legacy scores 0.0. No shots → 0.0
    (the existing rule-metric no-data convention).

    OBSERVED VALUE, measured on reference run ``8a9a288b`` (9 scenes / 66 shots —
    push_in 20, drift 16, locked 15, pull_back 9, shake 6): **1.0**. Do not read 1.0
    as a broken metric; it is what a multi-mood episode is supposed to score.

    **The reachable range is set by mood, not by quality, and 0.2 is effectively
    unreachable.** ``scenario_chain.CAMERA_PREFERENCES`` exposes exactly **3** of the 5
    archetypes per mood, and ``_enforce_camera_variety`` guarantees ≥2 distinct
    archetypes in any scene with ≥2 shots. So a single-mood episode floors around
    **0.4–0.6** while a healthy multi-mood one reaches 1.0, and only a genuinely dead
    ``camera_movement`` path (all ``None``/legacy → ``"unmapped"``) reaches 0.0.

    Two consequences, both load-bearing:

    * **0.4 does not distinguish a healthy single-mood episode from a half-broken
      wiring path.** Read it together with the archetype set actually present, not
      alone.
    * It is nonetheless a **tiebreak input at position 4**, and the step between
      reachable values is 0.2 — far above its epsilon — so it *can* decide a stored
      winner. What it then rewards is **mood variety**, which is exactly the kind of
      thing an A/B prompt variant changes. Treat a win on this axis as "more mood
      variety", never as "better motion".

    Same failure shape as Story 10.4's dead ``legible`` Likert — an axis whose value
    barely moves on healthy input — caught here before implementation instead of after.
    """
    used = {
        key for sc in scenes for sh in (sc.get("shots") or [])
        if (key := _motion_key(sh)) != "unmapped"
    }
    return len(used) / len(CAMERA_ARCHETYPES)


def _motion_repeat_ratio(scenes: list[SceneState]) -> float:
    """Fraction of adjacent shot pairs sharing a motion key (lower is better).

    Shots are flattened in run order: scenes by ascending ``scene_num``, shots in
    their in-scene order.

    **Scene boundaries are counted, deliberately, and a nonzero value here is NOT
    an 11.2 violation.** ``scenario_chain._enforce_camera_variety`` forbids repeats
    only *within* a scene (Story 5.16's dip-to-black already breaks visual
    continuity across the boundary, so boundaries are intentionally exempt there).
    Counting within-scene pairs only would make this metric a constant 0.0 and
    worthless as an axis; boundary pairs are the only pairs that can ever repeat,
    which caps the reachable range at ``[0, (scenes-1)/(shots-1)]``. Do not "fix"
    ``_enforce_camera_variety`` because this number is above zero.

    OBSERVED VALUE AND RANGE, measured on reference run ``8a9a288b``: **0.0154**
    (1 of 65 pairs; reachable range there is ``[0, 0.123]``), and that single
    repeat is a ``locked``→``locked`` scene boundary. It goes to 1.0 when every shot
    lands in ``"unmapped"``, i.e. when 11.2's wiring is dead.

    **It is a tiebreak input at position 3, and one boundary pair (1/65 ≈ 0.0154) is
    already above its epsilon** — so this axis can decide a stored winner on a single
    scene boundary. Since only boundaries can repeat, what it actually measures across
    two variants is *how their scenes are cut up*: a variant with more scenes has a
    larger reachable range and is structurally more exposed. Read a win here as "fewer
    repeated archetypes across scene boundaries", not as "better motion".

    Fewer than 2 shots → 0.0. That is the best possible value for a run with no
    adjacent pair at all; a 1-shot run would therefore win this step. Left as 0.0
    because the I/O contract specifies it and a run that degenerate cannot reach A/B
    evaluation (``_validate_pair`` requires two complete runs, and a complete run has
    every scene's shots) — but it is the one input here that is best-by-vacuity.
    """
    keys = [
        _motion_key(sh)
        for sc in sorted(scenes, key=lambda sc: sc["scene_num"])
        for sh in (sc.get("shots") or [])
    ]
    if len(keys) < 2:
        return 0.0
    return sum(a == b for a, b in zip(keys, keys[1:])) / (len(keys) - 1)


# ── Visual metrics (Story 13.2) — one edge read, then pure ──────────────────

VISUAL_SCORE_FILENAME = "visual_score.json"
"""Filename ``scripts/score_shot_narration.py --dsg`` writes its report to, under
``<workspace_path>/<run_id>/``. It lives HERE, in the consumer, and the script
imports it: ``scripts/`` already puts ``src`` on ``sys.path`` and imports
``yt_flow.*``, but ``src/`` cannot import ``scripts/``. One spelling of the
contract, in the direction the dependency already runs."""


def _load_visual_scores(run_id: str, workspace_path: str) -> dict | None:
    """The run's offline visual-score report, or ``None`` when there isn't one.

    The ONLY I/O in the rule-metric layer, and it is called from ``evaluate_ab``,
    not from ``_compute_rule_metrics`` — every metric function stays pure and takes
    the already-parsed dict (``_avg_subtitle_sync_error``'s convention). Absent is
    the normal case: nobody has to pay for a VLM pass to evaluate a pair. A
    corrupt/unparseable artifact also reads as absent, because a half-parsed
    readability number is worse than no number.

    The ``isinstance`` check is not decoration: ``[]``, ``"x"`` and ``3`` are all valid
    JSON that ``json.loads`` returns happily, and a non-dict reaching ``_unreadable_rate``
    would raise ``AttributeError`` **inside** ``evaluate_ab``'s span, marking the trace
    failed and aborting an A/B evaluation that does not depend on this file at all. A
    wrong-shaped optional artifact must not be able to kill the evaluation.
    """
    path = Path(workspace_path) / run_id / VISUAL_SCORE_FILENAME
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) else None


def _unreadable_rate(report: dict) -> float | None:
    """Fraction of scored frames the blind judge could not read (lower is better).

    Pure over an already-parsed ``visual_score.json``. Story 10.4 measured this at
    12/66 = **0.182** on run ``8a9a288b`` — and it only exists because 10.4's
    iteration 2 replaced a dead 1–5 ``legible`` Likert (66 frames produced
    ``{4: 46, 5: 20}``) with the boolean the judge was already volunteering.

    ``None`` — never 0.0 — when nothing was scored: 0.0 would read as "no
    unreadable frames", the exact opposite of "no measurement".

    Every field is type- and range-checked because this file is written by a separate
    process and may be stale, truncated or hand-edited. An out-of-range pair would
    otherwise publish a "fraction" above 1.0, and a string would raise inside
    ``evaluate_ab``. Unparseable reads as unmeasured.
    """
    summary = report.get("summary")
    if not isinstance(summary, dict):
        return None
    scored, unreadable = summary.get("scored"), summary.get("unreadable")
    if not isinstance(scored, int) or isinstance(scored, bool) or scored <= 0:
        return None
    if not isinstance(unreadable, int) or isinstance(unreadable, bool):
        return None
    return unreadable / scored if 0 <= unreadable <= scored else None


def _mean_dsg_score(report: dict) -> float | None:
    """Mean per-shot DSG satisfied-fraction (0.0–1.0, higher is better), or ``None``.

    ``summary.mean_dsg`` is already the mean over rows that were *scorable*; a row
    whose propositions were all person-kind is unscorable and excluded there rather
    than counted as 0.0 (see the scorer's ``dsg_score``). ``None`` when the report
    predates ``--dsg`` — the 1–5 ``match`` Likert this replaces is not comparable
    to a fraction and is deliberately not coerced into one.

    A non-numeric or out-of-range value also reads as unmeasured. Unchecked it would
    travel into ``ab_result`` and then to the UI, where ``formatScore`` calls
    ``value.toFixed`` and a string blanks the comparison page.
    """
    summary = report.get("summary")
    value = summary.get("mean_dsg") if isinstance(summary, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and 0.0 <= value <= 1.0 else None


def _compute_rule_metrics(
    state_a: PipelineState, state_b: PipelineState, min_shot_clip_sec: float = 2.0,
    visual_a: dict | None = None, visual_b: dict | None = None,
) -> tuple[RuleBasedMetrics, RuleBasedMetrics]:
    """Both runs' rule metrics. ``visual_*`` are already-parsed ``visual_score.json``
    reports (``None`` when the offline scorer never ran) — this function does no I/O.

    Story 13.2 switched to keyword construction: nine fields built positionally is
    how two metrics get silently swapped.
    """
    scenes_a, scenes_b = state_a["scenes"], state_b["scenes"]
    match_rate = _scene_count_match_rate(len(scenes_a), len(scenes_b))  # symmetric across the pair

    def build(scenes: list[SceneState], visual: dict | None) -> RuleBasedMetrics:
        return RuleBasedMetrics(
            scene_count=len(scenes),
            scene_count_match_rate=match_rate,
            avg_subtitle_sync_error=_avg_subtitle_sync_error(scenes),
            audio_duration_variance_pct=_audio_duration_variance_pct(scenes),
            cut_alignment_error=_cut_alignment_error(scenes, min_shot_clip_sec),
            motion_archetype_coverage=_motion_archetype_coverage(scenes),
            motion_repeat_ratio=_motion_repeat_ratio(scenes),
            unreadable_rate=None if visual is None else _unreadable_rate(visual),
            mean_dsg_score=None if visual is None else _mean_dsg_score(visual),
        )

    return build(scenes_a, visual_a), build(scenes_b, visual_b)


# ── Pairwise comparison + winner determination (AC3, AC4) ──────────────────


@observe(name="pairwise-once")
async def _pairwise_once(scp_text: str, first: str, second: str, s: Settings) -> str:
    """One ordered LLM comparison. Returns "A"|"B"|"tie" (A/B are the *labels* of
    ``first``/``second``, so the caller controls ordering for bias mitigation)."""
    rendered = get_prompt(PAIRWISE_PROMPT).compile(
        scp_text=scp_text, content_first=first, content_second=second,
    )
    raw = await _post_chat(rendered, s.gemini_judge_model, s)
    try:
        winner = json.loads(raw)["winner"]
    except (ValueError, KeyError, TypeError) as exc:
        raise EvalJudgeError(f"pairwise: unparseable response: {raw!r}") from exc
    if winner not in ("first", "second", "tie"):
        raise EvalJudgeError(f"pairwise: winner must be first|second|tie, got {winner!r}")
    return {"first": "A", "second": "B", "tie": "tie"}[winner]


# Story 13.2: THE rule tiebreak, in one place. Keys are ``_rule_metrics_to_dict``'s
# spelling — i.e. ``ab_result.rule_based_scores`` — because a stored row has to be
# re-scorable by the same code that produced it.
#
#   #  key                        direction  eps      note
#   1  scene_count_match_rate     higher     0.01     symmetric across the pair → NEVER
#                                                     fires; kept so stored rows keep
#                                                     their meaning
#   2  cut_alignment_error        lower      0.01 s   promoted in 13.2; the one timing
#                                                     metric 11.4 did not invert
#   3  motion_repeat_ratio        lower      0.01     new in 13.2
#   4  motion_archetype_coverage  higher     0.1      new in 13.2; its own step is 0.2,
#                                                     so a smaller eps would be noise
#   5  subtitle_sync_error        lower      0.01 s   DEMOTED in 13.2 (see the metric)
#   6  audio_duration_variance    lower      0.0001   ratio (= 0.01 percentage point)
#
# EPSILON IS PER KEY, not one shared 0.01, because these six are not in one unit: two
# are seconds, three are unitless 0–1 ratios with different granularities, and
# ``audio_duration_variance`` is a percentage divided by 100. A single absolute 0.01
# meant a 0.6-percentage-point audio-variance gap tied while a 10 ms cut gap decided —
# and it made the old dataclass path (strict ``<`` on the pct scale) and the old dict
# path (``> 0.01`` on the ratio scale) disagree on real inputs (8.0 % vs 8.6 % → the
# point-sum said "A", the lexicographic dict said "tie").
#
# ``unreadable_rate``/``mean_dsg_score`` are deliberately ABSENT: they exist only if
# someone ran the offline VLM pass, and a winner that silently depended on that would
# be a trap. Their inclusion is Story 13.4's decision, not this table's.
_TIEBREAK_CHAIN: tuple[tuple[str, bool, float], ...] = (  # (key, higher_is_better, eps)
    ("scene_count_match_rate", True, 0.01),
    ("cut_alignment_error", False, 0.01),
    ("motion_repeat_ratio", False, 0.01),
    ("motion_archetype_coverage", True, 0.1),
    ("subtitle_sync_error", False, 0.01),
    ("audio_duration_variance", False, 0.0001),
)


def _comparable(value: object) -> float | None:
    """``value`` as a finite float, or ``None`` if it cannot be compared.

    Rejects ``None``, strings, ``bool`` (an ``int`` subtype that would read as 0/1),
    NaN and infinities. A stored ``ab_result`` row is JSON that other code wrote, and
    ``json.loads`` happily accepts ``NaN``; ``abs(nan - x) > eps`` is always ``False``,
    so an unguarded NaN does not raise — it silently makes a step tie and lets a later
    metric pick the winner. Silent is the failure mode worth spending a guard on.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _rule_tiebreak_from_dicts(a: dict, b: dict) -> str:
    """OQ-6 rule tiebreak over ``rule_based_scores`` dicts → ``"A"``|``"B"``|``"tie"``.

    Lexicographic: the first key whose two values differ by more than that key's own
    epsilon decides, and nothing after it is consulted.

    **A step is SKIPPED unless both sides carry a comparable number.** No defaulting:
    substituting 0.0 for a missing key would hand the step to whichever run was not
    measured, because four of the six keys are lower-is-better and 0.0 is their best
    possible value. That is the ``cut_alignment_error`` trap in particular — see its
    docstring — and it is why absence is skipped rather than filled in. Consequences
    that fall out of the same rule: a key missing from BOTH sides (an ``ab_result`` row
    stored before 11.4 or 13.2, fed back through ``determine_winner``) ties that step
    and falls through instead of raising ``KeyError``, and a ``null``/NaN/string value
    in a hand-edited or merged row cannot decide a winner either.

    Story 13.2 unified this with ``determine_winner``'s old hardcoded 3a/3b/3c block,
    which could return a DIFFERENT winner from the old ``_rule_tiebreak``: on a 1–1
    split (A better on one metric, B on another) the point-sum said ``"tie"`` while
    lexicographic said ``"A"``, so ``EvaluationResult.winner`` and the stored
    ``ab_result.winner`` disagreed. Intended behaviour changes that came with the
    merge, recorded rather than discovered later: aggregation is now lexicographic
    (not point-sum), and the epsilon is an explicit per-key band (see the table)
    instead of the dataclass path's strict ``<`` and the dict path's shared ``0.01``.
    """
    for key, higher_is_better, eps in _TIEBREAK_CHAIN:
        va, vb = _comparable(a.get(key)), _comparable(b.get(key))
        if va is None or vb is None:
            continue
        if abs(va - vb) > eps:
            return "A" if (va > vb) == higher_is_better else "B"
    return "tie"


def _rule_tiebreak(metrics_a: RuleBasedMetrics, metrics_b: RuleBasedMetrics) -> str:
    """Dataclass-shaped entry point to ``_rule_tiebreak_from_dicts``. One definition.

    The dict form uses the ratio scale for ``audio_duration_variance`` (pct ÷ 100)
    where the dataclass field is a percentage, but the *order relation* is identical,
    so converting first cannot change the winner.
    """
    return _rule_tiebreak_from_dicts(_rule_metrics_to_dict(metrics_a), _rule_metrics_to_dict(metrics_b))


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
    """Check both runs exist, are complete, and B points back to A. Returns the pair id.

    Story 4.1's data model (``create_ab_run``): the B run stores
    ``ab_pair_id=<A run's id>``; A's own ``ab_pair_id`` stays ``None``. So a valid
    pair is "B.ab_pair_id == A.id", not "both runs share one id". The pair id is
    A's own id, since that's what B's ab_pair_id already points to.
    """
    status_a, pair_a = _load_run_meta(run_a_id)
    status_b, pair_b = _load_run_meta(run_b_id)
    for rid, status in ((run_a_id, status_a), (run_b_id, status_b)):
        if status != "complete":
            raise ValueError(f"run {rid}: status is {status!r}, must be 'complete' to evaluate")
    if pair_b != run_a_id:
        raise ValueError(
            f"runs are not a valid A/B pair: {run_a_id} ab_pair_id={pair_a!r}, "
            f"{run_b_id} ab_pair_id={pair_b!r}, expected {run_b_id} ab_pair_id={run_a_id!r}"
        )
    return run_a_id


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
    # Story 12.2: the judge is Gemini's, so this is the key the evaluation needs —
    # a DeepSeek key is no longer required to score an A/B pair.
    if not s.gemini_api_key:
        raise RuntimeError("YTFLOW_GEMINI_API_KEY is not configured")

    ab_pair_id = _validate_pair(run_a_id, run_b_id)  # AC7: raises before any scoring
    state_a = await _load_state(run_a_id, s.db_path)
    state_b = await _load_state(run_b_id, s.db_path)
    text_a, text_b = _artifact_text(state_a), _artifact_text(state_b)

    # Story 13.2: the one filesystem read the metric layer needs, done here at the
    # edge so _compute_rule_metrics stays pure. Absent for every run nobody ran the
    # offline visual scorer on, which is the normal case.
    visual_a = _load_visual_scores(run_a_id, s.workspace_path)
    visual_b = _load_visual_scores(run_b_id, s.workspace_path)

    span = _enter_trace(ab_pair_id)
    try:
        metrics_a, metrics_b = _compute_rule_metrics(state_a, state_b, s.min_shot_clip_sec,
                                                     visual_a, visual_b)
        scores_a, scores_b = await asyncio.gather(
            _score_run(state_a["scp_text"], text_a, s),
            _score_run(state_b["scp_text"], text_b, s),
        )
        pairwise = await _pairwise_compare(
            state_a["scp_text"], text_a, text_b, scores_a, scores_b,
            metrics_a, metrics_b, run_a_id, run_b_id, s,
        )
        winner, winner_run_id, reason = _resolve_winner(pairwise, run_a_id, run_b_id)
        trace_url = _finish_trace(span, ab_pair_id, winner, reason, s.gemini_judge_model)

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
            ab_pair_id=ab_pair_id,
            trace_url=trace_url,
        )

        return EvaluationResult(
            ab_pair_id=ab_pair_id, run_a_id=run_a_id, run_b_id=run_b_id,
            scores_a=scores_a, scores_b=scores_b, metrics_a=metrics_a, metrics_b=metrics_b,
            pairwise=pairwise, winner=winner, winner_run_id=winner_run_id,
            reason=reason, langfuse_trace_url=trace_url,
        )
    except Exception as exc:  # noqa: BLE001 — mark the span, then let the exception through unchanged
        _mark_trace_error(span, exc)
        raise
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

    # Step 3: Rule-based tiebreaker — the SAME function ``_rule_tiebreak`` uses, so
    # ``EvaluationResult.winner`` and the stored ``ab_result.winner`` can no longer
    # disagree (Story 13.2). Returns "tie" when the whole chain is exhausted, which
    # is also step 4. All keys are read with .get, so legacy stored rows re-score.
    return (_rule_tiebreak_from_dicts(rule_based_scores["A"], rule_based_scores["B"]), None)


# ── Story 4.3: Result storage (DB + Langfuse, AD-10 non-fatal) ──────────────


async def store_evaluation_results(
    run_a_id: str,
    run_b_id: str,
    llm_judge_scores: dict,
    rule_based_scores: dict,
    pairwise_result: dict,
    ab_pair_id: str | None = None,
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
        # Same deterministic id used to open the eval trace in evaluate_ab
        # (create_trace_id(seed=ab_pair_id)); every score attaches to that trace.
        eval_trace_id = langfuse.create_trace_id(seed=ab_pair_id) if ab_pair_id else None

        # Per-axis scores (6 total: 3 axes × 2 variants)
        for variant in ("A", "B"):
            variant_run_id = run_a_id if variant == "A" else run_b_id
            for axis in ("atmosphere", "narrative_coherence", "article_fidelity"):
                value = float(llm_judge_scores[variant].get(axis, 0))
                langfuse.create_score(
                    name=f"{axis}_{variant}",
                    value=value,
                    trace_id=eval_trace_id,
                    data_type="NUMERIC",
                    score_id=f"{variant_run_id}-{axis}_{variant}",
                    comment=f"3-run average for {axis} (variant {variant})",
                )

        # Pairwise winner as CATEGORICAL score ("tie" when no decisive winner)
        majority = pairwise_result.get("majority_winner") or "tie"
        langfuse.create_score(
            name="pairwise_winner",
            value=majority,
            trace_id=eval_trace_id,
            data_type="CATEGORICAL",
            score_id=f"{run_a_id}-pairwise_winner",
        )

        # Rule-based metrics as NUMERIC scores. Story 13.2 added the motion pair and
        # the visual pair, and stopped defaulting an absent key to 0.0: the visual
        # keys are only present when the offline scorer ran, and ingesting 0.0 for
        # `unreadable_rate` would publish "perfect readability" for a run nobody
        # measured. A legacy dict missing a key simply contributes no score.
        for variant in ("A", "B"):
            variant_run_id = run_a_id if variant == "A" else run_b_id
            for metric in ("scene_count_match_rate", "subtitle_sync_error", "audio_duration_variance",
                           "cut_alignment_error", "motion_archetype_coverage", "motion_repeat_ratio",
                           "unreadable_rate", "mean_dsg_score"):
                # _comparable, not float(): a null/string in a stored row would raise
                # INSIDE the AD-10 try and silently drop every remaining score,
                # including all of variant B's. One bad key must cost one score.
                value = _comparable(rule_based_scores[variant].get(metric))
                if value is None:
                    continue
                langfuse.create_score(
                    name=f"{metric}_{variant}",
                    value=value,
                    trace_id=eval_trace_id,
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
    """The ``ab_result.rule_based_scores`` schema, and the tiebreak chain's input shape.

    Story 13.2: the two motion keys are always emitted (pure functions of state), the
    two visual keys only when they were actually measured. Absence is expressed by
    OMITTING the key — a defaulted ``unreadable_rate: 0.0`` would be published as
    "no unreadable frames", which is a reading nobody took.
    """
    out = {
        "scene_count_match_rate": metrics.scene_count_match_rate,
        "subtitle_sync_error": metrics.avg_subtitle_sync_error,
        # pct → proportion (0–1) to match the ab_result schema (spec 4.3)
        "audio_duration_variance": metrics.audio_duration_variance_pct / 100.0,
        "motion_archetype_coverage": metrics.motion_archetype_coverage,
        "motion_repeat_ratio": metrics.motion_repeat_ratio,
    }
    # Omitted-when-unmeasured, all three for the same reason: the tiebreak skips a key
    # it cannot compare, so absence costs the run nothing, whereas a defaulted 0.0
    # would be its BEST possible value on every one of these (lower-is-better for two,
    # and "no unreadable frames" for the third).
    for key, value in (("cut_alignment_error", metrics.cut_alignment_error),
                       ("unreadable_rate", metrics.unreadable_rate),
                       ("mean_dsg_score", metrics.mean_dsg_score)):
        if value is not None:
            out[key] = value
    return out


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
    # True count of comparison runs that agree with the final winner (0 when the
    # winner came from the floor/tiebreaker path with no recorded comparisons).
    if final and final != "tie":
        majority_count = sum(1 for r in runs if r["winner"] == final)
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


def _finish_trace(
    span, ab_pair_id: str, winner: str | None, reason: str | None, judge_model: str | None = None
) -> str | None:
    if span is None:
        return None
    try:
        client = get_client()
        # The parent span IS the trace root; enrich it (langfuse v4 has no
        # update_current_trace). ab_pair_id already keys the trace via the id seed.
        # judge_provider/judge_model (Story 12.2 AC8) make a stored verdict
        # attributable to the model that produced it — without them, a later
        # provider change silently rewrites the meaning of old scores.
        client.update_current_span(
            output={"winner": winner, "reason": reason},
            metadata={"ab_pair_id": ab_pair_id, "judge_provider": "gemini", "judge_model": judge_model},
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


def _mark_trace_error(span, exc: Exception) -> None:
    """Best-effort mark the still-open "ab-evaluation" span as failed before
    ``_exit_trace`` closes it — otherwise a raised exception leaves the trace
    looking like a clean success (AD-10: tracing itself must never raise)."""
    if span is None:
        return
    try:
        get_client().update_current_span(level="ERROR", status_message=str(exc))
    except Exception:  # noqa: BLE001
        pass
