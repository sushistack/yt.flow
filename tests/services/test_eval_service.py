"""Unit tests for src/yt_flow/services/eval_service.py (Story 4.2).

No live DeepSeek / Langfuse / DB: the LLM call, prompt fetch, settings, trace
sink, and checkpoint/run-table reads are all faked. Rule-based metrics run
against the real PipelineState fixtures (pure functions, exact assertions).
"""

import json

import aiosqlite
import httpx
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from sqlmodel import Session

from yt_flow import db
from yt_flow.db.models import Run
from yt_flow.domain.state import PipelineState
from yt_flow.services import eval_service as es
from tests.services.fixtures import eval_pipeline_states as fx


# ── Fakes / wiring ──────────────────────────────────────────────────────────

class FakeSettings:
    deepseek_api_key = "sk-test"
    deepseek_base_url = "https://api.deepseek.com"
    deepseek_model = "deepseek-v4-flash"
    deepseek_judge_model = "deepseek-v4-flash"
    deepseek_max_tokens = 8192
    db_path = "unused-mocked.db"


class _Tmpl:
    """Fake Prompt Hub prompt: compile() serializes name+vars so the fake
    _post_chat can decide a response deterministically."""

    def __init__(self, name):
        self.name = name

    def compile(self, **kw):
        return json.dumps({"prompt": self.name, **kw})


def _wire(monkeypatch, score_fn, winner_fn=None):
    """Install fake prompt fetch + fake LLM. score_fn(content, axis)->int,
    winner_fn(first, second)->'first'|'second'|'tie'."""
    monkeypatch.setattr(es, "get_prompt", lambda name: _Tmpl(name))
    monkeypatch.setattr(es, "_settings", lambda: FakeSettings())

    async def fake_post(rendered, model, s, *, timeout=es.JUDGE_TIMEOUT_SEC):
        req = json.loads(rendered)
        if req["prompt"] == es.JUDGE_PROMPT:
            return json.dumps({"axis": req["axis"], "chain_of_thought": "x",
                               "score": score_fn(req["artifact_content"], req["axis"])})
        winner = winner_fn(req["content_first"], req["content_second"])
        return json.dumps({"winner": winner, "reason": "x"})

    monkeypatch.setattr(es, "_post_chat", fake_post)


def _is_a(content: str) -> bool:
    return "Containment begins" in content


# ── Rule-based metrics (AC2) — exact, pure ──────────────────────────────────

def test_compute_rule_metrics_exact():
    ma, mb = es._compute_rule_metrics(fx.state_a(), fx.state_b())
    assert ma.scene_count == 2 and mb.scene_count == 3
    # scene_count_match_rate is symmetric across the pair
    assert ma.scene_count_match_rate == pytest.approx(2 / 3)
    assert mb.scene_count_match_rate == pytest.approx(2 / 3)
    assert ma.avg_subtitle_sync_error == pytest.approx(0.35)   # mean(0.2, 0.5)
    assert mb.avg_subtitle_sync_error == pytest.approx(0.1)
    assert ma.audio_duration_variance_pct == pytest.approx(25.0)  # pstdev(3,5)/4*100
    assert mb.audio_duration_variance_pct == pytest.approx(0.0)   # all equal


def test_scene_count_match_rate_edges():
    assert es._scene_count_match_rate(3, 3) == 1.0
    assert es._scene_count_match_rate(0, 0) == 1.0   # no div-by-zero
    assert es._scene_count_match_rate(2, 4) == pytest.approx(0.5)


def test_subtitle_sync_zero_without_timings():
    s = fx.state_a()
    for sc in s["scenes"]:
        sc["word_timings"] = []
    assert es._avg_subtitle_sync_error(s["scenes"]) == 0.0


# ── Score parsing (AC1) ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ('{"score": 4}', 4),
    ('{"score": "5"}', 5),      # string coerced
])
def test_parse_score_ok(raw, expected):
    assert es._parse_score(raw, "atmosphere") == expected


@pytest.mark.parametrize("raw", [
    "not json",
    '{"nope": 1}',        # missing key
    '{"score": 0}',       # out of range
    '{"score": 6}',
    '{"score": true}',    # bool rejected
    '{"score": 3.0}',     # prompt requires integer, not float
    '{"score": 4.6}',
])
def test_parse_score_rejects(raw):
    with pytest.raises(es.EvalJudgeError):
        es._parse_score(raw, "atmosphere")


async def test_judge_score_once_retries_malformed_response(monkeypatch):
    calls = {"n": 0}

    async def fake_post(*a, **k):
        calls["n"] += 1
        return '{"score": 4.6}' if calls["n"] == 1 else '{"score": 4}'

    monkeypatch.setattr(es, "_post_chat", fake_post)
    assert await es._judge_score_once("prompt", "atmosphere", FakeSettings()) == 4
    assert calls["n"] == 2


