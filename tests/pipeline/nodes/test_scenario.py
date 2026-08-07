"""Unit tests for src/yt_flow/pipeline/nodes/scenario.py orchestration (multi-stage
chain redesign — see docs/superpowers/specs/2026-07-03-scenario-multistage-design.md).

Per-stage parsing/validation is covered by test_scenario_chain.py; these tests
only cover scenario_node's own responsibility: sequencing, the bounded retry,
and surfacing errors as PipelineState.error.
"""

import json

import httpx
import pytest

import yt_flow.pipeline.nodes.scenario as sc
import yt_flow.pipeline.nodes.scenario_chain as chain

# Captured before the autouse `_isolate` fixture below monkeypatches
# `sc._record_trace` to a no-op — tests that exercise the real function call
# this reference directly instead of the (per-test) stubbed module attribute.
_real_record_trace = sc._record_trace


class FakeSettings:
    deepseek_api_key = "sk-test"
    deepseek_base_url = "https://api.deepseek.com"
    deepseek_model = "deepseek-v4-flash"
    deepseek_max_tokens = 8192
    deepseek_reasoning = "low"
    # Story 12.2 model split — the prose/judge provider.
    gemini_api_key = "gm-test-secret"
    gemini_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_writing_model = "gemini-3.6-flash"
    gemini_writing_max_tokens = 16384
    content_language = "ko"


class FakePrompt:
    def compile(self, **variables):
        return "rendered"


RESEARCH = {"core_identity": "x", "frozen_descriptor": "desc", "entity_sheet": "entity sheet", "story_logline": "logline", "dramatic_beats": "x", "environment": "x", "hooks": "x"}
# Story 12.1: structure entries now carry the retention contract, and the scoped
# repair is handed the matching positional subset — so the fixture has to look
# like a real outline entry, not just the fields build_scenes reads.
STRUCTURE = [{
    "scene_num": 1, "act": "hook", "synopsis": "x", "key_points": [], "emotional_beat": "tension",
    "estimated_duration_sec": 45, "mood": "escalation",
    "event": {"who": "경비원", "what": "격리실에 진입했다", "consequence": "통신이 끊겼다"},
    "hook_type": "shock", "loops_planted": ["loop_a", "loop_b"], "loops_closed": [],
    "pattern_interrupt": "tone_shift", "word_budget": 45,
    "fact_references": ["재단 인원 14명이 사망했다"],
}]
WRITING = {"scp_id": "SCP-173", "title": "t", "scenes": [{"scene_num": 1, "narration": "문장.", "location": "x", "characters_present": [], "color_palette": "x", "atmosphere": "x"}]}
VISUAL = [{"image_prompt": "shot", "negative_prompt": "neg", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}]
REVIEW_PASS = {"overall_pass": True, "coverage_pct": 90.0, "issues": [], "corrections": [], "storytelling_score": 80, "storytelling_issues": []}
REVIEW_FAIL = {**REVIEW_PASS, "overall_pass": False, "issues": [{"scene_num": 1, "description": "bad", "correction": "fix it"}]}
CRITIC_PASS = {"verdict": "pass", "feedback": "good", "scene_notes": []}
CRITIC_RETRY = {"verdict": "retry", "feedback": "다시 써주세요", "scene_notes": []}


def _retention_outline(total: int) -> list[dict]:
    """A contract-valid outline (word_budget 45 x 4 = the 180 floor at total=4)."""
    return [{
        **STRUCTURE[0], "scene_num": pos,
        "hook_type": "shock" if pos == 1 else "none",
        "loops_planted": ["loop_a", "loop_b"] if pos == 1 else [],
        "loops_closed": ["loop_a", "loop_b"] if pos == total else [],
        "pattern_interrupt": "tone_shift" if pos % 3 == 1 else "none",
        "word_budget": 45,
    } for pos in range(1, total + 1)]


def _state(**over):
    base = {
        "run_id": "run-123",
        "scp_id": "SCP-173",
        "scp_text": "SCP-173 is a concrete statue.",
        "scenes": [],
        "video_path": None,
        "current_stage": "",
        "gate_states": {},
        "prompt_variant": None,
        "error": None,
    }
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(sc, "_settings", lambda: FakeSettings())
    monkeypatch.setattr(sc, "_record_trace", lambda **kw: None)
    # scenario.py binds `get_prompt` via `from ... import get_prompt` (matches the
    # tests/conftest.py `stub_profile` fixture, which patches `scenario.get_prompt`
    # directly) — so the seam here must be the module-local name, not the
    # prompt_service module attribute.
    monkeypatch.setattr(sc, "get_prompt", lambda *a, **k: FakePrompt())


async def _async_return(value):
    return value


def _provider_name(args) -> str:
    """Which provider seam a substage was handed (Story 12.2 AC1). Identity against
    the module attributes, so a monkeypatched fake still resolves to its provider."""
    call = next((a for a in args if callable(a)), None)
    if call is sc._call_gemini:
        return "gemini"
    if call is sc._call_deepseek:
        return "deepseek"
    return f"unrouted:{call!r}"


def _stub_chain(monkeypatch, *, review=REVIEW_PASS, critic=CRITIC_PASS, review_retry=None, critic_retry=None, tts_normalize=None, providers=None):
    calls = {"research": 0, "structure": 0, "writing": 0, "repair": 0, "cast": 0, "visual": 0, "review": 0, "critic": 0, "tts_normalize": 0}

    def _note(stage, args):
        if providers is not None:
            providers.append((stage, _provider_name(args)))

    async def fake_research(*a, **k):
        calls["research"] += 1
        _note("research", a)
        return RESEARCH

    async def fake_structure(*a, **k):
        calls["structure"] += 1
        _note("structure", a)
        return STRUCTURE

    async def fake_writing(*a, **k):
        calls["writing"] += 1
        _note("writing", a)
        return WRITING

    async def fake_repair(*a, **k):
        calls["repair"] += 1
        _note("repair", a)
        return a[1]

    async def fake_cast_decision(*a, **k):
        calls["cast"] += 1
        _note("cast", a)
        return {}

    async def fake_visual(*a, **k):
        calls["visual"] += 1
        _note("visual", a)
        return VISUAL

    async def fake_review(*a, **k):
        calls["review"] += 1
        _note("review", a)
        return review_retry if (calls["writing"] > 1 and review_retry) else review

    async def fake_critic(*a, **k):
        calls["critic"] += 1
        _note("critic", a)
        return critic_retry if (calls["writing"] > 1 and critic_retry) else critic

    async def fake_tts_normalize(writing, *a, **k):
        calls["tts_normalize"] += 1
        _note("tts_normalize", a)
        return tts_normalize if tts_normalize is not None else writing

    monkeypatch.setattr(sc, "research_step", fake_research)
    monkeypatch.setattr(sc, "structure_step", fake_structure)
    monkeypatch.setattr(sc, "writing_step", fake_writing)
    monkeypatch.setattr(sc, "writing_scene_repair_step", fake_repair)
    monkeypatch.setattr(sc, "cast_decision_step", fake_cast_decision)
    monkeypatch.setattr(sc, "visual_breakdown_step", fake_visual)
    monkeypatch.setattr(sc, "review_step", fake_review)
    monkeypatch.setattr(sc, "critic_step", fake_critic)
    monkeypatch.setattr(sc, "tts_normalize_step", fake_tts_normalize)
    return calls


async def test_success_populates_scenes(monkeypatch):
    _stub_chain(monkeypatch)
    out = await sc.scenario_node(_state())
    assert out["current_stage"] == "scenario"
    assert out.get("error") is None
    assert len(out["scenes"]) == 1
    assert out["scenes"][0]["shots"][0]["image_prompt"] == "shot"
    assert out["scenes"][0]["mood"] == "escalation"


async def test_no_retry_when_critic_passes(monkeypatch):
    calls = _stub_chain(monkeypatch)
    await sc.scenario_node(_state())
    assert calls["writing"] == 1


async def test_retries_once_when_critic_says_retry(monkeypatch):
    calls = _stub_chain(monkeypatch, critic=CRITIC_RETRY, critic_retry=CRITIC_PASS)
    out = await sc.scenario_node(_state())
    assert calls["writing"] == 2  # exactly one retry, not an open loop
    assert calls["tts_normalize"] == 1  # normalizes once, after the retry settles
    assert out.get("error") is None


async def test_retries_once_when_review_fails(monkeypatch):
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL, review_retry=REVIEW_PASS)
    out = await sc.scenario_node(_state())
    assert calls["writing"] == 1
    assert calls["repair"] == 1
    assert calls["tts_normalize"] == 1  # normalizes once, after the retry settles
    assert out.get("error") is None


async def test_scoped_repair_preserves_metadata_and_repaired_fields_win(monkeypatch):
    _stub_chain(monkeypatch, review=REVIEW_FAIL)
    cast_scenes = []

    async def minimal_repair(*args, **kwargs):
        return [{"scene_num": 1, "narration": "수정된 문장.", "location": "repaired-location"}]

    async def capture_cast(_scp_id, scene, *args, **kwargs):
        cast_scenes.append(scene)
        return {}

    monkeypatch.setattr(sc, "writing_scene_repair_step", minimal_repair)
    monkeypatch.setattr(sc, "cast_decision_step", capture_cast)

    out = await sc.scenario_node(_state())

    assert out.get("error") is None
    scene = out["scenes"][0]
    assert scene["narration"] == "수정된 문장."
    repaired_scene = cast_scenes[-1]
    assert repaired_scene["location"] == "repaired-location"
    assert repaired_scene["characters_present"] == WRITING["scenes"][0]["characters_present"]
    assert repaired_scene["color_palette"] == WRITING["scenes"][0]["color_palette"]
    assert repaired_scene["atmosphere"] == WRITING["scenes"][0]["atmosphere"]


