"""Unit tests for scripts/eval_prompts.py (Story 6.2).

No live Langfuse / DeepSeek: dataset ops go through an in-memory fake client,
scenario_node and the LLM judge are faked. Verifies the runner never touches
run_service, the LangGraph graph, DB, or FastAPI routes — it only imports
scenario_node and eval_service scoring primitives.
"""

import json
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
                    try:
                        result = ev(input=item.input, output=output, expected_output=None, metadata=None)
                        if asyncio.iscoroutine(result):
                            result = await result
                    except Exception:
                        # real SDK: an evaluator that raises yields no evaluations for that item
                        continue
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
    async def fake_scenario_node(state, *, trace_sink=None):
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


def test_evaluate_label_filters_to_scp_id(monkeypatch):
    captured = []
    _wire_scenario_capturing_state(monkeypatch, captured)
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    results = ep.evaluate_label(_client_with_seeded_dataset(), ep.DATASET_NAME, "production", scp_id="SCP-049")

    assert {s["scp_id"] for s in captured} == {"SCP-049"}
    assert {r.scp_id for r in results} == {"SCP-049"}


def test_evaluate_label_scp_filter_does_not_mutate_dataset(monkeypatch):
    captured = []
    _wire_scenario_capturing_state(monkeypatch, captured)
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))
    dataset = _client_with_seeded_dataset().get_dataset(ep.DATASET_NAME)

    class ReusedDatasetClient:
        def get_dataset(self, name):
            return dataset

    ep.evaluate_label(ReusedDatasetClient(), ep.DATASET_NAME, "production", scp_id="SCP-049")
    ep.evaluate_label(ReusedDatasetClient(), ep.DATASET_NAME, "production")

    assert [s["scp_id"] for s in captured].count("SCP-049") == 2
    assert {s["scp_id"] for s in captured[-len(ep.GOLDEN_IDS):]} == set(ep.GOLDEN_IDS)


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


# ── per-item timeout (AC4) ───────────────────────────────────────────────────


def test_run_scenario_times_out(monkeypatch):
    import asyncio

    async def slow_scenario_node(state, *, trace_sink=None):
        await asyncio.sleep(10)
        return {"scenes": [], "current_stage": "scenario", "error": None}

    monkeypatch.setattr(ep, "scenario_node", slow_scenario_node)

    item = FakeDatasetItem("SCP-096", {"scp_id": "SCP-096", "scp_text": "x"})
    result = asyncio.run(ep._run_scenario(item, "production", timeout=0.05))

    assert result["scenes"] == []
    assert "timeout" in result["error"].lower()


def test_evaluate_label_passes_timeout_to_run_scenario(monkeypatch):
    captured_timeouts = []

    async def fake_run_scenario(item, label, *, timeout=ep.DEFAULT_ITEM_TIMEOUT_SECONDS):
        captured_timeouts.append(timeout)
        return {"scenes": [{"scene_num": 1, "narration": "hi", "shots": [{"image_prompt": "p"}]}], "current_stage": "scenario", "error": None}

    monkeypatch.setattr(ep, "_run_scenario", fake_run_scenario)
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    ep.evaluate_label(_client_with_seeded_dataset(), ep.DATASET_NAME, "production", timeout=5.0)

    assert captured_timeouts == [5.0] * len(ep.GOLDEN_IDS)