# ── Pairwise + winner logic (AC3, AC4) ──────────────────────────────────────

async def _pairwise(monkeypatch, score_fn, winner_fn):
    _wire(monkeypatch, score_fn, winner_fn)
    scores_a = await es._score_run("scp", "Containment begins.", FakeSettings())
    scores_b = await es._score_run("scp", "Statue contained.", FakeSettings())
    ma, mb = es._compute_rule_metrics(fx.state_a(), fx.state_b())
    return await es._pairwise_compare(
        "scp", "Containment begins.", "Statue contained.",
        scores_a, scores_b, ma, mb, "run-a", "run-b", FakeSettings())


async def test_pairwise_both_orders_agree(monkeypatch):
    # A wins in both A→B and B→A → A is final winner, no tiebreaker.
    res = await _pairwise(monkeypatch, lambda c, a: 4,
                          winner_fn=lambda first, second: "first" if _is_a(first) else "second")
    assert res.a_to_b_winner == "A" and res.b_to_a_winner == "A"
    assert res.tiebreaker_winner is None and res.final_winner == "A"


async def test_pairwise_contradiction_triggers_tiebreaker(monkeypatch):
    # Judge always prefers whatever it sees FIRST → A→B says A, B→A says B → contradiction.
    res = await _pairwise(monkeypatch, lambda c, a: 4,
                          winner_fn=lambda first, second: "first")
    assert res.a_to_b_winner == "A" and res.b_to_a_winner == "B"
    assert res.tiebreaker_winner == "A"   # 3rd run (A shown first) → A
    assert res.final_winner == "A"


async def test_pairwise_both_tie_uses_rule_tiebreak(monkeypatch):
    # Both orders tie → rule-based tiebreaker. B has lower sync error AND lower
    # audio variance → B wins the rule tiebreak.
    res = await _pairwise(monkeypatch, lambda c, a: 4, winner_fn=lambda f, s: "tie")
    assert res.a_to_b_winner == "tie" and res.b_to_a_winner == "tie"
    assert res.final_winner == "B"


async def test_pairwise_one_below_floor_short_circuits(monkeypatch):
    # Run B scores 1 on every axis → below floor → A wins with no LLM comparison.
    calls = {"n": 0}

    def winner_fn(f, s):
        calls["n"] += 1
        return "tie"

    res = await _pairwise(monkeypatch,
                          score_fn=lambda c, a: 1 if not _is_a(c) else 4,
                          winner_fn=winner_fn)
    assert res.final_winner == "A"
    assert res.below_floor == ["run-b"]
    assert calls["n"] == 0   # no pairwise LLM call made


async def test_pairwise_both_below_floor(monkeypatch):
    res = await _pairwise(monkeypatch, score_fn=lambda c, a: 1, winner_fn=lambda f, s: "tie")
    assert res.final_winner is None
    assert set(res.below_floor) == {"run-a", "run-b"}


def test_rule_tiebreak_prefers_lower_error():
    ma, mb = es._compute_rule_metrics(fx.state_a(), fx.state_b())  # B is cleaner
    assert es._rule_tiebreak(ma, mb) == "B"  # B passes sync+variance thresholds
    assert es._rule_tiebreak(ma, ma) == "tie"


# ── Precondition validation (AC7) ───────────────────────────────────────────

@pytest.fixture
def _memdb():
    db.init("sqlite://")
    yield
    db._engine = None


def _seed_run(run_id, status="complete", ab_pair_id=None):
    with Session(db._engine) as session:
        session.add(Run(id=run_id, scp_id="SCP-173", status=status, ab_pair_id=ab_pair_id))
        session.commit()


def test_validate_pair_ok_story_4_1_directional_link(_memdb):
    _seed_run("run-a")
    _seed_run("run-b", ab_pair_id="run-a")
    assert es._validate_pair("run-a", "run-b") == "run-a"


def test_validate_pair_missing_run(_memdb):
    _seed_run("run-a")
    with pytest.raises(ValueError, match="run-b: not found"):
        es._validate_pair("run-a", "run-b")


def test_validate_pair_not_complete(_memdb):
    _seed_run("run-a")
    _seed_run("run-b", status="running", ab_pair_id="run-a")
    with pytest.raises(ValueError, match="run-b: status is 'running'"):
        es._validate_pair("run-a", "run-b")


def test_validate_pair_mismatched_ab_id(_memdb):
    _seed_run("run-a", ab_pair_id="pair-1")
    _seed_run("run-b", ab_pair_id="pair-2")
    with pytest.raises(ValueError, match="not a valid A/B pair"):
        es._validate_pair("run-a", "run-b")