async def test_accepts_second_pass_result_even_if_still_failing(monkeypatch):
    # Bounded retry: even if the second pass ALSO comes back "retry", accept it —
    # never loop a third time.
    calls = _stub_chain(monkeypatch, critic=CRITIC_RETRY, critic_retry=CRITIC_RETRY)
    out = await sc.scenario_node(_state())
    assert calls["writing"] == 2
    assert out.get("error") is None
    assert out["scenes"]


def test_retry_scope_unions_valid_flags_and_records_rejections():
    scenes = [{"scene_num": 1}, {"scene_num": 2}, {"scene_num": 3}]
    review = {"issues": [{"scene_num": 2}, {"scene_num": 2}, {"scene_num": True}, {"scene_num": 0}]}
    critic = {"scene_notes": [{"scene_num": 3}, {"scene_num": -1}, {"scene_num": 9}, {"scene_num": "1"}]}
    indexes, rejected = sc._retry_scope(review, critic, scenes)
    assert indexes == [1, 2]
    assert [item["reason"] for item in rejected] == [
        "duplicate", "boolean", "non-positive", "non-positive", "out-of-range", "not-integer",
    ]


def test_retry_scope_rejects_scene_num_position_mismatch():
    # writing_step's own model-reported scene_num can drift from position (a tested
    # failure mode elsewhere in this chain, e.g. duplicate scene_num=1 twice) — a
    # review/critic reference to "scene_num 2" must not be trusted as position 1
    # unless the scene actually at position 1 agrees it is scene_num 2.
    scenes = [{"scene_num": 1}, {"scene_num": 1}]
    review = {"issues": [{"scene_num": 2}]}
    critic = {"scene_notes": []}
    indexes, rejected = sc._retry_scope(review, critic, scenes)
    assert indexes == []
    assert rejected == [{"source": "review", "scene_num": 2, "reason": "scene_num-mismatch"}]


async def test_batched_writing_output_satisfies_the_retry_scope_scene_num_guard(monkeypatch):
    """The real (per-scene batched) writing_step feeding the real _retry_scope.

    Each writing call now sees exactly one scene, so the model answers
    ``scene_num: 1`` for every scene — if writing_step passed that through, the
    6.5/6.6 mismatch guard would reject every reviewer reference past scene 1 and
    the scoped repair would silently degrade to a full rewrite forever. Position
    is therefore the sole source of scene_num.
    """
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    structure = [{"scene_num": i + 1, "act": "act", "synopsis": f"syn{i + 1}", "mood": "dread"} for i in range(4)]

    async def call(rendered, s):
        return "scenes:\n  - scene_num: 1\n    narration: 문장.\n    location: chamber\n    color_palette: grey\n    atmosphere: tense\n", {}, "stop"

    writing = await sc.writing_step("SCP-173", structure, "desc", "guide", "", FakeSettings(), call)
    assert [scene["scene_num"] for scene in writing["scenes"]] == [1, 2, 3, 4]

    review = {"issues": [{"scene_num": 3, "description": "bad", "correction": "fix"}]}
    indexes, rejected = sc._retry_scope(review, {"scene_notes": [{"scene_num": 4}]}, writing["scenes"])
    assert indexes == [2, 3]
    assert rejected == []


async def test_a_truncation_the_chain_cannot_absorb_still_fails_the_run(monkeypatch):
    """The re-roll lives inside `_call_stage_with_retry` (tested in
    test_scenario_chain.py, which drives the real stage against a truncating
    DeepSeek). Here the step is stubbed, so the escaping TruncationError stands
    for a stage that already re-rolled and truncated again: the run must fail
    loudly, and scenario_node must not add a re-roll of its own."""
    _stub_chain(monkeypatch)
    attempts = {"n": 0}

    async def always_truncating(*a, **k):
        attempts["n"] += 1
        raise sc.TruncationError("truncated", prompt_name="scenario/structure", completion_tokens=32768)

    monkeypatch.setattr(sc, "structure_step", always_truncating)
    out = await sc.scenario_node(_state())
    assert "truncated" in out["error"]
    assert attempts["n"] == 1, "scenario_node no longer wraps structure — the chain owns the re-roll"


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeHttpClient:
    def __init__(self, payload):
        self._payload = payload
        self.sent = None  # request body of the last post, for request-shape assertions

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        self.sent = kwargs.get("json")
        return _FakeResponse(self._payload)


async def test_call_deepseek_falls_back_to_reasoning_content_when_truncated(monkeypatch):
    """Root cause of the 0-byte truncation dumps: a reasoning model cut off
    mid-reasoning returns content="" with every token in reasoning_content, so
    returning only `content` threw the runaway evidence away."""
    payload = {
        "choices": [{
            "finish_reason": "length",
            "message": {"content": "", "reasoning_content": "runaway chain of thought"},
        }],
        "usage": {"completion_tokens": 32768},
    }
    monkeypatch.setattr(sc.httpx, "AsyncClient", lambda **kw: _FakeHttpClient(payload))
    raw, usage, finish_reason = await sc._call_deepseek("rendered", FakeSettings())
    assert (raw, finish_reason) == ("runaway chain of thought", "length")
    assert usage["completion_tokens"] == 32768


async def test_call_deepseek_ignores_reasoning_content_on_a_complete_response(monkeypatch):
    payload = {
        "choices": [{
            "finish_reason": "stop",
            "message": {"content": "scenes: []", "reasoning_content": "thinking out loud"},
        }],
        "usage": {},
    }
    monkeypatch.setattr(sc.httpx, "AsyncClient", lambda **kw: _FakeHttpClient(payload))
    raw, _, finish_reason = await sc._call_deepseek("rendered", FakeSettings())
    assert (raw, finish_reason) == ("scenes: []", "stop")


@pytest.mark.parametrize("setting,expected", [
    ("low", {"reasoning_effort": "low"}),
    ("medium", {"reasoning_effort": "medium"}),
    ("high", {"reasoning_effort": "high"}),
    ("disabled", {"thinking": {"type": "disabled"}}),  # the only form that probed reasoning_tokens=0
    ("default", {}),  # API default → send neither field, request unchanged
])
async def test_call_deepseek_sends_one_reasoning_field_per_setting(monkeypatch, setting, expected):
    payload = {"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}], "usage": {}}
    client = _FakeHttpClient(payload)
    monkeypatch.setattr(sc.httpx, "AsyncClient", lambda **kw: client)

    class S(FakeSettings):
        deepseek_reasoning = setting

    await sc._call_deepseek("rendered", S())
    body = client.sent
    assert {k: body[k] for k in ("reasoning_effort", "thinking") if k in body} == expected
    assert body["max_tokens"] == 8192  # batching/budget untouched by the reasoning knob


async def test_scene_retry_repairs_only_flagged_position_and_reuses_other_objects(monkeypatch):
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL, review_retry=REVIEW_PASS)
    original_scene = WRITING["scenes"][0]
    repaired = {**original_scene, "narration": "수정된 문장."}

    async def fake_repair(*a, **k):
        calls["repair"] += 1
        return [repaired]

    monkeypatch.setattr(sc, "writing_scene_repair_step", fake_repair)
    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert out["scenes"][0]["narration"] == "수정된 문장."
    assert calls["writing"] == 1
    assert calls["repair"] == 1
    assert calls["cast"] == 2 and calls["visual"] == 2


async def test_critic_only_flag_triggers_scene_scoped_repair(monkeypatch):
    # review passes outright; only critic flags a scene — must still scope, not full-fallback.
    critic_flagged = {"verdict": "retry", "feedback": "다시", "scene_notes": [{"scene_num": 1, "feedback": "고쳐주세요"}]}
    calls = _stub_chain(monkeypatch, review=REVIEW_PASS, critic=critic_flagged)
    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert calls["writing"] == 1
    assert calls["repair"] == 1


async def test_second_review_failure_after_scene_repair_remains_bounded(monkeypatch):
    # review fails identically on both the initial pass and the scoped-repair pass —
    # the scoped-repair branch must accept the second result rather than retry a third time.
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL)
    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert calls["writing"] == 1
    assert calls["repair"] == 1
    assert calls["review"] == 2


async def test_scene_repair_trace_fields_and_usage_recorded(monkeypatch):
    _stub_chain(monkeypatch, review=REVIEW_FAIL, review_retry=REVIEW_PASS)
    trace_sink: list[dict] = []
    out = await sc.scenario_node(_state(), trace_sink=trace_sink)
    assert out["error"] is None
    scene_stages = [s for s in trace_sink if s.get("retry_scope") == "scene"]
    repair_stage_names = {"writing_scene_repair", "visual_breakdown", "review", "critic_agent"}
    assert repair_stage_names <= {s["name"] for s in scene_stages}
    assert all(s["pass_index"] == 2 for s in scene_stages)
    assert all(s["target_scene_indexes"] == [0] for s in scene_stages)
    for field in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
        assert all(field in s for s in scene_stages)


async def test_no_valid_scene_uses_explicit_full_fallback_trace(monkeypatch):
    calls = _stub_chain(monkeypatch, critic=CRITIC_RETRY, critic_retry=CRITIC_PASS)
    trace_sink: list[dict] = []
    out = await sc.scenario_node(_state(), trace_sink=trace_sink)
    assert out["error"] is None and calls["writing"] == 2 and calls["repair"] == 0
    retry_stages = [stage for stage in trace_sink if stage.get("pass_index") == 2]
    assert retry_stages
    assert all(stage["retry_scope"] == "full-fallback" for stage in retry_stages)
    assert retry_stages[0]["rejected_scene_identifiers"][0]["reason"] == "no-valid-scene"


