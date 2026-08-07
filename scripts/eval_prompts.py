"""Golden-set offline prompt regression eval runner (Story 6.2).

Runs ``scenario_node`` only (no DB run row, graph, gate, image/TTS/subtitle/
video work) against a fixed Langfuse dataset for a given prompt label, scores
each item with the Epic 4 LLM-judge axes + scenario-applicable rule metrics,
and — with ``--baseline`` — prints a per-axis comparison and promotion
verdict. Uses ``Langfuse.Dataset.run_experiment`` so dataset-run creation and
per-item score recording happen inside the SDK; this script only supplies the
task (run scenario) and evaluator (score it) functions (AC5).

Usage:
    uv run python scripts/eval_prompts.py --seed
    uv run python scripts/eval_prompts.py --label candidate
    uv run python scripts/eval_prompts.py --label candidate --baseline production
"""

import argparse
import asyncio
import copy
import hashlib
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from langfuse import Evaluation  # noqa: E402

from yt_flow.config import Settings  # noqa: E402
from yt_flow.domain.state import STORY_ARCHETYPE_FALLBACK, STORY_ARCHETYPES  # noqa: E402
from yt_flow.pipeline.nodes import scenario as scenario_module  # noqa: E402
from yt_flow.pipeline.nodes.scenario import _call_deepseek, _call_gemini, scenario_node  # noqa: E402
from yt_flow.pipeline.nodes.scenario_chain import (  # noqa: E402
    cast_decision_step,
    research_step,
    split_sentences,
    structure_step,
    visual_breakdown_step,
    writing_step,
)
from yt_flow.services.eval_service import AXES, _score_run  # noqa: E402
from yt_flow.services.prompt_service import build_client, get_prompt, get_prompt_with_fallback  # noqa: E402

DATASET_NAME = "golden-scps"
GOLDEN_IDS = ("SCP-096", "SCP-173", "SCP-049")
SCPS_PATH = Path(__file__).parent.parent / "data" / "scps.json"
LABELS = ("production", "candidate")
STAGES = ("full", "writing", "cast_decision", "visual_breakdown")
PROFILES = ("smoke", "promotion")
SMOKE_DEFAULT_SCP_ID = "SCP-049"  # constant canary for score history (Story 6.6) — do not rotate
# Median-of-N regenerations per item for the promotion gate (Story 6.10, AC1).
# Mirrors eval_service.REPS_PER_AXIS=3 — but repeats the *generation* to absorb
# run-to-run generation noise, not the judge sampling within one generation.
PROMOTION_REPS = 3
NOT_A_PROMOTION_GATE = "NOT A PROMOTION GATE"
PROMOTION_GATE_AUTHORITY = "PROMOTION GATE"

# Story 6-12: the candidate-vs-production A/B gate is FROZEN during pipeline
# development. Any run with a --baseline (the two-sided comparison) burns heavy
# tokens (full-scenario regeneration × 2 labels × reps) and only matters for
# production-quality tuning — deferred until the pipeline itself is complete.
# Set this env var to "1" to run it deliberately once quality tuning resumes.
AB_GATE_OVERRIDE_ENV = "YTFLOW_ALLOW_AB_GATE"

# A full scenario item was observed taking >20min against the previous 600s
# default, timing out symmetrically on candidate and production alike (Story
# 6.6 evidence). 1200s covers the observed runtime for full-scenario gates.
DEFAULT_ITEM_TIMEOUT_SECONDS = 1200.0
# Stage isolation only runs one chain segment — the smaller pre-6.6 default still fits (AC5).
DEFAULT_STAGE_TIMEOUT_SECONDS = 600.0
ARTIFACT_ROOT = Path(__file__).parent.parent / "tmp" / "eval-prompts"
CACHE_ROOT = ARTIFACT_ROOT / "cache"

# Settings.deepseek_max_tokens' own default — truncation-prone for the scenario chain (AC6).
_RISKY_DEFAULT_MAX_TOKENS = 8192
# Minimum safe value for a full-scenario promotion gate (AC5) — not just "not the default",
# since any value below this still truncates visual_breakdown.
_MIN_MAX_TOKENS_FOR_PROMOTION = 16000


def _new_run_dir(*parts: str) -> Path:
    return ARTIFACT_ROOT / "-".join((time.strftime("%Y%m%d-%H%M%S"), str(time.time_ns()), *parts))


def positive_timeout(value: str) -> float:
    timeout = float(value)
    if timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be greater than 0")
    return timeout


def positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return n


# ── tiered profile resolution (Story 6.6, AC1-3, AC6) ───────────────────────
#
# Pure CLI/config helper: no --profile is a no-op (backward-compatible
# promotion-shaped behavior, AC1). "smoke" is a fast one-canary iteration gate
# that never authorizes promotion (AC2, AC4). "promotion" is the only profile
# whose PASS may move the production label — it always runs all three golden
# items against candidate-vs-production and rejects any diagnostic narrowing
# (AC3, AC6).


@dataclass
class ResolvedProfile:
    label: str | None
    baseline: str | None
    scp_id: str | None
    stage: str
    timeout: float
    authority_note: str | None  # non-None only for a profile that is NOT promotion authority
    reps: int  # generation repetitions the gate medians over (Story 6.10)


