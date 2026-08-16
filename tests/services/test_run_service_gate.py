"""Story 2.3 — run_service gate-aware event loop: interrupt detection, DB sync,
SSE fan-out, and resume routing. [AD-3, AD-4]

Uses a real compiled graph (AsyncSqliteSaver on a temp file) + in-memory SQLModel
runs table. A fake SSE registry records fan-out without needing a live subscriber.
"""

import asyncio
import copy
import json
import uuid

import pytest

import pytest_asyncio
from sqlmodel import Session

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.db.models import Run
from yt_flow.services import run_service

from tests.stubs import fakes


class _FakeRegistry:
    """Records published events; publish() matches SSEQueueRegistry's signature."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, run_id: str, event: dict) -> None:
        self.events.append(event)


def _kinds(reg: _FakeRegistry, name: str) -> list[dict]:
    return [e for e in reg.events if e["event"] == name]


def _stages(reg: _FakeRegistry, name: str) -> list[str]:
    return [e["data"]["stage"] for e in _kinds(reg, name)]


def _seed(run_id: str, status: str = "running", prompt_variant: str | None = None,
          ab_pair_id: str | None = None) -> None:
    with Session(db._engine) as session:
        session.add(Run(id=run_id, scp_id="SCP-096", status=status,
                         prompt_variant=prompt_variant, ab_pair_id=ab_pair_id))
        session.commit()


def _load(run_id: str) -> Run:
    with Session(db._engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        return run


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch, stub_stage_nodes):
    # Real graph on a temp checkpointer + in-memory runs table. Stage nodes are
    # stubbed to instant successes: these tests exercise gate/status mechanics,
    # and a genuinely failing stage no longer reaches its gate (error routes to END).
    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path / "ws"))
    monkeypatch.setenv("YTFLOW_ASSETS_PATH", str(tmp_path / "assets"))
    # Story 5.8: start_run now auto-triggers character reference search/generation
    # for a never-before-seen scp_id — keep these gate/status-mechanics tests offline (B-2).
    fakes.patch_character_reference_seams(monkeypatch)
    db.init("sqlite://")
    settings = Settings(
        langfuse_host="http://localhost",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        db_path=str(tmp_path / "cp.db"),
    )
    saver = await run_service.init(settings)
    yield
    await saver.conn.close()
    run_service._graph = None
    run_service._configs.clear()
    db._engine = None


async def test_start_run_pauses_at_scenario_gate(env):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()

    await run_service.start_run(run_id, "SCP-096", "scp text", reg)

    run = _load(run_id)
    assert run.status == "awaiting_approval"
    assert run.current_stage == "scenario"
    assert json.loads(run.gate_states)["scenario"] == "pending"
    assert _stages(reg, "gate_pending") == ["scenario"]
    assert "scenario" in _stages(reg, "stage_entry")
    assert "scenario" in _stages(reg, "stage_exit")


async def test_approve_advances_to_next_gate(env):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)
    reg.events.clear()

    await run_service.resume_run(run_id, "scenario", "approve", reg)

    run = _load(run_id)
    states = json.loads(run.gate_states)
    assert states["scenario"] == "approved"
    assert states["image"] == "pending"
    assert run.status == "awaiting_approval"
    assert "image" in _stages(reg, "stage_entry")   # AC2: stage_entry for image
    assert _stages(reg, "gate_pending") == ["image"]


async def test_reject_scenario_fails_and_terminates(env):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)
    reg.events.clear()

    await run_service.resume_run(run_id, "scenario", "reject", reg)

    run = _load(run_id)
    assert run.status == "failed"                    # AC3: scenario reject → failed
    assert json.loads(run.gate_states)["scenario"] == "rejected"
    assert _kinds(reg, "run_failed")                 # AC3: run_failed emitted
    assert run_id not in run_service._configs        # config cleaned up


async def test_reject_image_loops_back_to_pending(env):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)
    await run_service.resume_run(run_id, "scenario", "approve", reg)  # pause at image
    reg.events.clear()

    await run_service.resume_run(run_id, "image", "reject", reg)

    run = _load(run_id)
    # non-scenario reject loops back → image reruns → gate_image re-interrupts (retry)
    assert run.status == "awaiting_approval"
    assert json.loads(run.gate_states)["image"] == "pending"
    assert _stages(reg, "gate_pending") == ["image"]


def _shot(**over) -> dict:
    base = {"shot_id": "S1", "sentence_indices": [0], "image_prompt": "p", "negative_prompt": "n",
            "camera_angle": None, "camera_movement": None, "image_path": None, "cast": []}
    base.update(over)
    return base


async def _seed_shot_with_image_path(run_id: str, path: str) -> None:
    """Plant a scene+shot with a pre-existing image_path, as if a prior attempt completed it.

    stub_stage_nodes' scenario stub never populates ``scenes`` (default: []) — build
    the scene wholesale rather than assuming one already exists.
    """
    config = run_service._configs[run_id]
    scene = {"scene_num": 1, "narration": "n", "audio_path": None, "audio_duration": None,
              "word_timings": [], "subtitle_path": None, "shots": [_shot(image_path=path)]}
    # as_node="image": the graph is paused at gate_image's interrupt — attributing the
    # update to "image" keeps gate_image the next task (mirrors edit_artifact's pattern).
    await run_service._graph.aupdate_state(config, {"scenes": [scene]}, as_node="image")


async def test_reject_image_nullifies_shot_image_path_before_reentry(env):
    # Story 2.6 AC1/2/4: reject must clear image_path — a stub image node never
    # rewrites it, so this proves resume_run's own nullify branch, decoupled from
    # image_node's real disk-cache behaviour (covered separately by the stub-profile
    # e2e regression test).
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)
    await run_service.resume_run(run_id, "scenario", "approve", reg)  # pause at image
    await _seed_shot_with_image_path(run_id, "old.png")

    await run_service.resume_run(run_id, "image", "reject", reg)

    config = run_service._configs[run_id]
    snap = await run_service._graph.aget_state(config)
    assert snap.values["scenes"][0]["shots"][0]["image_path"] is None


async def test_approve_leaves_scenes_untouched(env):
    # Story 2.6 AC5: approve moves forward, never nullifies.
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)
    await run_service.resume_run(run_id, "scenario", "approve", reg)  # pause at image
    await _seed_shot_with_image_path(run_id, "old.png")

    await run_service.resume_run(run_id, "image", "approve", reg)

    config = run_service._configs[run_id]
    snap = await run_service._graph.aget_state(config)
    assert snap.values["scenes"][0]["shots"][0]["image_path"] == "old.png"


async def test_full_approval_completes(env):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)
    for stage in ("scenario", "image", "tts", "subtitle", "video"):
        await run_service.resume_run(run_id, stage, "approve", reg)

    run = _load(run_id)
    assert run.status == "complete"                  # AC4: reaches END → complete
    assert "video" in _stages(reg, "stage_exit")     # AC4: stage_exit for video
    assert run_id not in run_service._configs


# ── A/B eval trigger on Variant B completion (eval-ab-trigger-wiring) ──────────


async def test_regular_run_completion_does_not_trigger_ab_eval(env, monkeypatch):
    called = {"count": 0}

    async def boom(*a, **k):
        called["count"] += 1
        raise AssertionError("evaluate_ab must not run for a non-A/B run")

    monkeypatch.setattr(run_service.eval_service, "evaluate_ab", boom)
    run_id = str(uuid.uuid4())
    _seed(run_id)  # prompt_variant=None, ab_pair_id=None — plain run
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)
    for stage in ("scenario", "image", "tts", "subtitle", "video"):
        await run_service.resume_run(run_id, stage, "approve", reg)
    await asyncio.gather(*run_service._bg_tasks)

    assert _load(run_id).status == "complete"
    assert called["count"] == 0


async def test_variant_b_completion_triggers_ab_eval(env, monkeypatch):
    calls = []

    async def fake_evaluate_ab(run_a_id, run_b_id):
        calls.append((run_a_id, run_b_id))

    monkeypatch.setattr(run_service.eval_service, "evaluate_ab", fake_evaluate_ab)
    source_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    _seed(source_id, status="complete")
    _seed(run_id, prompt_variant="B", ab_pair_id=source_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)
    for stage in ("scenario", "image", "tts", "subtitle", "video"):
        await run_service.resume_run(run_id, stage, "approve", reg)
    await asyncio.gather(*run_service._bg_tasks)

    assert _load(run_id).status == "complete"
    assert calls == [(source_id, run_id)]


async def test_ab_eval_failure_does_not_affect_run_status(env, monkeypatch, caplog):
    async def boom(run_a_id, run_b_id):
        # Story 12.2: the judge runs on Gemini, so this is the key whose absence
        # actually stops an A/B evaluation now. Kept as the realistic failure this
        # test is named for rather than a generic RuntimeError.
        raise RuntimeError("YTFLOW_GEMINI_API_KEY is not configured")

    monkeypatch.setattr(run_service.eval_service, "evaluate_ab", boom)
    source_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    _seed(source_id, status="complete")
    _seed(run_id, prompt_variant="B", ab_pair_id=source_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)

    with caplog.at_level("WARNING", logger="yt_flow.services.run_service"):
        for stage in ("scenario", "image", "tts", "subtitle", "video"):
            await run_service.resume_run(run_id, stage, "approve", reg)
        await asyncio.gather(*run_service._bg_tasks)

    assert _load(run_id).status == "complete"        # AD-10: eval failure is non-fatal
    assert any("A/B evaluation failed" in r.message for r in caplog.records)


async def test_astream_failure_marks_failed(env, monkeypatch):
    # AD-4: services catches an astream() error during iteration, sets failed, fans out.
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()

    async def _boom(*args, **kwargs):
        raise RuntimeError("kaboom")
        yield  # unreachable — makes this an async generator

    monkeypatch.setattr(run_service._graph, "astream", _boom)
    await run_service.start_run(run_id, "SCP-096", "t", reg)

    run = _load(run_id)
    assert run.status == "failed"
    assert run.error == "kaboom"
    assert _kinds(reg, "run_failed")


async def test_node_failure_surfaces_failing_stage_in_trace_payload(env, monkeypatch):
    # SYS-INT-008 / FR-13: a failed node's stage (not just its exception) must be
    # surfaced — LangGraph attaches "During task with name '<node>'" as an exception
    # note (PEP 678); _stage_from_exception parses it instead of hardcoding "unknown".
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)  # pauses at gate_scenario
    reg.events.clear()

    exc = ValueError("image node exploded")
    exc.add_note("During task with name 'image' and id 'deadbeef'")

    async def _boom(*args, **kwargs):
        raise exc
        yield  # unreachable — makes this an async generator

    monkeypatch.setattr(run_service._graph, "astream", _boom)
    await run_service.resume_run(run_id, "scenario", "approve", reg)

    run = _load(run_id)
    assert run.status == "failed"
    assert run.error == "image node exploded"
    assert run.current_stage == "image"  # not "unknown" — the actual failing node
    [event] = _kinds(reg, "run_failed")
    assert event["data"]["stage"] == "image"
    assert event["data"]["error"] == "image node exploded"


def test_stage_from_exception_falls_back_to_unknown_without_notes():
    assert run_service._stage_from_exception(RuntimeError("no notes here")) == "unknown"


# ── Story 3.8 D7: status is "running" (not stale "awaiting_approval") while the
#    resumed stage is still executing ────────────────────────────────────────


async def test_resume_run_reports_running_while_stage_in_flight(tmp_path, monkeypatch):
    from yt_flow.pipeline import nodes

    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path / "ws"))
    monkeypatch.setenv("YTFLOW_ASSETS_PATH", str(tmp_path / "assets"))
    fakes.patch_character_reference_seams(monkeypatch)
    db.init("sqlite://")

    def _instant(stage):
        async def node(state):
            return {"current_stage": stage, "error": None}
        return node

    for s in nodes.STAGES:
        monkeypatch.setitem(nodes.STAGE_NODES, s, _instant(s))
    gate = asyncio.Event()

    async def blocking_image(state):
        await gate.wait()
        return {"current_stage": "image", "error": None}

    monkeypatch.setitem(nodes.STAGE_NODES, "image", blocking_image)

    settings = Settings(
        langfuse_host="http://localhost", langfuse_public_key="pk",
        langfuse_secret_key="sk", db_path=str(tmp_path / "cp-d7.db"),
    )
    saver = await run_service.init(settings)  # rebuild graph with the blocking image node
    try:
        run_id = str(uuid.uuid4())
        _seed(run_id)
        reg = _FakeRegistry()
        await run_service.start_run(run_id, "SCP-096", "t", reg)  # pauses at scenario gate

        task = asyncio.create_task(run_service.resume_run(run_id, "scenario", "approve", reg))
        for _ in range(200):
            if _load(run_id).status == "running":
                break
            await asyncio.sleep(0.005)
        # AC6: truthful "running" while image (the next stage) is still executing —
        # not the stale "awaiting_approval" that resume_run used to leave behind.
        assert _load(run_id).status == "running"

        gate.set()
        await task
        assert _load(run_id).status == "awaiting_approval"  # settles at the image gate as before
    finally:
        await saver.conn.close()
        run_service._graph = None
        run_service._configs.clear()
        db._engine = None


# ── SYS-INT-007 / AD-10: Langfuse client raises → stage completes, error logged ──


class _RaisingClient:
    """Stands in for get_client() when the real Langfuse client can't reach the server."""

    def start_as_current_observation(self, *a, **k):
        raise ConnectionError("langfuse host unreachable")

    def create_trace_id(self, *, seed=None):
        return seed or ""