async def test_scene_repair_truncation_falls_back_to_full_rewrite(monkeypatch):
    # Story 6.9: scoped repair can run away past max_tokens even though a full
    # rewrite of every scene fits — a TruncationError from repair must recover
    # via the full-rewrite path, not fail the whole run.
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL, review_retry=REVIEW_PASS)

    async def truncating_repair(*a, **k):
        calls["repair"] += 1
        raise sc.TruncationError(
            "scenario/writing_scene_repair response truncated (finish_reason=length); raise max_tokens",
            prompt_name="scenario/writing_scene_repair", completion_tokens=16000, raw="가" * 5000,
        )

    monkeypatch.setattr(sc, "writing_scene_repair_step", truncating_repair)
    trace_sink: list[dict] = []
    out = await sc.scenario_node(_state(), trace_sink=trace_sink)

    assert out["error"] is None
    assert out["scenes"]  # produced scenes via the fallback, not a failed run
    assert calls["repair"] == 1  # tried the scoped repair exactly once
    assert calls["writing"] == 2  # then the full rewrite regenerated everything
    retry_stages = [s for s in trace_sink if s.get("pass_index") == 2]
    assert retry_stages
    assert all(s["retry_scope"] == "scene-repair-truncated-fallback" for s in retry_stages)
    assert retry_stages[0]["rejected_scene_identifiers"][0]["reason"] == "scene-repair-truncated"
    # the fallback rewrote every scene, so the tts_normalize trace must not advertise
    # the pre-fallback flagged subset (mirrors the full-fallback branch's empty scope)
    tts_stage = next(s for s in trace_sink if s["name"] == "tts_normalize")
    assert tts_stage["target_scene_count"] == 0


async def test_downstream_stage_truncation_in_repair_pass_fails_run(monkeypatch):
    # Story 6.9 review: recovery is narrow — only writing_scene_repair truncation
    # falls back. A truncation in the repair pass's review/critic/visual/cast
    # stages (all raise TruncationError too) must fail the run, never silently
    # trigger a full rewrite.
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL, review_retry=REVIEW_PASS)
    review_calls = {"n": 0}

    async def truncating_review(*a, **k):
        review_calls["n"] += 1
        if review_calls["n"] == 1:
            return REVIEW_FAIL  # pass-1 review fails → enter scoped repair
        raise sc.TruncationError(
            "scenario/review response truncated (finish_reason=length); raise max_tokens",
            prompt_name="scenario/review", completion_tokens=16000, raw="가" * 100,
        )

    monkeypatch.setattr(sc, "review_step", truncating_review)
    out = await sc.scenario_node(_state())

    assert out["error"] and "stage=scenario" in out["error"]
    assert "scenes" not in out
    assert calls["repair"] == 1   # scoped repair itself ran
    assert calls["writing"] == 1  # but NO full-rewrite fallback fired


async def test_non_truncation_repair_error_still_surfaces_as_error(monkeypatch):
    # The recovery set is narrow (Story 6.9/6.10): only writing_scene_repair
    # truncation and a genuine coverage mismatch fall back. Any OTHER repair
    # failure (here: empty narration) still propagates as a run error, never
    # silently swallowed into a full rewrite.
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL, review_retry=REVIEW_PASS)

    async def boom_repair(*a, **k):
        calls["repair"] += 1
        raise ValueError("writing_scene_repair: scene[1] has empty narration")

    monkeypatch.setattr(sc, "writing_scene_repair_step", boom_repair)
    out = await sc.scenario_node(_state())

    assert out["error"] and "stage=scenario" in out["error"]
    assert "scenes" not in out
    assert calls["repair"] == 1
    assert calls["writing"] == 1  # no fallback full rewrite fired


async def test_scene_repair_coverage_mismatch_falls_back_to_full_rewrite(monkeypatch):
    # Story 6.10: SCP-049's scoped repair intermittently returns a scene set it
    # can't map back (SceneCoverageError). Like truncation, that must recover via
    # a full rewrite so the item stays scoreable, not fail the whole run.
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL, review_retry=REVIEW_PASS)

    async def mismatching_repair(*a, **k):
        calls["repair"] += 1
        raise sc.SceneCoverageError(
            "writing_scene_repair: scene coverage mismatch; expected [3, 2] got [2, 3]",
            prompt_name="scenario/writing_scene_repair",
        )

    monkeypatch.setattr(sc, "writing_scene_repair_step", mismatching_repair)
    trace_sink: list[dict] = []
    out = await sc.scenario_node(_state(), trace_sink=trace_sink)

    assert out["error"] is None
    assert out["scenes"]  # produced scenes via the fallback, not a failed run
    assert calls["repair"] == 1  # tried the scoped repair exactly once
    assert calls["writing"] == 2  # then the full rewrite regenerated everything
    retry_stages = [s for s in trace_sink if s.get("pass_index") == 2]
    assert retry_stages
    assert all(s["retry_scope"] == "scene-repair-coverage-fallback" for s in retry_stages)
    tts_stage = next(s for s in trace_sink if s["name"] == "tts_normalize")
    assert tts_stage["target_scene_count"] == 0


async def test_eight_scenes_one_flag_adds_exactly_five_calls_and_preserves_unflagged(monkeypatch):
    structure = [{**STRUCTURE[0], "scene_num": i + 1} for i in range(8)]
    writing = {
        **WRITING,
        "scenes": [{**WRITING["scenes"][0], "scene_num": i + 1, "narration": f"문장 {i + 1}."} for i in range(8)],
    }
    visuals = [[{**VISUAL[0], "image_prompt": f"shot-{i + 1}"}] for i in range(8)]
    counts = {"repair": 0, "cast": 0, "visual": 0, "review": 0, "critic": 0}
    reviewed_visuals: list[dict] = []
    monkeypatch.setattr(sc, "structure_step", lambda *a, **k: _async_return(structure))
    monkeypatch.setattr(sc, "writing_step", lambda *a, **k: _async_return(writing))

    async def fake_visual(*a, **k):
        counts["visual"] += 1
        return visuals[a[1]["scene_num"] - 1]

    async def fake_cast(*a, **k):
        counts["cast"] += 1
        return {}

    async def fake_repair(*a, **k):
        counts["repair"] += 1
        return [{**a[1][0], "narration": "수정됨."}]

    async def fake_review(*a, **k):
        counts["review"] += 1
        reviewed_visuals.append(a[2])
        return REVIEW_FAIL if counts["review"] == 1 else REVIEW_PASS

    async def fake_critic(*a, **k):
        counts["critic"] += 1
        return CRITIC_PASS

    monkeypatch.setattr(sc, "research_step", lambda *a, **k: _async_return(RESEARCH))
    monkeypatch.setattr(sc, "cast_decision_step", fake_cast)
    monkeypatch.setattr(sc, "visual_breakdown_step", fake_visual)
    monkeypatch.setattr(sc, "writing_scene_repair_step", fake_repair)
    monkeypatch.setattr(sc, "review_step", fake_review)
    monkeypatch.setattr(sc, "critic_step", fake_critic)
    monkeypatch.setattr(sc, "tts_normalize_step", lambda value, *a, **k: _async_return(value))

    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert counts == {"repair": 1, "cast": 9, "visual": 9, "review": 2, "critic": 2}
    retry_calls = counts["repair"] + counts["cast"] - 8 + counts["visual"] - 8 + counts["review"] - 1 + counts["critic"] - 1
    assert retry_calls == 5
    assert out["scenes"][0]["narration"] == "수정됨."
    assert [scene["narration"] for scene in out["scenes"][1:]] == [scene["narration"] for scene in writing["scenes"][1:]]
    assert all(reviewed_visuals[1][idx] is reviewed_visuals[0][idx] for idx in range(1, 8))


async def test_scoped_repair_receives_the_positionally_matching_structure_subset(monkeypatch):
    """Story 12.1 AC9. Two NON-ADJACENT flagged scenes, so a subset that happened
    to be a contiguous slice (or the whole structure) can't pass by accident."""
    structure = [{**STRUCTURE[0], "scene_num": i + 1, "synopsis": f"syn{i + 1}"} for i in range(6)]
    writing = {
        **WRITING,
        "scenes": [{**WRITING["scenes"][0], "scene_num": i + 1, "narration": f"문장 {i + 1}."} for i in range(6)],
    }
    review_fail = {
        **REVIEW_PASS, "overall_pass": False,
        "issues": [
            {"scene_num": 2, "description": "bad", "correction": "fix"},
            {"scene_num": 5, "description": "bad", "correction": "fix"},
        ],
    }
    captured: dict = {}
    reviews = {"n": 0}

    async def fake_repair(scp_id, originals, scene_structure, *a, **k):
        captured["structure"] = scene_structure
        captured["originals"] = originals
        return [{**scene, "narration": "수정됨."} for scene in originals]

    async def fake_review(*a, **k):
        reviews["n"] += 1
        return review_fail if reviews["n"] == 1 else REVIEW_PASS

    monkeypatch.setattr(sc, "research_step", lambda *a, **k: _async_return(RESEARCH))
    monkeypatch.setattr(sc, "structure_step", lambda *a, **k: _async_return(structure))
    monkeypatch.setattr(sc, "writing_step", lambda *a, **k: _async_return(writing))
    monkeypatch.setattr(sc, "writing_scene_repair_step", fake_repair)
    monkeypatch.setattr(sc, "cast_decision_step", lambda *a, **k: _async_return({}))
    monkeypatch.setattr(sc, "visual_breakdown_step", lambda *a, **k: _async_return(VISUAL))
    monkeypatch.setattr(sc, "review_step", fake_review)
    monkeypatch.setattr(sc, "critic_step", lambda *a, **k: _async_return(CRITIC_PASS))
    monkeypatch.setattr(sc, "tts_normalize_step", lambda value, *a, **k: _async_return(value))

    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert [scene["scene_num"] for scene in captured["originals"]] == [2, 5]
    assert captured["structure"] == [structure[1], structure[4]]
    assert captured["structure"][0] is structure[1] and captured["structure"][1] is structure[4]


