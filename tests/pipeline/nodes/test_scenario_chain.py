import json
from pathlib import Path

import pytest

import yt_flow.pipeline.nodes.scenario_chain as chain

CASSETTE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "cassettes"


def _load_cassette(name):
    return json.loads((CASSETTE_DIR / name).read_text(encoding="utf-8"))


def _deepseek_from_cassette(name):
    data = _load_cassette(name)
    choice = data["choices"][0]

    async def fake(rendered, s):
        return choice["message"]["content"], data.get("usage", {}), choice.get("finish_reason")

    return fake


class FakePrompt:
    def compile(self, **variables):
        return "rendered"


def test_split_sentences_basic():
    assert chain.split_sentences("격리 절차가 시작된다. 요원들이 진입한다.") == [
        "격리 절차가 시작된다.",
        "요원들이 진입한다.",
    ]


def test_split_sentences_question_and_exclamation():
    assert chain.split_sentences("무슨 일이야? 도망쳐! 늦었어.") == ["무슨 일이야?", "도망쳐!", "늦었어."]


def test_split_sentences_empty_string():
    assert chain.split_sentences("") == []


def test_split_sentences_strips_whitespace_and_blank_segments():
    assert chain.split_sentences("첫 문장.   \n\n  둘째 문장.  ") == ["첫 문장.", "둘째 문장."]


async def test_research_step_returns_frozen_descriptor(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_research.json")
    result = await chain.research_step("SCP-173", "text", "guide", None, call)
    assert result["frozen_descriptor"].startswith("Silhouette")
    assert result["core_identity"]


async def test_research_step_rejects_empty_frozen_descriptor(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"core_identity": "x", "frozen_descriptor": "", "dramatic_beats": "x", "environment": "x", "hooks": "x"}), {}, "stop"

    with pytest.raises(ValueError, match="frozen_descriptor"):
        await chain.research_step("SCP-173", "text", "guide", None, call)


async def test_structure_step_returns_scene_list(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_structure.json")
    research = {"frozen_descriptor": "desc"}
    scenes = await chain.structure_step("SCP-173", research, "guide", None, call)
    assert len(scenes) == 2
    assert scenes[0]["scene_num"] == 1
    assert scenes[0]["emotional_beat"] == "tension"


async def test_structure_step_rejects_empty_scene_list(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"scenes": []}), {}, "stop"

    with pytest.raises(ValueError, match="scenes"):
        await chain.structure_step("SCP-173", {"frozen_descriptor": "d"}, "guide", None, call)


