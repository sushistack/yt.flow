import copy
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
    for placeholder in ("{{scp_id}}", "{{stock_cast_catalog}}", "{{characters_present}}", "{{numbered_sentences}}", "{{sentence_count}}"):
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

    with pytest.raises(chain.SceneCoverageError, match="expected 2 scenes"):
        await chain.writing_scene_repair_step("SCP-173", originals, "feedback", "desc", "guide", None, call)


async def test_writing_scene_repair_reorders_permutation_to_expected(monkeypatch):
    # Story 6.10: the observed SCP-049 habit is the model returning the requested
    # scenes in a different order (sorted by scene_num). That is the same scene
    # set, so it recovers by reordering to the requested positional order — it is
    # NOT a coverage failure and must not raise.
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    originals = [{"scene_num": 4, "narration": "old 4"}, {"scene_num": 2, "narration": "old 2"}]

    async def call(rendered, s):
        return "scenes:\n  - scene_num: 2\n    narration: fixed 2\n  - scene_num: 4\n    narration: fixed 4\n", {}, "stop"

    result = await chain.writing_scene_repair_step("SCP-173", originals, "feedback", "desc", "guide", None, call)
    assert [sc["scene_num"] for sc in result] == [4, 2]  # reordered back to the requested order
    assert result[0]["narration"] == "fixed 4"
    assert result[1]["narration"] == "fixed 2"


async def test_writing_scene_repair_genuine_set_mismatch_raises_scene_coverage_error(monkeypatch):
    # A genuinely different scene set (right count, wrong identifiers) can't be
    # mapped back to the originals — it is a real coverage mismatch and must
    # raise SceneCoverageError so the caller falls back to a full rewrite.
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    originals = [{"scene_num": 2, "narration": "old 2"}, {"scene_num": 4, "narration": "old 4"}]

    async def call(rendered, s):
        return "scenes:\n  - scene_num: 2\n    narration: fixed 2\n  - scene_num: 5\n    narration: wrong\n", {}, "stop"

    with pytest.raises(chain.SceneCoverageError, match="coverage mismatch"):
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


async def test_call_stage_with_retry_repairs_freetext_colon_deterministically(monkeypatch):
    """Story 6.11: an unquoted colon in a free-text field is repaired
    deterministically (block-literal) with NO second DeepSeek call and no LLM
    repair prompt — the old ``scenario/yaml_syntax_repair`` path is gone."""
    stage_prompt = _CapturingPrompt()
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: stage_prompt)
    call_count = 0

    async def call(rendered, s):
        nonlocal call_count
        call_count += 1
        return "frozen_descriptor: SCP-049 says: remain calm", {}, "stop"

    def parse(raw):
        data = chain._parse_yaml(raw)
        if not isinstance(data, dict) or "frozen_descriptor" not in data:
            raise ValueError("missing frozen_descriptor")
        return data

    result = await chain._call_stage_with_retry("scenario/research", {"a": "b"}, None, call, parse)

    assert result == {"frozen_descriptor": "SCP-049 says: remain calm"}
    assert call_count == 1  # deterministic fix adds no model call
    assert stage_prompt.calls == [{"a": "b", "parse_error": ""}]


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


async def test_call_stage_with_retry_yaml_error_normalizer_cannot_fix_propagates(monkeypatch):
    """Story 6.11: a YAML-syntax failure the deterministic normalizer can't
    repair (not a free-text scalar) propagates after exactly ONE model call —
    no LLM fallback, no second attempt."""
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call_count = 0

    async def call(rendered, s):
        nonlocal call_count
        call_count += 1
        return "key: [unterminated", {}, "stop"

    with pytest.raises(yaml.YAMLError):
        await chain._call_stage_with_retry("scenario/research", {}, None, call, chain._parse_yaml)
    assert call_count == 1  # deterministic YAML repair adds no model call


async def test_call_stage_with_retry_semantic_retry_is_bounded(monkeypatch):
    """A semantic (ValueError) validation failure retries exactly once; a second
    ValueError propagates unchanged (bounded — no third attempt)."""
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call_count = 0

    async def call(rendered, s):
        nonlocal call_count
        call_count += 1
        return "other: value", {}, "stop"

    def parse(raw):
        chain._parse_yaml(raw)
        raise ValueError(f"still invalid attempt {call_count}")

    with pytest.raises(ValueError, match="attempt 2"):
        await chain._call_stage_with_retry("scenario/research", {}, None, call, parse)
    assert call_count == 2  # bounded — no third attempt


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


# ── deterministic free-text repair (Story 6.11) ──────────────────────────────


def _repair(broken):
    """Drive the repair exactly as ``_call_stage_with_retry`` does: parse, and on
    YAMLError re-parse with the flagged free-text line(s) block-ified."""
    try:
        return chain._parse_yaml(broken)
    except yaml.YAMLError as exc:
        return chain._reparse_repairing_freetext(broken, chain._parse_yaml, exc)


def test_repair_top_level_freetext_colon():
    broken = "frozen_descriptor: SCP-049 is: a plague doctor"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(broken)
    assert _repair(broken) == {"frozen_descriptor": "SCP-049 is: a plague doctor"}  # byte-identical


