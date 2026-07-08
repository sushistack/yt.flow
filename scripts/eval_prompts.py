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
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from langfuse import Evaluation  # noqa: E402

from yt_flow.config import Settings  # noqa: E402
from yt_flow.pipeline.nodes.scenario import scenario_node  # noqa: E402
from yt_flow.services.eval_service import AXES, _score_run  # noqa: E402
from yt_flow.services.prompt_service import build_client  # noqa: E402

DATASET_NAME = "golden-scps"
GOLDEN_IDS = ("SCP-096", "SCP-173", "SCP-049")
SCPS_PATH = Path(__file__).parent.parent / "data" / "scps.json"
LABELS = ("production", "candidate")


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


# ── scenario task + scoring evaluator ───────────────────────────────────────


async def _run_scenario(item, label: str) -> dict:
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
    return await scenario_node(state)


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
    return evals


# ── per-item results + label evaluation ─────────────────────────────────────


@dataclass
class ItemResult:
    scp_id: str
    failed: bool
    error: str | None = None
    axes: dict[str, float] = field(default_factory=dict)
    total: float | None = None
    rule_metrics: dict[str, float] = field(default_factory=dict)


def _to_item_result(item_result) -> ItemResult:
    scp_id = item_result.item.input["scp_id"]
    by_name = {ev.name: ev for ev in item_result.evaluations}
    if "failed" in by_name:
        return ItemResult(scp_id, failed=True, error=by_name["failed"].comment)
    if "total" not in by_name or any(ax not in by_name for ax in AXES):
        # real Langfuse SDK swallows an evaluator exception into evaluations=[] for the item
        return ItemResult(scp_id, failed=True, error="evaluator produced no scores")
    axes = {ax: by_name[ax].value for ax in AXES}
    rule_metrics = {name: ev.value for name, ev in by_name.items() if name not in AXES and name != "total"}
    return ItemResult(scp_id, failed=False, axes=axes, total=by_name["total"].value, rule_metrics=rule_metrics)


def evaluate_label(client, dataset_name: str, label: str, *, max_concurrency: int = 3) -> list[ItemResult]:
    dataset = client.get_dataset(dataset_name)

    async def _task(*, item):
        return await _run_scenario(item, label)

    result = dataset.run_experiment(
        name=f"golden-eval-{label}",
        task=_task,
        evaluators=[_score_evaluator],
        max_concurrency=max_concurrency,
    )
    return [_to_item_result(ir) for ir in result.item_results]


# ── baseline comparison (AC6) ────────────────────────────────────────────────


def compare(candidate: list[ItemResult], baseline: list[ItemResult]) -> tuple[str, list[dict]]:
    if not candidate or not baseline:
        return "FAIL", [{"scp_id": "*", "status": "no results — dataset empty or run produced nothing"}]

    baseline_by_id = {r.scp_id: r for r in baseline}
    candidate_ids = {r.scp_id for r in candidate}
    rows: list[dict] = []
    verdict = "PASS"

    for cand in candidate:
        base = baseline_by_id.get(cand.scp_id)
        if cand.failed or base is None or base.failed:
            verdict = "FAIL"
            rows.append({
                "scp_id": cand.scp_id,
                "status": "item failure",
                "candidate_error": cand.error if cand.failed else None,
                "baseline_error": base.error if base and base.failed else ("missing baseline result" if base is None else None),
            })
            continue

        deltas = {ax: cand.axes[ax] - base.axes[ax] for ax in AXES}
        total_delta = cand.total - base.total
        regressed = any(d < 0 for d in deltas.values()) or total_delta < 0
        if regressed:
            verdict = "FAIL"
        rows.append({
            "scp_id": cand.scp_id,
            "status": "regressed" if regressed else "ok",
            "deltas": deltas,
            "total_delta": total_delta,
        })

    for scp_id in sorted(set(baseline_by_id) - candidate_ids):
        verdict = "FAIL"
        rows.append({"scp_id": scp_id, "status": "missing from candidate run"})

    return verdict, rows


def print_comparison(candidate_label: str, baseline_label: str, rows: list[dict], verdict: str) -> None:
    print(f"\n=== {candidate_label} vs {baseline_label} (golden-set) ===")
    for row in rows:
        if row["status"] in ("item failure", "missing from candidate run", "no results — dataset empty or run produced nothing"):
            print(f"  {row['scp_id']}: FAIL ({row['status']})")
            if row.get("candidate_error"):
                print(f"    {candidate_label}: {row['candidate_error']}")
            if row.get("baseline_error"):
                print(f"    {baseline_label}: {row['baseline_error']}")
            continue
        deltas = ", ".join(f"{ax}={d:+.2f}" for ax, d in row["deltas"].items())
        print(f"  {row['scp_id']}: {row['status']:9s} {deltas}  total={row['total_delta']:+.2f}")
    print(f"\nVerdict: {verdict}")


def print_report(label: str, results: list[ItemResult]) -> None:
    print(f"\n=== {label} (golden-set) ===")
    for r in results:
        if r.failed:
            print(f"  {r.scp_id}: FAILED — {r.error}")
            continue
        axes = ", ".join(f"{ax}={v:.2f}" for ax, v in r.axes.items())
        metrics = ", ".join(f"{k}={v:.2f}" for k, v in r.rule_metrics.items())
        print(f"  {r.scp_id}: {axes}  total={r.total:.2f}")
        print(f"    rules: {metrics}")


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Golden-set offline prompt regression eval (Story 6.2)")
    ap.add_argument("--dataset", default=DATASET_NAME)
    ap.add_argument("--label", choices=LABELS)
    ap.add_argument("--baseline", choices=LABELS)
    ap.add_argument("--seed", action="store_true", help="seed/update the golden dataset from data/scps.json")
    ap.add_argument("--max-concurrency", type=int, default=3)
    args = ap.parse_args(argv)

    if args.baseline and not args.label:
        ap.error("--baseline requires --label")
    if args.label and args.baseline and args.label == args.baseline:
        ap.error("--label and --baseline must differ")

    client = build_client()

    if args.seed:
        seed_dataset(client, args.dataset)
        print(f"seeded dataset {args.dataset!r} with {len(GOLDEN_IDS)} items")

    if not args.label:
        return 0

    candidate = evaluate_label(client, args.dataset, args.label, max_concurrency=args.max_concurrency)

    if not args.baseline:
        print_report(args.label, candidate)
        return 1 if not candidate or any(r.failed for r in candidate) else 0

    baseline = evaluate_label(client, args.dataset, args.baseline, max_concurrency=args.max_concurrency)
    verdict, rows = compare(candidate, baseline)
    print_comparison(args.label, args.baseline, rows, verdict)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
