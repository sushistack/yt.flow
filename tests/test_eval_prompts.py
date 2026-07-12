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


@pytest.fixture(autouse=True)
def _authorize_ab_gate(monkeypatch):
    # Story 6-12: the A/B candidate-vs-production gate is frozen unless
    # YTFLOW_ALLOW_AB_GATE=1. These tests exercise the gate mechanics, so they
    # run authorized; the freeze guard itself has dedicated tests that delenv it.
    monkeypatch.setenv(ep.AB_GATE_OVERRIDE_ENV, "1")
    # Story 8-12: --baseline additionally hard-refuses whenever CLAUDECODE/AI_AGENT
    # is present (unconditional, not overridable) — unset both so these tests run
    # as if from a plain terminal, same as CI. The AI-session block has its own
    # dedicated test below that sets CLAUDECODE back on.
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("AI_AGENT", raising=False)


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

    async def fake_run_scenario(item, label, *, timeout=ep.DEFAULT_ITEM_TIMEOUT_SECONDS, no_cache=False):
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
        # Real prompts render distinct text per stage; a fixed "rendered" would make every
        # stage's cache key collide with the story-6.13 stage cache now wired in by default.
        return f"rendered:{sorted(variables.items())}"


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


# ── profile resolution: pure helper (AC1-3, AC6, Story 6.6) ────────────────


def test_resolve_profile_none_is_pure_passthrough():
    resolved = ep.resolve_profile(
        None, label="candidate", baseline="production", scp_id="SCP-096", stage="writing", timeout=42.0
    )
    assert resolved.label == "candidate"
    assert resolved.baseline == "production"
    assert resolved.scp_id == "SCP-096"
    assert resolved.stage == "writing"
    assert resolved.timeout == 42.0
    assert resolved.authority_note is None


def test_resolve_profile_none_defaults_full_timeout():
    resolved = ep.resolve_profile(None, label=None, baseline=None, scp_id=None, stage="full", timeout=None)
    assert resolved.timeout == ep.DEFAULT_ITEM_TIMEOUT_SECONDS


def test_resolve_profile_none_defaults_stage_timeout():
    resolved = ep.resolve_profile(None, label=None, baseline=None, scp_id=None, stage="writing", timeout=None)
    assert resolved.timeout == ep.DEFAULT_STAGE_TIMEOUT_SECONDS


def test_resolve_profile_smoke_defaults_canary_and_label():
    resolved = ep.resolve_profile(
        "smoke", label=None, baseline=None, scp_id=None, stage="full", timeout=None
    )
    assert resolved.scp_id == ep.SMOKE_DEFAULT_SCP_ID
    assert resolved.label == "candidate"
    assert resolved.baseline is None
    assert resolved.authority_note == ep.NOT_A_PROMOTION_GATE


def test_resolve_profile_smoke_scp_id_override():
    resolved = ep.resolve_profile(
        "smoke", label=None, baseline=None, scp_id="SCP-173", stage="full", timeout=None
    )
    assert resolved.scp_id == "SCP-173"


def test_resolve_profile_smoke_allows_baseline():
    resolved = ep.resolve_profile(
        "smoke", label=None, baseline="production", scp_id=None, stage="full", timeout=None
    )
    assert resolved.baseline == "production"
    assert resolved.authority_note == ep.NOT_A_PROMOTION_GATE


def test_resolve_profile_smoke_allows_stage_isolation():
    resolved = ep.resolve_profile(
        "smoke", label=None, baseline=None, scp_id=None, stage="writing", timeout=None
    )
    assert resolved.stage == "writing"
    assert resolved.timeout == ep.DEFAULT_STAGE_TIMEOUT_SECONDS


def test_resolve_profile_promotion_defaults_label_and_baseline():
    resolved = ep.resolve_profile(
        "promotion", label=None, baseline=None, scp_id=None, stage="full", timeout=None
    )
    assert resolved.label == "candidate"
    assert resolved.baseline == "production"
    assert resolved.scp_id is None
    assert resolved.authority_note is None
    assert resolved.timeout == ep.DEFAULT_ITEM_TIMEOUT_SECONDS


def test_resolve_profile_promotion_rejects_scp_id():
    with pytest.raises(ValueError):
        ep.resolve_profile("promotion", label=None, baseline=None, scp_id="SCP-096", stage="full", timeout=None)