async def test_trace_setup_failure_is_non_fatal_and_logged(env, monkeypatch, caplog):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    monkeypatch.setattr(run_service, "get_client", lambda: _RaisingClient())

    with caplog.at_level("WARNING", logger="yt_flow.services.run_service"):
        await run_service.start_run(run_id, "SCP-096", "t", reg)

    run = _load(run_id)
    assert run.status == "awaiting_approval"  # pipeline unaffected by the tracing failure
    assert any("Langfuse" in r.message for r in caplog.records)  # AD-10: error is logged


async def test_trace_teardown_failure_is_non_fatal_and_logged(env, monkeypatch, caplog):
    class _RaisingExitSpan:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            raise ConnectionError("flush failed")

    class _RaisingExitClient:
        def start_as_current_observation(self, *a, **k):
            return _RaisingExitSpan()

        def create_trace_id(self, *, seed=None):
            return seed or ""

    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    monkeypatch.setattr(run_service, "get_client", lambda: _RaisingExitClient())

    with caplog.at_level("WARNING", logger="yt_flow.services.run_service"):
        await run_service.start_run(run_id, "SCP-096", "t", reg)

    run = _load(run_id)
    assert run.status == "awaiting_approval"  # pipeline unaffected by the tracing failure
    assert any("Langfuse" in r.message for r in caplog.records)  # AD-10: error is logged


