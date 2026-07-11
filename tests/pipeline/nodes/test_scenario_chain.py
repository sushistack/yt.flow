import json
import logging
from pathlib import Path

import pytest
import yaml

import yt_flow.pipeline.nodes.scenario_chain as chain
import yt_flow.pipeline.nodes.sound_design as sound_design

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
    assert result["entity_sheet"]
    assert result["story_logline"]


async def test_research_step_tolerates_missing_entity_sheet_and_logline(monkeypatch):
    # Variant A/None still reads the pre-existing production prompt, which doesn't
    # ask for these two new fields at all yet — an absent key must not crash the
    # pipeline (AC5: existing contracts stay intact).
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"core_identity": "x", "frozen_descriptor": "x", "dramatic_beats": "x", "environment": "x", "hooks": "x"}), {}, "stop"

    result = await chain.research_step("SCP-173", "text", "guide", None, call)
    assert result.get("entity_sheet") is None
    assert result.get("story_logline") is None


async def test_research_step_rejects_empty_frozen_descriptor(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"core_identity": "x", "frozen_descriptor": "", "entity_sheet": "x", "story_logline": "x", "dramatic_beats": "x", "environment": "x", "hooks": "x"}), {}, "stop"

    with pytest.raises(ValueError, match="frozen_descriptor"):
        await chain.research_step("SCP-173", "text", "guide", None, call)


async def test_research_step_rejects_empty_entity_sheet(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"core_identity": "x", "frozen_descriptor": "x", "entity_sheet": "", "story_logline": "x", "dramatic_beats": "x", "environment": "x", "hooks": "x"}), {}, "stop"

    with pytest.raises(ValueError, match="entity_sheet"):
        await chain.research_step("SCP-173", "text", "guide", None, call)


async def test_research_step_rejects_empty_story_logline(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"core_identity": "x", "frozen_descriptor": "x", "entity_sheet": "x", "story_logline": "", "dramatic_beats": "x", "environment": "x", "hooks": "x"}), {}, "stop"

    with pytest.raises(ValueError, match="story_logline"):
        await chain.research_step("SCP-173", "text", "guide", None, call)


async def test_research_step_candidate_label_requires_entity_sheet(monkeypatch):
    # Variant B intentionally reads the new candidate prompt, which always asks for
    # entity_sheet/story_logline — unlike variant A/None, an absent key here is a
    # real regression, not backward-compat noise.
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt_with_fallback", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"core_identity": "x", "frozen_descriptor": "x", "dramatic_beats": "x", "environment": "x", "hooks": "x"}), {}, "stop"

    with pytest.raises(ValueError, match="entity_sheet"):
        await chain.research_step("SCP-173", "text", "guide", None, call, label="candidate")


async def test_research_step_rejects_non_string_entity_sheet(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"core_identity": "x", "frozen_descriptor": "x", "entity_sheet": ["not", "a", "string"], "story_logline": "x", "dramatic_beats": "x", "environment": "x", "hooks": "x"}
        return json.dumps(payload), {}, "stop"

    with pytest.raises(ValueError, match="entity_sheet"):
        await chain.research_step("SCP-173", "text", "guide", None, call)


def test_scene_role_text_ignores_non_dict_input():
    assert chain._scene_role_text("not a dict") == ""
    assert chain._scene_role_text(None) == ""


def test_scene_role_text_coerces_non_string_fields():
    assert chain._scene_role_text({"act": ["hook"], "emotional_beat": "tension", "synopsis": "x"}) == "['hook'] / tension: x"


def test_visual_breakdown_prompt_file_has_required_placeholders():
    prompt_path = Path(__file__).parent.parent.parent.parent / "prompts" / "scenario" / "visual_breakdown.md"
    content = prompt_path.read_text(encoding="utf-8")
    for placeholder in ("{{story_logline}}", "{{scene_role}}", "{{entity_sheet}}", "{{scp_visual_reference}}", "{{numbered_sentences}}", "{{sentence_count}}", "{{scp_id}}", "{{cast_by_sentence}}"):
        assert placeholder in content, f"missing {placeholder} in visual_breakdown.md"


def test_cast_decision_prompt_file_has_required_placeholders():
    prompt_path = Path(__file__).parent.parent.parent.parent / "prompts" / "scenario" / "cast_decision.md"
    content = prompt_path.read_text(encoding="utf-8")
    for placeholder in ("{{scp_id}}", "{{stock_cast_keys}}", "{{characters_present}}", "{{numbered_sentences}}", "{{sentence_count}}"):
        assert placeholder in content, f"missing {placeholder} in cast_decision.md"
    assert "pose_hint" in content


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


async def test_structure_step_candidate_label_requires_title(monkeypatch):
    # Story 5.17 AC:2 — variant B intentionally reads the candidate prompt, which
    # always asks for title; an absent/empty title there is a real regression.
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt_with_fallback", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"scenes": [{"scene_num": 1, "act": "hook", "synopsis": "x", "mood": "dread"}]}
        return json.dumps(payload), {}, "stop"

    with pytest.raises(ValueError, match="title"):
        await chain.structure_step("SCP-173", {"frozen_descriptor": "x"}, "guide", None, call, label="candidate")


async def test_structure_step_label_none_tolerates_missing_title(monkeypatch):
    # Variant A/None still reads the pre-promotion production prompt, which
    # doesn't emit title/kicker at all yet — absence must not crash the pipeline.
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"scenes": [{"scene_num": 1, "act": "hook", "synopsis": "x", "mood": "dread"}]}
        return json.dumps(payload), {}, "stop"

    scenes = await chain.structure_step("SCP-173", {"frozen_descriptor": "x"}, "guide", None, call)
    assert scenes[0]["scene_num"] == 1


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


async def test_writing_step_collapses_embedded_newlines_in_narration(monkeypatch):
    """Live golden-set eval (Story 6.4) caught DeepSeek writing one sentence
    per physical line inside a YAML ``narration: |`` block literal — collapse
    it back to the single flowing line JSON output always produced."""
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return "scenes:\n  - scene_num: 1\n    narration: |\n      첫 문장.\n      둘째 문장.\n", {}, "stop"

    result = await chain.writing_step("SCP-173", [{"scene_num": 1}], "desc", "guide", "", None, call)
    assert result["scenes"][0]["narration"] == "첫 문장. 둘째 문장."