async def test_retention_violation_fails_the_run_before_any_writing_call(monkeypatch):
    """Story 12.1 AC7 end-to-end: a broken outline surfaces as PipelineState.error
    after exactly one structure call, and no writing/cast/visual work starts."""
    calls = _stub_chain(monkeypatch)
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    monkeypatch.setattr(sc, "structure_step", chain.structure_step)  # the real stage
    deepseek = {"n": 0}

    async def fake_deepseek(rendered, s):
        deepseek["n"] += 1
        outline = _retention_outline(4)
        outline[3]["loops_closed"] = []  # promises made, never paid
        return json.dumps({"scenes": outline}), {}, "stop"

    monkeypatch.setattr(sc, "_call_deepseek", fake_deepseek)

    out = await sc.scenario_node(_state())
    assert "retention[loop_unclosed]" in out["error"]
    assert "stage=scenario" in out["error"]
    assert "scenes" not in out
    assert deepseek["n"] == 1, "a retention violation must never buy an LLM regeneration"
    assert (calls["writing"], calls["cast"], calls["visual"], calls["review"]) == (0, 0, 0, 0)


async def test_contract_valid_outline_runs_the_whole_chain(monkeypatch):
    """The positive counterpart the failure test needs to mean anything. Same real
    `structure_step`, same stubs — only the outline differs. Without it, a validator
    that rejected EVERY outline would still pass the AC7 test above."""
    calls = _stub_chain(monkeypatch)
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    monkeypatch.setattr(sc, "structure_step", chain.structure_step)  # the real stage
    deepseek = {"n": 0}

    async def fake_deepseek(rendered, s):
        deepseek["n"] += 1
        return json.dumps({"scenes": _retention_outline(4)}), {}, "stop"

    monkeypatch.setattr(sc, "_call_deepseek", fake_deepseek)

    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert deepseek["n"] == 1, "a valid outline must not be regenerated either"
    assert (calls["writing"], calls["cast"], calls["visual"], calls["review"]) == (1, 1, 1, 1)


async def test_scoped_repair_subset_degrades_to_empty_when_writing_overproduces(monkeypatch):
    """`_repair_and_review` pairs `structure[idx]`, but writing can return more
    scenes than the outline has entries (a known model behaviour the visual path
    already guards). The flagged index must degrade to `{}` rather than raising
    IndexError and failing an otherwise recoverable run."""
    structure = [{**STRUCTURE[0], "scene_num": i + 1} for i in range(3)]
    writing = {
        **WRITING,
        "scenes": [{**WRITING["scenes"][0], "scene_num": i + 1, "narration": f"문장 {i + 1}."} for i in range(5)],
    }
    review_fail = {
        **REVIEW_PASS, "overall_pass": False,
        "issues": [{"scene_num": 5, "description": "bad", "correction": "fix"}],
    }
    captured: dict = {}
    reviews = {"n": 0}

    async def fake_repair(scp_id, originals, scene_structure, *a, **k):
        captured["structure"] = scene_structure
        return [{**scene, "narration": "수정됨."} for scene in originals]

    async def fake_review(*a, **k):
        reviews["n"] += 1
        return review_fail if reviews["n"] == 1 else REVIEW_PASS

    monkeypatch.setattr(sc, "research_step", lambda *a, **k: _async_return(RESEARCH))
    monkeypatch.setattr(sc, "structure_step", lambda *a, **k: _async_return(structure))
    monkeypatch.setattr(sc, "writing_step", lambda *a, **k: _async_return(writing))
    monkeypatch.setattr(sc, "writing_scene_repair_step", fake_repair)
    monkeypatch.setattr(sc, "cast_decision_step", lambda *a, **k: _async_return({}))
    monkeypatch.setattr(sc, "visual_breakdown_step", lambda *a, **k: _async_return(VISUAL))
    monkeypatch.setattr(sc, "review_step", fake_review)
    monkeypatch.setattr(sc, "critic_step", lambda *a, **k: _async_return(CRITIC_PASS))
    monkeypatch.setattr(sc, "tts_normalize_step", lambda value, *a, **k: _async_return(value))

    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert captured["structure"] == [{}]