async def test_stage_failure_marks_run_failed(env, monkeypatch, tmp_path):
    # The silent-failure bug (live 2026-07-03): a stage that sets state["error"]
    # must mark the run failed + gate_states[stage]="failed" (retryable via the
    # existing retry endpoint), publish run_failed, and never offer a gate.
    from yt_flow.pipeline import nodes

    async def failing_scenario(state):
        return {"current_stage": "scenario", "error": "stage=scenario run_id=r: boom"}

    monkeypatch.setitem(nodes.STAGE_NODES, "scenario", failing_scenario)
    settings = Settings(
        langfuse_host="http://localhost", langfuse_public_key="pk",
        langfuse_secret_key="sk", db_path=str(tmp_path / "cp-fail.db"),
    )
    saver = await run_service.init(settings)  # rebuild graph with the failing node
    try:
        run_id = str(uuid.uuid4())
        _seed(run_id)
        reg = _FakeRegistry()

        await run_service.start_run(run_id, "SCP-096", "t", reg)

        run = _load(run_id)
        assert run.status == "failed"
        assert "boom" in (run.error or "")
        assert json.loads(run.gate_states)["scenario"] == "failed"
        failed = _kinds(reg, "run_failed")
        assert failed and failed[0]["data"]["stage"] == "scenario"
        assert _stages(reg, "gate_pending") == []  # no gate for a failed stage
        assert run_id not in run_service._configs
    finally:
        await saver.conn.close()


