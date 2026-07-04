"""Unit tests for scripts/eval_prompts.py (Story 6.2).

No live Langfuse / DeepSeek: dataset ops go through an in-memory fake client,
scenario_node and the LLM judge are faked. Verifies the runner never touches
run_service, the LangGraph graph, DB, or FastAPI routes — it only imports
scenario_node and eval_service scoring primitives.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import eval_prompts as ep  # noqa: E402

from yt_flow.services.eval_service import AxisScores  # noqa: E402


# ── prompt_variant_for_label (AC2, AC3, AC8) ────────────────────────────────


def test_candidate_maps_to_variant_b():
    assert ep.prompt_variant_for_label("candidate") == "B"


def test_production_maps_to_no_variant():
    assert ep.prompt_variant_for_label("production") is None


def test_unsupported_label_rejected():
    with pytest.raises(ValueError):
        ep.prompt_variant_for_label("staging")


# ── Fakes ────────────────────────────────────────────────────────────────────


class FakeDatasetItem:
    def __init__(self, item_id, input_data):
        self.id = item_id
        self.input = input_data


class FakeDataset:
    """Mirrors the observable contract of langfuse.Dataset.run_experiment:
    calls task(item=item) then each evaluator(input=, output=, expected_output=,
    metadata=), both possibly async — same calling convention the real SDK uses."""

    def __init__(self, items):
        self.items = items

    def run_experiment(self, *, name, task, evaluators, max_concurrency=50, **_):
        import asyncio
        from types import SimpleNamespace

        async def _run():
            item_results = []
            for item in self.items:
                output = task(item=item)
                if asyncio.iscoroutine(output):
                    output = await output
                evaluations = []
                for ev in evaluators:
                    result = ev(input=item.input, output=output, expected_output=None, metadata=None)
                    if asyncio.iscoroutine(result):
                        result = await result
                    evaluations.extend(result if isinstance(result, list) else [result])
                item_results.append(SimpleNamespace(item=item, output=output, evaluations=evaluations))
            return SimpleNamespace(item_results=item_results)

        return asyncio.run(_run())


class FakeLangfuseClient:
    def __init__(self):
        self.datasets: dict[str, dict] = {}
        self.items: dict[str, dict[str, FakeDatasetItem]] = {}

    def create_dataset(self, *, name, description=None, metadata=None):
        self.datasets[name] = {"description": description, "metadata": metadata}

    def create_dataset_item(self, *, dataset_name, input, id, expected_output=None, metadata=None):
        self.items.setdefault(dataset_name, {})[id] = FakeDatasetItem(id, input)

    def get_dataset(self, name):
        return FakeDataset(list(self.items[name].values()))


# ── seed_dataset idempotency (AC1) ──────────────────────────────────────────


def test_seed_dataset_creates_all_golden_ids():
    client = FakeLangfuseClient()
    ep.seed_dataset(client)
    assert set(client.items[ep.DATASET_NAME]) == set(ep.GOLDEN_IDS)


def test_seed_dataset_is_idempotent_no_duplicates():
    client = FakeLangfuseClient()
    ep.seed_dataset(client)
    ep.seed_dataset(client)
    assert len(client.items[ep.DATASET_NAME]) == len(ep.GOLDEN_IDS)


# ── evaluate_label: scenario_node wiring (AC2, AC3) ─────────────────────────


def _wire_scenario_capturing_state(monkeypatch, captured, *, error=None, scenes=None):
    async def fake_scenario_node(state):
        captured.append(dict(state))
        if error:
            return {"current_stage": "scenario", "error": error}
        return {"scenes": scenes or [{"scene_num": 1, "narration": "hi", "shots": [{"image_prompt": "p"}]}],
                "current_stage": "scenario", "error": None}

    monkeypatch.setattr(ep, "scenario_node", fake_scenario_node)


def _wire_score_run(monkeypatch, axis_scores):
    async def fake_score_run(scp_text, artifact_text, settings):
        return axis_scores

    monkeypatch.setattr(ep, "_score_run", fake_score_run)


def _client_with_seeded_dataset():
    client = FakeLangfuseClient()
    ep.seed_dataset(client)
    return client


def test_evaluate_label_candidate_builds_variant_b_state(monkeypatch):
    captured = []
    _wire_scenario_capturing_state(monkeypatch, captured)
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    ep.evaluate_label(_client_with_seeded_dataset(), ep.DATASET_NAME, "candidate")

    assert all(s["prompt_variant"] == "B" for s in captured)
    assert {s["scp_id"] for s in captured} == set(ep.GOLDEN_IDS)


def test_evaluate_label_production_builds_no_variant_state(monkeypatch):
    captured = []
    _wire_scenario_capturing_state(monkeypatch, captured)
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    ep.evaluate_label(_client_with_seeded_dataset(), ep.DATASET_NAME, "production")

    assert all(s["prompt_variant"] is None for s in captured)


def test_evaluate_label_never_touches_run_service_or_db(monkeypatch):
    # ep.py has no import of run_service/graph/db/FastAPI — this just proves the
    # scenario path used here is the direct fake, not a real pipeline run.
    captured = []
    _wire_scenario_capturing_state(monkeypatch, captured)
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    results = ep.evaluate_label(_client_with_seeded_dataset(), ep.DATASET_NAME, "production")

    assert len(results) == len(ep.GOLDEN_IDS)
    assert all(not r.failed for r in results)


def test_evaluate_label_records_axis_and_total_scores(monkeypatch):
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(atmosphere=5, narrative_coherence=4, article_fidelity=3, total=12))

    results = ep.evaluate_label(_client_with_seeded_dataset(), ep.DATASET_NAME, "production")

    r = results[0]
    assert r.axes == {"atmosphere": 5, "narrative_coherence": 4, "article_fidelity": 3}
    assert r.total == 12


def test_evaluate_label_computes_rule_metrics():
    scenes = [
        {"scene_num": 1, "narration": "a", "shots": [{"image_prompt": "x"}, {"image_prompt": "y"}]},
        {"scene_num": 2, "narration": "", "shots": [{"image_prompt": ""}]},
    ]
    metrics = ep._rule_metrics(scenes)
    assert metrics["scene_count"] == 2
    assert metrics["shot_count"] == 3
    assert metrics["empty_narration_count"] == 1
    assert metrics["empty_image_prompt_count"] == 1
    assert metrics["avg_shots_per_scene"] == 1.5


# ── item failure handling (AC7) ──────────────────────────────────────────────


def test_scenario_failure_marks_item_failed_and_continues(monkeypatch):
    captured = []
    _wire_scenario_capturing_state(monkeypatch, captured, error="boom")
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    results = ep.evaluate_label(_client_with_seeded_dataset(), ep.DATASET_NAME, "production")

    assert len(results) == len(ep.GOLDEN_IDS)  # loop continued for every item
    assert all(r.failed for r in results)
    assert all(r.error == "boom" for r in results)


# ── baseline comparison + verdict (AC6) ─────────────────────────────────────


def _ok(scp_id, atmosphere, narrative_coherence, article_fidelity):
    total = atmosphere + narrative_coherence + article_fidelity
    return ep.ItemResult(
        scp_id, failed=False,
        axes={"atmosphere": atmosphere, "narrative_coherence": narrative_coherence, "article_fidelity": article_fidelity},
        total=total,
    )


def test_compare_passes_when_candidate_matches_or_beats_baseline():
    candidate = [_ok("SCP-096", 4, 4, 4)]
    baseline = [_ok("SCP-096", 4, 4, 4)]
    verdict, rows = ep.compare(candidate, baseline)
    assert verdict == "PASS"
    assert rows[0]["status"] == "ok"


def test_compare_fails_on_any_axis_regression():
    candidate = [_ok("SCP-096", 3, 4, 4)]  # atmosphere dropped
    baseline = [_ok("SCP-096", 4, 4, 4)]
    verdict, rows = ep.compare(candidate, baseline)
    assert verdict == "FAIL"
    assert rows[0]["status"] == "regressed"


def test_compare_fails_when_candidate_item_failed():
    candidate = [ep.ItemResult("SCP-096", failed=True, error="boom")]
    baseline = [_ok("SCP-096", 4, 4, 4)]
    verdict, rows = ep.compare(candidate, baseline)
    assert verdict == "FAIL"
    assert rows[0]["status"] == "item failure"


def test_compare_fails_when_baseline_item_failed():
    candidate = [_ok("SCP-096", 4, 4, 4)]
    baseline = [ep.ItemResult("SCP-096", failed=True, error="boom")]
    verdict, rows = ep.compare(candidate, baseline)
    assert verdict == "FAIL"
    assert rows[0]["status"] == "item failure"


# ── CLI exit codes ───────────────────────────────────────────────────────────


def test_main_exits_nonzero_on_item_failure(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    _wire_scenario_capturing_state(monkeypatch, [], error="boom")
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    assert ep.main(["--label", "production"]) == 1


def test_main_exits_zero_when_all_items_pass(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    assert ep.main(["--label", "production"]) == 0


def test_main_baseline_mode_exits_nonzero_on_regression(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    _wire_scenario_capturing_state(monkeypatch, [])

    calls = {"n": 0}

    async def fake_score_run(scp_text, artifact_text, settings):
        calls["n"] += 1
        # First label evaluated (candidate) scores lower than the second (production).
        return AxisScores(3, 4, 4, 11) if calls["n"] <= len(ep.GOLDEN_IDS) else AxisScores(4, 4, 4, 12)

    monkeypatch.setattr(ep, "_score_run", fake_score_run)

    assert ep.main(["--label", "candidate", "--baseline", "production"]) == 1


def test_main_seed_only_exits_zero(monkeypatch):
    client = FakeLangfuseClient()
    monkeypatch.setattr(ep, "build_client", lambda: client)

    assert ep.main(["--seed"]) == 0
    assert set(client.items[ep.DATASET_NAME]) == set(ep.GOLDEN_IDS)