async def test_both_critic_call_sites_receive_the_source_text(monkeypatch):
    """AC12a at the node boundary: `critic_step` leads with `scp_text`, and the
    post-repair call site inside `_repair_and_review` must pass it too. A stale
    positional call site there would hand the critic an empty fact sheet and score
    substance against nothing — while the initial-pass site still looked correct.

    The critic must flag a SPECIFIC scene: an empty `scene_notes` yields no retry
    indexes, so the run takes the full-rewrite path and re-enters the *initial*
    call site, leaving the post-repair one unexercised."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    critic_flagged = {**CRITIC_RETRY, "scene_notes": [{"scene_num": 1, "feedback": "고쳐주세요"}]}
    seen: list = []

    async def fake_critic(scp_text, *a, **k):
        seen.append(scp_text)
        return critic_flagged if len(seen) == 1 else CRITIC_PASS

    calls = _stub_chain(monkeypatch)
    monkeypatch.setattr(sc, "critic_step", fake_critic)

    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert calls["repair"] == 1, "the scoped-repair path must run, not a full rewrite"
    assert seen == ["SCP-173 is a concrete statue."] * 2  # initial pass + post-repair


async def test_stage_failure_surfaces_as_error(monkeypatch):
    _stub_chain(monkeypatch)

    async def boom(*a, **k):
        raise RuntimeError("Langfuse prompt fetch failed: name='scenario/research'")

    monkeypatch.setattr(sc, "research_step", boom)
    out = await sc.scenario_node(_state())
    assert out["current_stage"] == "scenario"
    assert out["error"] and "stage=scenario" in out["error"] and "run-123" in out["error"]
    assert "scenes" not in out


async def test_duplicate_llm_scene_num_does_not_corrupt_shots(monkeypatch):
    # Writing stage emits TWO scenes, both claiming scene_num=1 (a real, if
    # rare, LLM misbehavior) — each scene's visual_breakdown must still keep
    # its own distinct shots; nothing may silently collapse or drop.
    writing_two_scenes = {
        "scp_id": "SCP-173",
        "title": "t",
        "scenes": [
            {"scene_num": 1, "narration": "첫 씬 문장.", "location": "a", "characters_present": [], "color_palette": "a", "atmosphere": "a"},
            {"scene_num": 1, "narration": "둘째 씬 문장.", "location": "b", "characters_present": [], "color_palette": "b", "atmosphere": "b"},
        ],
    }

    call_count = {"n": 0}

    async def fake_research(*a, **k):
        return RESEARCH

    async def fake_structure(*a, **k):
        return STRUCTURE

    async def fake_writing(*a, **k):
        return writing_two_scenes

    async def fake_visual(scp_id, scene, sentences, *a, **k):
        # Distinguish the two scenes by their own narration/location so the
        # test can prove which shot ended up where.
        call_count["n"] += 1
        tag = scene["location"]
        return [{"image_prompt": f"shot-for-{tag}", "negative_prompt": "neg", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}]

    async def fake_review(*a, **k):
        return REVIEW_PASS

    async def fake_critic(*a, **k):
        return CRITIC_PASS

    async def fake_tts_normalize(writing, *a, **k):
        return writing

    async def fake_cast_decision(*a, **k):
        return {}

    monkeypatch.setattr(sc, "research_step", fake_research)
    monkeypatch.setattr(sc, "structure_step", fake_structure)
    monkeypatch.setattr(sc, "writing_step", fake_writing)
    monkeypatch.setattr(sc, "cast_decision_step", fake_cast_decision)
    monkeypatch.setattr(sc, "visual_breakdown_step", fake_visual)
    monkeypatch.setattr(sc, "review_step", fake_review)
    monkeypatch.setattr(sc, "critic_step", fake_critic)
    monkeypatch.setattr(sc, "tts_normalize_step", fake_tts_normalize)

    out = await sc.scenario_node(_state())

    assert call_count["n"] == 2  # both scenes' visual_breakdown actually ran
    assert out.get("error") is None
    scenes = out["scenes"]
    assert len(scenes) == 2
    # Each output scene must carry ITS OWN shot, not both collapsing onto one.
    assert scenes[0]["shots"][0]["image_prompt"] == "shot-for-a"
    assert scenes[1]["shots"][0]["image_prompt"] == "shot-for-b"


async def test_scene_count_exceeding_structure_logs_warning_instead_of_crashing(monkeypatch, caplog):
    # writing_step and structure_step are two independent LLM calls; if writing
    # ever emits more scenes than structure, the extra scene must get an empty
    # (not crashing) scene_role and a visible warning instead of silent data loss.
    writing_two_scenes = {
        "scp_id": "SCP-173",
        "title": "t",
        "scenes": [
            {"scene_num": 1, "narration": "첫 씬.", "location": "a", "characters_present": [], "color_palette": "a", "atmosphere": "a"},
            {"scene_num": 2, "narration": "둘째 씬.", "location": "b", "characters_present": [], "color_palette": "b", "atmosphere": "b"},
        ],
    }
    captured_roles = []

    async def fake_visual(scp_id, scene, sentences, cast_by_sentence, frozen_descriptor, entity_sheet, story_logline, scene_role, *a, **k):
        captured_roles.append(scene_role)
        return VISUAL

    _stub_chain(monkeypatch)
    monkeypatch.setattr(sc, "structure_step", lambda *a, **k: _async_return(STRUCTURE))  # only 1 entry
    monkeypatch.setattr(sc, "writing_step", lambda *a, **k: _async_return(writing_two_scenes))
    monkeypatch.setattr(sc, "visual_breakdown_step", fake_visual)

    with caplog.at_level("WARNING"):
        out = await sc.scenario_node(_state())

    assert out.get("error") is None
    assert STRUCTURE[0] in captured_roles
    assert {} in captured_roles  # scene 2 has no matching structure entry
    assert "more scenes" in caplog.text


async def test_visual_breakdown_receives_entity_sheet_logline_and_scene_role(monkeypatch):
    _stub_chain(monkeypatch)
    captured = {}

    async def fake_visual(scp_id, scene, sentences, cast_by_sentence, frozen_descriptor, entity_sheet, story_logline, scene_role, *a, **k):
        captured["entity_sheet"] = entity_sheet
        captured["story_logline"] = story_logline
        captured["scene_role"] = scene_role
        return VISUAL

    monkeypatch.setattr(sc, "visual_breakdown_step", fake_visual)
    out = await sc.scenario_node(_state())

    assert out.get("error") is None
    assert captured["entity_sheet"] == RESEARCH["entity_sheet"]
    assert captured["story_logline"] == RESEARCH["story_logline"]
    assert captured["scene_role"] == STRUCTURE[0]  # positional match with structure_step's scenes


async def test_missing_api_key_sets_error(monkeypatch):
    class NoKeySettings(FakeSettings):
        deepseek_api_key = ""

    monkeypatch.setattr(sc, "_settings", lambda: NoKeySettings())
    _stub_chain(monkeypatch)
    out = await sc.scenario_node(_state())
    assert out["error"] and "DEEPSEEK_API_KEY" in out["error"]


async def test_non_ko_content_language_sets_error_without_calling_chain(monkeypatch):
    class NonKoSettings(FakeSettings):
        content_language = "en"

    monkeypatch.setattr(sc, "_settings", lambda: NonKoSettings())
    calls = _stub_chain(monkeypatch)
    out = await sc.scenario_node(_state())
    assert out["error"] and "content_language" in out["error"]
    assert calls["research"] == 0
    assert calls["structure"] == 0
    assert calls["writing"] == 0


async def test_variant_b_fetches_format_guide_with_candidate_label(monkeypatch):
    monkeypatch.setattr(sc, "get_prompt_with_fallback", lambda *a, **k: FakePrompt())
    _stub_chain(monkeypatch)
    label_calls = {}

    async def fake_research(*a, label=None, **k):
        label_calls["research"] = label
        return RESEARCH

    monkeypatch.setattr(sc, "research_step", fake_research)

    out = await sc.scenario_node(_state(prompt_variant="B"))

    assert out.get("error") is None
    assert label_calls["research"] == "candidate"


async def test_variant_a_and_none_fetch_format_guide_without_label(monkeypatch):
    calls = []
    monkeypatch.setattr(sc, "get_prompt", lambda *a, **k: calls.append((a, k)) or FakePrompt())
    monkeypatch.setattr(
        sc, "get_prompt_with_fallback",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called for variant A/None")),
    )
    _stub_chain(monkeypatch)

    for variant in (None, "A"):
        calls.clear()
        out = await sc.scenario_node(_state(prompt_variant=variant))
        assert out.get("error") is None
        assert calls == [(("scenario/format_guide",), {})]


async def test_tts_normalize_runs_after_critic_and_before_build_scenes(monkeypatch):
    order = []

    async def fake_critic(*a, **k):
        order.append("critic")
        return CRITIC_PASS

    async def fake_tts_normalize(writing, *a, **k):
        order.append("tts_normalize")
        return {**writing, "scenes": [{**s, "narration": "정규화됨."} for s in writing["scenes"]]}

    _stub_chain(monkeypatch, critic=CRITIC_PASS)
    monkeypatch.setattr(sc, "critic_step", fake_critic)
    monkeypatch.setattr(sc, "tts_normalize_step", fake_tts_normalize)

    out = await sc.scenario_node(_state())

    assert order == ["critic", "tts_normalize"]
    assert out.get("error") is None
    assert out["scenes"][0]["narration"] == "정규화됨."


async def test_tts_normalize_failure_surfaces_as_error(monkeypatch):
    _stub_chain(monkeypatch)

    async def boom(*a, **k):
        raise ValueError("tts_normalize: expected 1 scenes, got 0")

    monkeypatch.setattr(sc, "tts_normalize_step", boom)
    out = await sc.scenario_node(_state())
    assert out["current_stage"] == "scenario"
    assert out["error"] and "stage=scenario" in out["error"] and "run-123" in out["error"]
    assert "scenes" not in out


async def test_tts_normalize_receives_variant_b_candidate_label(monkeypatch):
    _stub_chain(monkeypatch)
    label_calls = {}

    async def fake_tts_normalize(writing, *a, label=None, **k):
        label_calls["tts_normalize"] = label
        return writing

    monkeypatch.setattr(sc, "get_prompt_with_fallback", lambda *a, **k: FakePrompt())
    monkeypatch.setattr(sc, "tts_normalize_step", fake_tts_normalize)

    out = await sc.scenario_node(_state(prompt_variant="B"))

    assert out.get("error") is None
    assert label_calls["tts_normalize"] == "candidate"


# ── _usage_totals / stage token-field enrichment (Story 6.3) ───────────────


def test_usage_totals_sums_across_calls():
    usage_list = [
        {"prompt_tokens": 10, "completion_tokens": 5, "prompt_cache_hit_tokens": 8, "prompt_cache_miss_tokens": 2},
        {"prompt_tokens": 20, "completion_tokens": 3, "prompt_cache_hit_tokens": 15, "prompt_cache_miss_tokens": 5},
    ]
    assert sc._usage_totals(usage_list) == {
        "prompt_tokens": 30,
        "completion_tokens": 8,
        "prompt_cache_hit_tokens": 23,
        "prompt_cache_miss_tokens": 7,
    }


def test_usage_totals_empty_list_is_all_zero():
    assert sc._usage_totals([]) == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
    }


def test_usage_totals_degrades_missing_or_bad_fields_to_zero_without_raising():
    usage_list = [
        {"prompt_tokens": 10},  # other fields absent
        {"prompt_tokens": None, "completion_tokens": "not-a-number"},  # wrong types
        {"prompt_tokens": True, "completion_tokens": -1},  # bool/negative are not valid counts
        "not-a-dict",  # malformed entry entirely
        {"prompt_tokens": 5, "prompt_cache_hit_tokens": 3},
    ]
    assert sc._usage_totals(usage_list) == {
        "prompt_tokens": 15,
        "completion_tokens": 0,
        "prompt_cache_hit_tokens": 3,
        "prompt_cache_miss_tokens": 0,
    }


async def test_scenario_node_copies_stages_to_explicit_trace_sink(monkeypatch):
    _stub_chain(monkeypatch)
    trace_sink = []

    out = await sc.scenario_node(_state(), trace_sink=trace_sink)

    assert out["error"] is None
    assert [stage["name"] for stage in trace_sink] == [
        "research", "structure", "writing", "visual_breakdown", "review", "critic_agent", "tts_normalize",
    ]


async def test_scenario_node_stages_carry_token_fields(monkeypatch):
    """AC3/AC4: every stages.append(...) site folds in usage-derived token fields."""
    captured = {}
    monkeypatch.setattr(sc, "_record_trace", lambda **kw: captured.update(kw))

    async def fake_research(*a, usage_sink=None, **k):
        if usage_sink is not None:
            usage_sink.append({"prompt_tokens": 100, "prompt_cache_hit_tokens": 60})
        return RESEARCH

    async def fake_structure(*a, usage_sink=None, **k):
        if usage_sink is not None:
            usage_sink.append({"prompt_tokens": 50})
        return STRUCTURE

    _stub_chain(monkeypatch)
    monkeypatch.setattr(sc, "research_step", fake_research)
    monkeypatch.setattr(sc, "structure_step", fake_structure)

    out = await sc.scenario_node(_state())
    assert out.get("error") is None

    stages_by_name = {s["name"]: s for s in captured["stages"]}
    assert stages_by_name["research"]["prompt_tokens"] == 100
    assert stages_by_name["research"]["prompt_cache_hit_tokens"] == 60
    assert stages_by_name["research"]["prompt_cache_miss_tokens"] == 0
    assert stages_by_name["structure"]["prompt_tokens"] == 50
    # Stages whose fakes never touch usage_sink still carry the zeroed fields (AC3).
    assert stages_by_name["writing"]["prompt_tokens"] == 0
    assert stages_by_name["visual_breakdown"]["prompt_cache_hit_tokens"] == 0


def test_record_trace_marks_error_level_and_status_message(monkeypatch):
    """Spec: langfuse tracing coverage audit — a caught scenario error must mark
    the span level=ERROR with status_message=str(error), not just a blind span."""
    calls = []

    class _FakeLF:
        def update_current_span(self, **kw):
            calls.append(kw)

    monkeypatch.setattr(sc, "get_client", lambda: _FakeLF())

    err = ValueError("stage=scenario run_id=run-123: boom")
    _real_record_trace(stages=[{"name": "research", "latency_ms": 1}], total_latency_ms=5, error=err)

    assert len(calls) == 1
    assert calls[0]["level"] == "ERROR"
    assert calls[0]["status_message"] == str(err)


def test_record_trace_success_path_has_no_error_level(monkeypatch):
    """Companion case: the success path (error=None) must not set level/status_message
    at all — only the error branch does."""
    calls = []

    class _FakeLF:
        def update_current_span(self, **kw):
            calls.append(kw)

    monkeypatch.setattr(sc, "get_client", lambda: _FakeLF())

    _real_record_trace(stages=[{"name": "research", "latency_ms": 1}], total_latency_ms=5, error=None)

    assert len(calls) == 1
    assert "level" not in calls[0]
    assert "status_message" not in calls[0]


# ── Story 12.2: DeepSeek / Gemini provider split ────────────────────────────
#
# The binding ownership table. Gemini owns every prose-producing/prose-revising
# call and every call that judges that prose; DeepSeek keeps planning, visual
# metadata, and the Qwen-tuned TTS normalization pass. Asserted by *identity of
# the injected seam*, not call counts — counts vary with scene count and branch.

_STAGE_OWNER = {
    "research": "deepseek",
    "structure": "deepseek",
    "writing": "gemini",
    "repair": "gemini",
    "cast": "deepseek",
    "visual": "deepseek",
    "review": "gemini",
    "critic": "gemini",
    "tts_normalize": "deepseek",
}


def _misrouted(seen: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(stage, provider) for stage, provider in seen if _STAGE_OWNER[stage] != provider]


async def test_provider_split_on_the_normal_path(monkeypatch):
    seen: list[tuple[str, str]] = []
    _stub_chain(monkeypatch, providers=seen)
    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert _misrouted(seen) == []
    assert {stage for stage, _ in seen} == {
        "research", "structure", "writing", "cast", "visual", "review", "critic", "tts_normalize",
    }


async def test_provider_split_on_the_scene_scoped_repair_path(monkeypatch):
    """The repaired narration must not silently revert to DeepSeek, and pass 2's
    review/critic must judge it on Gemini too."""
    seen: list[tuple[str, str]] = []
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL, review_retry=REVIEW_PASS, providers=seen)
    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert calls["repair"] == 1
    assert _misrouted(seen) == []
    assert ("repair", "gemini") in seen
    assert [p for p in seen if p[0] == "review"] == [("review", "gemini")] * 2


async def test_provider_split_on_the_full_rewrite_path(monkeypatch):
    """critic says retry with no usable scene reference -> full rewrite. Both
    writing passes are Gemini's."""
    seen: list[tuple[str, str]] = []
    calls = _stub_chain(monkeypatch, critic=CRITIC_RETRY, critic_retry=CRITIC_PASS, providers=seen)
    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert (calls["writing"], calls["repair"]) == (2, 0)
    assert _misrouted(seen) == []
    assert [p for p in seen if p[0] == "writing"] == [("writing", "gemini")] * 2