def test_repair_scene_list_narration_colon():
    broken = "scenes:\n  - scene_num: 1\n    narration: 박사가 말했다: 위험해\n    mood: dread"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(broken)
    data = _repair(broken)
    assert data["scenes"][0]["narration"] == "박사가 말했다: 위험해"
    assert data["scenes"][0]["scene_num"] == 1  # sibling keys untouched
    assert data["scenes"][0]["mood"] == "dread"


def test_repair_dash_narration_colon():
    broken = "scenes:\n  - narration: he said: run"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(broken)
    assert _repair(broken)["scenes"][0] == {"narration": "he said: run"}


def test_repair_multiple_broken_freetext_lines_in_one_doc():
    # two broken free-text lines → the bounded loop repairs each flagged line in turn
    broken = "shots:\n  - image_prompt: dark hall, style: cinematic\n    negative_prompt: blurry: bad"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(broken)
    data = _repair(broken)
    assert data["shots"][0]["image_prompt"] == "dark hall, style: cinematic"
    assert data["shots"][0]["negative_prompt"] == "blurry: bad"


def test_repair_does_not_corrupt_valid_siblings():
    # F1 regression (mark-targeted): only the flagged line is rewritten. A valid
    # quoted value keeps no literal quotes, a trailing comment is NOT absorbed,
    # and an empty scalar stays empty — none of these are the flagged line.
    broken = (
        'frozen_descriptor: "SCP-049: plague doctor"\n'
        "story_logline: a lab goes dark  # ominous\n"
        'image_prompt: ""\n'
        "narration: he said: run"
    )
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(broken)
    data = _repair(broken)
    assert data["frozen_descriptor"] == "SCP-049: plague doctor"  # quotes NOT literal
    assert data["story_logline"] == "a lab goes dark"             # comment NOT absorbed
    assert data["image_prompt"] == ""                             # empty stays empty
    assert data["narration"] == "he said: run"                   # the flagged line, fixed


def test_repair_leaves_valid_output_untouched():
    ok = "scenes:\n  - scene_num: 1\n    narration: a quiet room"  # parses first try
    assert _repair(ok) == {"scenes": [{"scene_num": 1, "narration": "a quiet room"}]}


def test_repair_non_freetext_colon_propagates():
    # a colon in a non-free-text value is out of scope — not repaired, propagates
    with pytest.raises(yaml.YAMLError):
        _repair("mood: dread: extra")


def test_blockify_line_skips_block_literal_and_quoted_values():
    assert chain._blockify_line("narration: |-", 0) is None       # already a block scalar
    assert chain._blockify_line('narration: "x: y"', 0) is None   # quoted — parses or is ambiguous
    assert chain._blockify_line("mood: dread: extra", 0) is None  # not a free-text key
    assert chain._blockify_line("narration: he said: run", 9) is None  # line_no out of range


# ── usage_sink plumbing (Story 6.3: token/cache observability) ─────────────