def test_validate_pair_null_ab_id(_memdb):
    _seed_run("run-a", ab_pair_id=None)
    _seed_run("run-b", ab_pair_id=None)
    with pytest.raises(ValueError, match="not a valid A/B pair"):
        es._validate_pair("run-a", "run-b")


# ── Checkpoint state loading (AC7) ──────────────────────────────────────────

async def _seed_checkpoint(db_path: str, run_id: str, values: PipelineState) -> None:
    conn = await aiosqlite.connect(db_path)
    saver = AsyncSqliteSaver(conn)
    await saver.setup()

    async def node(state):
        return values

    g = StateGraph(PipelineState)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    graph = g.compile(checkpointer=saver)
    await graph.ainvoke(values, {"configurable": {"thread_id": run_id}})
    await conn.close()


async def test_load_state_ok(tmp_path):
    p = str(tmp_path / "cp.db")
    await _seed_checkpoint(p, "run-a", fx.state_a("run-a"))
    state = await es._load_state("run-a", p)
    assert state["run_id"] == "run-a"
    assert len(state["scenes"]) == 2


async def test_load_state_missing_checkpoint(tmp_path):
    p = str(tmp_path / "cp.db")
    await _seed_checkpoint(p, "run-a", fx.state_a("run-a"))
    with pytest.raises(ValueError, match="ghost: no LangGraph checkpoint"):
        await es._load_state("ghost", p)


async def test_load_state_malformed_no_scenes(tmp_path):
    p = str(tmp_path / "cp.db")
    bad = fx.state_a("run-x")
    bad["scenes"] = []
    await _seed_checkpoint(p, "run-x", bad)
    with pytest.raises(ValueError, match="run-x: checkpoint has no 'scenes'"):
        await es._load_state("run-x", p)


async def test_load_state_malformed_scene_without_narration(tmp_path):
    p = str(tmp_path / "cp.db")
    bad = fx.state_a("run-x")
    bad["scenes"][0]["narration"] = ""
    await _seed_checkpoint(p, "run-x", bad)
    with pytest.raises(ValueError, match="run-x: checkpoint scene 0 has no narration"):
        await es._load_state("run-x", p)


async def test_load_state_malformed_no_video_path(tmp_path):
    p = str(tmp_path / "cp.db")
    bad = fx.state_a("run-x")
    bad["video_path"] = None
    await _seed_checkpoint(p, "run-x", bad)
    with pytest.raises(ValueError, match="run-x: checkpoint 'video_path' missing"):
        await es._load_state("run-x", p)


# ── _post_chat timeout retry (AC5) ──────────────────────────────────────────

class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _FakeClient:
    state: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        st = _FakeClient.state
        st["n"] += 1
        if st["n"] <= st["fail"]:
            raise httpx.TimeoutException("timed out")
        return _Resp(st["payload"])


async def test_post_chat_retries_once_on_timeout(monkeypatch):
    _FakeClient.state = {"n": 0, "fail": 1,
                         "payload": {"choices": [{"message": {"content": '{"score":4}'}}]}}
    monkeypatch.setattr(es.httpx, "AsyncClient", _FakeClient)
    out = await es._post_chat("prompt", "model", FakeSettings())
    assert json.loads(out)["score"] == 4
    assert _FakeClient.state["n"] == 2   # first timed out, retry succeeded


async def test_post_chat_raises_after_second_timeout(monkeypatch):
    _FakeClient.state = {"n": 0, "fail": 2, "payload": {}}
    monkeypatch.setattr(es.httpx, "AsyncClient", _FakeClient)
    with pytest.raises(httpx.TimeoutException):
        await es._post_chat("prompt", "model", FakeSettings())
    assert _FakeClient.state["n"] == 2   # exactly two attempts, no third


# ── evaluate_ab orchestration (AC1–AC7) ─────────────────────────────────────

@pytest.fixture
def _no_trace(monkeypatch):
    # Isolate from Langfuse: trace lifecycle is exercised separately.
    monkeypatch.setattr(es, "_enter_trace", lambda ab_pair_id: None)
    monkeypatch.setattr(es, "_finish_trace", lambda *a: None)
    monkeypatch.setattr(es, "_exit_trace", lambda span: None)


async def test_evaluate_ab_end_to_end(monkeypatch, _memdb, _no_trace):
    _seed_run("run-a")
    _seed_run("run-b", ab_pair_id="run-a")
    monkeypatch.setattr(es, "_load_state",
                        lambda rid, dbp: _return(fx.state_a("run-a") if rid == "run-a" else fx.state_b("run-b")))
    # A scores 4 everywhere, B scores 3 → A above floor, B above floor; A wins pairwise.
    _wire(monkeypatch, score_fn=lambda c, a: 4 if _is_a(c) else 3,
          winner_fn=lambda first, second: "first" if _is_a(first) else "second")

    res = await es.evaluate_ab("run-a", "run-b")
    assert res.ab_pair_id == "run-a"
    assert res.scores_a.total == pytest.approx(12.0)   # 4×3 axes
    assert res.scores_b.total == pytest.approx(9.0)
    assert res.winner == "A" and res.winner_run_id == "run-a"
    assert res.metrics_a.scene_count == 2 and res.metrics_b.scene_count == 3