async def test_stage_traces_name_the_provider_and_model(monkeypatch):
    """AC8: a trace must say which provider/model served each stage, or the 13.4
    bias reassessment has no evidence to work from."""
    _stub_chain(monkeypatch)
    stages: list[dict] = []
    await sc.scenario_node(_state(), trace_sink=stages)
    by_name = {stage["name"]: stage for stage in stages}
    assert by_name["writing"]["provider"] == "gemini"
    assert by_name["writing"]["model"] == FakeSettings.gemini_writing_model
    assert by_name["review"]["provider"] == "gemini"
    assert by_name["critic_agent"]["provider"] == "gemini"
    assert by_name["research"]["provider"] == "deepseek"
    assert by_name["research"]["model"] == FakeSettings.deepseek_model
    assert by_name["tts_normalize"]["provider"] == "deepseek"
    # A credential must never ride along in trace metadata.
    assert FakeSettings.gemini_api_key not in json.dumps(stages, ensure_ascii=False)


async def test_missing_gemini_key_fails_before_any_stage_runs(monkeypatch):
    class NoGeminiKey(FakeSettings):
        gemini_api_key = ""

    calls = _stub_chain(monkeypatch)
    monkeypatch.setattr(sc, "_settings", lambda: NoGeminiKey())
    out = await sc.scenario_node(_state())
    assert "YTFLOW_GEMINI_API_KEY" in out["error"]
    assert calls["research"] == 0, "the key check must precede every LLM call, Gemini's or not"


async def test_gemini_stage_semantic_retry_stays_on_gemini(monkeypatch):
    """A parse/validation failure inside a Gemini-owned stage retries on Gemini.
    A silent mid-stage provider swap would invalidate quality attribution."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    _stub_chain(monkeypatch)
    monkeypatch.setattr(sc, "writing_step", chain.writing_step)  # the real stage
    gemini = {"n": 0}

    async def fake_gemini(rendered, s):
        gemini["n"] += 1
        if gemini["n"] == 1:
            return "scenes:\n  - scene_num: 1\n", {}, "stop"  # no narration -> semantic failure
        return (
            "scenes:\n  - scene_num: 1\n    narration: 문장.\n"
            "    location: 격리실\n    color_palette: 차가운 회색\n    atmosphere: 긴장감\n"
        ), {}, "stop"

    async def fake_deepseek(rendered, s):
        raise AssertionError("a Gemini-owned stage must never fall back to DeepSeek")

    monkeypatch.setattr(sc, "_call_gemini", fake_gemini)
    monkeypatch.setattr(sc, "_call_deepseek", fake_deepseek)

    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert gemini["n"] == 2, "exactly one bounded semantic retry, same provider"


async def test_gemini_writing_text_survives_deepseek_tts_normalize(monkeypatch):
    """Distinguishable fakes prove the delivered narration is Gemini's, while the
    DeepSeek-owned tts_normalize pass still receives and preserves it (AC5)."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    _stub_chain(monkeypatch)
    monkeypatch.setattr(sc, "writing_step", chain.writing_step)
    monkeypatch.setattr(sc, "tts_normalize_step", chain.tts_normalize_step)
    received: list[str] = []

    async def fake_gemini(rendered, s):
        return (
            "scenes:\n  - scene_num: 1\n    narration: 제미나이가 쓴 문장입니다.\n"
            "    location: 격리실\n    color_palette: 차가운 회색\n    atmosphere: 긴장감\n"
        ), {}, "stop"

    async def fake_deepseek(rendered, s):
        received.append(rendered)
        return (
            "scenes:\n  - scene_num: 1\n"
            "    display_narration: 제미나이가 쓴 문장입니다.\n"
            "    narration: 제미나이가 쓴 문장입니다.\n"
        ), {}, "stop"

    monkeypatch.setattr(sc, "_call_gemini", fake_gemini)
    monkeypatch.setattr(sc, "_call_deepseek", fake_deepseek)

    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert out["scenes"][0]["narration"] == "제미나이가 쓴 문장입니다."
    assert received, "tts_normalize must still run on DeepSeek"


# ── _call_gemini transport contract (AC3) ───────────────────────────────────


class _CapturingHttpClient(_FakeHttpClient):
    def __init__(self, payload, sink, *, raise_status=None, timeout=False):
        super().__init__(payload)
        self._sink = sink
        self._raise_status = raise_status
        self._timeout = timeout

    async def post(self, url, **kwargs):
        self._sink.append({"url": url, **kwargs})
        if self._timeout:
            raise httpx.TimeoutException("gemini timed out")
        resp = _FakeResponse(self._payload)
        if self._raise_status is not None:
            exc = self._raise_status
            resp.raise_for_status = lambda: (_ for _ in ()).throw(exc)
        return resp


