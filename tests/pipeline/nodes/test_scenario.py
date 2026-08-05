"""Unit tests for src/yt_flow/pipeline/nodes/scenario.py orchestration (multi-stage
chain redesign — see docs/superpowers/specs/2026-07-03-scenario-multistage-design.md).

Per-stage parsing/validation is covered by test_scenario_chain.py; these tests
only cover scenario_node's own responsibility: sequencing, the bounded retry,
and surfacing errors as PipelineState.error.
"""

import pytest

import yt_flow.pipeline.nodes.scenario as sc

# Captured before the autouse `_isolate` fixture below monkeypatches
# `sc._record_trace` to a no-op — tests that exercise the real function call
# this reference directly instead of the (per-test) stubbed module attribute.
_real_record_trace = sc._record_trace


class FakeSettings:
    deepseek_api_key = "sk-test"
    deepseek_base_url = "https://api.deepseek.com"
    deepseek_model = "deepseek-v4-flash"
    deepseek_max_tokens = 8192
    content_language = "ko"


class FakePrompt:
    def compile(self, **variables):
        return "rendered"


RESEARCH = {"core_identity": "x", "frozen_descriptor": "desc", "entity_sheet": "entity sheet", "story_logline": "logline", "dramatic_beats": "x", "environment": "x", "hooks": "x"}
STRUCTURE = [{"scene_num": 1, "act": "hook", "synopsis": "x", "key_points": [], "emotional_beat": "tension", "estimated_duration_sec": 45, "mood": "escalation"}]
WRITING = {"scp_id": "SCP-173", "title": "t", "scenes": [{"scene_num": 1, "narration": "문장.", "location": "x", "characters_present": [], "color_palette": "x", "atmosphere": "x"}]}
VISUAL = [{"image_prompt": "shot", "negative_prompt": "neg", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}]
REVIEW_PASS = {"overall_pass": True, "coverage_pct": 90.0, "issues": [], "corrections": [], "storytelling_score": 80, "storytelling_issues": []}
REVIEW_FAIL = {**REVIEW_PASS, "overall_pass": False, "issues": [{"scene_num": 1, "description": "bad", "correction": "fix it"}]}
CRITIC_PASS = {"verdict": "pass", "feedback": "good", "scene_notes": []}
CRITIC_RETRY = {"verdict": "retry", "feedback": "다시 써주세요", "scene_notes": []}


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


def _stub_chain(monkeypatch, *, review=REVIEW_PASS, critic=CRITIC_PASS, review_retry=None, critic_retry=None, tts_normalize=None):
    calls = {"research": 0, "structure": 0, "writing": 0, "repair": 0, "cast": 0, "visual": 0, "review": 0, "critic": 0, "tts_normalize": 0}

    async def fake_research(*a, **k):
        calls["research"] += 1
        return RESEARCH

    async def fake_structure(*a, **k):
        calls["structure"] += 1
        return STRUCTURE

    async def fake_writing(*a, **k):
        calls["writing"] += 1
        return WRITING

    async def fake_repair(*a, **k):
        calls["repair"] += 1
        return a[1]

    async def fake_cast_decision(*a, **k):
        calls["cast"] += 1
        return {}

    async def fake_visual(*a, **k):
        calls["visual"] += 1
        return VISUAL

    async def fake_review(*a, **k):
        calls["review"] += 1
        return review_retry if (calls["writing"] > 1 and review_retry) else review

    async def fake_critic(*a, **k):
        calls["critic"] += 1
        return critic_retry if (calls["writing"] > 1 and critic_retry) else critic

    async def fake_tts_normalize(writing, *a, **k):
        calls["tts_normalize"] += 1
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
        return "scenes:\n  - scene_num: 1\n    narration: 문장.\n", {}, "stop"

    writing = await sc.writing_step("SCP-173", structure, "desc", "guide", "", FakeSettings(), call)
    assert [scene["scene_num"] for scene in writing["scenes"]] == [1, 2, 3, 4]

    review = {"issues": [{"scene_num": 3, "description": "bad", "correction": "fix"}]}
    indexes, rejected = sc._retry_scope(review, {"scene_notes": [{"scene_num": 4}]}, writing["scenes"])
    assert indexes == [2, 3]
    assert rejected == []


async def test_structure_truncation_rerolls_instead_of_failing_the_run(monkeypatch):
    """Story 6.9's fallback extended to the INITIAL structure generation: this is
    where 6 of 6 live attempts on 2026-08-05 died."""
    calls = _stub_chain(monkeypatch)
    attempts = {"n": 0}

    async def truncating_structure(*a, **k):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise sc.TruncationError(
                "scenario/structure response truncated (finish_reason=length); raise max_tokens",
                prompt_name="scenario/structure", completion_tokens=16384, raw="runaway",
            )
        calls["structure"] += 1
        return STRUCTURE

    monkeypatch.setattr(sc, "structure_step", truncating_structure)
    out = await sc.scenario_node(_state())
    assert out["error"] is None
    assert attempts["n"] == 2


async def test_structure_truncating_twice_still_fails_the_run(monkeypatch):
    _stub_chain(monkeypatch)
    attempts = {"n": 0}

    async def always_truncating(*a, **k):
        attempts["n"] += 1
        raise sc.TruncationError("truncated", prompt_name="scenario/structure", completion_tokens=32768)

    monkeypatch.setattr(sc, "structure_step", always_truncating)
    out = await sc.scenario_node(_state())
    assert "truncated" in out["error"]
    assert attempts["n"] == 2, "recovery is exactly one re-roll, not a retry loop"


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

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
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
