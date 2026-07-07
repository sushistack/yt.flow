import json
import logging
from pathlib import Path

import pytest

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
    for placeholder in ("{{story_logline}}", "{{scene_role}}", "{{entity_sheet}}", "{{scp_visual_reference}}", "{{numbered_sentences}}", "{{sentence_count}}", "{{scp_id}}", "{{stock_cast_keys}}"):
        assert placeholder in content, f"missing {placeholder} in visual_breakdown.md"


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


async def test_visual_breakdown_step_maps_one_shot_per_sentence(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_visual_breakdown.json")
    scene = {"scene_num": 1, "location": "x", "atmosphere": "y", "color_palette": "z", "characters_present": []}
    sentences = ["첫 문장.", "(정적)", "셋째 문장."]
    result = await chain.visual_breakdown_step("SCP-173", scene, sentences, "desc", "entity sheet", "logline", {}, None, call)
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
        await chain.visual_breakdown_step("SCP-173", scene, ["문장1.", "문장2."], "desc", "entity sheet", "logline", {}, None, call)


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
    await chain.visual_breakdown_step("SCP-173", scene, ["문장1."], "frozen desc", "entity sheet text", "story logline text", scene_role, None, call)

    assert captured.kwargs["scp_visual_reference"] == "frozen desc"
    assert captured.kwargs["entity_sheet"] == "entity sheet text"
    assert captured.kwargs["story_logline"] == "story logline text"
    assert "hook" in captured.kwargs["scene_role"]
    assert "tension" in captured.kwargs["scene_role"]
    assert "the discovery" in captured.kwargs["scene_role"]
    assert captured.kwargs["scp_id"] == "SCP-173"
    assert captured.kwargs["stock_cast_keys"] == "STOCK-d-class, STOCK-researcher, STOCK-security"


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