_GEMINI_OK = {
    "choices": [{"finish_reason": "stop", "message": {"content": "scenes: []"}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33},
}


def _capture(monkeypatch, payload, **kw):
    sink: list[dict] = []
    monkeypatch.setattr(sc.httpx, "AsyncClient", lambda **_: _CapturingHttpClient(payload, sink, **kw))
    return sink


async def test_call_gemini_posts_the_openai_compatible_contract(monkeypatch):
    sink = _capture(monkeypatch, _GEMINI_OK)
    raw, usage, finish_reason = await sc._call_gemini("rendered prompt", FakeSettings())

    assert (raw, finish_reason) == ("scenes: []", "stop")
    request = sink[0]
    assert request["url"] == f"{FakeSettings.gemini_base_url}/chat/completions"
    assert request["headers"]["Authorization"] == f"Bearer {FakeSettings.gemini_api_key}"
    assert request["json"] == {
        "model": FakeSettings.gemini_writing_model,
        "messages": [{"role": "user", "content": "rendered prompt"}],
        "max_tokens": FakeSettings.gemini_writing_max_tokens,
    }
    # Gemini reports no DeepSeek cache metrics; they stay absent, never fabricated.
    assert usage == {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33}
    assert sc._usage_totals([usage]) == {
        "prompt_tokens": 11, "completion_tokens": 22,
        "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0,
    }


async def test_call_gemini_normalizes_a_token_limit_finish_to_the_truncation_signal(monkeypatch):
    payload = {
        "choices": [{"finish_reason": "MAX_TOKENS", "message": {"content": "partial"}}],
        "usage": {"completion_tokens": 16384},
    }
    _capture(monkeypatch, payload)
    raw, _, finish_reason = await sc._call_gemini("rendered", FakeSettings())
    assert (raw, finish_reason) == ("partial", "length"), "must reach the chain's bounded re-roll"


async def test_call_gemini_rejects_a_blocked_empty_response(monkeypatch):
    payload = {"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]}
    _capture(monkeypatch, payload)
    with pytest.raises(RuntimeError) as exc:
        await sc._call_gemini("rendered", FakeSettings())
    assert "content_filter" in str(exc.value)
    assert FakeSettings.gemini_api_key not in str(exc.value)


async def test_call_gemini_rejects_a_response_with_no_choices(monkeypatch):
    _capture(monkeypatch, {"choices": []})
    with pytest.raises(RuntimeError) as exc:
        await sc._call_gemini("rendered", FakeSettings())
    assert FakeSettings.gemini_api_key not in str(exc.value)


async def test_call_gemini_propagates_an_http_error_without_falling_back(monkeypatch):
    err = httpx.HTTPStatusError("429 RESOURCE_EXHAUSTED", request=None, response=None)
    _capture(monkeypatch, _GEMINI_OK, raise_status=err)
    with pytest.raises(httpx.HTTPStatusError):
        await sc._call_gemini("rendered", FakeSettings())


async def test_call_gemini_propagates_a_timeout(monkeypatch):
    _capture(monkeypatch, _GEMINI_OK, timeout=True)
    with pytest.raises(httpx.TimeoutException):
        await sc._call_gemini("rendered", FakeSettings())


async def test_call_gemini_without_a_key_fails_before_any_http(monkeypatch, caplog):
    class NoGeminiKey(FakeSettings):
        gemini_api_key = ""

    sink = _capture(monkeypatch, _GEMINI_OK)
    with pytest.raises(RuntimeError, match="YTFLOW_GEMINI_API_KEY"):
        await sc._call_gemini("rendered", NoGeminiKey())
    assert sink == []
    assert FakeSettings.gemini_api_key not in caplog.text


async def test_a_gemini_outage_surfaces_as_a_scenario_error_not_a_deepseek_rewrite(monkeypatch):
    """AC1/AD-10: no code path silently falls back after a provider error."""
    _stub_chain(monkeypatch)
    monkeypatch.setattr(sc, "writing_step", chain.writing_step)
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    async def dead_gemini(rendered, s):
        raise httpx.HTTPStatusError("503 unavailable", request=None, response=None)

    async def fake_deepseek(rendered, s):
        raise AssertionError("a Gemini outage must not be papered over by DeepSeek")

    monkeypatch.setattr(sc, "_call_gemini", dead_gemini)
    monkeypatch.setattr(sc, "_call_deepseek", fake_deepseek)

    out = await sc.scenario_node(_state())
    assert out["error"] and "503" in out["error"]
    assert "scenes" not in out


# ── Story 12.3: pass-2 verdict surfaced as scenario_quality (AC1-3, 5) ────────

CRITIC_NOTES = {"verdict": "accept_with_notes", "feedback": "사소한 지적", "scene_notes": []}
CONTRADICTION = {
    "scene_num": 1,
    "narration_quote": "개체는 파란 눈을 가지고 있습니다",
    "grounding_source": "entity_sheet",
    "grounding_quote": "눈은 검은색이다",
    "explanation": "눈 색이 접지 자료와 반대다",
    "correction": "개체는 검은 눈을 가지고 있습니다",
}


async def test_review_receives_entity_sheet_on_both_passes(monkeypatch):
    """AC4 wiring: the grounding source must reach review on the initial write AND
    on the scoped repair — a repair pass judged without it is the pass that ships."""
    seen: list[str] = []

    async def capturing_review(*a, **k):
        seen.append(k.get("entity_sheet"))
        return REVIEW_FAIL if len(seen) == 1 else REVIEW_PASS

    _stub_chain(monkeypatch)
    monkeypatch.setattr(sc, "review_step", capturing_review)
    out = await sc.scenario_node(_state())

    assert out.get("error") is None
    assert seen == ["entity sheet", "entity sheet"]


async def test_clean_pass1_records_quality_without_warning(monkeypatch):
    _stub_chain(monkeypatch)
    out = await sc.scenario_node(_state())
    quality = out["scenario_quality"]
    assert "warning" not in quality
    assert quality["final_pass_index"] == 1
    assert quality["retry_scope"] == "none"
    assert quality["review_overall_pass"] is True
    assert quality["critic_verdict"] == "pass"


def _sequenced(monkeypatch, attr, *values):
    """Replace a chain step with one yielding each value in turn (the last repeats).

    `_stub_chain`'s own `*_retry` arguments key off the WRITING count, so they only
    fire on the full-rewrite path — the scoped-repair path needs a per-call seam.
    """
    state = {"n": 0}

    async def fake(*a, **k):
        state["n"] += 1
        return values[min(state["n"], len(values)) - 1]

    monkeypatch.setattr(sc, attr, fake)
    return state


async def test_pass2_that_resolves_carries_no_warning(monkeypatch):
    _stub_chain(monkeypatch, review=REVIEW_FAIL)
    _sequenced(monkeypatch, "review_step", REVIEW_FAIL, REVIEW_PASS)  # scoped repair fixed it
    out = await sc.scenario_node(_state())
    quality = out["scenario_quality"]
    assert "warning" not in quality
    assert quality["final_pass_index"] == 2
    assert quality["retry_scope"] == "scene"


async def test_unresolved_pass2_critic_retry_warns_but_run_succeeds(monkeypatch):
    """AC1+AC2: the bounded retry is unchanged and the stage still reaches the gate."""
    # REVIEW_FAIL carries a mappable scene_num, so the bounded retry is the SCOPED
    # repair; the critic still says "retry" once it is done.
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL, critic=CRITIC_RETRY)
    out = await sc.scenario_node(_state())

    assert out.get("error") is None            # non-fatal: the human still decides
    assert len(out["scenes"]) == 1
    assert calls["writing"] == 1 and calls["repair"] == 1  # no third pass
    assert calls["review"] == 2 and calls["critic"] == 2
    assert calls["tts_normalize"] == 1
    quality = out["scenario_quality"]
    assert quality["warning"]["code"] == "unresolved_pass2"
    assert quality["warning"]["message"]
    assert quality["critic_verdict"] == "retry"
    assert quality["critic_feedback"] == "다시 써주세요"


async def test_critic_feedback_keeps_its_per_scene_lines(monkeypatch):
    """[review fix] `_aggregate_critic` joins per-scene feedback with newlines and the
    UI renders the field `whitespace-pre-wrap`. Collapsing ALL whitespace turned that
    into one unreadable paragraph at the exact moment the operator has to read it."""
    multiline = {**CRITIC_RETRY, "feedback": "Scene 1: 훅이  약합니다.\n\nScene 2:  늘어집니다."}
    _stub_chain(monkeypatch, review=REVIEW_FAIL, critic=multiline)
    quality = (await sc.scenario_node(_state()))["scenario_quality"]
    assert quality["critic_feedback"] == "Scene 1: 훅이 약합니다.\nScene 2: 늘어집니다."


async def test_critic_feedback_stays_bounded_across_lines(monkeypatch):
    long_critic = {**CRITIC_RETRY, "feedback": "\n".join(["가" * 200] * 40)}  # ~8k chars
    _stub_chain(monkeypatch, review=REVIEW_FAIL, critic=long_critic)
    quality = (await sc.scenario_node(_state()))["scenario_quality"]
    assert len(quality["critic_feedback"]) == sc._MAX_FEEDBACK_CHARS
    assert quality["critic_feedback"].endswith("…")


async def test_unresolved_pass2_failed_review_warns(monkeypatch):
    _stub_chain(monkeypatch, review=REVIEW_FAIL)  # overall_pass still false after repair
    out = await sc.scenario_node(_state())
    quality = out["scenario_quality"]
    assert quality["warning"]["code"] == "unresolved_pass2"
    assert quality["review_overall_pass"] is False
    assert [i["description"] for i in quality["review_issues"]] == ["bad"]


async def test_accept_with_notes_alone_neither_retries_nor_warns(monkeypatch):
    calls = _stub_chain(monkeypatch, critic=CRITIC_NOTES)
    out = await sc.scenario_node(_state())
    assert calls["writing"] == 1 and calls["repair"] == 0  # AC3: not a retry trigger
    assert "warning" not in out["scenario_quality"]


async def test_accept_with_notes_after_a_pass1_failure_is_clean(monkeypatch):
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL, critic=CRITIC_RETRY)
    _sequenced(monkeypatch, "review_step", REVIEW_FAIL, REVIEW_PASS)
    _sequenced(monkeypatch, "critic_step", CRITIC_RETRY, CRITIC_NOTES)
    out = await sc.scenario_node(_state())
    assert calls["repair"] == 1
    assert out["scenario_quality"]["final_pass_index"] == 2
    assert "warning" not in out["scenario_quality"]


async def test_unresolved_warning_records_full_fallback_scope(monkeypatch):
    # No mappable scene_num → the full-rewrite fallback; still unresolved afterwards.
    unmappable = {**REVIEW_PASS, "overall_pass": False,
                  "issues": [{"scene_num": 99, "description": "bad", "correction": "fix"}]}
    calls = _stub_chain(monkeypatch, review=unmappable)
    out = await sc.scenario_node(_state())
    assert calls["writing"] == 2 and calls["repair"] == 0
    quality = out["scenario_quality"]
    assert quality["retry_scope"] == "full-fallback"
    assert quality["warning"]["code"] == "unresolved_pass2"


async def test_unresolved_warning_records_truncation_fallback_scope(monkeypatch):
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL)

    async def truncating_repair(*a, **k):
        calls["repair"] += 1
        raise sc.TruncationError(
            "scenario/writing_scene_repair response truncated (finish_reason=length)",
            prompt_name="scenario/writing_scene_repair", completion_tokens=16000, raw="가" * 10,
        )

    monkeypatch.setattr(sc, "writing_scene_repair_step", truncating_repair)
    out = await sc.scenario_node(_state())
    assert out.get("error") is None
    assert out["scenario_quality"]["retry_scope"] == "scene-repair-truncated-fallback"
    assert out["scenario_quality"]["warning"]["code"] == "unresolved_pass2"


async def test_quality_carries_grounded_contradiction_evidence(monkeypatch):
    review = {**REVIEW_FAIL, "grounded_contradictions": [CONTRADICTION]}
    _stub_chain(monkeypatch, review=review)
    out = await sc.scenario_node(_state())
    evidence = out["scenario_quality"]["grounded_contradictions"]
    assert len(evidence) == 1
    assert evidence[0]["grounding_quote"] == "눈은 검은색이다"
    assert evidence[0]["scene_num"] == 1


