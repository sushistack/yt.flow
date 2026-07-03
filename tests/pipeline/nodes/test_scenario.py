"""Unit tests for src/yt_flow/pipeline/nodes/scenario.py orchestration (multi-stage
chain redesign — see docs/superpowers/specs/2026-07-03-scenario-multistage-design.md).

Per-stage parsing/validation is covered by test_scenario_chain.py; these tests
only cover scenario_node's own responsibility: sequencing, the bounded retry,
and surfacing errors as PipelineState.error.
"""

import pytest

import yt_flow.pipeline.nodes.scenario as sc


class FakeSettings:
    deepseek_api_key = "sk-test"
    deepseek_base_url = "https://api.deepseek.com"
    deepseek_model = "deepseek-v4-flash"
    deepseek_max_tokens = 8192


class FakePrompt:
    def compile(self, **variables):
        return "rendered"


RESEARCH = {"core_identity": "x", "frozen_descriptor": "desc", "dramatic_beats": "x", "environment": "x", "hooks": "x"}
STRUCTURE = [{"scene_num": 1, "act": "hook", "synopsis": "x", "key_points": [], "emotional_beat": "tension", "estimated_duration_sec": 45}]
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


def _stub_chain(monkeypatch, *, review=REVIEW_PASS, critic=CRITIC_PASS, review_retry=None, critic_retry=None):
    calls = {"writing": 0}

    async def fake_research(*a, **k):
        return RESEARCH

    async def fake_structure(*a, **k):
        return STRUCTURE

    async def fake_writing(*a, **k):
        calls["writing"] += 1
        return WRITING

    async def fake_visual(*a, **k):
        return VISUAL

    async def fake_review(*a, **k):
        return review_retry if (calls["writing"] > 1 and review_retry) else review

    async def fake_critic(*a, **k):
        return critic_retry if (calls["writing"] > 1 and critic_retry) else critic

    monkeypatch.setattr(sc, "research_step", fake_research)
    monkeypatch.setattr(sc, "structure_step", fake_structure)
    monkeypatch.setattr(sc, "writing_step", fake_writing)
    monkeypatch.setattr(sc, "visual_breakdown_step", fake_visual)
    monkeypatch.setattr(sc, "review_step", fake_review)
    monkeypatch.setattr(sc, "critic_step", fake_critic)
    return calls


async def test_success_populates_scenes(monkeypatch):
    _stub_chain(monkeypatch)
    out = await sc.scenario_node(_state())
    assert out["current_stage"] == "scenario"
    assert out.get("error") is None
    assert len(out["scenes"]) == 1
    assert out["scenes"][0]["shots"][0]["image_prompt"] == "shot"


async def test_no_retry_when_critic_passes(monkeypatch):
    calls = _stub_chain(monkeypatch)
    await sc.scenario_node(_state())
    assert calls["writing"] == 1


async def test_retries_once_when_critic_says_retry(monkeypatch):
    calls = _stub_chain(monkeypatch, critic=CRITIC_RETRY, critic_retry=CRITIC_PASS)
    out = await sc.scenario_node(_state())
    assert calls["writing"] == 2  # exactly one retry, not an open loop
    assert out.get("error") is None


async def test_retries_once_when_review_fails(monkeypatch):
    calls = _stub_chain(monkeypatch, review=REVIEW_FAIL, review_retry=REVIEW_PASS)
    out = await sc.scenario_node(_state())
    assert calls["writing"] == 2
    assert out.get("error") is None


async def test_accepts_second_pass_result_even_if_still_failing(monkeypatch):
    # Bounded retry: even if the second pass ALSO comes back "retry", accept it —
    # never loop a third time.
    calls = _stub_chain(monkeypatch, critic=CRITIC_RETRY, critic_retry=CRITIC_RETRY)
    out = await sc.scenario_node(_state())
    assert calls["writing"] == 2
    assert out.get("error") is None
    assert out["scenes"]


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

    async def fake_visual(scene, sentences, *a, **k):
        # Distinguish the two scenes by their own narration/location so the
        # test can prove which shot ended up where.
        call_count["n"] += 1
        tag = scene["location"]
        return [{"image_prompt": f"shot-for-{tag}", "negative_prompt": "neg", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}]

    async def fake_review(*a, **k):
        return REVIEW_PASS

    async def fake_critic(*a, **k):
        return CRITIC_PASS

    monkeypatch.setattr(sc, "research_step", fake_research)
    monkeypatch.setattr(sc, "structure_step", fake_structure)
    monkeypatch.setattr(sc, "writing_step", fake_writing)
    monkeypatch.setattr(sc, "visual_breakdown_step", fake_visual)
    monkeypatch.setattr(sc, "review_step", fake_review)
    monkeypatch.setattr(sc, "critic_step", fake_critic)

    out = await sc.scenario_node(_state())

    assert call_count["n"] == 2  # both scenes' visual_breakdown actually ran
    assert out.get("error") is None
    scenes = out["scenes"]
    assert len(scenes) == 2
    # Each output scene must carry ITS OWN shot, not both collapsing onto one.
    assert scenes[0]["shots"][0]["image_prompt"] == "shot-for-a"
    assert scenes[1]["shots"][0]["image_prompt"] == "shot-for-b"


async def test_missing_api_key_sets_error(monkeypatch):
    class NoKeySettings(FakeSettings):
        deepseek_api_key = ""

    monkeypatch.setattr(sc, "_settings", lambda: NoKeySettings())
    _stub_chain(monkeypatch)
    out = await sc.scenario_node(_state())
    assert out["error"] and "DEEPSEEK_API_KEY" in out["error"]


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