# ── Story 12.3: pass-2 quality context through SSE + artifacts + clearing ─────

_QUALITY = {
    "final_pass_index": 2,
    "retry_scope": "scene",
    "review_overall_pass": False,
    "critic_verdict": "retry",
    "critic_feedback": "장면 2가 늘어집니다",
    "rule_metrics": {
        "aggregate": {"character_count": 120, "sentence_count": 8,
                      "duplicate_sentence_count": 1, "repeated_4gram_count": 0},
        "scenes": [], "repeated_ngrams": [], "slop_phrase_hits": [], "slop_vocabulary_version": 1,
    },
    "grounded_contradictions": [],
    "review_issues": [],
    "outline_grounding": [{"scene_num": 4, "code": "event_unsupported", "detail": "…"}],
    "warning": {
        "code": "unresolved_pass2", "message": "확인 후 승인하세요",
        # Story 12.8: the reason a pass-2 warning may be unfixable by another repair.
        "outline_originated": {"scenes": [4], "note": "씬 리페어로는 고칠 수 없습니다"},
    },
}

_SCENE = {
    "scene_num": 1, "narration": "문장.", "shots": [], "audio_path": None,
    "audio_duration": None, "word_timings": [], "subtitle_path": None,
    "mood": "escalation", "title": "", "kicker": "", "display_narration": "문장.",
}