async def test_rule_metrics_are_code_derived_and_unspoofable(monkeypatch):
    """AC5: metrics are merged AFTER review parsing, so a model that reports its
    own flattering numbers cannot overwrite them."""
    review = {**REVIEW_PASS, "rule_metrics": {"aggregate": {"character_count": 999999}}}
    writing = {**WRITING, "scenes": [{**WRITING["scenes"][0], "narration": "같은 문장. 같은 문장."}]}

    async def fake_writing(*a, **k):
        return writing

    _stub_chain(monkeypatch, review=review)
    monkeypatch.setattr(sc, "writing_step", fake_writing)
    out = await sc.scenario_node(_state())

    metrics = out["scenario_quality"]["rule_metrics"]
    assert metrics["aggregate"]["character_count"] == len("같은문장.같은문장.")
    assert metrics["aggregate"]["duplicate_sentence_count"] == 1
    assert metrics["scenes"][0]["scene_num"] == 1
    assert metrics["slop_vocabulary_version"] == chain.SLOP_VOCABULARY_VERSION


async def test_rule_metrics_measure_pre_normalization_writing(monkeypatch):
    """The review/critic judged the writing text, so the metrics must describe the
    same text — not the TTS-normalized rewrite that follows."""
    normalized = {**WRITING, "scenes": [{**WRITING["scenes"][0], "narration": "가나다라마바사아자차." * 5}]}
    _stub_chain(monkeypatch, tts_normalize=normalized)
    out = await sc.scenario_node(_state())
    assert out["scenario_quality"]["rule_metrics"]["aggregate"]["character_count"] == len("문장.")


async def test_quality_is_json_and_checkpoint_safe(monkeypatch):
    _stub_chain(monkeypatch, review={**REVIEW_FAIL, "grounded_contradictions": [CONTRADICTION]},
                critic=CRITIC_RETRY)
    out = await sc.scenario_node(_state())
    round_tripped = json.loads(json.dumps(out["scenario_quality"], ensure_ascii=False))
    assert round_tripped == out["scenario_quality"]


async def test_quality_bounds_runaway_feedback_and_issue_lists(monkeypatch, caplog):
    huge_issues = [{"scene_num": 1, "type": "fact_error", "severity": "warning",
                    "description": "가" * 5000, "correction": "나"} for _ in range(50)]
    review = {**REVIEW_PASS, "overall_pass": False, "issues": huge_issues}
    _stub_chain(monkeypatch, review=review)
    with caplog.at_level("WARNING"):
        out = await sc.scenario_node(_state())
    quality = out["scenario_quality"]
    assert len(quality["review_issues"]) == sc._MAX_QUALITY_ITEMS
    assert all(len(i["description"]) <= sc._MAX_QUALITY_TEXT for i in quality["review_issues"])
    # No silent caps: the drop is logged, not hidden behind a full-looking list.
    assert "review issues" in caplog.text


async def test_failed_scenario_returns_no_quality(monkeypatch):
    _stub_chain(monkeypatch)

    async def boom(*a, **k):
        raise ValueError("structure blew up")

    monkeypatch.setattr(sc, "structure_step", boom)
    out = await sc.scenario_node(_state())
    assert out["error"]
    assert "scenario_quality" not in out


async def test_unresolved_warning_records_coverage_fallback_scope(monkeypatch):
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL)

    async def mismatching_repair(*a, **k):
        calls["repair"] += 1
        raise sc.SceneCoverageError(
            "writing_scene_repair: scene coverage mismatch; expected [1] got [2]",
            prompt_name="scenario/writing_scene_repair",
        )

    monkeypatch.setattr(sc, "writing_scene_repair_step", mismatching_repair)
    out = await sc.scenario_node(_state())
    assert out.get("error") is None
    quality = out["scenario_quality"]
    assert quality["retry_scope"] == "scene-repair-coverage-fallback"
    assert quality["final_pass_index"] == 2
    assert quality["warning"]["code"] == "unresolved_pass2"


async def test_quality_survives_a_langgraph_checkpoint_round_trip(monkeypatch, tmp_path):
    """The gate reads this out of a checkpoint, so the whole object has to survive
    the checkpointer's serializer, not just json.dumps."""
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    _stub_chain(monkeypatch, review={**REVIEW_FAIL, "grounded_contradictions": [CONTRADICTION]},
                critic=CRITIC_RETRY)
    out = await sc.scenario_node(_state())
    serde = JsonPlusSerializer()
    assert serde.loads_typed(serde.dumps_typed(out["scenario_quality"])) == out["scenario_quality"]


# --- Story 12.4: archetype propagation ----------------------------------------
# scenario.py's only job here is narrow: resolve the research-owned value ONCE,
# hand it to structure, and report it. These tests pin "once" and "reported",
# because a second selection is exactly what would make an episode's outline and
# its recorded archetype disagree.

_RESEARCH_WITH_ARCHETYPE = {
    **RESEARCH,
    "story_archetype": "discovery_log",
    "story_archetype_fallback_used": False,
    "archetype_rationale": "회수 기록과 날짜 항목이 있다",
}


def _stub_chain_with_research(monkeypatch, research, **over):
    """`_stub_chain`, plus a research seam returning `research` and a recorder for
    every `story_archetype` kwarg structure_step was handed."""
    calls = _stub_chain(monkeypatch, **over)
    seen: list[str] = []
    real_structure = sc.structure_step

    async def fake_research(*a, **k):
        calls["research"] += 1
        return research

    async def fake_structure(*a, **k):
        seen.append(k.get("story_archetype"))
        return await real_structure(*a, **k)

    monkeypatch.setattr(sc, "research_step", fake_research)
    monkeypatch.setattr(sc, "structure_step", fake_structure)
    return calls, seen


async def test_selected_archetype_is_returned_and_passed_to_structure(monkeypatch):
    calls, seen = _stub_chain_with_research(monkeypatch, _RESEARCH_WITH_ARCHETYPE)
    out = await sc.scenario_node(_state())
    assert out["story_archetype"] == "discovery_log"
    assert out["story_archetype_fallback_used"] is False
    assert seen == ["discovery_log"]  # resolved once, handed over explicitly
    assert calls["structure"] == 1


async def test_fallback_flag_reaches_the_state(monkeypatch):
    _stub_chain_with_research(monkeypatch, {
        **RESEARCH, "story_archetype": "incident_first", "story_archetype_fallback_used": True,
    })
    out = await sc.scenario_node(_state())
    assert (out["story_archetype"], out["story_archetype_fallback_used"]) == ("incident_first", True)


async def test_research_without_the_field_degrades_to_the_production_template(monkeypatch):
    """A stubbed/older research seam must not crash the stage (AD-10) — but a seam
    that has stopped selecting IS a selector failure, so the flag AC6 added to
    expose exactly that drift must not read clean while it happens."""
    _, seen = _stub_chain_with_research(monkeypatch, RESEARCH)
    out = await sc.scenario_node(_state())
    assert out["story_archetype"] == "incident_first"
    assert out["story_archetype_fallback_used"] is True
    assert seen == ["incident_first"]


async def test_scene_scoped_repair_does_not_reselect(monkeypatch):
    # A scoped repair never calls writing_step, so `_stub_chain`'s writing-count
    # retry switch (full-rewrite only) can't drive it — flag scene 1 in `review`
    # and let the repair pass clear it, exactly as the 12.1 repair tests do.
    calls, seen = _stub_chain_with_research(
        monkeypatch, _RESEARCH_WITH_ARCHETYPE, review=REVIEW_FAIL, review_retry=REVIEW_PASS,
    )
    out = await sc.scenario_node(_state())
    assert calls["repair"] == 1                    # the repair pass really ran
    assert calls["structure"] == 1 and seen == ["discovery_log"]
    assert out["story_archetype"] == "discovery_log"


async def test_full_rewrite_fallback_does_not_reselect(monkeypatch):
    # review fails with no usable scene_num → the full-rewrite branch
    review_fail = {**REVIEW_PASS, "overall_pass": False,
                   "issues": [{"scene_num": "nope", "description": "bad", "correction": "fix"}]}
    calls, seen = _stub_chain_with_research(
        monkeypatch, _RESEARCH_WITH_ARCHETYPE, review=review_fail, review_retry=REVIEW_PASS,
    )
    out = await sc.scenario_node(_state())
    assert calls["writing"] == 2 and calls["repair"] == 0  # full rewrite, not scoped repair
    assert calls["structure"] == 1 and seen == ["discovery_log"]
    assert out["story_archetype"] == "discovery_log"


async def test_research_and_structure_traces_carry_the_selection(monkeypatch):
    _stub_chain_with_research(monkeypatch, _RESEARCH_WITH_ARCHETYPE)
    sink: list[dict] = []
    await sc.scenario_node(_state(), trace_sink=sink)
    by_name = {stage["name"]: stage for stage in sink}
    assert by_name["research"]["story_archetype"] == "discovery_log"
    assert by_name["research"]["story_archetype_fallback_used"] is False
    assert by_name["structure"]["story_archetype"] == "discovery_log"
    # stage names and token accounting are untouched (AC8)
    assert [s["name"] for s in sink][:2] == ["research", "structure"]
    assert all("prompt_tokens" in s for s in sink)


async def test_a_failed_run_reports_no_archetype(monkeypatch):
    """AC8: a failed rerun must never show the previous attempt's template beside a
    new error — the failure path returns only stage + error."""
    _stub_chain_with_research(monkeypatch, _RESEARCH_WITH_ARCHETYPE)

    async def boom(*a, **k):
        raise RuntimeError("writing exploded")

    monkeypatch.setattr(sc, "writing_step", boom)
    out = await sc.scenario_node(_state())
    assert out["error"].startswith("stage=scenario run_id=run-123:")
    assert "story_archetype" not in out
    assert "story_archetype_fallback_used" not in out