async def test_evaluate_ab_both_below_floor(monkeypatch, _memdb, _no_trace):
    _seed_run("run-a")
    _seed_run("run-b", ab_pair_id="run-a")
    monkeypatch.setattr(es, "_load_state",
                        lambda rid, dbp: _return(fx.state_a("run-a") if rid == "run-a" else fx.state_b("run-b")))
    _wire(monkeypatch, score_fn=lambda c, a: 1, winner_fn=lambda f, s: "tie")

    res = await es.evaluate_ab("run-a", "run-b")
    assert res.winner is None and res.winner_run_id is None
    assert res.reason == "both_below_floor"


async def test_evaluate_ab_validates_before_scoring(monkeypatch, _memdb, _no_trace):
    _seed_run("run-a", status="running")
    _seed_run("run-b", ab_pair_id="run-a")
    called = {"scored": False}

    def boom(*a, **k):
        called["scored"] = True
        raise AssertionError("scoring must not start before validation")

    monkeypatch.setattr(es, "_load_state", boom)
    monkeypatch.setattr(es, "_settings", lambda: FakeSettings())
    with pytest.raises(ValueError, match="run-a: status is 'running'"):
        await es.evaluate_ab("run-a", "run-b")
    assert called["scored"] is False


# ── Langfuse trace lifecycle (AC6, AD-10 non-fatal) ─────────────────────────

async def test_evaluate_ab_langfuse_failure_non_fatal(monkeypatch, _memdb):
    _seed_run("run-a")
    _seed_run("run-b", ab_pair_id="run-a")
    monkeypatch.setattr(es, "_load_state",
                        lambda rid, dbp: _return(fx.state_a("run-a") if rid == "run-a" else fx.state_b("run-b")))
    _wire(monkeypatch, score_fn=lambda c, a: 4, winner_fn=lambda f, s: "first")
    # get_client blows up everywhere the trace helpers touch it.
    monkeypatch.setattr(es, "get_client", lambda: (_ for _ in ()).throw(RuntimeError("langfuse down")))

    res = await es.evaluate_ab("run-a", "run-b")
    assert res.winner is not None            # evaluation unaffected by tracing failure
    assert res.langfuse_trace_url is None


def test_enter_trace_keys_on_ab_pair_id(monkeypatch):
    rec = {}

    class _FakeLF:
        def create_trace_id(self, *, seed=None):
            rec["seed"] = seed
            return f"trace-{seed}"

        def start_as_current_observation(self, *, name, as_type, trace_context):
            rec["ctx"] = trace_context

            class _Span:
                def __enter__(self_): return self_
                def __exit__(self_, *a): return False
            return _Span()

    monkeypatch.setattr(es, "get_client", lambda: _FakeLF())
    span = es._enter_trace("pair-1")
    assert span is not None
    assert rec["seed"] == "pair-1"
    assert rec["ctx"]["trace_id"] == "trace-pair-1"


def test_finish_trace_persists_full_evaluation_payload(monkeypatch):
    rec = {}

    class _FakeLF:
        def update_current_span(self, *, output, metadata):
            rec["output"] = output
            rec["metadata"] = metadata

        def get_trace_url(self):
            return "https://trace.local/t"

    result = es.EvaluationResult(
        ab_pair_id="run-a",
        run_a_id="run-a",
        run_b_id="run-b",
        scores_a=es.AxisScores(4, 4, 4, 12),
        scores_b=es.AxisScores(3, 3, 3, 9),
        metrics_a=es.RuleBasedMetrics(2, 1.0, 0.2, 5.0),
        metrics_b=es.RuleBasedMetrics(2, 1.0, 0.3, 7.0),
        pairwise=es.PairwiseResult("A", "A", None, "A", []),
        winner="A",
        winner_run_id="run-a",
        reason="run A preferred",
        langfuse_trace_url=None,
    )

    monkeypatch.setattr(es, "get_client", lambda: _FakeLF())
    assert es._finish_trace(object(), result) == "https://trace.local/t"
    assert rec["output"]["scores_a"]["total"] == 12
    assert rec["output"]["metrics_b"]["avg_subtitle_sync_error"] == 0.3
    assert rec["output"]["pairwise"]["final_winner"] == "A"
    assert rec["metadata"]["ab_pair_id"] == "run-a"


def _return(value):
    async def _coro():
        return value
    return _coro()