def resolve_profile(
    profile: str | None,
    *,
    label: str | None,
    baseline: str | None,
    scp_id: str | None,
    stage: str,
    timeout: float | None,
    reps: int | None = None,
) -> ResolvedProfile:
    default_timeout = DEFAULT_STAGE_TIMEOUT_SECONDS if stage != "full" else DEFAULT_ITEM_TIMEOUT_SECONDS
    resolved_timeout = timeout if timeout is not None else default_timeout

    if profile is None:
        return ResolvedProfile(label, baseline, scp_id, stage, resolved_timeout, authority_note=None, reps=reps or 1)

    if profile == "promotion":
        if scp_id is not None:
            raise ValueError("--profile promotion rejects --scp-id: all three golden items are mandatory (AC3)")
        if stage != "full":
            raise ValueError("--profile promotion rejects --stage isolation: it is diagnostic-only, never promotion authority (AC6)")
        label = label or "candidate"
        baseline = baseline or "production"
        if label != "candidate" or baseline != "production":
            raise ValueError("--profile promotion only supports --label candidate --baseline production (AC3)")
        reps = reps or PROMOTION_REPS
        if reps < PROMOTION_REPS:
            raise ValueError(
                f"--profile promotion requires --reps >= {PROMOTION_REPS} — the median gate needs "
                f"enough trials to absorb generation noise (Story 6.10, AC1)"
            )
        return ResolvedProfile(label, baseline, None, stage, resolved_timeout, authority_note=None, reps=reps)

    # profile == "smoke"
    label = label or "candidate"
    scp_id = scp_id or SMOKE_DEFAULT_SCP_ID
    return ResolvedProfile(label, baseline, scp_id, stage, resolved_timeout, authority_note=NOT_A_PROMOTION_GATE, reps=reps or 1)


def prompt_variant_for_label(label: str) -> str | None:
    if label == "candidate":
        return "B"
    if label == "production":
        return None
    raise ValueError(f"Only production/candidate labels are supported by Prompt Policy, got {label!r}")


def load_golden_scps() -> dict[str, str]:
    scps = {s["id"]: s["scp_text"] for s in json.loads(SCPS_PATH.read_text(encoding="utf-8"))}
    missing = [scp_id for scp_id in GOLDEN_IDS if scp_id not in scps]
    if missing:
        raise SystemExit(f"golden SCPs missing from {SCPS_PATH}: {missing}")
    return {scp_id: scps[scp_id] for scp_id in GOLDEN_IDS}


def seed_dataset(client, dataset_name: str = DATASET_NAME) -> None:
    """Idempotent: ``create_dataset``/``create_dataset_item`` upsert by name/id (AC1)."""
    client.create_dataset(name=dataset_name, description="Story 6.2 fixed SCP inputs for offline prompt regression eval")
    for scp_id, scp_text in load_golden_scps().items():
        client.create_dataset_item(dataset_name=dataset_name, id=scp_id, input={"scp_id": scp_id, "scp_text": scp_text})


# ── stage-call cache (Story 6.13) ───────────────────────────────────────────
#
# Keyed on the exact rendered prompt text + model name (AC1, AC3) — this is
# strictly what changes whenever a Langfuse prompt version or a variable
# changes, so it's a stronger, simpler key than a separate version field
# (see Dev Notes). Local JSON files under CACHE_ROOT; no TTL/eviction (YAGNI —
# entries only grow when a prompt's rendered text actually changes).


def _cache_key(rendered: str, provider: str, model: str, max_tokens: int) -> str:
    # max_tokens is part of the actual request body (scenario.py's provider calls)
    # and directly governs truncation (_RISKY_DEFAULT_MAX_TOKENS below) — omitting
    # it would let a max-tokens bump meant to fix a truncated response instead
    # silently replay the old truncated cache entry.
    #
    # `provider` is in the key even though model names already differ between
    # DeepSeek and Gemini (Story 12.2 AC9): the rendered prompt text is identical
    # across providers for a stage, so an operator pinning both to the same model
    # string would otherwise collide two providers' answers into one entry.
    return hashlib.sha256(f"{rendered}\0{provider}\0{model}\0{max_tokens}".encode()).hexdigest()


def _cache_get(key: str) -> tuple[str, dict, str | None] | None:
    path = CACHE_ROOT / f"{key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["raw"], data["usage"], data["finish_reason"]
    except (json.JSONDecodeError, KeyError):
        return None  # partial/corrupt write (e.g. process killed mid-run) — treat as a miss


def _cache_put(key: str, raw: str, usage: dict, finish_reason: str | None) -> None:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    path = CACHE_ROOT / f"{key}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"raw": raw, "usage": usage, "finish_reason": finish_reason}, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)  # atomic on POSIX — a reader never observes a partially-written file


def _cached_call(provider: str, call):
    """Wraps a ``call(rendered, s) -> (raw, usage, finish_reason)`` provider callable
    with the stage cache. Model name + max_tokens come from the ``s`` argument each
    call already carries (AC1) — never constructs its own ``Settings()``. Caches the
    real call's result unconditionally, including a truncated (finish_reason ==
    "length") one, so a cached truncation replays the same downstream
    ``TruncationError`` deterministically.

    ``provider`` is "deepseek" or "gemini" and selects which pinned model/token
    settings identify the entry — the same two values the real request body carries.
    """

    def _identity(s) -> tuple[str, int]:
        if provider == "gemini":
            return s.gemini_writing_model, s.gemini_writing_max_tokens
        return s.deepseek_model, s.deepseek_max_tokens

    async def wrapper(rendered, s):
        model, max_tokens = _identity(s)
        key = _cache_key(rendered, provider, model, max_tokens)
        cached = _cache_get(key)
        if cached is not None:
            return cached
        raw, usage, finish_reason = await call(rendered, s)
        _cache_put(key, raw, usage, finish_reason)
        return raw, usage, finish_reason

    return wrapper


# ── scenario task + scoring evaluator ───────────────────────────────────────