@pytest.fixture
def quality_scenario(monkeypatch):
    """A scenario stage that reports an unresolved pass-2 on its FIRST execution and a
    clean result on every later one.

    Tests using it must list `stub_stage_nodes, quality_scenario, env` in that order:
    `build_graph` binds node callables at build time, so this has to land after the
    blanket stub and before `env` compiles the graph.

    The "clean on re-run" half is what makes the clearing assertion meaningful — the
    second update omits `scenario_quality` entirely, so only an explicit clear can
    turn it back to None.
    """
    from yt_flow.pipeline import nodes

    runs = {"n": 0}

    async def node(state):
        runs["n"] += 1
        update = {"current_stage": "scenario", "error": None, "scenes": [dict(_SCENE)]}
        if runs["n"] == 1:
            update["scenario_quality"] = copy.deepcopy(_QUALITY)
        return update

    monkeypatch.setitem(nodes.STAGE_NODES, "scenario", node)
    return runs


async def test_gate_pending_forwards_scenario_quality(stub_stage_nodes, quality_scenario, env):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()

    await run_service.start_run(run_id, "SCP-096", "scp text", reg)

    event = _kinds(reg, "gate_pending")[0]["data"]
    assert event["stage"] == "scenario"
    assert event["scenario_quality"]["warning"]["code"] == "unresolved_pass2"
    # DB projection stays a flat stage→string map — no schema change (AC6).
    assert json.loads(_load(run_id).gate_states) == {"scenario": "pending"}


async def test_gate_pending_omits_quality_when_absent(env):
    """Pre-12.3 scenario output: the payload is byte-identical to before.

    Exact-dict on purpose, and it stays exact after Story 13.1: this is the only guard
    that a CLEAN run's gate frame gained no keys at all. `env`'s offline seams now cover
    vision enrichment too, so provisioning here degrades for no reason and adds no
    `warnings`/`warning_count`.
    """
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)
    assert _kinds(reg, "gate_pending")[0]["data"] == {"run_id": run_id, "stage": "scenario"}


async def test_downstream_gate_pending_never_carries_quality(stub_stage_nodes, quality_scenario, env):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)
    reg.events.clear()

    await run_service.resume_run(run_id, "scenario", "approve", reg)

    assert _kinds(reg, "gate_pending")[0]["data"] == {"run_id": run_id, "stage": "image"}


async def test_artifacts_are_the_durable_authority_for_the_warning(stub_stage_nodes, quality_scenario, env):
    """AC6: a client that missed the SSE frame (or reloaded) still gets the warning."""
    run_id = str(uuid.uuid4())
    _seed(run_id)
    await run_service.start_run(run_id, "SCP-096", "t", None)  # no SSE registry at all

    artifacts = await run_service.get_stage_artifacts(run_id, "scenario")
    assert artifacts["scenario_quality"]["warning"]["code"] == "unresolved_pass2"
    # Repeated reads are stable — nothing consumed the warning.
    again = await run_service.get_stage_artifacts(run_id, "scenario")
    assert again["scenario_quality"] == artifacts["scenario_quality"]


async def test_retry_scenario_clears_stale_quality(stub_stage_nodes, quality_scenario, env):
    """AC8: the verdict describes the discarded draft, so it must not outlive it."""
    run_id = str(uuid.uuid4())
    _seed(run_id)
    await run_service.start_run(run_id, "SCP-096", "t", None)
    await run_service.resume_run(run_id, "scenario", "reject", None)  # → failed, retryable

    await run_service.retry_stage(run_id, "scenario", None)
    await asyncio.gather(*list(run_service._bg_tasks))  # the retry re-runs in the background

    assert quality_scenario["n"] == 2  # the clean re-run happened
    artifacts = await run_service.get_stage_artifacts(run_id, "scenario")
    assert artifacts["scenario_quality"] is None


async def test_full_restart_clears_stale_quality(stub_stage_nodes, quality_scenario, env):
    run_id = str(uuid.uuid4())
    _seed(run_id)
    await run_service.start_run(run_id, "SCP-096", "t", None)

    await run_service.full_restart_run(run_id, None)

    assert quality_scenario["n"] == 2
    artifacts = await run_service.get_stage_artifacts(run_id, "scenario")
    assert artifacts["scenario_quality"] is None