async def test_call_stage_returns_usage_alongside_raw_text(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    async def call(rendered, s):
        return "key: value", {"prompt_tokens": 10}, "stop"

    raw, usage = await chain._call_stage("scenario/research", {}, None, call)
    assert raw == "key: value"
    assert usage == {"prompt_tokens": 10}


async def test_call_stage_raises_truncation_error_with_evidence(monkeypatch):
    # Story 6.9: finish_reason=length must raise TruncationError carrying the
    # completion token count and raw runaway text so a caller can confirm the
    # cause (runaway generation, not batch volume) and route on it.
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    async def call(rendered, s):
        return "가" * 100, {"completion_tokens": 16000}, "length"

    with pytest.raises(chain.TruncationError) as excinfo:
        await chain._call_stage("scenario/writing_scene_repair", {}, None, call)
    assert isinstance(excinfo.value, ValueError)  # existing except paths still catch it
    assert "truncated" in str(excinfo.value)
    assert excinfo.value.completion_tokens == 16000
    assert excinfo.value.raw == "가" * 100
    # scenario_node's narrow recovery keys on prompt_name — it must be the real
    # stage name so only writing_scene_repair truncation falls back (Story 6.9 review).
    assert excinfo.value.prompt_name == "scenario/writing_scene_repair"


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

    responses = iter([("other: value", {"prompt_tokens": 1}), ("key: value", {"prompt_tokens": 2})])

    async def call(rendered, s):
        raw, usage = next(responses)
        return raw, usage, "stop"

    def parse(raw):
        data = chain._parse_yaml(raw)
        if "key" not in data:  # semantic (ValueError) failure triggers the second model call
            raise ValueError("missing key")
        return data

    usage_sink: list[dict] = []
    result = await chain._call_stage_with_retry(
        "scenario/research", {}, None, call, parse, usage_sink=usage_sink
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


async def test_research_step_retries_once_on_semantic_failure_then_succeeds(monkeypatch):
    """A semantic-validation failure (missing frozen_descriptor) still triggers
    exactly one full-stage retry. (YAML *syntax* failures are now handled
    deterministically without a second model call — Story 6.11.)"""
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    responses = iter(
        [
            "core_identity: x",  # valid YAML but missing non-empty frozen_descriptor → ValueError
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


@pytest.mark.parametrize("bad_direction", ["up", "", 5, ["left"], None])
def test_parse_cast_invalid_movement_direction_normalizes_then_repairs(bad_direction):
    """An invalid movement_direction normalizes to "none" (AC:2) and then
    goes through the same mode-aware repair as an absent direction — here
    "enter" + position="left" repairs "none" to "left"."""
    raw = [{
        "card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing",
        "movement_mode": "enter", "movement_direction": bad_direction,
    }]
    assert chain.parse_cast(raw)[0]["movement_direction"] == "left"


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
    """An explicit direction different from position is a genuine choice and
    passes through unchanged (here overriding center's "right" default)."""
    raw = [{
        "card_key": "SCP-049", "position": "center", "depth": "near", "pose": "standing",
        "movement_mode": "cross", "movement_direction": "left",
    }]
    assert chain.parse_cast(raw)[0]["movement_direction"] == "left"


@pytest.mark.parametrize("position", ["left", "right"])
def test_parse_cast_cross_same_side_direction_falls_back_to_opposite(position):
    """An explicit direction equal to position would collapse "cross" into a
    zero-amplitude no-op (start/end thirds coincide), so it is repaired to
    the opposite side instead of trusted as-is."""
    raw = [{
        "card_key": "SCP-049", "position": position, "depth": "near", "pose": "standing",
        "movement_mode": "cross", "movement_direction": position,
    }]
    expected = "right" if position == "left" else "left"
    assert chain.parse_cast(raw)[0]["movement_direction"] == expected


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
        # "medium" not "wide": wide + lone near would now trip Story 8.18's R3 repair.
        "camera_type": "medium", "cast": [{"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing"}],
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
            # "medium" not "wide": wide + lone near would now trip Story 8.18's R3 repair.
            {"image_prompt": "shot one", "negative_prompt": "n", "sentence_start": 1, "sentence_end": 1,
             "camera_type": "medium", "cast": [{"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing"}]},
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


# ── camera archetypes (Story 11.2: mood-driven camera_movement wiring) ─────────


def test_camera_archetypes_closed_vocabulary():
    from yt_flow.domain.state import CAMERA_ARCHETYPES

    assert CAMERA_ARCHETYPES == ("push_in", "pull_back", "drift", "locked", "shake")


@pytest.mark.parametrize("mood", sound_design.MOOD_VALUES)
def test_camera_preferences_cover_every_mood(mood):
    # Lockstep invariant (7.2 pattern): every taxonomy mood has a preference order.
    prefs = chain.CAMERA_PREFERENCES[mood]
    assert len(prefs) >= 2
    assert len(set(prefs)) == len(prefs)  # no duplicates — validator needs distinct alternates


def test_camera_preferences_no_extra_keys():
    assert set(chain.CAMERA_PREFERENCES) == set(sound_design.MOOD_VALUES)


def test_camera_preferences_values_are_archetypes():
    from yt_flow.domain.state import CAMERA_ARCHETYPES

    for prefs in chain.CAMERA_PREFERENCES.values():
        assert all(a in CAMERA_ARCHETYPES for a in prefs)


def test_camera_preferences_reach_all_archetypes():
    # AC1/AC2: all 5 archetypes reachable through some mood's preference order.
    from yt_flow.domain.state import CAMERA_ARCHETYPES

    reachable = {a for prefs in chain.CAMERA_PREFERENCES.values() for a in prefs}
    assert reachable == set(CAMERA_ARCHETYPES)


@pytest.mark.parametrize(
    ("mood", "default"),
    [("dread", "push_in"), ("clinical", "locked"), ("escalation", "shake"), ("revelation", "push_in")],
)
def test_camera_mood_defaults(mood, default):
    assert chain.CAMERA_PREFERENCES[mood][0] == default


@pytest.mark.parametrize("mood", sound_design.MOOD_VALUES)
def test_camera_preferences_first_alternate_renders_distinct(mood):
    # Review finding (11.2): a run of mood defaults alternates prefs[0]/prefs[1]
    # after _enforce_camera_variety, so those two must render as *different*
    # EffectSpecs or the archetype-level variety is visually void (e.g. the
    # shake placeholder and push_in both map to an in-center push).
    # Story 11.3 (AC:4): comparison widened to (EffectSpec, camera-shake
    # filter) — the shake archetype's EffectSpec legitimately equals push_in's
    # (same in-center base push), but its noise profile makes the final render
    # chain distinct, and that render-level distinctness is what this guard
    # must pin so archetype monotony can't silently come back.
    from yt_flow.pipeline.nodes.video import _camera_shake_filter, select_effect

    prefs = chain.CAMERA_PREFERENCES[mood]
    for scene_index in range(3):
        default_render = (
            select_effect({"camera_movement": prefs[0]}, scene_index),
            _camera_shake_filter(prefs[0], 4.0, k=scene_index),
        )
        alternate_render = (
            select_effect({"camera_movement": prefs[1]}, scene_index),
            _camera_shake_filter(prefs[1], 4.0, k=scene_index),
        )
        assert default_render != alternate_render


def test_shake_and_push_in_render_distinct_chains():
    # Story 11.3 AC:4: the 11.2 LOW — shake's placeholder rendered identically
    # to push_in. Same base EffectSpec is fine; the camera stage must differ.
    from yt_flow.pipeline.nodes.video import _camera_shake_filter

    for k in range(3):
        assert _camera_shake_filter("shake", 4.0, k=k) != _camera_shake_filter("push_in", 4.0, k=k)


def _one_shot_visual(**shot_extra):
    shot = {"image_prompt": "a", "negative_prompt": "b", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}
    shot.update(shot_extra)
    return {0: [shot]}


def test_build_scenes_camera_movement_defaults_from_mood():
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    scenes = chain.build_scenes(writing, _one_shot_visual(), [{"mood": "escalation"}])
    assert scenes[0]["shots"][0]["camera_movement"] == "shake"  # escalation default


def test_build_scenes_camera_movement_valid_override_adopted():
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    scenes = chain.build_scenes(
        writing, _one_shot_visual(camera_movement=" Pull_Back "), [{"mood": "dread"}]
    )
    assert scenes[0]["shots"][0]["camera_movement"] == "pull_back"


def test_build_scenes_camera_movement_invalid_override_falls_back_with_warning(caplog):
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    with caplog.at_level(logging.WARNING):
        scenes = chain.build_scenes(
            writing, _one_shot_visual(camera_movement="dolly zoom"), [{"mood": "dread"}]
        )
    assert scenes[0]["shots"][0]["camera_movement"] == "push_in"  # dread default
    assert any("dolly zoom" in r.message for r in caplog.records)


def test_build_scenes_camera_movement_absent_no_warning(caplog):
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    with caplog.at_level(logging.WARNING):
        scenes = chain.build_scenes(writing, _one_shot_visual(), [{"mood": "clinical"}])
    assert scenes[0]["shots"][0]["camera_movement"] == "locked"  # clinical default
    assert not caplog.records


# ── _enforce_camera_variety (Story 11.2 AC4: adjacent-duplicate ban) ────────────


def _shots_with_cameras(values):
    return [
        {"shot_id": f"S001{i:02d}", "camera_movement": v}
        for i, v in enumerate(values)
    ]


def test_enforce_camera_variety_no_adjacent_duplicates_property():
    shots = _shots_with_cameras(["push_in"] * 5)
    chain._enforce_camera_variety(shots, "dread")
    cams = [s["camera_movement"] for s in shots]
    assert all(a != b for a, b in zip(cams, cams[1:]))
    from yt_flow.domain.state import CAMERA_ARCHETYPES

    assert all(c in CAMERA_ARCHETYPES for c in cams)


def test_enforce_camera_variety_deterministic():
    a = _shots_with_cameras(["shake", "shake", "push_in", "push_in"])
    b = _shots_with_cameras(["shake", "shake", "push_in", "push_in"])
    chain._enforce_camera_variety(a, "escalation")
    chain._enforce_camera_variety(b, "escalation")
    assert [s["camera_movement"] for s in a] == [s["camera_movement"] for s in b]


def test_enforce_camera_variety_single_shot_harmless():
    shots = _shots_with_cameras(["locked"])
    chain._enforce_camera_variety(shots, "clinical")
    assert shots[0]["camera_movement"] == "locked"


def test_enforce_camera_variety_leaves_valid_sequences_untouched():
    shots = _shots_with_cameras(["push_in", "drift", "push_in"])
    chain._enforce_camera_variety(shots, "dread")
    assert [s["camera_movement"] for s in shots] == ["push_in", "drift", "push_in"]


def test_enforce_camera_variety_logs_reassignment(caplog):
    shots = _shots_with_cameras(["locked", "locked"])
    with caplog.at_level(logging.INFO):
        chain._enforce_camera_variety(shots, "clinical")
    assert any("S00101" in r.message for r in caplog.records)


def test_build_scenes_applies_camera_variety_to_defaults():
    # AC4 integration: mood default gives every shot the same archetype;
    # the validator must scatter adjacent duplicates.
    writing = {"scenes": [{"scene_num": 1, "narration": "하나. 둘. 셋."}]}
    visual = {0: [
        {"image_prompt": "a", "negative_prompt": "", "sentence_start": i, "sentence_end": i, "camera_type": "wide"}
        for i in (1, 2, 3)
    ]}
    scenes = chain.build_scenes(writing, visual, [{"mood": "dread"}])
    cams = [s["camera_movement"] for s in scenes[0]["shots"]]
    assert all(a != b for a, b in zip(cams, cams[1:]))
    assert cams[0] == "push_in"  # first shot keeps the mood default


def test_build_scenes_camera_variety_overrides_llm_duplicates():
    # AC4: the ban is absolute — LLM overrides that violate it are reassigned too.
    writing = {"scenes": [{"scene_num": 1, "narration": "하나. 둘."}]}
    visual = {0: [
        {"image_prompt": "a", "negative_prompt": "", "sentence_start": i, "sentence_end": i,
         "camera_type": "wide", "camera_movement": "shake"}
        for i in (1, 2)
    ]}
    scenes = chain.build_scenes(writing, visual, [{"mood": "escalation"}])
    cams = [s["camera_movement"] for s in scenes[0]["shots"]]
    assert cams[0] == "shake"
    assert cams[1] != "shake"


# ── _enforce_cast_diversity (Story 8.18: placement-diversity repair) ────────────


def _cast_member(card="SCP-049", position="center", depth="mid", **extra):
    member = {"card_key": card, "position": position, "depth": depth, "pose": "standing"}
    member.update(extra)
    return member


def _cast_shots(casts, camera_angle=None):
    return [
        {"shot_id": f"S001{i:02d}", "camera_angle": camera_angle, "cast": cast}
        for i, cast in enumerate(casts)
    ]


def _assert_no_diversity_violations(shots):
    # R1: no two members of one shot share a position.
    for shot in shots:
        positions = [m["position"] for m in shot["cast"]]
        assert len(positions) == len(set(positions)), shot
    # R2: no card holds an identical (position, depth) for >2 consecutive shots.
    runs: dict = {}
    for shot in shots:
        new_runs: dict = {}
        for m in shot["cast"]:
            key = (m["position"], m["depth"])
            prev = runs.get(m["card_key"])
            count = prev[1] + 1 if prev and prev[0] == key else 1
            assert count <= chain._MAX_CONSECUTIVE_SAME_PLACEMENT, shot
            new_runs[m["card_key"]] = (key, count)
        runs = new_runs


def test_enforce_cast_diversity_all_identical_fake_case():
    # epics.md mandated regression: LLM emitted every shot, every member center/mid.
    shots = _cast_shots(
        [[_cast_member("SCP-049"), _cast_member("STOCK-researcher")] for _ in range(6)]
    )
    chain._enforce_cast_diversity(shots)
    _assert_no_diversity_violations(shots)


def test_enforce_cast_diversity_r1_stacking_repaired_in_isolation():
    shots = _cast_shots([[_cast_member("SCP-049", "left"), _cast_member("STOCK-researcher", "left")]])
    chain._enforce_cast_diversity(shots)
    # Later member moves to the opposing third first.
    assert shots[0]["cast"][0]["position"] == "left"
    assert shots[0]["cast"][1]["position"] == "right"


def test_enforce_cast_diversity_r1_does_not_displace_later_sibling():
    # B stacks on A's left; its preferred opposing third (right) is C's slot.
    # B must go to center — C never moves (mark-targeted, 6.11 lesson).
    shots = _cast_shots(
        [[_cast_member("A", "left"), _cast_member("B", "left"), _cast_member("C", "right")]]
    )
    chain._enforce_cast_diversity(shots)
    assert [m["position"] for m in shots[0]["cast"]] == ["left", "center", "right"]


def test_enforce_cast_diversity_r1_center_stack_fills_left_then_right():
    shots = _cast_shots(
        [[_cast_member("A", "center"), _cast_member("B", "center"), _cast_member("C", "center")]]
    )
    chain._enforce_cast_diversity(shots)
    assert [m["position"] for m in shots[0]["cast"]] == ["center", "left", "right"]


def test_enforce_cast_diversity_r1_four_members_keep_slot_beyond_three(caplog):
    shots = _cast_shots(
        [[_cast_member(k, "center") for k in ("A", "B", "C", "D")]]
    )
    with caplog.at_level(logging.INFO):
        chain._enforce_cast_diversity(shots)
    # 3-slot renderer limit: the 4th member keeps its slot, INFO-logged.
    assert [m["position"] for m in shots[0]["cast"]] == ["center", "left", "right", "center"]
    assert any("3" in r.message and "slot" in r.message for r in caplog.records)


def test_enforce_cast_diversity_r2_third_consecutive_repeat_reassigned():
    shots = _cast_shots([[_cast_member(position="left", depth="mid")] for _ in range(3)])
    chain._enforce_cast_diversity(shots)
    assert [s["cast"][0]["position"] for s in shots] == ["left", "left", "right"]
    assert [s["cast"][0]["depth"] for s in shots] == ["mid", "mid", "mid"]  # position-only repair


def test_enforce_cast_diversity_r2_two_repeats_stay_legal():
    shots = _cast_shots([[_cast_member(position="left", depth="near")] for _ in range(2)])
    before = copy.deepcopy(shots)
    chain._enforce_cast_diversity(shots)
    assert shots == before


def test_enforce_cast_diversity_r2_depth_change_breaks_run():
    casts = [
        [_cast_member(position="left", depth="near")],
        [_cast_member(position="left", depth="mid")],
        [_cast_member(position="left", depth="near")],
    ]
    shots = _cast_shots(casts)
    before = copy.deepcopy(shots)
    chain._enforce_cast_diversity(shots)
    assert shots == before


def test_enforce_cast_diversity_r2_respects_r1_occupancy():
    # The repeating card cannot move onto another member's slot.
    casts = [
        [_cast_member("A", "left", "mid")],
        [_cast_member("A", "left", "mid")],
        [_cast_member("A", "left", "mid"), _cast_member("B", "right", "mid")],
    ]
    shots = _cast_shots(casts)
    chain._enforce_cast_diversity(shots)
    # A prefers the opposing third (right) but B holds it -> center.
    assert shots[2]["cast"][0]["position"] == "center"
    assert shots[2]["cast"][1]["position"] == "right"
    _assert_no_diversity_violations(shots)


def test_enforce_cast_diversity_r3_wide_near_majority_demoted():
    cast = [
        _cast_member("A", "left", "near"),
        _cast_member("B", "center", "near"),
        _cast_member("C", "right", "far"),
    ]
    shots = _cast_shots([cast], camera_angle="wide")
    chain._enforce_cast_diversity(shots)
    assert [m["depth"] for m in shots[0]["cast"]] == ["mid", "mid", "far"]
    assert [m["position"] for m in shots[0]["cast"]] == ["left", "center", "right"]


def test_enforce_cast_diversity_r3_wide_near_minority_untouched():
    cast = [_cast_member("A", "left", "near"), _cast_member("B", "right", "mid")]
    shots = _cast_shots([cast], camera_angle="wide")
    before = copy.deepcopy(shots)
    chain._enforce_cast_diversity(shots)
    assert shots == before  # 1 of 2 is not a strict majority


def test_enforce_cast_diversity_r3_closeup_lone_far_promoted():
    for angle in ("close-up", "over-the-shoulder"):
        shots = _cast_shots([[_cast_member("A", "left", "far")]], camera_angle=angle)
        chain._enforce_cast_diversity(shots)
        assert shots[0]["cast"][0]["depth"] == "mid"


def test_enforce_cast_diversity_r3_closeup_far_with_company_untouched():
    cast = [_cast_member("A", "left", "far"), _cast_member("B", "right", "near")]
    shots = _cast_shots([cast], camera_angle="close-up")
    before = copy.deepcopy(shots)
    chain._enforce_cast_diversity(shots)
    assert shots == before  # lone-far rule only


def test_enforce_cast_diversity_r3_unknown_or_missing_camera_untouched():
    for angle in (None, "POV", "medium", "dutch tilt"):
        shots = _cast_shots([[_cast_member("A", "left", "near")]], camera_angle=angle)
        before = copy.deepcopy(shots)
        chain._enforce_cast_diversity(shots)
        assert shots == before


def test_enforce_cast_diversity_movement_rederived_on_reassignment():
    # B stacks on left and moves to right; its old cross direction "right"
    # becomes degenerate there (start/end thirds coincide) -> re-derived "left".
    cast = [
        _cast_member("A", "left"),
        _cast_member(
            "B", "left",
            movement_mode="cross", movement_direction="right", movement_pace="slow",
        ),
    ]
    shots = _cast_shots([cast])
    chain._enforce_cast_diversity(shots)
    moved = shots[0]["cast"][1]
    assert moved["position"] == "right"
    assert moved["movement_direction"] == "left"
    assert moved["movement_mode"] == "cross"
    assert moved["movement_pace"] == "slow"


def test_enforce_cast_diversity_deterministic():
    casts = [[_cast_member("A"), _cast_member("B")] for _ in range(5)]
    a = _cast_shots(copy.deepcopy(casts))
    b = _cast_shots(copy.deepcopy(casts))
    chain._enforce_cast_diversity(a)
    chain._enforce_cast_diversity(b)
    assert a == b


def test_enforce_cast_diversity_idempotent():
    shots = _cast_shots(
        [[_cast_member("A"), _cast_member("B", "center", "near")] for _ in range(6)],
        camera_angle="wide",
    )
    chain._enforce_cast_diversity(shots)
    once = copy.deepcopy(shots)
    chain._enforce_cast_diversity(shots)
    assert shots == once


def test_enforce_cast_diversity_valid_sequence_byte_identical():
    casts = [
        [_cast_member("A", "left", "near"), _cast_member("B", "right", "mid")],
        [_cast_member("A", "center", "near")],
        [_cast_member("A", "left", "near"), _cast_member("B", "center", "far")],
    ]
    shots = _cast_shots(casts, camera_angle="medium")
    before = copy.deepcopy(shots)
    chain._enforce_cast_diversity(shots)
    assert shots == before


def test_enforce_cast_diversity_single_shot_and_empty_cast_harmless():
    shots = _cast_shots([[_cast_member()]])
    before = copy.deepcopy(shots)
    chain._enforce_cast_diversity(shots)
    assert shots == before

    shots = _cast_shots([[], [_cast_member()], []])
    before = copy.deepcopy(shots)
    chain._enforce_cast_diversity(shots)
    assert shots == before


def test_enforce_cast_diversity_absence_resets_run():
    casts = [
        [_cast_member("A", "left", "mid")],
        [_cast_member("A", "left", "mid")],
        [],
        [_cast_member("A", "left", "mid")],
    ]
    shots = _cast_shots(casts)
    before = copy.deepcopy(shots)
    chain._enforce_cast_diversity(shots)
    assert shots == before  # the gap restarts the consecutive count


def test_enforce_cast_diversity_logs_reassignment(caplog):
    shots = _cast_shots([[_cast_member("SCP-049", "left"), _cast_member("STOCK-d-class", "left")]])
    with caplog.at_level(logging.INFO):
        chain._enforce_cast_diversity(shots)
    assert any(
        "S00100" in r.message and "STOCK-d-class" in r.message for r in caplog.records
    )


def test_build_scenes_applies_cast_diversity():
    # Integration: violations planted in raw visual_breakdown payloads come out
    # repaired in the returned scenes (post parse_cast, post empty-prompt merge).
    writing = {"scenes": [{"scene_num": 1, "narration": "하나. 둘. 셋. 넷."}]}
    raw_cast = [
        {"card_key": "scp-049", "position": "center", "depth": "mid"},
        {"card_key": "STOCK-researcher", "position": "center", "depth": "mid"},
    ]
    visual = {0: [
        {"image_prompt": "a", "negative_prompt": "", "sentence_start": i, "sentence_end": i,
         "camera_type": "medium", "cast": raw_cast}
        for i in (1, 2, 3, 4)
    ]}
    scenes = chain.build_scenes(writing, visual, [{"mood": "dread"}])
    _assert_no_diversity_violations(scenes[0]["shots"])


# ── _suppress_cast_on_no_figure_framing (Story 8.19) ───────────────────────────
#
# Diagnosed defect (Task 0, run c6be1954): 27/121 cast-bearing shots composited
# a full-body card over a prompt that framed an object macro or an empty
# environment. Root cause is ordering, not key choice — cast_decision_step reads
# the narration only, and visual_breakdown_step invents the framing afterwards,
# so the prompt's own "object close-up -> cast: []" rule asks the LLM to predict
# a decision that does not exist yet.


def _framing_shot(image_prompt, cast=None, shot_id="S00100", **extra):
    shot = {
        "shot_id": shot_id,
        "image_prompt": image_prompt,
        "negative_prompt": "",
        "camera_angle": "close-up",
        "cast": [_cast_member("SCP-049", "left", "mid")] if cast is None else cast,
        "location_key": "containment-chamber",
        "sentence_indices": [0],
    }
    shot.update(extra)
    return shot


@pytest.mark.parametrize("prompt", [
    # Verbatim prompt heads from the diagnosed cases in run c6be1954.
    "extreme close-up of a ceramic surface texture, the glaze has fine cracks",       # S00113
    "extreme close-up of a wall-mounted cardiac monitor screen, a green waveform",    # S00406
    "extreme close-up of a digital wall clock, the second hand stopped at the 12",    # S00409
    "close-up of the interview table's edge, a steel surface with a faint scratch",   # S00301
    "close-up on scp-049's mask where it meets the skin",
    "macro close-up of a stopwatch display, LCD numerals reading 00:00:30",           # S00410
    "macro shot of a cracked lens",
    "static wide shot, underground containment chamber, no visible subject",          # S00100
    # An object framing may still mention a person *part* drawn by the background
    # prompt itself — the card still has nowhere to stand, so it still goes.
    "close-up of a computer monitor, one feed shows a cell with a figure's feet visible",  # S00712
    "close-up of the concrete floor, a pair of bare feet still as stone, dust settling",   # d55a265b S00508
])
def test_suppress_cast_drops_cast_on_no_figure_framing(prompt):
    shots = [_framing_shot(prompt)]
    chain._suppress_cast_on_no_figure_framing(shots)
    assert shots[0]["cast"] == []


@pytest.mark.parametrize("prompt", [
    "wide shot, concrete containment chamber with a single steel table center",
    "medium shot of a village thoroughfare, left side a low stone wall",
    "static medium shot, tiled examination room with a central steel table",
    "high-angle wide shot of the containment cell, a gurney with a folded white sheet",
    "pull-out wide shot of the containment chamber, the entire room is visible",
])
def test_suppress_cast_leaves_normal_framings_untouched(prompt):
    before = [_framing_shot(prompt)]
    after = copy.deepcopy(before)
    chain._suppress_cast_on_no_figure_framing(after)
    assert after == before


def test_suppress_cast_is_case_insensitive():
    shots = [_framing_shot("EXTREME CLOSE-UP of a ceramic surface")]
    chain._suppress_cast_on_no_figure_framing(shots)
    assert shots[0]["cast"] == []


def test_suppress_cast_handles_korean_prompt_without_raising():
    # Precision-first: a non-English prompt carries no marker, so nothing is dropped.
    shots = [_framing_shot("좁은 복도의 와이드 샷, 형광등이 깜빡인다")]
    chain._suppress_cast_on_no_figure_framing(shots)
    assert len(shots[0]["cast"]) == 1


def test_suppress_cast_empty_cast_is_noop():
    shots = [_framing_shot("extreme close-up of a floor tile", cast=[])]
    chain._suppress_cast_on_no_figure_framing(shots)
    assert shots[0]["cast"] == []


@pytest.mark.parametrize("shots", [
    [],
    [{}],
    [{"shot_id": "S00100"}],                                        # no image_prompt at all
    [{"shot_id": "S00100", "image_prompt": None, "cast": [1]}],      # non-str prompt
    [{"shot_id": "S00100", "image_prompt": "extreme close-up", "cast": None}],
    ["not a dict"],
])
def test_suppress_cast_is_total_and_never_raises(shots):
    chain._suppress_cast_on_no_figure_framing(shots)  # must not raise


def test_suppress_cast_preserves_every_non_cast_field():
    # Mark-targeted (6.11/8.18 lesson): only `cast` changes on a violating shot.
    shot = _framing_shot("extreme close-up of a floor tile", camera_movement="push-in")
    before = copy.deepcopy(shot)
    chain._suppress_cast_on_no_figure_framing([shot])
    assert shot["cast"] == []
    for key, value in before.items():
        if key != "cast":
            assert shot[key] == value, key


def test_suppress_cast_does_not_touch_sibling_shots():
    shots = [
        _framing_shot("wide shot of the corridor", shot_id="S00100"),
        _framing_shot("extreme close-up of a floor tile", shot_id="S00101"),
        _framing_shot("medium shot of the office desk", shot_id="S00102"),
    ]
    chain._suppress_cast_on_no_figure_framing(shots)
    assert len(shots[0]["cast"]) == 1
    assert shots[1]["cast"] == []
    assert len(shots[2]["cast"]) == 1


def test_suppress_cast_never_crosses_into_location_namespace():
    # AC7: cast suppression must not rewrite the location decision.
    shots = [_framing_shot("extreme close-up of a floor tile")]
    chain._suppress_cast_on_no_figure_framing(shots)
    assert shots[0]["location_key"] == "containment-chamber"


def test_suppress_cast_deterministic_and_idempotent():
    a = [_framing_shot("extreme close-up of a floor tile")]
    b = copy.deepcopy(a)
    chain._suppress_cast_on_no_figure_framing(a)
    chain._suppress_cast_on_no_figure_framing(b)
    assert a == b
    chain._suppress_cast_on_no_figure_framing(a)  # second pass changes nothing
    assert a == b


def test_suppress_cast_logs_decision_evidence(caplog):
    # AC9: namespace, decision, method and reason are recoverable from logs.
    shots = [_framing_shot("extreme close-up of a floor tile")]
    with caplog.at_level(logging.INFO):
        chain._suppress_cast_on_no_figure_framing(shots)
    record = " ".join(r.message for r in caplog.records)
    assert "S00100" in record
    assert "cast" in record
    assert "extreme close-up" in record
    assert "SCP-049" in record


def test_build_scenes_suppresses_cast_on_no_figure_framing():
    # Integration through the real merge/parse path, using the diagnosed prompts.
    writing = {"scenes": [{"scene_num": 1, "narration": "하나. 둘."}]}
    raw_cast = [{"card_key": "SCP-049", "position": "left", "depth": "mid"}]
    visual = {0: [
        {"image_prompt": "wide shot of the containment chamber", "negative_prompt": "",
         "sentence_start": 1, "sentence_end": 1, "camera_type": "wide", "cast": raw_cast,
         "location_key": "containment-chamber"},
        {"image_prompt": "extreme close-up of a ceramic surface texture", "negative_prompt": "",
         "sentence_start": 2, "sentence_end": 2, "camera_type": "close-up", "cast": raw_cast,
         "location_key": "containment-chamber"},
    ]}
    shots = chain.build_scenes(writing, visual, [{"mood": "dread"}])[0]["shots"]
    assert len(shots[0]["cast"]) == 1                      # normal framing keeps its card
    assert shots[1]["cast"] == []                          # macro framing loses it
    assert shots[1]["location_key"] == "containment-chamber"   # other namespace untouched
    assert shots[1]["image_prompt"] == "extreme close-up of a ceramic surface texture"


def test_build_scenes_suppresses_cast_before_diversity_repair():
    """The suppress -> diversity order in build_scenes is load-bearing, so pin it.

    R2 caps consecutive identical (position, depth) runs per card_key. If the two
    passes were swapped, R2 would count a shot whose card is about to be dropped
    and move a *surviving* sibling off its LLM-chosen slot for a repeat the viewer
    never sees. Three shots, same slot, middle one an object macro: with the
    correct order the macro's card is gone before R2 counts, the run is 1-1-1, and
    nothing is reassigned.
    """
    writing = {"scenes": [{"scene_num": 1, "narration": "하나. 둘. 셋."}]}
    slot = [{"card_key": "SCP-049", "position": "left", "depth": "mid"}]
    prompts = [
        "wide shot of the containment chamber",
        "extreme close-up of a ceramic surface texture",   # suppressed -> breaks the run
        "medium shot of the containment chamber",
    ]
    visual = {0: [
        {"image_prompt": p, "negative_prompt": "", "sentence_start": i, "sentence_end": i,
         "camera_type": "medium", "cast": slot}
        for i, p in enumerate(prompts, start=1)
    ]}
    shots = chain.build_scenes(writing, visual, [{"mood": "dread"}])[0]["shots"]
    assert shots[1]["cast"] == []
    # Both survivors keep the slot the LLM chose — R2 never saw a 3-shot run.
    assert [m["position"] for m in shots[0]["cast"]] == ["left"]
    assert [m["position"] for m in shots[2]["cast"]] == ["left"], (
        "a surviving sibling was reassigned — _enforce_cast_diversity counted the "
        "suppressed shot, so the two passes have been reordered"
    )


def test_stock_cast_catalog_covers_every_stock_key():
    from yt_flow.domain.state import STOCK_CAST_KEYS, STOCK_CAST_ROLES
    assert set(STOCK_CAST_ROLES) == set(STOCK_CAST_KEYS)
    assert all(desc.strip() for desc in STOCK_CAST_ROLES.values())


def test_cast_decision_prompt_carries_role_catalog_and_no_fit_rule():
    prompt_path = Path(__file__).parent.parent.parent.parent / "prompts" / "scenario" / "cast_decision.md"
    content = prompt_path.read_text(encoding="utf-8")
    assert "{{stock_cast_catalog}}" in content
    # The diagnosed failure was substituting the nearest stock role for a non-Foundation person.
    assert "cast\": []" in content or "`cast`: []" in content or '"cast": []' in content


async def test_cast_decision_step_renders_role_catalog(monkeypatch):
    from yt_flow.domain.state import STOCK_CAST_ROLES
    captured = {}

    class CatalogPrompt:
        def compile(self, **kwargs):
            captured.update(kwargs)
            return "rendered"

    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: CatalogPrompt()
    )

    async def fake(rendered, s):
        return yaml.safe_dump({"shots": [{"sentence": 1, "cast": []}]}), {}, "stop"

    await chain.cast_decision_step("SCP-049", {}, ["문장 하나."], None, fake)
    catalog = captured["stock_cast_catalog"]
    for key, desc in STOCK_CAST_ROLES.items():
        assert key in catalog
        assert desc.split(" —")[0].strip() in catalog