async def _run_scenario(
    item, label: str, *, timeout: float = DEFAULT_ITEM_TIMEOUT_SECONDS, no_cache: bool = False
) -> dict:
    """Runs scenario_node and folds in the per-stage token/cache metadata Story 6.3
    added to `_record_trace` — captured here (not read back from Langfuse) so evidence
    survives even for a PASSING item, which `write_artifact` used to skip entirely."""
    state = {
        "run_id": f"offline-eval-{label}-{item.input['scp_id']}",
        "scp_id": item.input["scp_id"],
        "scp_text": item.input["scp_text"],
        "scenes": [],
        "video_path": None,
        "current_stage": "scenario",
        "gate_states": {},
        "prompt_variant": prompt_variant_for_label(label),
        "error": None,
    }
    stages: list[dict] = []
    # scenario_node's internal *_step calls reference scenario.py's module-level
    # `_call_deepseek` / `_call_gemini` by name directly (no injectable parameter) —
    # the only seam available without touching scenario.py/scenario_chain.py (AC5, AC6).
    # Story 12.2: BOTH seams are wrapped, so the cache covers the whole run and
    # production's provider routing is unchanged by the caching.
    #
    # evaluate_label() runs several _run_scenario calls concurrently
    # (max_concurrency), all sharing these module attributes. Set/restore
    # always relative to the fixed callables imported at module load
    # (never whatever the attribute currently holds) so an overlapping task's
    # finally-restore can never leave the module stuck on a stale wrapper —
    # worst case under interleaving is an occasional missed cache hit (a wasted
    # real call), never corruption or a permanently-patched module.
    # ponytail: doesn't eliminate every interleaving race, just its unsafe
    # outcomes; add a lock around the patch window if a real bug surfaces.
    if not no_cache:
        scenario_module._call_deepseek = _cached_call("deepseek", _call_deepseek)
        scenario_module._call_gemini = _cached_call("gemini", _call_gemini)
    try:
        out = await asyncio.wait_for(scenario_node(state, trace_sink=stages), timeout=timeout)
    except TimeoutError:
        out = {"scenes": [], "current_stage": "scenario", "error": f"timeout after {timeout:.0f}s"}
    finally:
        scenario_module._call_deepseek = _call_deepseek
        scenario_module._call_gemini = _call_gemini
    return {**out, "stages": stages}


def _rule_metrics(scenes: list[dict]) -> dict[str, float]:
    shot_counts = [len(sc["shots"]) for sc in scenes]
    return {
        "scene_count": len(scenes),
        "shot_count": sum(shot_counts),
        "empty_narration_count": sum(1 for sc in scenes if not sc["narration"].strip()),
        "empty_image_prompt_count": sum(1 for sc in scenes for sh in sc["shots"] if not sh["image_prompt"].strip()),
        "avg_shots_per_scene": statistics.fmean(shot_counts) if shot_counts else 0.0,
    }


def _failed(comment: str) -> list[Evaluation]:
    return [Evaluation(name="failed", value=True, data_type="BOOLEAN", comment=comment)]


async def _score_evaluator(*, input, output, expected_output=None, metadata=None) -> list[Evaluation]:
    if output.get("error"):
        return _failed(output["error"])
    scenes = output.get("scenes")
    if not scenes:
        return _failed("scenario produced no scenes")
    try:
        axis_scores = await _score_run(input["scp_text"], "\n\n".join(sc["narration"] for sc in scenes), Settings())
    except Exception as exc:  # judge timeout/parse errors are a failed item, not a crashed run (AC7)
        return _failed(f"scoring failed: {exc}")
    evals = [Evaluation(name=axis, value=getattr(axis_scores, axis)) for axis in AXES]
    evals.append(Evaluation(name="total", value=axis_scores.total))
    evals.extend(Evaluation(name=name, value=value) for name, value in _rule_metrics(scenes).items())
    evals.extend(_archetype_evaluations(output))
    return evals


# Story 12.4: the selected archetype, observed — informational in the current DEV
# MODE, deliberately NOT part of winner selection (one episode correctly has ONE
# template, so a different choice is not a regression).
_CATEGORICAL_METRICS = ("story_archetype",)


def _archetype_evaluations(output: dict) -> list[Evaluation]:
    """Categorical selection + the two deterministic booleans (AC6).

    ``story_archetype_fallback_used`` is not redundant with ``_valid``: validity is
    measured AFTER resolution, so it is always true and on its own would hide a
    selector that has silently stopped selecting.
    """
    archetype = output.get("story_archetype")
    return [
        Evaluation(name="story_archetype", value=str(archetype or ""), data_type="CATEGORICAL"),
        Evaluation(name="story_archetype_valid", value=archetype in STORY_ARCHETYPES, data_type="BOOLEAN"),
        Evaluation(
            name="story_archetype_fallback_used",
            value=bool(output.get("story_archetype_fallback_used")),
            data_type="BOOLEAN",
        ),
    ]


# ── per-item results + label evaluation ─────────────────────────────────────


@dataclass
class ItemResult:
    scp_id: str
    failed: bool
    error: str | None = None
    axes: dict[str, float] = field(default_factory=dict)
    total: float | None = None
    rule_metrics: dict[str, float] = field(default_factory=dict)
    # Story 12.4 — the categorical selection lives in its own field, never in the
    # numeric `rule_metrics` dict that median/delta arithmetic iterates over.
    story_archetype: str | None = None
    artifact_path: str | None = None
    parsed_state: object = None
    # Populated only by aggregate_runs (Story 6.10) — a single run leaves the
    # defaults, so every existing single-run caller is unaffected.
    n_runs: int = 1
    n_failed_runs: int = 0
    failed_run_reasons: list[str] = field(default_factory=list)
    # Ordered raw trials retained by aggregate_runs so compare() can take the
    # median of paired candidate-vs-baseline deltas (not a difference of medians).
    run_results: list["ItemResult"] = field(default_factory=list, repr=False)