def test_nullify_clears_quality_only_for_scenario():
    assert run_service._nullify("scenario", [])["scenario_quality"] is None
    assert "scenario_quality" not in run_service._nullify("image", [dict(_SCENE)])
    assert "scenario_quality" not in run_service._nullify("video", [dict(_SCENE)])


def test_initial_state_starts_with_no_quality():
    assert run_service._initial_state("r", "SCP-096", "t")["scenario_quality"] is None


# Story 12.4 — the selected archetype is scenario-owned state, cleared on exactly
# the same boundary as the quality verdict.


def test_nullify_clears_the_archetype_only_for_scenario():
    update = run_service._nullify("scenario", [])
    assert update["story_archetype"] is None
    assert update["story_archetype_fallback_used"] is False
    for stage in ("image", "tts", "subtitle", "video"):
        downstream = run_service._nullify(stage, [dict(_SCENE)])
        assert "story_archetype" not in downstream, stage
        assert "story_archetype_fallback_used" not in downstream, stage


def test_initial_state_starts_with_no_archetype():
    state = run_service._initial_state("r", "SCP-096", "t")
    assert state["story_archetype"] is None
    assert state["story_archetype_fallback_used"] is False


@pytest.fixture
def archetype_scenario(monkeypatch):
    """A scenario stage that reports an archetype on its FIRST run and FAILS on the
    next — so a stale selection surviving the rerun would be visible."""
    from yt_flow.pipeline import nodes

    runs = {"n": 0}

    async def node(state):
        runs["n"] += 1
        if runs["n"] == 1:
            return {
                "current_stage": "scenario", "error": None, "scenes": [dict(_SCENE)],
                "story_archetype": "discovery_log", "story_archetype_fallback_used": True,
            }
        return {"current_stage": "scenario", "error": "stage=scenario run_id=x: boom"}

    monkeypatch.setitem(nodes.STAGE_NODES, "scenario", node)
    return runs


async def test_failed_scenario_retry_cannot_retain_the_previous_archetype(
    stub_stage_nodes, archetype_scenario, env,
):
    """AC8: the rerun failed, so state must show the new error and NO archetype —
    never the discarded draft's template sitting beside it."""
    run_id = str(uuid.uuid4())
    _seed(run_id)
    await run_service.start_run(run_id, "SCP-096", "t", None)
    await run_service.resume_run(run_id, "scenario", "reject", None)  # → failed, retryable

    await run_service.retry_stage(run_id, "scenario", None)
    await asyncio.gather(*list(run_service._bg_tasks))

    assert archetype_scenario["n"] == 2
    snap = await run_service._graph.aget_state({"configurable": {"thread_id": run_id}})
    assert snap.values["error"]  # the rerun really did fail
    assert snap.values.get("story_archetype") is None
    assert not snap.values.get("story_archetype_fallback_used")


async def test_edit_scenario_artifact_writes_both_narration_tracks(env):
    """A hand edit must reach subtitles too, not just TTS.

    ``display_narration`` is what the subtitle stage renders and ``narration`` is
    what TTS speaks (Story 5.18). Writing only the latter left live run e5ed4b3a
    shipping captions that still carried a stage direction the narrator no longer
    read — audio and subtitles disagreed on *content*, not just wording. The
    spoken track also gets SCP designations spelled, matching what
    ``tts_normalize_step`` produces for generated scenes.
    """
    run_id = str(uuid.uuid4())
    _seed(run_id)
    reg = _FakeRegistry()
    await run_service.start_run(run_id, "SCP-096", "t", reg)

    config = run_service._configs[run_id]
    await run_service._graph.aupdate_state(
        config,
        {"scenes": [{"scene_num": 1, "narration": "옛 문장.", "display_narration": "옛 문장.",
                     "audio_path": None, "audio_duration": None, "word_timings": [],
                     "subtitle_path": None, "shots": []}]},
        as_node="scenario",
    )

    body = "재단이 그에게 붙인 번호는, SCP-049입니다."
    await run_service.edit_artifact(run_id, "scenario", body, 1)

    scene = (await run_service._graph.aget_state(config)).values["scenes"][0]
    assert scene["display_narration"] == body            # subtitles: the readable form
    assert "에스씨피 공사구" in scene["narration"]        # TTS: spelled designation
    assert "SCP-049" not in scene["narration"]