def test_main_passes_timeout_flag(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    captured = {}
    real_evaluate_label = ep.evaluate_label

    def spy_evaluate_label(*a, **k):
        captured.update(k)
        return real_evaluate_label(*a, **k)

    monkeypatch.setattr(ep, "evaluate_label", spy_evaluate_label)

    ep.main(["--label", "production", "--timeout", "12.5"])

    assert captured["timeout"] == 12.5


# ── failure artifacts (AC3, AC5) ─────────────────────────────────────────────


def test_write_artifact_creates_json_file(tmp_path):
    path = ep.write_artifact(
        tmp_path, label="candidate", scp_id="SCP-049", stage="full",
        error="boom", finish_reason="length", raw_output="{broken", parsed_state={"a": 1},
    )
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {
        "label": "candidate", "scp_id": "SCP-049", "stage": "full",
        "finish_reason": "length", "error": "boom", "raw_output": "{broken", "parsed_state": {"a": 1},
    }


def test_evaluate_label_full_failure_artifact_includes_parsed_state(monkeypatch, tmp_path):
    parsed_state = {"current_stage": "scenario", "error": "boom", "scenes": [{"scene_num": 1}]}

    async def fake_scenario_node(state, *, trace_sink=None):
        return parsed_state

    monkeypatch.setattr(ep, "scenario_node", fake_scenario_node)
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    results = ep.evaluate_label(
        _client_with_seeded_dataset(), ep.DATASET_NAME, "production", scp_id="SCP-049", run_dir=tmp_path
    )

    data = json.loads(Path(results[0].artifact_path).read_text(encoding="utf-8"))
    # _run_scenario folds in `stages` (Story 6.3) alongside whatever scenario_node returned.
    assert data["parsed_state"] == {**parsed_state, "stages": []}


def test_evaluate_label_writes_artifact_on_failure(monkeypatch, tmp_path):
    _wire_scenario_capturing_state(monkeypatch, [], error="boom")
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    results = ep.evaluate_label(_client_with_seeded_dataset(), ep.DATASET_NAME, "production", run_dir=tmp_path)

    assert all(r.artifact_path for r in results)
    assert all(Path(r.artifact_path).exists() for r in results)


def test_evaluate_label_skips_artifact_when_no_run_dir(monkeypatch):
    _wire_scenario_capturing_state(monkeypatch, [], error="boom")
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    results = ep.evaluate_label(_client_with_seeded_dataset(), ep.DATASET_NAME, "production")

    assert all(r.artifact_path is None for r in results)


def test_print_report_includes_artifact_path(capsys):
    r = ep.ItemResult("SCP-096", failed=True, error="boom", artifact_path="/tmp/x.json")
    ep.print_report("production", [r])
    out = capsys.readouterr().out
    assert "/tmp/x.json" in out


def test_print_comparison_includes_artifact_paths(capsys):
    rows = [{
        "scp_id": "SCP-096",
        "status": "item failure",
        "candidate_error": "candidate exploded",
        "baseline_error": "baseline exploded",
        "candidate_artifact": "/tmp/cand.json",
        "baseline_artifact": "/tmp/base.json",
    }]
    ep.print_comparison("candidate", "production", rows, "FAIL")
    out = capsys.readouterr().out
    assert "/tmp/cand.json" in out
    assert "/tmp/base.json" in out


def test_compare_includes_candidate_and_baseline_artifact_paths():
    candidate = [ep.ItemResult("SCP-096", failed=True, error="boom", artifact_path="/tmp/cand.json")]
    baseline = [ep.ItemResult("SCP-096", failed=True, error="boom2", artifact_path="/tmp/base.json")]
    verdict, rows = ep.compare(candidate, baseline)
    assert rows[0]["candidate_artifact"] == "/tmp/cand.json"
    assert rows[0]["baseline_artifact"] == "/tmp/base.json"


# ── stage targeting (AC2, AC5) ───────────────────────────────────────────────


class FakeSettings:
    deepseek_api_key = "sk-test"
    deepseek_base_url = "https://api.deepseek.com"
    deepseek_model = "deepseek-v4-flash"
    deepseek_max_tokens = 8192
    content_language = "ko"


class FakePrompt:
    def compile(self, **variables):
        return "rendered"


def _stub_stage_functions(monkeypatch, *, fail_at=None):
    calls = {"research": 0, "structure": 0, "writing": 0, "cast_decision": 0, "visual_breakdown": 0}

    async def fake_research_step(*a, **k):
        calls["research"] += 1
        return {"frozen_descriptor": "d", "entity_sheet": "e", "story_logline": "l"}

    async def fake_structure_step(*a, **k):
        calls["structure"] += 1
        return [{"scene_num": 1}]

    async def fake_writing_step(*a, **k):
        calls["writing"] += 1
        if fail_at == "writing":
            raise ValueError("writing exploded")
        return {"scenes": [{"scene_num": 1, "narration": "Hello world."}]}

    async def fake_cast_decision_step(*a, **k):
        calls["cast_decision"] += 1
        if fail_at == "cast_decision":
            raise ValueError("cast_decision exploded")
        return {1: []}

    async def fake_visual_breakdown_step(*a, **k):
        calls["visual_breakdown"] += 1
        if fail_at == "visual_breakdown":
            raise ValueError("visual_breakdown exploded")
        return [{"sentence_start": 1, "image_prompt": "p"}]

    monkeypatch.setattr(ep, "get_prompt", lambda *a, **k: FakePrompt())
    monkeypatch.setattr(ep, "research_step", fake_research_step)
    monkeypatch.setattr(ep, "structure_step", fake_structure_step)
    monkeypatch.setattr(ep, "writing_step", fake_writing_step)
    monkeypatch.setattr(ep, "cast_decision_step", fake_cast_decision_step)
    monkeypatch.setattr(ep, "visual_breakdown_step", fake_visual_breakdown_step)
    return calls


def test_run_stage_chain_writing_succeeds(monkeypatch):
    import asyncio

    _stub_stage_functions(monkeypatch)
    failed, actual_stage, error, finish_reason, raw = asyncio.run(
        ep._run_stage_chain("SCP-096", "text", "production", "writing", FakeSettings(), 5.0)
    )
    assert failed is False
    assert actual_stage == "writing"
    assert error is None


def test_run_stage_chain_writing_failure_stops_before_later_stages(monkeypatch):
    import asyncio

    calls = _stub_stage_functions(monkeypatch, fail_at="writing")
    failed, actual_stage, error, finish_reason, raw = asyncio.run(
        ep._run_stage_chain("SCP-096", "text", "production", "writing", FakeSettings(), 5.0)
    )
    assert failed is True
    assert actual_stage == "writing"
    assert "writing exploded" in error
    assert calls["cast_decision"] == 0
    assert calls["visual_breakdown"] == 0


def test_run_stage_chain_cast_decision_failure(monkeypatch):
    import asyncio

    calls = _stub_stage_functions(monkeypatch, fail_at="cast_decision")
    failed, actual_stage, error, finish_reason, raw = asyncio.run(
        ep._run_stage_chain("SCP-096", "text", "production", "cast_decision", FakeSettings(), 5.0)
    )
    assert failed is True
    assert actual_stage == "cast_decision"
    assert "cast_decision exploded" in error
    assert calls["writing"] == 1
    assert calls["visual_breakdown"] == 0


def test_run_stage_chain_visual_breakdown_failure(monkeypatch):
    import asyncio

    calls = _stub_stage_functions(monkeypatch, fail_at="visual_breakdown")
    failed, actual_stage, error, finish_reason, raw = asyncio.run(
        ep._run_stage_chain("SCP-096", "text", "production", "visual_breakdown", FakeSettings(), 5.0)
    )
    assert failed is True
    assert actual_stage == "visual_breakdown"
    assert "visual_breakdown exploded" in error
    assert calls["cast_decision"] == 1


def test_run_stage_chain_captures_raw_and_finish_reason_on_truncation(monkeypatch):
    """Real research_step/structure_step/writing_step against a scripted
    _call_deepseek — proves the artifact-worthy raw/finish_reason comes from
    the actual failing DeepSeek call, not a stubbed step function (AC3)."""
    import asyncio
    import json as jsonlib

    responses = [
        (jsonlib.dumps({"frozen_descriptor": "d"}), {}, "stop"),
        (jsonlib.dumps({"scenes": [{"scene_num": 1}]}), {}, "stop"),
        ("{truncated partial json", {}, "length"),
    ]

    async def scripted_call_deepseek(rendered, s):
        return responses.pop(0)

    monkeypatch.setattr(ep, "get_prompt", lambda *a, **k: FakePrompt())
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    monkeypatch.setattr(ep, "_call_deepseek", scripted_call_deepseek)

    failed, actual_stage, error, finish_reason, raw = asyncio.run(
        ep._run_stage_chain("SCP-096", "text", "production", "writing", FakeSettings(), 5.0)
    )

    assert failed is True
    assert actual_stage == "writing"
    assert "truncated" in error
    assert finish_reason == "length"
    assert raw == "{truncated partial json"


def test_run_stage_filters_by_scp_id(monkeypatch):
    _stub_stage_functions(monkeypatch)
    results = ep.run_stage(_client_with_seeded_dataset(), ep.DATASET_NAME, "production", "writing", scp_id="SCP-049")
    assert {r.scp_id for r in results} == {"SCP-049"}


def test_run_stage_writes_artifact_on_failure(monkeypatch, tmp_path):
    _stub_stage_functions(monkeypatch, fail_at="writing")
    results = ep.run_stage(
        _client_with_seeded_dataset(), ep.DATASET_NAME, "production", "writing", scp_id="SCP-049", run_dir=tmp_path
    )
    assert results[0].failed is True
    assert results[0].artifact_path is not None
    data = json.loads(Path(results[0].artifact_path).read_text(encoding="utf-8"))
    assert data["stage"] == "writing"
    assert data["scp_id"] == "SCP-049"


def test_run_stage_reports_actual_prerequisite_stage_on_failure(monkeypatch, tmp_path):
    _stub_stage_functions(monkeypatch, fail_at="writing")

    results = ep.run_stage(
        _client_with_seeded_dataset(),
        ep.DATASET_NAME,
        "production",
        "visual_breakdown",
        scp_id="SCP-049",
        run_dir=tmp_path,
    )

    assert results[0].stage == "writing"
    data = json.loads(Path(results[0].artifact_path).read_text(encoding="utf-8"))
    assert data["stage"] == "writing"


def test_print_stage_report_includes_failures_and_artifacts(capsys):
    results = [ep.StageResult("SCP-049", "writing", failed=True, error="boom", artifact_path="/tmp/x.json")]
    ep.print_stage_report("production", "writing", results)
    out = capsys.readouterr().out
    assert "SCP-049" in out
    assert "stage=writing" in out
    assert "boom" in out
    assert "/tmp/x.json" in out


def test_main_stage_mode_exits_nonzero_on_failure(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    _stub_stage_functions(monkeypatch, fail_at="writing")

    assert ep.main(["--label", "production", "--stage", "writing", "--scp-id", "SCP-049"]) == 1


def test_main_stage_mode_exits_zero_on_success(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    _stub_stage_functions(monkeypatch)

    assert ep.main(["--label", "production", "--stage", "writing", "--scp-id", "SCP-049"]) == 0


def test_main_rejects_baseline_with_non_full_stage():
    with pytest.raises(SystemExit):
        ep.main(["--label", "candidate", "--baseline", "production", "--stage", "writing"])


def test_main_rejects_non_positive_timeout():
    with pytest.raises(SystemExit):
        ep.main(["--label", "production", "--timeout", "0"])


# ── item failure handling (AC7) ──────────────────────────────────────────────


def test_scenario_failure_marks_item_failed_and_continues(monkeypatch):
    captured = []
    _wire_scenario_capturing_state(monkeypatch, captured, error="boom")
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    results = ep.evaluate_label(_client_with_seeded_dataset(), ep.DATASET_NAME, "production")

    assert len(results) == len(ep.GOLDEN_IDS)  # loop continued for every item
    assert all(r.failed for r in results)
    assert all(r.error == "boom" for r in results)


def test_empty_scenes_marks_item_failed():
    import asyncio

    result = asyncio.run(ep._score_evaluator(input={"scp_text": "x"}, output={"scenes": [], "error": None}))
    assert result[0].name == "failed"


def test_scoring_exception_marks_item_failed_not_crashed(monkeypatch):
    _wire_scenario_capturing_state(monkeypatch, [])

    async def raising_score_run(scp_text, artifact_text, settings):
        raise RuntimeError("judge timed out")

    monkeypatch.setattr(ep, "_score_run", raising_score_run)

    results = ep.evaluate_label(_client_with_seeded_dataset(), ep.DATASET_NAME, "production")

    assert len(results) == len(ep.GOLDEN_IDS)  # run continued for every item, did not crash
    assert all(r.failed for r in results)


def test_to_item_result_treats_missing_scores_as_failed():
    from types import SimpleNamespace

    item_result = SimpleNamespace(item=FakeDatasetItem("SCP-096", {"scp_id": "SCP-096"}), evaluations=[])
    result = ep._to_item_result(item_result)
    assert result.failed is True


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
    assert rows[0]["candidate_error"] == "boom"
    assert rows[0]["baseline_error"] is None


def test_compare_fails_when_baseline_item_failed():
    candidate = [_ok("SCP-096", 4, 4, 4)]
    baseline = [ep.ItemResult("SCP-096", failed=True, error="boom")]
    verdict, rows = ep.compare(candidate, baseline)
    assert verdict == "FAIL"
    assert rows[0]["status"] == "item failure"
    assert rows[0]["candidate_error"] is None
    assert rows[0]["baseline_error"] == "boom"


def test_print_comparison_includes_item_failure_errors(capsys):
    rows = [{
        "scp_id": "SCP-096",
        "status": "item failure",
        "candidate_error": "candidate exploded",
        "baseline_error": "baseline exploded",
    }]
    ep.print_comparison("candidate", "production", rows, "FAIL")
    out = capsys.readouterr().out
    assert "SCP-096: FAIL (item failure)" in out
    assert "candidate: candidate exploded" in out
    assert "production: baseline exploded" in out


def test_compare_fails_on_empty_candidate():
    verdict, rows = ep.compare([], [_ok("SCP-096", 4, 4, 4)])
    assert verdict == "FAIL"


def test_compare_fails_on_empty_baseline():
    verdict, rows = ep.compare([_ok("SCP-096", 4, 4, 4)], [])
    assert verdict == "FAIL"


def test_compare_fails_when_baseline_has_item_missing_from_candidate():
    candidate = [_ok("SCP-096", 4, 4, 4)]
    baseline = [_ok("SCP-096", 4, 4, 4), _ok("SCP-173", 4, 4, 4)]
    verdict, rows = ep.compare(candidate, baseline)
    assert verdict == "FAIL"
    assert any(r["scp_id"] == "SCP-173" and r["status"] == "missing from candidate run" for r in rows)


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


# ── token-budget gate warning (AC6) ─────────────────────────────────────────


def test_main_warns_when_max_tokens_at_risky_default(monkeypatch, capsys):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": 8192})())

    ep.main(["--label", "production"])

    assert "8192" in capsys.readouterr().err


def test_main_silent_when_max_tokens_raised(monkeypatch, capsys):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": 16000})())

    ep.main(["--label", "production"])

    assert capsys.readouterr().err == ""


def test_main_seed_only_exits_zero(monkeypatch):
    client = FakeLangfuseClient()
    monkeypatch.setattr(ep, "build_client", lambda: client)

    assert ep.main(["--seed"]) == 0
    assert set(client.items[ep.DATASET_NAME]) == set(ep.GOLDEN_IDS)


def test_main_rejects_invalid_scp_id(capsys):
    with pytest.raises(SystemExit):
        ep.main(["--label", "production", "--scp-id", "SCP-999"])
    err = capsys.readouterr().err
    for scp_id in ep.GOLDEN_IDS:
        assert scp_id in err


def test_new_run_dir_is_unique_within_same_second(monkeypatch):
    monkeypatch.setattr(ep.time, "strftime", lambda *_: "20260709-010203")
    values = iter([100, 101])
    monkeypatch.setattr(ep.time, "time_ns", lambda: next(values))

    assert ep._new_run_dir("candidate") != ep._new_run_dir("candidate")


def test_main_rejects_baseline_without_label():
    with pytest.raises(SystemExit):
        ep.main(["--baseline", "production"])


def test_main_rejects_label_equal_to_baseline():
    with pytest.raises(SystemExit):
        ep.main(["--label", "production", "--baseline", "production"])