def write_artifact(
    run_dir: Path,
    *,
    label: str,
    scp_id: str,
    stage: str,
    error: str | None,
    finish_reason: str | None = None,
    raw_output: str | None = None,
    parsed_state: object = None,
) -> Path:
    """Local debug artifact for an item/stage (AC3), written for every item (pass or fail) so
    Story 6.3's token/cache fields survive the process. Never committed — tmp/ is git-ignored."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{label}-{scp_id}-{stage}.json"
    path.write_text(
        json.dumps(
            {
                "label": label,
                "scp_id": scp_id,
                "stage": stage,
                "finish_reason": finish_reason,
                "error": error,
                "raw_output": raw_output,
                "parsed_state": parsed_state,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return path


def _to_item_result(item_result) -> ItemResult:
    scp_id = item_result.item.input["scp_id"]
    by_name = {ev.name: ev for ev in item_result.evaluations}
    output = getattr(item_result, "output", None)
    if "failed" in by_name:
        return ItemResult(scp_id, failed=True, error=by_name["failed"].comment, parsed_state=output)
    if "total" not in by_name or any(ax not in by_name for ax in AXES):
        # real Langfuse SDK swallows an evaluator exception into evaluations=[] for the item
        return ItemResult(scp_id, failed=True, error="evaluator produced no scores", parsed_state=output)
    axes = {ax: by_name[ax].value for ax in AXES}
    rule_metrics = {
        name: ev.value for name, ev in by_name.items()
        if name not in AXES and name != "total" and name not in _CATEGORICAL_METRICS
    }
    archetype = by_name["story_archetype"].value if "story_archetype" in by_name else None
    # parsed_state carries `stages` (Story 6.3 token/cache fields) through to write_artifact
    # even on a pass — evidence used to be discarded here for every non-failing item.
    return ItemResult(
        scp_id, failed=False, axes=axes, total=by_name["total"].value, rule_metrics=rule_metrics,
        story_archetype=archetype or None, parsed_state=output,
    )


def evaluate_label(
    client,
    dataset_name: str,
    label: str,
    *,
    max_concurrency: int = 3,
    scp_id: str | None = None,
    timeout: float = DEFAULT_ITEM_TIMEOUT_SECONDS,
    run_dir: Path | None = None,
    no_cache: bool = False,
) -> list[ItemResult]:
    dataset = client.get_dataset(dataset_name)
    if scp_id:
        dataset = copy.copy(dataset)
        dataset.items = [item for item in dataset.items if item.input["scp_id"] == scp_id]

    async def _task(*, item):
        return await _run_scenario(item, label, timeout=timeout, no_cache=no_cache)

    result = dataset.run_experiment(
        name=f"golden-eval-{label}",
        task=_task,
        evaluators=[_score_evaluator],
        max_concurrency=max_concurrency,
    )
    items = [_to_item_result(ir) for ir in result.item_results]
    if run_dir:
        for r in items:
            # Written for every item, not only failures — parsed_state.stages (Story 6.3)
            # is the only place prompt_cache_hit_tokens survives after this process exits;
            # Langfuse's own trace for this run is not reliably time-correlatable after the fact.
            r.artifact_path = str(write_artifact(
                run_dir, label=label, scp_id=r.scp_id, stage="full", error=r.error, parsed_state=r.parsed_state,
            ))
    return items


# ── stage isolation (AC2) ────────────────────────────────────────────────────
#
# Diagnostic-only path: calls the scenario_chain step functions directly
# (bypassing scenario_node's black-box error handling and Langfuse scoring)
# so a failure can be attributed to one real stage. Earlier stages run for
# real as prerequisites; only the first scene is carried into
# cast_decision/visual_breakdown — enough to reproduce a single-shot failure
# without scenario_node's full per-scene asyncio.gather fan-out.


@dataclass
class StageResult:
    scp_id: str
    stage: str
    failed: bool
    error: str | None = None
    artifact_path: str | None = None


async def _run_stage_chain(
    scp_id: str, scp_text: str, label: str, stage: str, s: Settings, timeout: float, *, no_cache: bool = False
) -> tuple[bool, str, str | None, str | None, str | None]:
    """Returns (failed, actual_stage, error, finish_reason, raw_output) — finish_reason/raw_output
    come from the last provider call made before failure (AC3).

    Story 12.2: each stage gets the provider that owns it in production, so an
    isolated ``writing`` run reproduces a real writing failure (Gemini) rather than
    a DeepSeek one. Earlier stages still run for real as prerequisites, which means
    a ``writing`` run does make DeepSeek research/structure calls — the *writing
    call itself* is the one that must never reach DeepSeek.
    """
    chain_label = "candidate" if label == "candidate" else None
    last_raw: str | None = None
    last_finish_reason: str | None = None
    current_stage = "format_guide"
    # `_call_deepseek`/`_call_gemini` resolve the module globals at this call's entry
    # (not at import time), so a test's monkeypatch.setattr(ep, "_call_gemini", ...)
    # done before invoking _run_stage_chain is honored (AC7); they are then fixed for
    # the duration of this one run, not re-resolved per stage.
    deepseek_call = _call_deepseek if no_cache else _cached_call("deepseek", _call_deepseek)
    gemini_call = _call_gemini if no_cache else _cached_call("gemini", _call_gemini)

    def _recorder(call):
        async def _recording_call(rendered, settings):
            nonlocal last_raw, last_finish_reason
            raw, usage, finish_reason = await call(rendered, settings)
            last_raw, last_finish_reason = raw, finish_reason
            return raw, usage, finish_reason

        return _recording_call

    _recording_call = _recorder(deepseek_call)
    _recording_gemini_call = _recorder(gemini_call)

    async def _inner() -> None:
        nonlocal current_stage
        format_guide = (
            get_prompt_with_fallback("scenario/format_guide", label=chain_label)
            if chain_label
            else get_prompt("scenario/format_guide")
        ).compile()
        current_stage = "research"
        research = await research_step(scp_id, scp_text, format_guide, s, _recording_call, label=chain_label)
        current_stage = "structure"
        structure = await structure_step(
            scp_id, research, format_guide, s, _recording_call,
            # Same resolution rule as scenario_node: research owns the choice, this
            # stage only obeys it (Story 12.4).
            story_archetype=research.get("story_archetype") or STORY_ARCHETYPE_FALLBACK,
            label=chain_label,
        )
        current_stage = "writing"
        writing = await writing_step(
            scp_id, structure, research["frozen_descriptor"], format_guide, "", s,
            _recording_gemini_call, label=chain_label,
        )
        if stage == "writing":
            return
        scene = writing["scenes"][0]
        sentences = split_sentences(scene["narration"])
        current_stage = "cast_decision"
        cast_by_sentence = await cast_decision_step(scp_id, scene, sentences, s, _recording_call, label=chain_label)
        if stage == "cast_decision":
            return
        current_stage = "visual_breakdown"
        await visual_breakdown_step(
            scp_id, scene, sentences, cast_by_sentence, research["frozen_descriptor"],
            research.get("entity_sheet", ""), research.get("story_logline", ""), structure[0],
            s, _recording_call, label=chain_label,
        )

    try:
        await asyncio.wait_for(_inner(), timeout=timeout)
        return False, stage, None, None, None
    except TimeoutError:
        return True, current_stage, f"{current_stage}: timeout after {timeout:.0f}s", last_finish_reason, last_raw
    except Exception as exc:  # any stage-function ValueError/JSONDecodeError — isolate, don't crash the script
        return True, current_stage, str(exc), last_finish_reason, last_raw


def run_stage(
    client,
    dataset_name: str,
    label: str,
    stage: str,
    *,
    scp_id: str | None = None,
    timeout: float = DEFAULT_STAGE_TIMEOUT_SECONDS,
    run_dir: Path | None = None,
    no_cache: bool = False,
) -> list[StageResult]:
    dataset = client.get_dataset(dataset_name)
    items = [item for item in dataset.items if scp_id is None or item.input["scp_id"] == scp_id]
    s = Settings()
    results = []
    for item in items:
        item_scp_id = item.input["scp_id"]
        failed, actual_stage, error, finish_reason, raw = asyncio.run(
            _run_stage_chain(item_scp_id, item.input["scp_text"], label, stage, s, timeout, no_cache=no_cache)
        )
        artifact_path = None
        if failed and run_dir:
            artifact_path = str(write_artifact(
                run_dir, label=label, scp_id=item_scp_id, stage=actual_stage,
                error=error, finish_reason=finish_reason, raw_output=raw,
            ))
        results.append(StageResult(item_scp_id, actual_stage, failed, error, artifact_path))
    return results


def print_stage_report(label: str, stage: str, results: list[StageResult]) -> None:
    print(f"\n=== {label} stage={stage} (golden-set) ===")
    for r in results:
        status = f"FAILED stage={r.stage} — {r.error}" if r.failed else "OK"
        print(f"  {r.scp_id}: {status}")
        if r.artifact_path:
            print(f"    artifact: {r.artifact_path}")


# ── baseline comparison (AC6, AC8) ──────────────────────────────────────────

_VERDICT_RANK = {"PASS": 0, "INCONCLUSIVE": 1, "FAIL": 2}


def _is_infra_failure(error: str | None) -> bool:
    """A timeout is the one failure class `_run_scenario` produces that reflects
    infrastructure health rather than the prompt/model output (AC8)."""
    return bool(error) and "timeout" in error.lower()


def aggregate_runs(runs: list[list[ItemResult]]) -> list[ItemResult]:
    """Collapse N per-item eval runs into one median-based ItemResult per item
    (Story 6.10, AC1/AC2).

    Judge each item on the **median** of its *successful* runs, not the mean:
    a hard-failing run (AC2 — e.g. SCP-049's scoped-repair error) produces no
    score at all, and a median just drops that data point, whereas a mean would
    need a sentinel value that skews the result. An item is isolated as failed
    only when it fails in a **majority** of runs (``n_fail * 2 > reps``); a
    minority failure is recorded in ``n_failed_runs``/``failed_run_reasons`` but
    does not fail the gate — no silent truncation of coverage. Item order
    follows first appearance across the runs.
    """
    order: list[str] = []
    for run in runs:
        for r in run:
            if r.scp_id not in order:
                order.append(r.scp_id)

    reps = len(runs)
    aggregated: list[ItemResult] = []
    for scp_id in order:
        group: list[ItemResult] = []
        for index, run in enumerate(runs, start=1):
            matches = [r for r in run if r.scp_id == scp_id]
            if len(matches) == 1:
                group.append(matches[0])
            else:
                reason = "missing item result" if not matches else "duplicate item results"
                group.append(ItemResult(scp_id, failed=True, error=f"{reason} in run {index}"))
        successes = [r for r in group if not r.failed]
        reasons = [r.error or "unknown failure" for r in group if r.failed]
        n_fail = len(reasons)
        artifact = next((r.artifact_path for r in group if r.artifact_path), None)
        if n_fail * 2 > reps or not successes:
            aggregated.append(ItemResult(
                scp_id, failed=True,
                error=(reasons[0] if reasons else "no successful run"),
                artifact_path=artifact, n_runs=reps, n_failed_runs=n_fail, failed_run_reasons=reasons,
                run_results=group,
            ))
            continue
        axes = {ax: statistics.median(r.axes[ax] for r in successes) for ax in AXES}
        # Story 12.4: the categorical selection is REPORTED (mode of the successful
        # reps, ties resolving to first-observed), never averaged — `statistics.mode`
        # on strings, deliberately nowhere near the median/delta arithmetic above.
        observed = [r.story_archetype for r in successes if r.story_archetype]
        aggregated.append(ItemResult(
            scp_id, failed=False,
            axes=axes, total=statistics.median(r.total for r in successes if r.total is not None),
            story_archetype=statistics.mode(observed) if observed else None,
            artifact_path=artifact, n_runs=reps, n_failed_runs=n_fail, failed_run_reasons=reasons,
            run_results=group,
        ))
    return aggregated


def compare(candidate: list[ItemResult], baseline: list[ItemResult]) -> tuple[str, list[dict]]:
    if not candidate or not baseline:
        return "FAIL", [{"scp_id": "*", "status": "no results — dataset empty or run produced nothing"}]

    baseline_by_id = {r.scp_id: r for r in baseline}
    candidate_ids = {r.scp_id for r in candidate}
    rows: list[dict] = []
    verdict = "PASS"

    def _downgrade(new: str) -> None:
        nonlocal verdict
        if _VERDICT_RANK[new] > _VERDICT_RANK[verdict]:
            verdict = new

    for cand in candidate:
        base = baseline_by_id.get(cand.scp_id)
        if cand.failed or base is None or base.failed:
            # Both sides hitting the same infra failure class (e.g. timeout) is not
            # regression evidence — a broken baseline can't justify promoting the
            # candidate, but it also isn't proof the candidate itself regressed (AC8).
            symmetric_infra = (
                cand.failed and base is not None and base.failed
                and _is_infra_failure(cand.error) and _is_infra_failure(base.error)
            )
            status = "inconclusive infrastructure failure" if symmetric_infra else "item failure"
            _downgrade("INCONCLUSIVE" if symmetric_infra else "FAIL")
            rows.append({
                "scp_id": cand.scp_id,
                "status": status,
                "candidate_error": cand.error if cand.failed else None,
                "baseline_error": base.error if base and base.failed else ("missing baseline result" if base is None else None),
                "candidate_artifact": cand.artifact_path if cand.failed else None,
                "baseline_artifact": base.artifact_path if base and base.failed else None,
                "n_runs": cand.n_runs,
                "candidate_failed_runs": cand.n_failed_runs,
                "baseline_failed_runs": base.n_failed_runs if base else 0,
                "candidate_fail_reasons": cand.failed_run_reasons,
                "baseline_fail_reasons": base.failed_run_reasons if base else [],
            })
            continue

        paired = [
            (cand_run, base_run)
            for cand_run, base_run in zip(cand.run_results, base.run_results, strict=True)
            if not cand_run.failed and not base_run.failed
        ] if cand.run_results and base.run_results else []
        if cand.run_results and base.run_results and not paired:
            _downgrade("FAIL")
            rows.append({
                "scp_id": cand.scp_id,
                "status": "item failure",
                "candidate_error": "no paired successful runs",
                "baseline_error": None,
                "candidate_artifact": cand.artifact_path,
                "baseline_artifact": base.artifact_path,
                "n_runs": cand.n_runs,
                "candidate_failed_runs": cand.n_failed_runs,
                "baseline_failed_runs": base.n_failed_runs,
                "candidate_fail_reasons": cand.failed_run_reasons,
                "baseline_fail_reasons": base.failed_run_reasons,
            })
            continue
        if paired:
            deltas = {
                ax: statistics.median(c.axes[ax] - b.axes[ax] for c, b in paired)
                for ax in AXES
            }
            total_delta = statistics.median(c.total - b.total for c, b in paired)
        else:
            deltas = {ax: cand.axes[ax] - base.axes[ax] for ax in AXES}
            total_delta = cand.total - base.total
        regressed = any(d < 0 for d in deltas.values()) or total_delta < 0
        if regressed:
            _downgrade("FAIL")
        rows.append({
            "scp_id": cand.scp_id,
            "status": "regressed" if regressed else "ok",
            "deltas": deltas,
            "total_delta": total_delta,
            # Median-gate provenance (Story 6.10): a minority hard-fail on either
            # side is tolerated but must stay visible — no silent coverage loss.
            "n_runs": cand.n_runs,
            "candidate_failed_runs": cand.n_failed_runs,
            "baseline_failed_runs": base.n_failed_runs,
            "candidate_fail_reasons": cand.failed_run_reasons,
            "baseline_fail_reasons": base.failed_run_reasons,
        })

    for scp_id in sorted(set(baseline_by_id) - candidate_ids):
        _downgrade("FAIL")
        rows.append({"scp_id": scp_id, "status": "missing from candidate run"})

    return verdict, rows


def print_comparison(candidate_label: str, baseline_label: str, rows: list[dict], verdict: str) -> None:
    print(f"\n=== {candidate_label} vs {baseline_label} (golden-set) ===")
    for row in rows:
        if row["status"] in (
            "item failure", "missing from candidate run",
            "no results — dataset empty or run produced nothing", "inconclusive infrastructure failure",
        ):
            row_verdict = "INCONCLUSIVE" if row["status"] == "inconclusive infrastructure failure" else "FAIL"
            print(f"  {row['scp_id']}: {row_verdict} ({row['status']})")
            _print_run_provenance(row, candidate_label, baseline_label)
            if row.get("candidate_error"):
                print(f"    {candidate_label}: {row['candidate_error']}")
            if row.get("candidate_artifact"):
                print(f"    {candidate_label} artifact: {row['candidate_artifact']}")
            if row.get("baseline_error"):
                print(f"    {baseline_label}: {row['baseline_error']}")
            if row.get("baseline_artifact"):
                print(f"    {baseline_label} artifact: {row['baseline_artifact']}")
            continue
        deltas = ", ".join(f"{ax}={d:+.2f}" for ax, d in row["deltas"].items())
        n_runs = row.get("n_runs", 1)
        median_note = f" (median of {n_runs} runs)" if n_runs > 1 else ""
        print(f"  {row['scp_id']}: {row['status']:9s} {deltas}  total={row['total_delta']:+.2f}{median_note}")
        _print_run_provenance(row, candidate_label, baseline_label)
    print(f"\nVerdict: {verdict}")


def _print_run_provenance(row: dict, candidate_label: str, baseline_label: str) -> None:
    """Surface per-run hard-failures on either side (Story 6.10, AC2) so a
    minority failure the median tolerated is never silently dropped from the
    report."""
    if row.get("n_runs", 1) <= 1:
        return
    for side, label in (("candidate", candidate_label), ("baseline", baseline_label)):
        n_fail = row.get(f"{side}_failed_runs", 0)
        if n_fail:
            reasons = "; ".join(row.get(f"{side}_fail_reasons", []))
            print(f"    {label}: {n_fail}/{row['n_runs']} run(s) hard-failed — {reasons}")


def print_report(label: str, results: list[ItemResult]) -> None:
    print(f"\n=== {label} (golden-set) ===")
    for r in results:
        if r.failed:
            print(f"  {r.scp_id}: FAILED — {r.error}")
            if r.artifact_path:
                print(f"    artifact: {r.artifact_path}")
            continue
        axes = ", ".join(f"{ax}={v:.2f}" for ax, v in r.axes.items())
        metrics = ", ".join(f"{k}={v:.2f}" for k, v in r.rule_metrics.items())
        print(f"  {r.scp_id}: {axes}  total={r.total:.2f}")
        print(f"    rules: {metrics}")
        if r.story_archetype:
            # Observed distribution, not a score. Three golden SCPs cannot cover four
            # archetypes and are not asserted to — exhaustiveness is unit-tested.
            observed = [x.story_archetype for x in r.run_results if x.story_archetype]
            print(f"    story_archetype: {r.story_archetype}"
                  + (f" (observed: {', '.join(observed)})" if len(observed) > 1 else ""))


def write_profile_metadata(run_dir: Path, profile: str, authority_note: str | None) -> Path:
    """Persists which profile authorized this run and whether it may move the
    production label — separate from per-item artifacts so their schema stays
    unchanged (AC4)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "_profile.json"
    path.write_text(
        json.dumps({"profile": profile, "authority": authority_note or PROMOTION_GATE_AUTHORITY}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Golden-set offline prompt regression eval (Story 6.2/6.6)")
    ap.add_argument("--dataset", default=DATASET_NAME)
    ap.add_argument("--label", choices=LABELS)
    ap.add_argument("--baseline", choices=LABELS)
    ap.add_argument(
        "--profile", choices=PROFILES,
        help=(
            "smoke: one-canary fast iteration gate, never promotion authority. "
            "promotion: mandatory three-item candidate-vs-production gate. "
            "Omit for pre-6.6 backward-compatible behavior."
        ),
    )
    ap.add_argument("--seed", action="store_true", help="seed/update the golden dataset from data/scps.json")
    ap.add_argument("--max-concurrency", type=int, default=3)
    ap.add_argument("--scp-id", choices=GOLDEN_IDS, help="run only this golden SCP item")
    ap.add_argument(
        "--timeout", type=positive_timeout, default=None,
        help=(
            f"per-item timeout in seconds (default: {DEFAULT_ITEM_TIMEOUT_SECONDS:.0f} full scenario, "
            f"{DEFAULT_STAGE_TIMEOUT_SECONDS:.0f} stage isolation)"
        ),
    )
    ap.add_argument(
        "--stage", choices=STAGES, default="full",
        help="isolate a scenario stage failure instead of scoring a full run (default: full)",
    )
    ap.add_argument(
        "--reps", type=positive_int, default=None,
        help=(
            f"baseline comparison only: regenerate each item N times per label and judge on the "
            f"median delta (default: {PROMOTION_REPS} under --profile promotion, 1 otherwise). "
            "Absorbs run-to-run generation noise so a single noisy trial no longer fails the gate (Story 6.10)."
        ),
    )
    ap.add_argument(
        "--no-cache", action="store_true",
        help="bypass the golden-set stage cache entirely — no read, no write (Story 6.13, for suspected cache bugs)",
    )
    args = ap.parse_args(argv)

    try:
        resolved = resolve_profile(
            args.profile, label=args.label, baseline=args.baseline,
            scp_id=args.scp_id, stage=args.stage, timeout=args.timeout, reps=args.reps,
        )
    except ValueError as exc:
        ap.error(str(exc))
    args.label, args.baseline, args.scp_id, args.timeout = resolved.label, resolved.baseline, resolved.scp_id, resolved.timeout

    if args.baseline and not args.label:
        ap.error("--baseline requires --label")
    if args.label and args.baseline and args.label == args.baseline:
        ap.error("--label and --baseline must differ")
    if args.stage != "full" and args.baseline:
        ap.error("--stage isolation does not support --baseline comparison; run each label separately")

    # Story 6-12: A/B gate frozen during pipeline development. --baseline means a
    # candidate-vs-production comparison — the token-heavy A/B. Single-label and
    # --profile smoke (no --baseline) diagnostics stay open.
    #
    # 2026-07-12: an AI session ran this override mid-story on request, then had to be
    # stopped by Jay. This check is deliberately NOT overridable by any env var an AI
    # session could set for itself — if CLAUDECODE/AI_AGENT is present, --baseline is
    # refused outright, no exceptions, no matter what an AI session is instructed to do.
    if args.baseline and ("CLAUDECODE" in os.environ or "AI_AGENT" in os.environ):
        ap.error(
            "A/B candidate-vs-production gate cannot run inside an AI coding session "
            "(CLAUDECODE/AI_AGENT env detected) — this is unconditional, not an env-var "
            f"toggle an agent can flip for itself. Jay runs --baseline / {AB_GATE_OVERRIDE_ENV}=1 "
            "manually in a plain terminal outside any AI session."
        )
    if args.baseline and os.environ.get(AB_GATE_OVERRIDE_ENV) != "1":
        ap.error(
            "A/B candidate-vs-production gate is FROZEN during pipeline development "
            "(Story 6-12 / docs/PROMPT_POLICY.md). It burns heavy tokens and only matters "
            "for production-quality tuning, not pipeline completeness. "
            f"Set {AB_GATE_OVERRIDE_ENV}=1 to run it deliberately once the pipeline is complete. "
            "Single-label runs (--label X, no --baseline) and --profile smoke remain available."
        )

    # Story 12.2: the chain spans two providers, so the preflight has to check BOTH
    # budgets. Checking only DeepSeek's would leave writing/review/critic — the three
    # stages with the live truncation history — governed by an unvalidated knob.
    if args.profile == "promotion":
        s = Settings()
        for env_var, value in (
            ("YTFLOW_DEEPSEEK_MAX_TOKENS", s.deepseek_max_tokens),
            ("YTFLOW_GEMINI_WRITING_MAX_TOKENS", s.gemini_writing_max_tokens),
        ):
            if value < _MIN_MAX_TOKENS_FOR_PROMOTION:
                ap.error(
                    f"--profile promotion requires {env_var} >= {_MIN_MAX_TOKENS_FOR_PROMOTION} "
                    f"(currently {value}) — anything below that truncates a scenario stage "
                    "and can masquerade as a prompt regression (AC5)"
                )

    client = build_client()

    if args.seed:
        seed_dataset(client, args.dataset)
        print(f"seeded dataset {args.dataset!r} with {len(GOLDEN_IDS)} items")

    if not args.label:
        return 0

    if Settings().deepseek_max_tokens == _RISKY_DEFAULT_MAX_TOKENS:
        print(
            f"WARNING: YTFLOW_DEEPSEEK_MAX_TOKENS is at the default {_RISKY_DEFAULT_MAX_TOKENS} — "
            "stage truncation is likely; set YTFLOW_DEEPSEEK_MAX_TOKENS=16000 or higher for eval runs (AC6).",
            file=sys.stderr,
        )

    run_dir = _new_run_dir(*([args.label, args.baseline] if args.baseline else [args.label]))
    if args.profile:
        write_profile_metadata(run_dir, args.profile, resolved.authority_note)

    def _announce_authority() -> None:
        if resolved.authority_note:
            print(f"\n{resolved.authority_note} — health feedback only, does not authorize moving the production label.")

    if args.stage != "full":
        stage_results = run_stage(
            client, args.dataset, args.label, args.stage, scp_id=args.scp_id, timeout=args.timeout, run_dir=run_dir,
            no_cache=args.no_cache,
        )
        print_stage_report(args.label, args.stage, stage_results)
        _announce_authority()
        return 1 if not stage_results or any(r.failed for r in stage_results) else 0

    if not args.baseline:
        candidate = evaluate_label(
            client, args.dataset, args.label,
            max_concurrency=args.max_concurrency, scp_id=args.scp_id, timeout=args.timeout, run_dir=run_dir,
            no_cache=args.no_cache,
        )
        print_report(args.label, candidate)
        _announce_authority()
        return 1 if not candidate or any(r.failed for r in candidate) else 0

    reps = resolved.reps

    def _eval_reps(label: str) -> list[list[ItemResult]]:
        # reps==1 writes straight into run_dir (unchanged pre-6.10 layout); >1
        # gets a per-rep subdir so each regeneration's artifacts don't overwrite.
        if reps == 1:
            return [evaluate_label(
                client, args.dataset, label,
                max_concurrency=args.max_concurrency, scp_id=args.scp_id, timeout=args.timeout, run_dir=run_dir,
                no_cache=args.no_cache,
            )]
        # Each rep exists to draw an independent regeneration for the median-of-N
        # noise gate (Story 6.10) — serving rep 2..N from rep 1's cache entry would
        # collapse the whole sample to one draw and silently defeat the gate, so
        # this loop always bypasses the cache regardless of --no-cache.
        return [
            evaluate_label(
                client, args.dataset, label,
                max_concurrency=args.max_concurrency, scp_id=args.scp_id, timeout=args.timeout,
                run_dir=run_dir / f"{label}-rep{i + 1}",
                no_cache=True,
            )
            for i in range(reps)
        ]

    if reps > 1:
        print(f"\nStatistical gate: {reps} regenerations per label, median per-item delta (Story 6.10).")
    candidate = aggregate_runs(_eval_reps(args.label))
    baseline = aggregate_runs(_eval_reps(args.baseline))
    verdict, rows = compare(candidate, baseline)
    print_comparison(args.label, args.baseline, rows, verdict)
    _announce_authority()
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