async def test_writing_step_returns_scenes(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_writing.json")
    result = await chain.writing_step("SCP-173", [{"scene_num": 1}], "desc", "guide", "", None, call)
    assert result["scenes"][0]["narration"]
    assert result["scenes"][0]["location"] == "underground containment chamber"


async def test_writing_step_rejects_empty_narration(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"scp_id": "SCP-173", "title": "t", "scenes": [{"scene_num": 1, "narration": "", "location": "x", "characters_present": [], "color_palette": "x", "atmosphere": "x"}]}
        return json.dumps(payload), {}, "stop"

    with pytest.raises(ValueError, match="narration"):
        await chain.writing_step("SCP-173", [{"scene_num": 1}], "desc", "guide", "", None, call)


async def test_visual_breakdown_step_maps_one_shot_per_sentence(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_visual_breakdown.json")
    scene = {"scene_num": 1, "location": "x", "atmosphere": "y", "color_palette": "z", "characters_present": []}
    sentences = ["첫 문장.", "(정적)", "셋째 문장."]
    result = await chain.visual_breakdown_step(scene, sentences, "desc", None, call)
    assert len(result) == 3
    assert result[0]["image_prompt"]
    assert result[1]["image_prompt"] == ""  # transition sentence, no image
    assert result[2]["camera_type"] == "wide"


async def test_visual_breakdown_step_rejects_count_mismatch(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"scene_num": 1, "visual_descriptions": [{"image_prompt": "x", "negative_prompt": "x", "sentence_start": 1, "sentence_end": 1, "entity_visible": False, "camera_type": "wide"}]}
        return json.dumps(payload), {}, "stop"

    scene = {"scene_num": 1, "location": "x", "atmosphere": "y", "color_palette": "z", "characters_present": []}
    with pytest.raises(ValueError, match="1:1"):
        await chain.visual_breakdown_step(scene, ["문장1.", "문장2."], "desc", None, call)


async def test_review_step_returns_report(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_review.json")
    writing = {"scenes": [{"scene_num": 1, "narration": "n"}]}
    result = await chain.review_step("scp text", writing, {1: []}, "desc", "guide", None, call)
    assert result["overall_pass"] is True
    assert result["coverage_pct"] == 92.0


async def test_review_step_rejects_missing_overall_pass(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"coverage_pct": 50.0}), {}, "stop"

    with pytest.raises(ValueError, match="overall_pass"):
        await chain.review_step("t", {"scenes": []}, {}, "desc", "guide", None, call)


async def test_critic_step_returns_verdict(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_critic.json")
    writing = {"scenes": [{"scene_num": 1, "narration": "n"}]}
    result = await chain.critic_step(writing, {1: []}, "guide", None, call)
    assert result["verdict"] == "pass"
    assert result["feedback"]


async def test_critic_step_rejects_unknown_verdict(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"verdict": "maybe", "feedback": "x", "scene_notes": []}), {}, "stop"

    with pytest.raises(ValueError, match="verdict"):
        await chain.critic_step({"scenes": []}, {}, "guide", None, call)


def test_build_scenes_merges_empty_prompt_into_previous_shot():
    writing = {
        "scenes": [
            {"scene_num": 1, "narration": "첫 문장. (정적) 셋째 문장."}
        ]
    }
    visual_by_scene = {
        1: [
            {"image_prompt": "shot one", "negative_prompt": "neg one", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"},
            {"image_prompt": "", "negative_prompt": "", "sentence_start": 2, "sentence_end": 2, "camera_type": "wide"},
            {"image_prompt": "shot three", "negative_prompt": "neg three", "sentence_start": 3, "sentence_end": 3, "camera_type": "close-up"},
        ]
    }
    scenes = chain.build_scenes(writing, visual_by_scene)
    assert len(scenes) == 1
    shots = scenes[0]["shots"]
    assert len(shots) == 2  # the empty-prompt sentence merged into shot 1, not its own shot
    assert shots[0]["sentence_indices"] == [0, 1]  # 0-based: sentences 1 and 2
    assert shots[1]["sentence_indices"] == [2]
    assert all(s["image_prompt"] for s in shots)  # never empty


def test_build_scenes_first_sentence_empty_falls_back_to_scene_context():
    writing = {"scenes": [{"scene_num": 1, "narration": "(정적) 둘째 문장.", "location": "hallway", "atmosphere": "cold dread"}]}
    visual_by_scene = {
        1: [
            {"image_prompt": "", "negative_prompt": "", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"},
            {"image_prompt": "shot two", "negative_prompt": "neg two", "sentence_start": 2, "sentence_end": 2, "camera_type": "medium"},
        ]
    }
    scenes = chain.build_scenes(writing, visual_by_scene)
    shots = scenes[0]["shots"]
    assert len(shots) == 2  # no previous shot to merge into -> kept as its own, backfilled
    assert "hallway" in shots[0]["image_prompt"] or "cold dread" in shots[0]["image_prompt"]
    assert shots[0]["sentence_indices"] == [0]


def test_build_scenes_scene_num_is_positional():
    writing = {"scenes": [
        {"scene_num": 1, "narration": "문장."},
        {"scene_num": 1, "narration": "다른 문장."},  # duplicate scene_num from a misbehaving LLM
    ]}
    visual_by_scene = {
        1: [{"image_prompt": "a", "negative_prompt": "b", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}],
    }
    # Reuse the same visual breakdown for both (test only cares about positional numbering).
    visual_by_scene_full = {1: visual_by_scene[1], 2: visual_by_scene[1]}
    scenes = chain.build_scenes(writing, visual_by_scene_full)
    assert [s["scene_num"] for s in scenes] == [1, 2]


def test_build_scenes_single_empty_shot_falls_back_not_raises():
    writing = {"scenes": [{"scene_num": 1, "narration": "(정적)", "location": "vault", "atmosphere": "silence"}]}
    visual_by_scene = {1: [{"image_prompt": "", "negative_prompt": "", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}]}
    scenes = chain.build_scenes(writing, visual_by_scene)
    assert len(scenes[0]["shots"]) == 1
    assert scenes[0]["shots"][0]["image_prompt"]