async def test_writing_scene_repair_requires_exact_ordered_coverage(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    originals = [
        {"scene_num": 2, "narration": "old 2"},
        {"scene_num": 4, "narration": "old 4"},
    ]

    async def call(rendered, s):
        return "scenes:\n  - scene_num: 2\n    narration: fixed\n", {}, "stop"

    with pytest.raises(ValueError, match="expected 2 scenes"):
        await chain.writing_scene_repair_step("SCP-173", originals, "feedback", "desc", "guide", None, call)


async def test_writing_scene_repair_rejects_extra_or_reordered_identifiers(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    originals = [{"scene_num": 2, "narration": "old 2"}, {"scene_num": 4, "narration": "old 4"}]

    async def call(rendered, s):
        return "scenes:\n  - scene_num: 4\n    narration: fixed 4\n  - scene_num: 2\n    narration: fixed 2\n", {}, "stop"

    with pytest.raises(ValueError, match="coverage mismatch"):
        await chain.writing_scene_repair_step("SCP-173", originals, "feedback", "desc", "guide", None, call)


async def test_writing_scene_repair_rejects_extra_scene(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    originals = [{"scene_num": 2, "narration": "old 2"}, {"scene_num": 4, "narration": "old 4"}]

    async def call(rendered, s):
        return (
            "scenes:\n"
            "  - scene_num: 2\n    narration: fixed 2\n"
            "  - scene_num: 4\n    narration: fixed 4\n"
            "  - scene_num: 5\n    narration: extra\n",
            {},
            "stop",
        )

    with pytest.raises(ValueError, match="expected 2 scenes"):
        await chain.writing_scene_repair_step("SCP-173", originals, "feedback", "desc", "guide", None, call)


async def test_research_step_collapses_embedded_newlines_in_freetext_fields(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        raw = (
            "core_identity: |\n  첫 줄.\n  둘째 줄.\n"
            "frozen_descriptor: |\n  첫 줄.\n  둘째 줄.\n"
            "entity_sheet: |\n  첫 줄.\n  둘째 줄.\n"
            "story_logline: |\n  첫 줄.\n  둘째 줄.\n"
            "hooks: |\n  첫 줄.\n  둘째 줄.\n"
        )
        return raw, {}, "stop"

    result = await chain.research_step("SCP-173", "text", "guide", None, call)
    for key in ("core_identity", "frozen_descriptor", "entity_sheet", "story_logline", "hooks"):
        assert result[key] == "첫 줄. 둘째 줄."


async def test_visual_breakdown_step_maps_one_shot_per_sentence(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_visual_breakdown.json")
    scene = {"scene_num": 1, "location": "x", "atmosphere": "y", "color_palette": "z", "characters_present": []}
    sentences = ["첫 문장.", "(정적)", "셋째 문장."]
    result = await chain.visual_breakdown_step("SCP-173", scene, sentences, {}, "desc", "entity sheet", "logline", {}, None, call)
    assert len(result) == 3
    assert result[0]["image_prompt"]
    assert result[1]["image_prompt"] == ""  # transition sentence, no image
    assert result[2]["camera_type"] == "wide"


async def test_visual_breakdown_step_attaches_precomputed_cast(monkeypatch):
    """Story 8.10: cast is decided by cast_decision_step, not the LLM in this call —
    attached onto each shot by sentence_start regardless of what the LLM echoes."""
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"scene_num": 1, "visual_descriptions": [
            {"image_prompt": "x", "negative_prompt": "x", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"},
            {"image_prompt": "y", "negative_prompt": "y", "sentence_start": 2, "sentence_end": 2, "camera_type": "medium"},
        ]}
        return json.dumps(payload), {}, "stop"

    scene = {"scene_num": 1, "location": "x", "atmosphere": "y", "color_palette": "z", "characters_present": []}
    cast_by_sentence = {1: [{"card_key": "SCP-173", "position": "center", "depth": "near", "pose": "standing"}], 2: []}
    result = await chain.visual_breakdown_step(
        "SCP-173", scene, ["문장1.", "문장2."], cast_by_sentence, "desc", "entity sheet", "logline", {}, None, call,
    )
    assert result[0]["cast"] == cast_by_sentence[1]
    assert result[1]["cast"] == []


async def test_visual_breakdown_step_rejects_count_mismatch(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"scene_num": 1, "visual_descriptions": [{"image_prompt": "x", "negative_prompt": "x", "sentence_start": 1, "sentence_end": 1, "entity_visible": False, "camera_type": "wide"}]}
        return json.dumps(payload), {}, "stop"

    scene = {"scene_num": 1, "location": "x", "atmosphere": "y", "color_palette": "z", "characters_present": []}
    with pytest.raises(ValueError, match="1:1"):
        await chain.visual_breakdown_step("SCP-173", scene, ["문장1.", "문장2."], {}, "desc", "entity sheet", "logline", {}, None, call)


async def test_visual_breakdown_step_rejects_non_int_sentence_start(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"scene_num": 1, "visual_descriptions": [
            {"image_prompt": "x", "negative_prompt": "x", "sentence_start": "1", "sentence_end": 1, "camera_type": "wide"}
        ]}
        return json.dumps(payload), {}, "stop"

    scene = {"scene_num": 1, "location": "x", "atmosphere": "y", "color_palette": "z", "characters_present": []}
    with pytest.raises(ValueError, match="sentence_start"):
        await chain.visual_breakdown_step("SCP-173", scene, ["문장1."], {1: []}, "desc", "entity sheet", "logline", {}, None, call)


async def test_visual_breakdown_step_collapses_embedded_newlines_in_prompts(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        raw = (
            "scene_num: 1\n"
            "visual_descriptions:\n"
            "  - image_prompt: |\n"
            "      첫 줄.\n"
            "      둘째 줄.\n"
            "    negative_prompt: |\n"
            "      첫 줄.\n"
            "      둘째 줄.\n"
            "    sentence_start: 1\n"
            "    sentence_end: 1\n"
            "    camera_type: wide\n"
        )
        return raw, {}, "stop"

    scene = {"scene_num": 1, "location": "x", "atmosphere": "y", "color_palette": "z", "characters_present": []}
    result = await chain.visual_breakdown_step("SCP-173", scene, ["문장1."], {1: []}, "desc", "entity sheet", "logline", {}, None, call)
    assert result[0]["image_prompt"] == "첫 줄. 둘째 줄."
    assert result[0]["negative_prompt"] == "첫 줄. 둘째 줄."


async def test_visual_breakdown_step_threads_story_and_entity_context(monkeypatch):
    class CapturingPrompt:
        def __init__(self):
            self.kwargs = None

        def compile(self, **kwargs):
            self.kwargs = kwargs
            return "rendered"

    captured = CapturingPrompt()
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: captured
    )

    async def call(rendered, s):
        payload = {"scene_num": 1, "visual_descriptions": [{"image_prompt": "x", "negative_prompt": "x", "sentence_start": 1, "sentence_end": 1, "entity_visible": False, "camera_type": "wide"}]}
        return json.dumps(payload), {}, "stop"

    scene = {"scene_num": 1, "location": "x", "atmosphere": "y", "color_palette": "z", "characters_present": []}
    scene_role = {"act": "hook", "emotional_beat": "tension", "synopsis": "the discovery"}
    cast_by_sentence = {1: [{"card_key": "SCP-173", "position": "center", "depth": "near", "pose": "standing"}]}
    await chain.visual_breakdown_step(
        "SCP-173", scene, ["문장1."], cast_by_sentence, "frozen desc", "entity sheet text", "story logline text",
        scene_role, None, call,
    )

    assert captured.kwargs["scp_visual_reference"] == "frozen desc"
    assert captured.kwargs["entity_sheet"] == "entity sheet text"
    assert captured.kwargs["story_logline"] == "story logline text"
    assert "hook" in captured.kwargs["scene_role"]
    assert "tension" in captured.kwargs["scene_role"]
    assert "the discovery" in captured.kwargs["scene_role"]
    assert captured.kwargs["scp_id"] == "SCP-173"
    assert json.loads(captured.kwargs["cast_by_sentence"]) == {"1": cast_by_sentence[1]}


# ── cast_decision_step (Story 8.10) ─────────────────────────────────────────


async def test_cast_decision_step_returns_cast_by_sentence(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"shots": [
            {"sentence": 1, "cast": [{"card_key": "SCP-173", "position": "center", "depth": "near", "pose": "standing"}]},
            {"sentence": 2, "cast": []},
        ]}
        return json.dumps(payload), {}, "stop"

    scene = {"scene_num": 1, "characters_present": ["SCP-173"]}
    result = await chain.cast_decision_step("SCP-173", scene, ["문장1.", "문장2."], None, call)
    assert result == {
        1: [{"card_key": "SCP-173", "position": "center", "depth": "near", "pose": "standing"}],
        2: [],
    }


async def test_cast_decision_step_rejects_count_mismatch(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"shots": [{"sentence": 1, "cast": []}]}
        return json.dumps(payload), {}, "stop"

    scene = {"scene_num": 1, "characters_present": []}
    with pytest.raises(ValueError, match="1:1"):
        await chain.cast_decision_step("SCP-173", scene, ["문장1.", "문장2."], None, call)


async def test_cast_decision_step_rejects_malformed_entries(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"shots": [
            "not-a-dict",
            {"sentence": "two", "cast": []},
            {"sentence": 1, "cast": [{"card_key": "SCP-173", "position": "center", "depth": "near", "pose": "standing"}]},
        ]}
        return json.dumps(payload), {}, "stop"

    scene = {"scene_num": 1, "characters_present": []}
    with pytest.raises(ValueError, match="malformed"):
        await chain.cast_decision_step("SCP-173", scene, ["문장1.", "문장2.", "문장3."], None, call)


async def test_cast_decision_step_rejects_non_list_cast(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"shots": [{"sentence": 1, "cast": "not-a-list"}]}
        return json.dumps(payload), {}, "stop"

    scene = {"scene_num": 1, "characters_present": []}
    with pytest.raises(ValueError, match="cast must be a list"):
        await chain.cast_decision_step("SCP-173", scene, ["문장1."], None, call)


async def test_cast_decision_step_rejects_duplicate_sentence(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"shots": [{"sentence": 1, "cast": []}, {"sentence": 1, "cast": []}]}
        return json.dumps(payload), {}, "stop"

    scene = {"scene_num": 1, "characters_present": []}
    with pytest.raises(ValueError, match="duplicate"):
        await chain.cast_decision_step("SCP-173", scene, ["문장1.", "문장2."], None, call)


async def test_cast_decision_step_rejects_out_of_range_sentence(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {"shots": [{"sentence": 1, "cast": []}, {"sentence": 3, "cast": []}]}
        return json.dumps(payload), {}, "stop"

    scene = {"scene_num": 1, "characters_present": []}
    with pytest.raises(ValueError, match="coverage mismatch"):
        await chain.cast_decision_step("SCP-173", scene, ["문장1.", "문장2."], None, call)


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


async def test_review_step_retries_non_boolean_overall_pass(monkeypatch):
    prompt = _CapturingPrompt()
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: prompt)
    responses = iter(["overall_pass: 'false'", "overall_pass: false"])

    async def call(rendered, s):
        return next(responses), {}, "stop"

    result = await chain.review_step("t", {"scenes": []}, {}, "desc", "guide", None, call)
    assert result["overall_pass"] is False
    assert len(prompt.calls) == 2


async def test_critic_step_returns_verdict(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_critic.json")
    writing = {"scenes": [{"scene_num": 1, "narration": "n"}]}
    result = await chain.critic_step(writing, {1: []}, "guide", None, call)
    assert result["verdict"] == "pass"
    assert result["feedback"]


async def test_critic_step_collapses_embedded_newlines_in_feedback(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return 'verdict: pass\nfeedback: |\n  첫 줄.\n  둘째 줄.\nscene_notes: []\n', {}, "stop"

    writing = {"scenes": [{"scene_num": 1, "narration": "n"}]}
    result = await chain.critic_step(writing, {1: []}, "guide", None, call)
    assert result["feedback"] == "첫 줄. 둘째 줄."


async def test_review_step_normalizes_nested_freetext_fields(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    async def call(rendered, s):
        return (
            "overall_pass: false\n"
            "issues:\n  - description: |\n      첫 줄.\n      둘째 줄.\n"
            "    correction: 42\n"
            "corrections:\n  - original: |\n      원문 한 줄.\n      원문 두 줄.\n"
            "    corrected: |\n      수정 한 줄.\n      수정 두 줄.\n"
            "storytelling_issues:\n  - description: |\n      문제 한 줄.\n      문제 두 줄.\n"
            "    correction: |\n      제안 한 줄.\n      제안 두 줄.\n"
        ), {}, "stop"

    result = await chain.review_step("t", {"scenes": []}, {}, "desc", "guide", None, call)

    assert result["issues"][0]["description"] == "첫 줄. 둘째 줄."
    assert result["issues"][0]["correction"] == 42
    assert result["corrections"][0]["original"] == "원문 한 줄. 원문 두 줄."
    assert result["corrections"][0]["corrected"] == "수정 한 줄. 수정 두 줄."
    assert result["storytelling_issues"][0]["description"] == "문제 한 줄. 문제 두 줄."
    assert result["storytelling_issues"][0]["correction"] == "제안 한 줄. 제안 두 줄."


async def test_critic_step_normalizes_scene_note_freetext_fields(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    async def call(rendered, s):
        return (
            "verdict: retry\nfeedback: ok\nscene_notes:\n"
            "  - scene_num: 1\n    issue: |\n      문제 한 줄.\n      문제 두 줄.\n"
            "    suggestion: |\n      제안 한 줄.\n      제안 두 줄.\n"
            "  - scene_num: 2\n    issue: 7\n"
        ), {}, "stop"

    result = await chain.critic_step({"scenes": []}, {}, "guide", None, call)

    assert result["scene_notes"][0]["issue"] == "문제 한 줄. 문제 두 줄."
    assert result["scene_notes"][0]["suggestion"] == "제안 한 줄. 제안 두 줄."
    assert result["scene_notes"][1]["issue"] == 7
    assert "suggestion" not in result["scene_notes"][1]


async def test_critic_step_rejects_unknown_verdict(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"verdict": "maybe", "feedback": "x", "scene_notes": []}), {}, "stop"

    with pytest.raises(ValueError, match="verdict"):
        await chain.critic_step({"scenes": []}, {}, "guide", None, call)


async def test_call_stage_uses_get_prompt_when_label_is_none(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt",
        lambda *a, **k: calls.append(("get_prompt", a, k)) or FakePrompt(),
    )
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt_with_fallback",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called when label is None")),
    )

    async def call(rendered, s):
        return "{}", {}, "stop"

    await chain._call_stage("scenario/research", {}, None, call, label=None)
    assert calls == [("get_prompt", ("scenario/research",), {})]


async def test_call_stage_uses_fallback_when_label_given(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called when label is set")),
    )
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt_with_fallback",
        lambda *a, **k: calls.append(("get_prompt_with_fallback", a, k)) or FakePrompt(),
    )

    async def call(rendered, s):
        return "{}", {}, "stop"

    await chain._call_stage("scenario/research", {}, None, call, label="candidate")
    assert calls == [("get_prompt_with_fallback", ("scenario/research",), {"label": "candidate"})]


# ── _parse_yaml / _call_stage_with_retry (Story 6.4: YAML output + bounded retry) ──


def test_parse_yaml_parses_plain_yaml():
    assert chain._parse_yaml("key: value") == {"key": "value"}


def test_parse_yaml_strips_yaml_fence():
    assert chain._parse_yaml("```yaml\nkey: value\n```") == {"key": "value"}


def test_parse_yaml_strips_bare_fence():
    assert chain._parse_yaml("```\nkey: value\n```") == {"key": "value"}


def test_parse_yaml_strips_json_fence():
    """A stage still running the pre-YAML production prompt emits JSON, and
    without json_object mode forcing bare output the model may fence it as
    ```json — that JSON parses fine as YAML once unfenced."""
    assert chain._parse_yaml('```json\n{"key": "value"}\n```') == {"key": "value"}


def test_parse_yaml_raises_yaml_error_on_malformed_input():
    with pytest.raises(yaml.YAMLError):
        chain._parse_yaml("key: [unterminated")


class _CapturingPrompt:
    def __init__(self):
        self.calls = []

    def compile(self, **variables):
        self.calls.append(variables)
        return "rendered"


async def test_call_stage_with_retry_routes_yaml_error_to_syntax_repair(monkeypatch):
    stage_prompt = _CapturingPrompt()
    repair_prompt = _CapturingPrompt()
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt",
        lambda name: repair_prompt if name == "scenario/yaml_syntax_repair" else stage_prompt,
    )

    responses = iter(["key: [unterminated", "key: value"])

    async def call(rendered, s):
        return next(responses), {}, "stop"

    def parse(raw):
        data = chain._parse_yaml(raw)
        if not isinstance(data, dict) or "key" not in data:
            raise ValueError("missing key")
        return data

    result = await chain._call_stage_with_retry("scenario/research", {"a": "b"}, None, call, parse)

    assert result == {"key": "value"}
    assert stage_prompt.calls == [{"a": "b", "parse_error": ""}]
    assert repair_prompt.calls[0]["broken_yaml"] == "key: [unterminated"
    assert "while parsing" in repair_prompt.calls[0]["yaml_error"]
    assert set(repair_prompt.calls[0]) == {"broken_yaml", "yaml_error"}


async def test_call_stage_with_retry_preserves_production_behavior_before_repair_promotion(
    monkeypatch, caplog
):
    stage_prompt = _CapturingPrompt()

    def get_prompt(name, **kwargs):
        if name == "scenario/yaml_syntax_repair":
            raise chain.prompt_service.PromptFetchError("missing production repair prompt")
        return stage_prompt

    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", get_prompt)
    responses = iter(["key: [unterminated", "key: value"])

    async def call(rendered, s):
        return next(responses), {}, "stop"

    with caplog.at_level("WARNING"):
        result = await chain._call_stage_with_retry(
            "scenario/research", {"a": "b"}, None, call, chain._parse_yaml
        )

    assert result == {"key": "value"}
    assert len(stage_prompt.calls) == 2
    assert "full-stage retry" in caplog.text


async def test_call_stage_with_retry_does_not_hide_missing_candidate_repair_prompt(monkeypatch):
    def get_with_fallback(name, **kwargs):
        if name == "scenario/yaml_syntax_repair":
            raise chain.prompt_service.PromptFetchError("missing candidate repair prompt")
        return FakePrompt()

    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt_with_fallback", get_with_fallback)

    async def call(rendered, s):
        return "key: [unterminated", {}, "stop"

    with pytest.raises(chain.prompt_service.PromptFetchError, match="missing candidate"):
        await chain._call_stage_with_retry(
            "scenario/research", {}, None, call, chain._parse_yaml, label="candidate"
        )


async def test_call_stage_with_retry_routes_value_error_to_full_regeneration(monkeypatch):
    stage_prompt = _CapturingPrompt()
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: stage_prompt)
    responses = iter(["other: value", "key: value"])

    async def call(rendered, s):
        return next(responses), {}, "stop"

    def parse(raw):
        data = chain._parse_yaml(raw)
        if "key" not in data:
            raise ValueError("missing key")
        return data

    result = await chain._call_stage_with_retry("scenario/research", {"a": "b"}, None, call, parse)

    assert result == {"key": "value"}
    assert len(stage_prompt.calls) == 2
    assert stage_prompt.calls[1]["a"] == "b"
    assert "Previous output failed validation" in stage_prompt.calls[1]["parse_error"]


async def test_call_stage_with_retry_exhausts_after_two_attempts(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call_count = 0

    async def call(rendered, s):
        nonlocal call_count
        call_count += 1
        return "key: [unterminated", {}, "stop"

    def parse(raw):
        return chain._parse_yaml(raw)

    with pytest.raises(yaml.YAMLError):
        await chain._call_stage_with_retry("scenario/research", {}, None, call, parse)
    assert call_count == 2  # bounded — no third attempt


async def test_call_stage_with_retry_second_failure_is_surfaced_not_first(monkeypatch):
    """The exception that propagates is the SECOND attempt's failure, even
    when it's a different error class than the first attempt's."""
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    responses = iter(["key: [unterminated", "key: value"])  # 1st: YAMLError, 2nd: parses but still invalid

    async def call(rendered, s):
        return next(responses), {}, "stop"

    def parse(raw):
        data = chain._parse_yaml(raw)
        raise ValueError(f"still invalid: {data}")

    with pytest.raises(ValueError, match="still invalid"):
        await chain._call_stage_with_retry("scenario/research", {}, None, call, parse)


async def test_call_stage_with_retry_handles_fenced_yaml_output(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return "```yaml\nkey: value\n```", {}, "stop"

    def parse(raw):
        data = chain._parse_yaml(raw)
        if not isinstance(data, dict) or "key" not in data:
            raise ValueError("missing key")
        return data

    result = await chain._call_stage_with_retry("scenario/research", {}, None, call, parse)
    assert result == {"key": "value"}


# ── usage_sink plumbing (Story 6.3: token/cache observability) ─────────────


async def test_call_stage_returns_usage_alongside_raw_text(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    async def call(rendered, s):
        return "key: value", {"prompt_tokens": 10}, "stop"

    raw, usage = await chain._call_stage("scenario/research", {}, None, call)
    assert raw == "key: value"
    assert usage == {"prompt_tokens": 10}


async def test_call_stage_with_retry_collects_one_usage_entry_on_first_success(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    async def call(rendered, s):
        return "key: value", {"prompt_tokens": 5, "prompt_cache_hit_tokens": 3}, "stop"

    usage_sink: list[dict] = []
    result = await chain._call_stage_with_retry(
        "scenario/research", {}, None, call, chain._parse_yaml, usage_sink=usage_sink
    )
    assert result == {"key": "value"}
    assert usage_sink == [{"prompt_tokens": 5, "prompt_cache_hit_tokens": 3}]


async def test_call_stage_with_retry_collects_both_usage_entries_on_retry(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    responses = iter([("key: [unterminated", {"prompt_tokens": 1}), ("key: value", {"prompt_tokens": 2})])

    async def call(rendered, s):
        raw, usage = next(responses)
        return raw, usage, "stop"

    usage_sink: list[dict] = []
    result = await chain._call_stage_with_retry(
        "scenario/research", {}, None, call, chain._parse_yaml, usage_sink=usage_sink
    )
    assert result == {"key": "value"}
    assert usage_sink == [{"prompt_tokens": 1}, {"prompt_tokens": 2}]


async def test_research_step_forwards_usage_into_sink(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    async def call(rendered, s):
        payload = {"frozen_descriptor": "desc"}
        return yaml.dump(payload), {"prompt_tokens": 7, "completion_tokens": 4}, "stop"

    usage_sink: list[dict] = []
    await chain.research_step("SCP-173", "text", "guide", None, call, usage_sink=usage_sink)
    assert usage_sink == [{"prompt_tokens": 7, "completion_tokens": 4}]


async def test_research_step_usage_sink_defaults_to_none_without_error(monkeypatch):
    """Existing callers that don't pass usage_sink keep working (Task 2's additive-only requirement)."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    async def call(rendered, s):
        payload = {"frozen_descriptor": "desc"}
        return yaml.dump(payload), {"prompt_tokens": 7}, "stop"

    result = await chain.research_step("SCP-173", "text", "guide", None, call)
    assert result["frozen_descriptor"] == "desc"


async def test_research_step_retries_once_on_malformed_yaml_then_succeeds(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    responses = iter(
        [
            "frozen_descriptor: [unterminated",
            "core_identity: x\nfrozen_descriptor: x\nentity_sheet: x\nstory_logline: x\n"
            "dramatic_beats: x\nenvironment: x\nhooks: x",
        ]
    )

    async def call(rendered, s):
        return next(responses), {}, "stop"

    result = await chain.research_step("SCP-173", "text", "guide", None, call)
    assert result["frozen_descriptor"] == "x"


async def test_tts_normalize_step_rewrites_narration(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_tts_normalize.json")
    writing = {
        "scp_id": "SCP-173",
        "title": "t",
        "scenes": [
            {
                "scene_num": 1,
                "narration": "14명. 단 하룻밤에 목이 꺾인 채 발견된 재단 인원 수입니다. (정적) 아무도 무기를 찾지 못했습니다.",
                "location": "underground containment chamber",
                "characters_present": ["SCP-173"],
                "color_palette": "cold gray",
                "atmosphere": "dread",
            }
        ],
    }
    result = await chain.tts_normalize_step(writing, "guide", None, call)
    assert result["scenes"][0]["narration"].startswith("열네 명.")
    # non-narration fields are preserved unchanged
    assert result["scenes"][0]["location"] == "underground containment chamber"
    assert result["scenes"][0]["characters_present"] == ["SCP-173"]
    # dual track (Story 5.18 AC:1): display_narration keeps the pre-normalization original
    assert result["scenes"][0]["display_narration"] == writing["scenes"][0]["narration"]


async def test_tts_normalize_step_collapses_embedded_newlines_in_narration(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return "scenes:\n  - scene_num: 1\n    narration: |\n      첫 문장.\n      둘째 문장.\n", {}, "stop"

    writing = {"scenes": [{"scene_num": 1, "narration": "첫 문장. 둘째 문장."}]}
    result = await chain.tts_normalize_step(writing, "guide", None, call)
    assert result["scenes"][0]["narration"] == "첫 문장. 둘째 문장."


async def test_tts_normalize_step_rejects_malformed_payload(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"scenes": "not-a-list"}), {}, "stop"

    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    with pytest.raises(ValueError, match="tts_normalize"):
        await chain.tts_normalize_step(writing, "guide", None, call)


async def test_tts_normalize_step_rejects_scene_count_mismatch(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"scenes": []}), {}, "stop"

    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    with pytest.raises(ValueError, match="tts_normalize"):
        await chain.tts_normalize_step(writing, "guide", None, call)


async def test_tts_normalize_step_matches_scenes_positionally(monkeypatch):
    # LLM echoes a duplicate/misleading scene_num — matching must be by list
    # position, not by the LLM's own scene_num, matching build_scenes()'s rule.
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {
            "scenes": [
                {"scene_num": 1, "narration": "정규화 첫째."},
                {"scene_num": 1, "narration": "정규화 둘째."},
            ]
        }
        return json.dumps(payload), {}, "stop"

    writing = {
        "scenes": [
            {"scene_num": 1, "narration": "원본 첫째."},
            {"scene_num": 2, "narration": "원본 둘째."},
        ]
    }
    result = await chain.tts_normalize_step(writing, "guide", None, call)
    assert result["scenes"][0]["narration"] == "정규화 첫째."
    assert result["scenes"][0]["scene_num"] == 1  # original scene_num preserved
    assert result["scenes"][1]["narration"] == "정규화 둘째."
    assert result["scenes"][1]["scene_num"] == 2


async def test_tts_normalize_step_falls_back_per_scene_on_sentence_count_mismatch(monkeypatch):
    # Scene 1's normalized text adds a sentence boundary -> keep original.
    # Scene 2 normalizes cleanly -> accept it. One bad scene must not fail the rest.
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        payload = {
            "scenes": [
                {"scene_num": 1, "narration": "첫 문장. 추가된 문장."},
                {"scene_num": 2, "narration": "정규화된 둘째 문장."},
            ]
        }
        return json.dumps(payload), {}, "stop"

    writing = {
        "scenes": [
            {"scene_num": 1, "narration": "원본 첫 문장."},
            {"scene_num": 2, "narration": "원본 둘째 문장."},
        ]
    }
    result = await chain.tts_normalize_step(writing, "guide", None, call)
    assert result["scenes"][0]["narration"] == "원본 첫 문장."  # fell back
    assert result["scenes"][1]["narration"] == "정규화된 둘째 문장."  # accepted
    # Mismatch degrades to single-track (Story 5.18 AC:2): display == spoken == original.
    assert result["scenes"][0]["display_narration"] == "원본 첫 문장."
    assert result["scenes"][1]["display_narration"] == "원본 둘째 문장."


async def test_tts_normalize_step_propagates_candidate_label(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called when label is set")),
    )
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt_with_fallback",
        lambda *a, **k: calls.append(("get_prompt_with_fallback", a, k)) or FakePrompt(),
    )

    async def call(rendered, s):
        return json.dumps({"scenes": [{"scene_num": 1, "narration": "문장."}]}), {}, "stop"

    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    await chain.tts_normalize_step(writing, "guide", None, call, label="candidate")
    assert calls == [("get_prompt_with_fallback", ("scenario/tts_normalize",), {"label": "candidate"})]


def test_build_scenes_merges_empty_prompt_into_previous_shot():
    writing = {
        "scenes": [
            {"scene_num": 1, "narration": "첫 문장. (정적) 셋째 문장."}
        ]
    }
    visual_by_scene = {
        0: [
            {"image_prompt": "shot one", "negative_prompt": "neg one", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"},
            {"image_prompt": "", "negative_prompt": "", "sentence_start": 2, "sentence_end": 2, "camera_type": "wide"},
            {"image_prompt": "shot three", "negative_prompt": "neg three", "sentence_start": 3, "sentence_end": 3, "camera_type": "close-up"},
        ]
    }
    scenes = chain.build_scenes(writing, visual_by_scene, [{}])
    assert len(scenes) == 1
    shots = scenes[0]["shots"]
    assert len(shots) == 2  # the empty-prompt sentence merged into shot 1, not its own shot
    assert shots[0]["sentence_indices"] == [0, 1]  # 0-based: sentences 1 and 2
    assert shots[1]["sentence_indices"] == [2]
    assert all(s["image_prompt"] for s in shots)  # never empty


def test_build_scenes_first_sentence_empty_falls_back_to_scene_context():
    writing = {"scenes": [{"scene_num": 1, "narration": "(정적) 둘째 문장.", "location": "hallway", "atmosphere": "cold dread"}]}
    visual_by_scene = {
        0: [
            {"image_prompt": "", "negative_prompt": "", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"},
            {"image_prompt": "shot two", "negative_prompt": "neg two", "sentence_start": 2, "sentence_end": 2, "camera_type": "medium"},
        ]
    }
    scenes = chain.build_scenes(writing, visual_by_scene, [{}])
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
        0: [{"image_prompt": "a", "negative_prompt": "b", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}],
    }
    visual_by_scene_full = {0: visual_by_scene[0], 1: visual_by_scene[0]}
    scenes = chain.build_scenes(writing, visual_by_scene_full, [{}, {}])
    assert [s["scene_num"] for s in scenes] == [1, 2]


def test_build_scenes_single_empty_shot_falls_back_not_raises():
    writing = {"scenes": [{"scene_num": 1, "narration": "(정적)", "location": "vault", "atmosphere": "silence"}]}
    visual_by_scene = {0: [{"image_prompt": "", "negative_prompt": "", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}]}
    scenes = chain.build_scenes(writing, visual_by_scene, [{}])
    assert len(scenes[0]["shots"]) == 1
    assert scenes[0]["shots"][0]["image_prompt"]


# ── mood field (Story 5.15: sourced from structure, normalized at chain time) ──


_ONE_SHOT_VISUAL = {0: [{"image_prompt": "a", "negative_prompt": "b", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}]}


def test_build_scenes_valid_structure_mood_passes_through_no_warning(caplog):
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    with caplog.at_level(logging.WARNING):
        scenes = chain.build_scenes(writing, _ONE_SHOT_VISUAL, [{"mood": "escalation"}])
    assert scenes[0]["mood"] == "escalation"
    assert not caplog.records


def test_build_scenes_mood_case_and_whitespace_normalized_no_warning(caplog):
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    with caplog.at_level(logging.WARNING):
        scenes = chain.build_scenes(writing, _ONE_SHOT_VISUAL, [{"mood": " Escalation "}])
    assert scenes[0]["mood"] == "escalation"
    assert not caplog.records


def test_build_scenes_structure_mood_wins_over_writing_mood():
    writing = {"scenes": [{"scene_num": 1, "narration": "문장.", "mood": "clinical"}]}
    scenes = chain.build_scenes(writing, _ONE_SHOT_VISUAL, [{"mood": "revelation"}])
    assert scenes[0]["mood"] == "revelation"


def test_build_scenes_invalid_structure_mood_falls_back_with_warning(caplog):
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    with caplog.at_level(logging.WARNING):
        scenes = chain.build_scenes(writing, _ONE_SHOT_VISUAL, [{"mood": "shock"}])
    assert scenes[0]["mood"] == sound_design.DEFAULT_MOOD
    assert any("1" in r.message and "shock" in r.message for r in caplog.records)


def test_build_scenes_missing_mood_key_falls_back_with_warning(caplog):
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    with caplog.at_level(logging.WARNING):
        scenes = chain.build_scenes(writing, _ONE_SHOT_VISUAL, [{}])
    assert scenes[0]["mood"] == sound_design.DEFAULT_MOOD
    assert len(caplog.records) == 1


def test_build_scenes_non_dict_structure_entry_falls_back_with_warning(caplog):
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    with caplog.at_level(logging.WARNING):
        scenes = chain.build_scenes(writing, _ONE_SHOT_VISUAL, ["not-a-dict"])
    assert scenes[0]["mood"] == sound_design.DEFAULT_MOOD
    assert len(caplog.records) == 1


def test_build_scenes_writing_over_produces_trailing_scene_falls_back_with_warning(caplog):
    writing = {"scenes": [
        {"scene_num": 1, "narration": "첫 문장."},
        {"scene_num": 2, "narration": "둘째 문장."},
    ]}
    visual_by_scene = {0: _ONE_SHOT_VISUAL[0], 1: _ONE_SHOT_VISUAL[0]}
    with caplog.at_level(logging.WARNING):
        scenes = chain.build_scenes(writing, visual_by_scene, [{"mood": "clinical"}])
    assert scenes[0]["mood"] == "clinical"
    assert scenes[1]["mood"] == sound_design.DEFAULT_MOOD
    assert any("2" in r.message and "None" in r.message for r in caplog.records)


# ── title/kicker fields (Story 5.17: sourced from structure, chapter-card text) ──


def test_build_scenes_populates_title_and_kicker_from_structure():
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    scenes = chain.build_scenes(
        writing, _ONE_SHOT_VISUAL, [{"title": "첫 면담", "kicker": "개체가 입을 열다"}]
    )
    assert scenes[0]["title"] == "첫 면담"
    assert scenes[0]["kicker"] == "개체가 입을 열다"


def test_build_scenes_title_and_kicker_default_empty_when_missing():
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    scenes = chain.build_scenes(writing, _ONE_SHOT_VISUAL, [{}])
    assert scenes[0]["title"] == ""
    assert scenes[0]["kicker"] == ""


def test_build_scenes_title_and_kicker_default_empty_when_structure_entry_non_dict():
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    scenes = chain.build_scenes(writing, _ONE_SHOT_VISUAL, ["not-a-dict"])
    assert scenes[0]["title"] == ""
    assert scenes[0]["kicker"] == ""


def test_build_scenes_title_and_kicker_stripped_to_first_line():
    # Typography-restraint rule (AC:4) enforced at data-assembly time, not just
    # by the prompt — a multi-line LLM title/kicker still becomes one line.
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    scenes = chain.build_scenes(
        writing, _ONE_SHOT_VISUAL,
        [{"title": "  첫 면담  \n둘째 줄", "kicker": "상황 한 줄\n스포일러 줄"}],
    )
    assert scenes[0]["title"] == "첫 면담"
    assert scenes[0]["kicker"] == "상황 한 줄"


def test_build_scenes_title_and_kicker_drop_non_string_values():
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    scenes = chain.build_scenes(
        writing, _ONE_SHOT_VISUAL, [{"title": ["첫 면담"], "kicker": {"text": "상황"}}]
    )
    assert scenes[0]["title"] == ""
    assert scenes[0]["kicker"] == ""


# ── parse_cast (Story 8.1: leniency table per Epic 8 Interfaces rules 4-6) ──────


def test_parse_cast_valid_entry_passes_through():
    raw = [{"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "sitting"}]
    assert chain.parse_cast(raw) == [
        {"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "sitting"}
    ]


def test_parse_cast_invalid_position_falls_back_to_center():
    raw = [{"card_key": "SCP-049", "position": "sideways", "depth": "near", "pose": "standing"}]
    assert chain.parse_cast(raw)[0]["position"] == "center"


def test_parse_cast_invalid_depth_falls_back_to_mid():
    raw = [{"card_key": "SCP-049", "position": "left", "depth": "very-far", "pose": "standing"}]
    assert chain.parse_cast(raw)[0]["depth"] == "mid"


def test_parse_cast_invalid_pose_falls_back_to_standing():
    raw = [{"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "crouching"}]
    assert chain.parse_cast(raw)[0]["pose"] == "standing"


def test_parse_cast_missing_pose_defaults_to_standing():
    raw = [{"card_key": "SCP-049", "position": "left", "depth": "near"}]
    assert chain.parse_cast(raw)[0]["pose"] == "standing"


def test_parse_cast_normalizes_enum_case_and_whitespace():
    raw = [{"card_key": "SCP-049", "position": " Left ", "depth": " NEAR ", "pose": " Sitting "}]
    assert chain.parse_cast(raw)[0] == {
        "card_key": "SCP-049",
        "position": "left",
        "depth": "near",
        "pose": "sitting",
    }


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("kneeling over a corpse", "kneeling over a corpse"),
        ("  lying on operating table  ", "lying on operating table"),
        ("", None),
        ("   ", None),
        (["kneeling"], None),
        ("x" * 81, None),
    ],
)
def test_parse_cast_pose_hint_leniency_table(hint, expected):
    raw = [{
        "card_key": "SCP-049",
        "position": "left",
        "depth": "near",
        "pose": "standing",
        "pose_hint": hint,
    }]
    member = chain.parse_cast(raw)[0]
    if expected is None:
        assert "pose_hint" not in member
    else:
        assert member["pose_hint"] == expected


def test_parse_cast_pose_hint_survives_when_other_fields_default():
    raw = [{
        "card_key": "SCP-049",
        "position": "offscreen",
        "depth": "deep",
        "pose": "crouching",
        "pose_hint": "reaching toward camera",
    }]
    assert chain.parse_cast(raw)[0] == {
        "card_key": "SCP-049",
        "position": "center",
        "depth": "mid",
        "pose": "standing",
        "pose_hint": "reaching toward camera",
    }


def test_parse_cast_drops_non_dict_entry(caplog):
    with caplog.at_level(logging.WARNING):
        result = chain.parse_cast(["not-a-dict", {"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing"}])
    assert len(result) == 1
    assert result[0]["card_key"] == "SCP-049"
    assert any("non-dict" in r.message for r in caplog.records)


def test_parse_cast_drops_empty_card_key(caplog):
    with caplog.at_level(logging.WARNING):
        result = chain.parse_cast([{"card_key": "", "position": "left", "depth": "near", "pose": "standing"}])
    assert result == []
    assert any("unusable card_key" in r.message for r in caplog.records)


def test_parse_cast_drops_non_string_card_key(caplog):
    with caplog.at_level(logging.WARNING):
        result = chain.parse_cast([{"card_key": 42, "position": "left", "depth": "near", "pose": "standing"}])
    assert result == []


def test_parse_cast_normalizes_scp_prefix_casing():
    raw = [{"card_key": "scp-049", "position": "left", "depth": "near", "pose": "standing"}]
    assert chain.parse_cast(raw)[0]["card_key"] == "SCP-049"


def test_parse_cast_normalizes_stock_key_casing():
    raw = [{"card_key": "stock-researcher", "position": "left", "depth": "near", "pose": "standing"}]
    assert chain.parse_cast(raw)[0]["card_key"] == "STOCK-researcher"


def test_parse_cast_derived_entity_key_passes_through_unchanged():
    raw = [{"card_key": "SCP-049-2", "position": "left", "depth": "near", "pose": "standing"}]
    assert chain.parse_cast(raw)[0]["card_key"] == "SCP-049-2"


def test_parse_cast_missing_cast_returns_empty_list():
    assert chain.parse_cast(None) == []


def test_parse_cast_non_list_returns_empty_list():
    assert chain.parse_cast({"card_key": "SCP-049"}) == []


# ── motion_style / motion_energy (Story 8.8) ─────────────────────────────────


def test_parse_cast_missing_motion_fields_are_omitted():
    raw = [{"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing"}]
    member = chain.parse_cast(raw)[0]
    assert "motion_style" not in member
    assert "motion_energy" not in member


@pytest.mark.parametrize("style", sorted(chain._VALID_MOTION_STYLES))
def test_parse_cast_every_legal_motion_style_passes_through(style):
    raw = [{"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing", "motion_style": style}]
    assert chain.parse_cast(raw)[0]["motion_style"] == style


@pytest.mark.parametrize("energy", sorted(chain._VALID_MOTION_ENERGIES))
def test_parse_cast_every_legal_motion_energy_passes_through(energy):
    raw = [{"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing", "motion_energy": energy}]
    assert chain.parse_cast(raw)[0]["motion_energy"] == energy


@pytest.mark.parametrize("bad_style", ["floating", "", 5, ["breath"], None])
def test_parse_cast_invalid_motion_style_normalizes_to_breath(bad_style):
    raw = [{
        "card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing",
        "motion_style": bad_style,
    }]
    assert chain.parse_cast(raw)[0]["motion_style"] == "breath"


@pytest.mark.parametrize("bad_energy", ["extreme", "", 3, ["low"], None])
def test_parse_cast_invalid_motion_energy_normalizes_to_medium(bad_energy):
    raw = [{
        "card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing",
        "motion_energy": bad_energy,
    }]
    assert chain.parse_cast(raw)[0]["motion_energy"] == "medium"


# ── movement_mode / movement_direction / movement_pace (Story 8.9) ──────────


def test_parse_cast_missing_movement_fields_are_omitted():
    raw = [{"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing"}]
    member = chain.parse_cast(raw)[0]
    assert "movement_mode" not in member
    assert "movement_direction" not in member
    assert "movement_pace" not in member


@pytest.mark.parametrize("mode", sorted(chain._VALID_MOVEMENT_MODES))
def test_parse_cast_every_legal_movement_mode_passes_through(mode):
    raw = [{
        "card_key": "SCP-049", "position": "center", "depth": "near", "pose": "standing",
        "movement_mode": mode,
    }]
    assert chain.parse_cast(raw)[0]["movement_mode"] == mode


@pytest.mark.parametrize("pace", sorted(chain._VALID_MOVEMENT_PACES))
def test_parse_cast_every_legal_movement_pace_passes_through(pace):
    raw = [{
        "card_key": "SCP-049", "position": "center", "depth": "near", "pose": "standing",
        "movement_mode": "drift", "movement_pace": pace,
    }]
    assert chain.parse_cast(raw)[0]["movement_pace"] == pace


@pytest.mark.parametrize("bad_mode", ["walk", "", 5, ["enter"], None])
def test_parse_cast_invalid_movement_mode_normalizes_to_anchored(bad_mode):
    raw = [{
        "card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing",
        "movement_mode": bad_mode,
    }]
    assert chain.parse_cast(raw)[0]["movement_mode"] == "anchored"


@pytest.mark.parametrize("bad_pace", ["snail", "", 3, ["slow"], None])
def test_parse_cast_invalid_movement_pace_normalizes_to_slow(bad_pace):
    raw = [{
        "card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing",
        "movement_mode": "drift", "movement_pace": bad_pace,
    }]
    assert chain.parse_cast(raw)[0]["movement_pace"] == "slow"


@pytest.mark.parametrize("mode", ["anchored", "drift"])
def test_parse_cast_anchored_and_drift_force_direction_none(mode):
    raw = [{
        "card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing",
        "movement_mode": mode, "movement_direction": "right",
    }]
    assert chain.parse_cast(raw)[0]["movement_direction"] == "none"


def test_parse_cast_approach_forces_direction_in():
    raw = [{
        "card_key": "SCP-049", "position": "center", "depth": "mid", "pose": "standing",
        "movement_mode": "approach", "movement_direction": "left",
    }]
    assert chain.parse_cast(raw)[0]["movement_direction"] == "in"


def test_parse_cast_retreat_forces_direction_out():
    raw = [{
        "card_key": "SCP-049", "position": "center", "depth": "mid", "pose": "standing",
        "movement_mode": "retreat", "movement_direction": "right",
    }]
    assert chain.parse_cast(raw)[0]["movement_direction"] == "out"


@pytest.mark.parametrize(
    ("mode", "position", "expected"),
    [
        ("enter", "left", "left"),
        ("enter", "right", "right"),
        ("enter", "center", "left"),
        ("exit", "left", "left"),
        ("exit", "right", "right"),
        ("exit", "center", "left"),
    ],
)
def test_parse_cast_enter_exit_default_direction_matches_position(mode, position, expected):
    raw = [{"card_key": "SCP-049", "position": position, "depth": "near", "pose": "standing", "movement_mode": mode}]
    assert chain.parse_cast(raw)[0]["movement_direction"] == expected


@pytest.mark.parametrize(
    ("position", "expected"),
    [("left", "right"), ("right", "left"), ("center", "right")],
)
def test_parse_cast_cross_default_direction_is_opposite_of_position(position, expected):
    raw = [{"card_key": "SCP-049", "position": position, "depth": "near", "pose": "standing", "movement_mode": "cross"}]
    assert chain.parse_cast(raw)[0]["movement_direction"] == expected


def test_parse_cast_cross_keeps_explicit_valid_direction():
    raw = [{
        "card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing",
        "movement_mode": "cross", "movement_direction": "left",
    }]
    assert chain.parse_cast(raw)[0]["movement_direction"] == "left"


def test_parse_cast_movement_direction_alone_defaults_mode_and_pace():
    """Any single movement key present triggers full resolution of all three
    (Story 8.9 leniency rule — interdependent, unlike 8.8's independent keys)."""
    raw = [{
        "card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing",
        "movement_direction": "right",
    }]
    member = chain.parse_cast(raw)[0]
    assert member["movement_mode"] == "anchored"
    assert member["movement_direction"] == "none"  # anchored forces direction back to none
    assert member["movement_pace"] == "slow"


# ── parse_location_key (Story 8.5: closed LocationKey vocabulary leniency) ──────


@pytest.mark.parametrize("key", sorted(chain._LOCATION_KEY_CANONICAL.values()))
def test_parse_location_key_every_valid_key_passes_through(key):
    assert chain.parse_location_key(key) == key


def test_parse_location_key_tolerates_whitespace_and_casing(caplog):
    with caplog.at_level(logging.WARNING):
        assert chain.parse_location_key("  Corridor  ") == "corridor"
    assert caplog.text == ""


def test_parse_location_key_unknown_string_falls_back_to_none_with_warning(caplog):
    with caplog.at_level(logging.WARNING):
        assert chain.parse_location_key("moon-base") is None
    assert "unknown location_key" in caplog.text


def test_parse_location_key_missing_returns_none_no_warning(caplog):
    with caplog.at_level(logging.WARNING):
        assert chain.parse_location_key(None) is None
    assert caplog.text == ""


@pytest.mark.parametrize("bad", [None, 5, ["corridor"], {"key": "corridor"}, 3.5])
def test_parse_location_key_non_string_returns_none_no_warning(bad, caplog):
    with caplog.at_level(logging.WARNING):
        assert chain.parse_location_key(bad) is None
    assert caplog.text == ""


# ── cast field (Story 8.1: build_scenes attaches parsed cast per shot) ──────────


def test_build_scenes_attaches_cast_to_shot():
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    visual_by_scene = {0: [{
        "image_prompt": "a", "negative_prompt": "b", "sentence_start": 1, "sentence_end": 1,
        "camera_type": "wide", "cast": [{"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing"}],
    }]}
    scenes = chain.build_scenes(writing, visual_by_scene, [{}])
    assert scenes[0]["shots"][0]["cast"] == [
        {"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing"}
    ]


def test_build_scenes_legacy_payload_without_cast_defaults_empty():
    # Old production prompt (pre-8.1) never emits "cast" at all.
    scenes = chain.build_scenes({"scenes": [{"scene_num": 1, "narration": "문장."}]}, _ONE_SHOT_VISUAL, [{}])
    assert scenes[0]["shots"][0]["cast"] == []


def test_build_scenes_merged_shot_contributes_no_cast_of_its_own():
    writing = {"scenes": [{"scene_num": 1, "narration": "첫 문장. (정적) 셋째 문장."}]}
    visual_by_scene = {
        0: [
            {"image_prompt": "shot one", "negative_prompt": "n", "sentence_start": 1, "sentence_end": 1,
             "camera_type": "wide", "cast": [{"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing"}]},
            {"image_prompt": "", "negative_prompt": "", "sentence_start": 2, "sentence_end": 2, "camera_type": "wide",
             "cast": [{"card_key": "STOCK-researcher", "position": "right", "depth": "far", "pose": "standing"}]},
            {"image_prompt": "shot three", "negative_prompt": "n", "sentence_start": 3, "sentence_end": 3, "camera_type": "close-up"},
        ]
    }
    scenes = chain.build_scenes(writing, visual_by_scene, [{}])
    shots = scenes[0]["shots"]
    assert len(shots) == 2
    # The merged empty-prompt sentence's cast is discarded, not merged into shot 1.
    assert shots[0]["cast"] == [{"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing"}]
    assert shots[1]["cast"] == []


def test_build_scenes_fallback_backfill_shot_gets_empty_cast():
    # Leading transition sentence with no previous shot to merge into: the LLM
    # may still have emitted a cast for it, but the backfilled "no visible
    # subject" prompt must not carry cast through.
    writing = {"scenes": [{"scene_num": 1, "narration": "(정적) 둘째 문장.", "location": "hallway", "atmosphere": "cold dread"}]}
    visual_by_scene = {
        0: [
            {"image_prompt": "", "negative_prompt": "", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide",
             "cast": [{"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing"}]},
            {"image_prompt": "shot two", "negative_prompt": "n", "sentence_start": 2, "sentence_end": 2, "camera_type": "medium"},
        ]
    }
    scenes = chain.build_scenes(writing, visual_by_scene, [{}])
    assert scenes[0]["shots"][0]["cast"] == []


# ── location_key field (Story 8.5: build_scenes attaches parsed location_key) ───


def test_build_scenes_attaches_valid_location_key_to_shot():
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    visual_by_scene = {0: [{
        "image_prompt": "a", "negative_prompt": "b", "sentence_start": 1, "sentence_end": 1,
        "camera_type": "wide", "location_key": "corridor",
    }]}
    scenes = chain.build_scenes(writing, visual_by_scene, [{}])
    assert scenes[0]["shots"][0]["location_key"] == "corridor"


def test_build_scenes_unknown_location_key_degrades_to_none():
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    visual_by_scene = {0: [{
        "image_prompt": "a", "negative_prompt": "b", "sentence_start": 1, "sentence_end": 1,
        "camera_type": "wide", "location_key": "moon-base",
    }]}
    scenes = chain.build_scenes(writing, visual_by_scene, [{}])
    assert scenes[0]["shots"][0]["location_key"] is None


def test_build_scenes_legacy_payload_without_location_key_defaults_none():
    # Old production prompt (pre-8.5) never emits "location_key" at all.
    scenes = chain.build_scenes({"scenes": [{"scene_num": 1, "narration": "문장."}]}, _ONE_SHOT_VISUAL, [{}])
    assert scenes[0]["shots"][0]["location_key"] is None


# ── display_narration field (Story 5.18: dual track — subtitle vs TTS) ──────────


def test_build_scenes_copies_display_narration_from_writing_scene():
    writing = {"scenes": [{"scene_num": 1, "narration": "정규화문.", "display_narration": "원문."}]}
    scenes = chain.build_scenes(writing, _ONE_SHOT_VISUAL, [{}])
    assert scenes[0]["display_narration"] == "원문."
    assert scenes[0]["narration"] == "정규화문."


def test_build_scenes_display_narration_defaults_to_narration_when_absent():
    # Old checkpoints / degraded scenes without a display_narration key (AC:7).
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    scenes = chain.build_scenes(writing, _ONE_SHOT_VISUAL, [{}])
    assert scenes[0]["display_narration"] == "문장."