def test_resolve_profile_promotion_rejects_stage_isolation():
    with pytest.raises(ValueError):
        ep.resolve_profile("promotion", label=None, baseline=None, scp_id=None, stage="writing", timeout=None)


def test_resolve_profile_promotion_rejects_mismatched_label_baseline():
    with pytest.raises(ValueError):
        ep.resolve_profile(
            "promotion", label="production", baseline="candidate", scp_id=None, stage="full", timeout=None
        )


# ── smoke profile CLI behavior (AC2, AC4, Story 6.6) ────────────────────────


def test_main_smoke_profile_runs_only_default_canary(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    captured = []
    _wire_scenario_capturing_state(monkeypatch, captured)
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    assert ep.main(["--profile", "smoke"]) == 0
    assert {s["scp_id"] for s in captured} == {ep.SMOKE_DEFAULT_SCP_ID}
    assert {s["prompt_variant"] for s in captured} == {"B"}  # candidate by default


def test_main_smoke_profile_prints_not_a_promotion_gate_on_pass(monkeypatch, capsys):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    assert ep.main(["--profile", "smoke"]) == 0
    assert ep.NOT_A_PROMOTION_GATE in capsys.readouterr().out


def test_main_smoke_profile_prints_not_a_promotion_gate_on_fail(monkeypatch, capsys):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    _wire_scenario_capturing_state(monkeypatch, [], error="boom")
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    assert ep.main(["--profile", "smoke"]) == 1
    assert ep.NOT_A_PROMOTION_GATE in capsys.readouterr().out


def test_main_smoke_profile_persists_authority_metadata(monkeypatch, tmp_path):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "_new_run_dir", lambda *parts: tmp_path / "-".join(parts))
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    ep.main(["--profile", "smoke"])

    meta = json.loads((tmp_path / "candidate" / "_profile.json").read_text(encoding="utf-8"))
    assert meta == {"profile": "smoke", "authority": ep.NOT_A_PROMOTION_GATE}


def test_main_smoke_profile_allows_stage_isolation(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    _stub_stage_functions(monkeypatch)
    monkeypatch.setattr(ep, "get_prompt_with_fallback", lambda *a, **k: FakePrompt())

    assert ep.main(["--profile", "smoke", "--stage", "writing"]) == 0


# ── promotion profile CLI behavior (AC3, AC5, AC6, Story 6.6) ───────────────


def test_main_promotion_profile_rejects_scp_id():
    with pytest.raises(SystemExit):
        ep.main(["--profile", "promotion", "--scp-id", "SCP-096"])


def test_main_promotion_profile_rejects_stage_isolation():
    with pytest.raises(SystemExit):
        ep.main(["--profile", "promotion", "--stage", "writing"])


def test_main_promotion_profile_runs_all_three_items(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": 16000})())
    captured = []
    _wire_scenario_capturing_state(monkeypatch, captured)
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    assert ep.main(["--profile", "promotion"]) == 0
    assert {s["scp_id"] for s in captured} == set(ep.GOLDEN_IDS)


def test_main_promotion_profile_uses_1200s_default_timeout(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": 16000})())
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    captured = {}
    real_evaluate_label = ep.evaluate_label

    def spy_evaluate_label(*a, **k):
        captured.update(k)
        return real_evaluate_label(*a, **k)

    monkeypatch.setattr(ep, "evaluate_label", spy_evaluate_label)

    ep.main(["--profile", "promotion"])

    assert captured["timeout"] == ep.DEFAULT_ITEM_TIMEOUT_SECONDS == 1200.0


def test_main_promotion_profile_rejects_risky_default_max_tokens(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": ep._RISKY_DEFAULT_MAX_TOKENS})())

    with pytest.raises(SystemExit):
        ep.main(["--profile", "promotion"])


def test_main_promotion_profile_does_not_reject_raised_max_tokens(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": 16000})())
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    assert ep.main(["--profile", "promotion"]) == 0


def test_main_promotion_profile_rejects_intermediate_risky_max_tokens(monkeypatch):
    # A value below 16000 still truncates visual_breakdown even if it isn't the
    # exact 8192 default — the preflight must reject any value under the floor.
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": 10000})())

    with pytest.raises(SystemExit):
        ep.main(["--profile", "promotion"])


def test_main_promotion_profile_persists_authority_metadata(monkeypatch, tmp_path):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": 16000})())
    monkeypatch.setattr(ep, "_new_run_dir", lambda *parts: tmp_path / "-".join(parts))
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    ep.main(["--profile", "promotion"])

    meta = json.loads((tmp_path / "candidate-production" / "_profile.json").read_text(encoding="utf-8"))
    assert meta == {"profile": "promotion", "authority": ep.PROMOTION_GATE_AUTHORITY}


def test_main_smoke_profile_not_rejected_by_risky_default_max_tokens(monkeypatch):
    """Only promotion hard-blocks on the risky default — smoke stays a fast, unblocked loop."""
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": ep._RISKY_DEFAULT_MAX_TOKENS})())
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    assert ep.main(["--profile", "smoke"]) == 0


# ── no-profile backward compatibility (AC1, Story 6.6) ──────────────────────


def test_main_without_profile_still_accepts_scp_id(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    captured = []
    _wire_scenario_capturing_state(monkeypatch, captured)
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    assert ep.main(["--label", "production", "--scp-id", "SCP-049"]) == 0
    assert {s["scp_id"] for s in captured} == {"SCP-049"}


def test_main_without_profile_default_full_timeout_is_1200(monkeypatch):
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

    ep.main(["--label", "production"])

    assert captured["timeout"] == 1200.0


def test_main_without_profile_default_stage_timeout_is_600(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    _stub_stage_functions(monkeypatch)

    captured = {}
    real_run_stage = ep.run_stage

    def spy_run_stage(*a, **k):
        captured.update(k)
        return real_run_stage(*a, **k)

    monkeypatch.setattr(ep, "run_stage", spy_run_stage)

    ep.main(["--label", "production", "--stage", "writing"])

    assert captured["timeout"] == 600.0


def test_main_without_profile_no_authority_banner_printed(monkeypatch, capsys):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    ep.main(["--label", "production"])

    assert "PROMOTION GATE" not in capsys.readouterr().out


def test_main_without_profile_writes_no_profile_metadata(monkeypatch, tmp_path):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "_new_run_dir", lambda *parts: tmp_path / "-".join(parts))
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    ep.main(["--label", "production"])

    assert not (tmp_path / "production" / "_profile.json").exists()


# ── INCONCLUSIVE symmetric infrastructure failure (AC8, Story 6.6) ──────────


def test_compare_inconclusive_on_symmetric_timeout():
    candidate = [ep.ItemResult("SCP-096", failed=True, error="timeout after 1200s")]
    baseline = [ep.ItemResult("SCP-096", failed=True, error="timeout after 1200s")]
    verdict, rows = ep.compare(candidate, baseline)
    assert verdict == "INCONCLUSIVE"
    assert rows[0]["status"] == "inconclusive infrastructure failure"


def test_compare_stays_fail_when_only_candidate_times_out():
    candidate = [ep.ItemResult("SCP-096", failed=True, error="timeout after 1200s")]
    baseline = [_ok("SCP-096", 4, 4, 4)]
    verdict, rows = ep.compare(candidate, baseline)
    assert verdict == "FAIL"
    assert rows[0]["status"] == "item failure"


def test_compare_stays_fail_when_timeout_and_non_timeout_error_mixed():
    candidate = [ep.ItemResult("SCP-096", failed=True, error="timeout after 1200s")]
    baseline = [ep.ItemResult("SCP-096", failed=True, error="scoring failed: boom")]
    verdict, rows = ep.compare(candidate, baseline)
    assert verdict == "FAIL"
    assert rows[0]["status"] == "item failure"


def test_compare_fail_from_other_item_overrides_inconclusive():
    candidate = [
        ep.ItemResult("SCP-096", failed=True, error="timeout after 1200s"),
        _ok("SCP-173", 3, 4, 4),  # regressed vs baseline
    ]
    baseline = [
        ep.ItemResult("SCP-096", failed=True, error="timeout after 1200s"),
        _ok("SCP-173", 4, 4, 4),
    ]
    verdict, rows = ep.compare(candidate, baseline)
    assert verdict == "FAIL"


def test_print_comparison_labels_inconclusive_row(capsys):
    rows = [{
        "scp_id": "SCP-096",
        "status": "inconclusive infrastructure failure",
        "candidate_error": "timeout after 1200s",
        "baseline_error": "timeout after 1200s",
        "candidate_artifact": None,
        "baseline_artifact": None,
    }]
    ep.print_comparison("candidate", "production", rows, "INCONCLUSIVE")
    out = capsys.readouterr().out
    assert "SCP-096: INCONCLUSIVE (inconclusive infrastructure failure)" in out
    assert "Verdict: INCONCLUSIVE" in out


def test_main_promotion_profile_exits_nonzero_on_inconclusive(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": 16000})())

    async def timeout_scenario_node(state, *, trace_sink=None):
        return {"scenes": [], "current_stage": "scenario", "error": "timeout after 1200s"}

    monkeypatch.setattr(ep, "scenario_node", timeout_scenario_node)

    assert ep.main(["--profile", "promotion"]) == 1


# ── statistical (median-of-N) gate: aggregate_runs (Story 6.10, AC1/AC2) ────


def test_aggregate_runs_medians_successful_runs():
    runs = [[_ok("SCP-096", 3, 4, 4)], [_ok("SCP-096", 4, 4, 4)], [_ok("SCP-096", 4, 4, 4)]]
    agg = ep.aggregate_runs(runs)
    assert agg[0].axes["atmosphere"] == 4  # median of [3, 4, 4], not mean 3.67
    assert agg[0].failed is False
    assert agg[0].n_runs == 3
    assert agg[0].n_failed_runs == 0


def test_aggregate_single_noisy_negative_cell_still_passes():
    # AC5(a): one run dips atmosphere; the median vs a steady baseline is 0 → PASS.
    cand = ep.aggregate_runs([[_ok("SCP-096", 3, 4, 4)], [_ok("SCP-096", 4, 4, 4)], [_ok("SCP-096", 4, 4, 4)]])
    base = ep.aggregate_runs([[_ok("SCP-096", 4, 4, 4)]] * 3)
    verdict, _ = ep.compare(cand, base)
    assert verdict == "PASS"


def test_aggregate_consistently_negative_cell_still_fails():
    # AC5(a): a cell negative in every run has a negative median → still FAIL.
    cand = ep.aggregate_runs([[_ok("SCP-096", 3, 4, 4)]] * 3)
    base = ep.aggregate_runs([[_ok("SCP-096", 4, 4, 4)]] * 3)
    verdict, rows = ep.compare(cand, base)
    assert verdict == "FAIL"
    assert rows[0]["status"] == "regressed"


def test_aggregate_minority_failure_uses_median_of_successes():
    # AC2/AC5(b): one hard-failing run out of three does not isolate the item.
    runs = [
        [ep.ItemResult("SCP-096", failed=True, error="boom")],
        [_ok("SCP-096", 4, 4, 4)],
        [_ok("SCP-096", 4, 4, 4)],
    ]
    agg = ep.aggregate_runs(runs)
    assert agg[0].failed is False
    assert agg[0].n_failed_runs == 1
    assert agg[0].axes["atmosphere"] == 4
    assert "boom" in agg[0].failed_run_reasons[0]


def test_aggregate_majority_failure_isolates_item():
    # AC2: fails in a majority of runs → item is FAIL, gate does not crash.
    runs = [
        [ep.ItemResult("SCP-096", failed=True, error="boom1")],
        [ep.ItemResult("SCP-096", failed=True, error="boom2")],
        [_ok("SCP-096", 4, 4, 4)],
    ]
    agg = ep.aggregate_runs(runs)
    assert agg[0].failed is True
    assert agg[0].n_failed_runs == 2
    assert agg[0].failed_run_reasons == ["boom1", "boom2"]


def test_aggregate_missing_item_counts_as_failed_run():
    runs = [
        [_ok("SCP-096", 4, 4, 4)],
        [],
        [],
    ]
    agg = ep.aggregate_runs(runs)
    assert agg[0].failed is True
    assert agg[0].n_failed_runs == 2
    assert agg[0].failed_run_reasons == [
        "missing item result in run 2",
        "missing item result in run 3",
    ]


def test_compare_uses_median_of_paired_deltas_not_difference_of_medians():
    candidate = ep.aggregate_runs([
        [_ok("SCP-096", 0, 4, 4)],
        [_ok("SCP-096", 100, 4, 4)],
        [_ok("SCP-096", 100, 4, 4)],
    ])
    baseline = ep.aggregate_runs([
        [_ok("SCP-096", 99, 4, 4)],
        [_ok("SCP-096", 99, 4, 4)],
        [_ok("SCP-096", 101, 4, 4)],
    ])
    verdict, rows = ep.compare(candidate, baseline)
    assert rows[0]["deltas"]["atmosphere"] == -1
    assert verdict == "FAIL"


def test_aggregate_all_runs_failed_isolates_item():
    runs = [[ep.ItemResult("SCP-096", failed=True, error="boom")]] * 3
    agg = ep.aggregate_runs(runs)
    assert agg[0].failed is True
    verdict, _ = ep.compare(agg, ep.aggregate_runs([[_ok("SCP-096", 4, 4, 4)]] * 3))
    assert verdict == "FAIL"


def test_aggregate_preserves_item_order_across_runs():
    runs = [
        [_ok("SCP-096", 4, 4, 4), _ok("SCP-173", 4, 4, 4)],
        [_ok("SCP-096", 4, 4, 4), _ok("SCP-173", 4, 4, 4)],
    ]
    agg = ep.aggregate_runs(runs)
    assert [r.scp_id for r in agg] == ["SCP-096", "SCP-173"]


# ── reps resolution (Story 6.10, AC1) ───────────────────────────────────────


def test_resolve_profile_promotion_defaults_reps_to_3():
    resolved = ep.resolve_profile(
        "promotion", label=None, baseline=None, scp_id=None, stage="full", timeout=None
    )
    assert resolved.reps == ep.PROMOTION_REPS == 3


def test_resolve_profile_none_defaults_reps_to_1():
    resolved = ep.resolve_profile(
        None, label="candidate", baseline="production", scp_id=None, stage="full", timeout=None
    )
    assert resolved.reps == 1


def test_resolve_profile_smoke_defaults_reps_to_1():
    resolved = ep.resolve_profile("smoke", label=None, baseline=None, scp_id=None, stage="full", timeout=None)
    assert resolved.reps == 1


def test_resolve_profile_promotion_rejects_reps_below_3():
    with pytest.raises(ValueError):
        ep.resolve_profile(
            "promotion", label=None, baseline=None, scp_id=None, stage="full", timeout=None, reps=2
        )


def test_resolve_profile_reps_override_above_floor():
    resolved = ep.resolve_profile(
        "promotion", label=None, baseline=None, scp_id=None, stage="full", timeout=None, reps=5
    )
    assert resolved.reps == 5


def test_main_promotion_profile_runs_reps_times_per_label(monkeypatch):
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": 16000})())
    captured = []
    _wire_scenario_capturing_state(monkeypatch, captured)
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    assert ep.main(["--profile", "promotion"]) == 0
    # 3 reps × 3 golden items × 2 labels (candidate + production)
    assert len(captured) == ep.PROMOTION_REPS * len(ep.GOLDEN_IDS) * 2
    assert {s["scp_id"] for s in captured} == set(ep.GOLDEN_IDS)


def test_main_promotion_median_tolerates_single_noisy_run(monkeypatch):
    # End-to-end: candidate dips atmosphere on exactly one of its runs; the
    # median gate must still PASS (a zero-tolerance gate would FAIL here).
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": 16000})())
    _wire_scenario_capturing_state(monkeypatch, [])

    calls = {"n": 0}
    n_items = len(ep.GOLDEN_IDS)

    async def noisy_score_run(scp_text, artifact_text, settings):
        calls["n"] += 1
        # Candidate is evaluated first (reps × items calls), production after.
        # Dip atmosphere on the very first candidate call only.
        if calls["n"] == 1:
            return AxisScores(3, 4, 4, 11)
        return AxisScores(4, 4, 4, 12)

    monkeypatch.setattr(ep, "_score_run", noisy_score_run)

    assert ep.main(["--profile", "promotion"]) == 0
    # candidate reps (3) + production reps (3), each covering all items
    assert calls["n"] == ep.PROMOTION_REPS * n_items * 2


# ── A/B gate freeze (Story 6-12) ────────────────────────────────────────────


def test_baseline_comparison_frozen_without_override(monkeypatch, capsys):
    monkeypatch.delenv(ep.AB_GATE_OVERRIDE_ENV, raising=False)
    with pytest.raises(SystemExit):
        ep.main(["--label", "candidate", "--baseline", "production"])
    assert "FROZEN" in capsys.readouterr().err


def test_promotion_profile_frozen_without_override(monkeypatch, capsys):
    monkeypatch.delenv(ep.AB_GATE_OVERRIDE_ENV, raising=False)
    with pytest.raises(SystemExit):
        ep.main(["--profile", "promotion"])
    assert "FROZEN" in capsys.readouterr().err


def test_baseline_blocked_in_ai_session_even_with_override(monkeypatch, capsys):
    # Story 8-12: unlike AB_GATE_OVERRIDE_ENV, this check is not an env var an
    # AI session can flip for itself — CLAUDECODE present blocks --baseline
    # unconditionally, override or not.
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(SystemExit):
        ep.main(["--label", "candidate", "--baseline", "production"])
    assert "AI coding session" in capsys.readouterr().err


def test_baseline_blocked_even_when_ai_session_var_is_empty_string(monkeypatch, capsys):
    # Presence, not truthiness: CLAUDECODE="" is still an AI-session marker
    # (some harnesses set the var without a value) and must still block.
    monkeypatch.setenv("CLAUDECODE", "")
    with pytest.raises(SystemExit):
        ep.main(["--label", "candidate", "--baseline", "production"])
    assert "AI coding session" in capsys.readouterr().err


def test_single_label_run_not_frozen(monkeypatch):
    # A single-label diagnostic (no --baseline) stays open even without the override.
    monkeypatch.delenv(ep.AB_GATE_OVERRIDE_ENV, raising=False)
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": 16000})())
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))
    assert ep.main(["--label", "candidate"]) in (0, 1)  # runs; not blocked by the freeze


# ── stage cache (Story 6.13) ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    # Story 6.13's cache is content-addressed local JSON under CACHE_ROOT — redirect it
    # into pytest's per-test tmp_path so cache entries never leak across tests/runs
    # (the test-isolation-workspace-pollution gotcha applies here too).
    monkeypatch.setattr(ep, "CACHE_ROOT", tmp_path / "cache")


def test_cache_key_differs_for_different_rendered_text():
    assert ep._cache_key("a", "model", 8192) != ep._cache_key("b", "model", 8192)


def test_cache_key_differs_for_different_model():
    assert ep._cache_key("same", "model-1", 8192) != ep._cache_key("same", "model-2", 8192)


def test_cache_key_differs_for_different_max_tokens():
    # max_tokens governs truncation (_RISKY_DEFAULT_MAX_TOKENS) — a bump meant to fix
    # a truncated response must not silently replay the old truncated cache entry.
    assert ep._cache_key("same", "model", 8192) != ep._cache_key("same", "model", 16000)


def test_cache_get_miss_returns_none():
    assert ep._cache_get(ep._cache_key("never cached", "model", 8192)) is None


def test_cache_put_then_get_roundtrips():
    key = ep._cache_key("rendered", "model", 8192)
    ep._cache_put(key, "raw text", {"completion_tokens": 5}, "stop")
    assert ep._cache_get(key) == ("raw text", {"completion_tokens": 5}, "stop")


def test_cache_get_treats_corrupt_json_as_a_miss():
    # A process killed mid-write (Ctrl-C/OOM during the 600-1200s eval timeouts this
    # script uses) can leave a truncated file — must degrade to a miss, not crash.
    key = ep._cache_key("rendered", "model", 8192)
    ep.CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    (ep.CACHE_ROOT / f"{key}.json").write_text('{"raw": "incomplete', encoding="utf-8")
    assert ep._cache_get(key) is None


def test_cached_call_deepseek_hits_cache_on_identical_rendered_text_and_model():
    import asyncio

    calls = {"n": 0}

    async def fake_call(rendered, s):
        calls["n"] += 1
        return ("raw", {}, "stop")

    wrapped = ep._cached_call_deepseek(fake_call)

    asyncio.run(wrapped("same text", FakeSettings()))
    asyncio.run(wrapped("same text", FakeSettings()))

    assert calls["n"] == 1  # AC8(a): identical rendered text + model -> exactly one real call


def test_cached_call_deepseek_misses_on_changed_text_but_hits_unrelated_unchanged_key():
    import asyncio

    calls = []

    async def fake_call(rendered, s):
        calls.append(rendered)
        return (f"raw-{rendered}", {}, "stop")

    wrapped = ep._cached_call_deepseek(fake_call)

    first = asyncio.run(wrapped("a", FakeSettings()))
    repeat_of_first = asyncio.run(wrapped("a", FakeSettings()))  # unrelated, unchanged -> still hits
    second = asyncio.run(wrapped("b", FakeSettings()))  # changed rendered text -> misses

    assert calls == ["a", "b"]  # AC8(b): only the changed key produced a second real call
    assert repeat_of_first == first
    assert second == ("raw-b", {}, "stop")


def test_cached_call_deepseek_caches_truncated_response_unconditionally():
    import asyncio

    calls = {"n": 0}

    async def fake_call(rendered, s):
        calls["n"] += 1
        return ("{truncated partial json", {}, "length")

    wrapped = ep._cached_call_deepseek(fake_call)

    first = asyncio.run(wrapped("x", FakeSettings()))
    second = asyncio.run(wrapped("x", FakeSettings()))

    assert calls["n"] == 1
    assert first == second == ("{truncated partial json", {}, "length")


def test_run_scenario_wires_cache_wrapper_for_scenario_node_call(monkeypatch):
    import asyncio

    original = ep.scenario_module._call_deepseek
    seen = {}

    async def fake_scenario_node(state, *, trace_sink=None):
        seen["wrapped"] = ep.scenario_module._call_deepseek is not original
        return {"scenes": [], "current_stage": "scenario", "error": None}

    monkeypatch.setattr(ep, "scenario_node", fake_scenario_node)

    item = FakeDatasetItem("SCP-096", {"scp_id": "SCP-096", "scp_text": "x"})
    asyncio.run(ep._run_scenario(item, "production"))

    assert seen["wrapped"] is True  # AC6: caching wrapper substituted for the duration of the call
    assert ep.scenario_module._call_deepseek is original  # ...and restored afterward


def test_run_scenario_no_cache_leaves_call_deepseek_unwrapped(monkeypatch):
    import asyncio

    original = ep.scenario_module._call_deepseek
    seen = {}

    async def fake_scenario_node(state, *, trace_sink=None):
        seen["unwrapped"] = ep.scenario_module._call_deepseek is original
        return {"scenes": [], "current_stage": "scenario", "error": None}

    monkeypatch.setattr(ep, "scenario_node", fake_scenario_node)

    item = FakeDatasetItem("SCP-096", {"scp_id": "SCP-096", "scp_text": "x"})
    asyncio.run(ep._run_scenario(item, "production", no_cache=True))

    assert seen["unwrapped"] is True  # AC4: --no-cache never substitutes the wrapper


def test_run_scenario_restores_call_deepseek_even_when_scenario_node_raises(monkeypatch):
    import asyncio

    original = ep.scenario_module._call_deepseek

    async def raising_scenario_node(state, *, trace_sink=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(ep, "scenario_node", raising_scenario_node)

    item = FakeDatasetItem("SCP-096", {"scp_id": "SCP-096", "scp_text": "x"})
    with pytest.raises(RuntimeError):
        asyncio.run(ep._run_scenario(item, "production"))

    assert ep.scenario_module._call_deepseek is original  # AC6: restored even on raise


def test_run_stage_chain_no_cache_calls_fresh_despite_identical_rendered_text(monkeypatch):
    """AC4/AC7/AC8(c): with --no-cache, every stage call goes straight to
    _call_deepseek even though every stage renders the exact same text (which
    would otherwise collide on one cache key) — proving the bypass is real,
    not just "no collision happened to occur"."""
    import asyncio
    import json as jsonlib

    class ConstantPrompt:
        def compile(self, **variables):
            return "identical rendered text for every stage"

    responses = [
        (jsonlib.dumps({"frozen_descriptor": "d"}), {}, "stop"),
        (jsonlib.dumps({"scenes": [{"scene_num": 1}]}), {}, "stop"),
        (jsonlib.dumps({"scenes": [{"scene_num": 1, "narration": "Hello world."}]}), {}, "stop"),
    ]

    async def scripted_call_deepseek(rendered, s):
        return responses.pop(0)

    monkeypatch.setattr(ep, "get_prompt", lambda *a, **k: ConstantPrompt())
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: ConstantPrompt())
    monkeypatch.setattr(ep, "_call_deepseek", scripted_call_deepseek)

    failed, actual_stage, error, finish_reason, raw = asyncio.run(
        ep._run_stage_chain("SCP-096", "text", "production", "writing", FakeSettings(), 5.0, no_cache=True)
    )

    assert failed is False
    assert actual_stage == "writing"
    assert responses == []  # all 3 canned responses consumed fresh — none served from cache


def test_run_stage_chain_cache_enabled_reuses_result_on_second_identical_run(monkeypatch):
    """AC1/AC2/AC8: through the real _run_stage_chain/_recording_call wiring point
    (not the _cached_call_deepseek helper in isolation) — a second run with identical
    scp_id/scp_text/settings hits cache for every stage; no second real call is made."""
    import asyncio

    responses = [
        (json.dumps({"frozen_descriptor": "d"}), {}, "stop"),
        (json.dumps({"scenes": [{"scene_num": 1}]}), {}, "stop"),
        (json.dumps({"scenes": [{"scene_num": 1, "narration": "Hello world."}]}), {}, "stop"),
    ]
    calls = {"n": 0}

    async def scripted_call_deepseek(rendered, s):
        calls["n"] += 1
        return responses.pop(0)

    monkeypatch.setattr(ep, "get_prompt", lambda *a, **k: FakePrompt())
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    monkeypatch.setattr(ep, "_call_deepseek", scripted_call_deepseek)

    for _ in range(2):
        failed, actual_stage, error, finish_reason, raw = asyncio.run(
            ep._run_stage_chain("SCP-096", "text", "production", "writing", FakeSettings(), 5.0)
        )
        assert failed is False
        assert actual_stage == "writing"

    assert responses == []  # all 3 canned responses consumed exactly once
    assert calls["n"] == 3  # the second run's 3 stage calls were all served from cache


def test_run_scenario_cache_enabled_hits_cache_on_second_call(monkeypatch):
    """AC1/AC6/AC8 through the real _run_scenario monkeypatch wiring point: a second
    _run_scenario call for the same item makes no additional underlying DeepSeek call."""
    import asyncio

    calls = {"n": 0}

    async def fake_underlying(rendered, s):
        calls["n"] += 1
        return ("raw", {}, "stop")

    monkeypatch.setattr(ep, "_call_deepseek", fake_underlying)

    async def fake_scenario_node(state, *, trace_sink=None):
        await ep.scenario_module._call_deepseek("same rendered text", FakeSettings())
        return {"scenes": [], "current_stage": "scenario", "error": None}

    monkeypatch.setattr(ep, "scenario_node", fake_scenario_node)

    item = FakeDatasetItem("SCP-096", {"scp_id": "SCP-096", "scp_text": "x"})
    asyncio.run(ep._run_scenario(item, "production"))
    asyncio.run(ep._run_scenario(item, "production"))

    assert calls["n"] == 1  # second call served from cache through the real wiring point


def test_main_threads_no_cache_flag_into_evaluate_label(monkeypatch):
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

    ep.main(["--label", "production", "--no-cache"])

    assert captured["no_cache"] is True


def test_main_promotion_reps_force_no_cache_even_without_flag(monkeypatch):
    """Each rep must be an independent regeneration for Story 6.10's median-of-N
    noise gate — serving rep 2..N from rep 1's cache would collapse the sample to
    one draw, so the reps loop always passes no_cache=True regardless of --no-cache."""
    client = _client_with_seeded_dataset()
    monkeypatch.setattr(ep, "build_client", lambda: client)
    monkeypatch.setattr(ep, "Settings", lambda: type("S", (), {"deepseek_max_tokens": 16000})())
    _wire_scenario_capturing_state(monkeypatch, [])
    _wire_score_run(monkeypatch, AxisScores(4, 4, 4, 12))

    captured_no_cache = []
    real_evaluate_label = ep.evaluate_label

    def spy_evaluate_label(*a, **k):
        captured_no_cache.append(k.get("no_cache"))
        return real_evaluate_label(*a, **k)

    monkeypatch.setattr(ep, "evaluate_label", spy_evaluate_label)

    assert ep.main(["--profile", "promotion"]) == 0  # note: no --no-cache flag passed

    assert captured_no_cache == [True] * (ep.PROMOTION_REPS * 2)  # candidate reps + production reps


def test_main_default_no_cache_is_false(monkeypatch):
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

    ep.main(["--label", "production"])

    assert captured["no_cache"] is False
