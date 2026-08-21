import asyncio
import copy
import json
import logging
import math
import re
from pathlib import Path

import pytest
import yaml

import yt_flow.domain.state as state
import yt_flow.pipeline.nodes.scenario_chain as chain
import yt_flow.pipeline.nodes.sound_design as sound_design
from tests.stubs import fakes

CASSETTE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "cassettes"

# One loader, so the structure cassette's contract-bound `word_budget` values are
# re-solved from the derived constants on EVERY replay path — this module's and the
# offline stub profile's alike (Story 12.6).
_load_cassette = fakes.load_cassette


def _deepseek_from_cassette(name):
    data = _load_cassette(name)
    choice = data["choices"][0]

    async def fake(rendered, s):
        return choice["message"]["content"], data.get("usage", {}), choice.get("finish_reason")

    return fake


class FakePrompt:
    def compile(self, **variables):
        return "rendered"


# Story 12.4: research also owns the narrative-template selection, so any payload
# that is supposed to REACH the end of validation needs these two. Kept as YAML
# text (not a dict) because most of these fixtures hand back raw strings.
_ARCHETYPE_YAML = (
    'story_archetype: "incident_first"\n'
    "archetype_rationale: 원문에 사건 기록이 있어 사건 우선 구조가 근거를 갖는다\n"
)
_ARCHETYPE_FIELDS = {
    "story_archetype": "incident_first",
    "archetype_rationale": "원문에 사건 기록이 있어 사건 우선 구조가 근거를 갖는다",
}


# review/critic are batched per scene, so a `writing` with no scenes issues no call
# at all — every single-call test needs exactly one scene.
_ONE_SCENE = {"scenes": [{"scene_num": 1, "narration": "문장 하나."}]}


# The one solve, shared with the structure cassette and the sibling test modules.
_budgets = fakes.retention_budgets


def _retention_scene(pos: int, total: int, **overrides) -> dict:
    """One contract-valid structure scene at 1-based ``pos`` of ``total``.

    Budget comes from ``_budgets`` so the outline satisfies the total band AND the
    Story 12.6 distribution checks. Loops are planted in scene 1 and settled in the
    last scene; a pattern interrupt lands every 3rd scene so no `none` run ever
    reaches 3.
    """
    budget = _budgets(total)[pos - 1]
    scene = {
        "scene_num": pos,
        "act": "hook" if pos == 1 else "mystery_expansion",
        "synopsis": f"scene {pos}",
        "event": {"who": f"연구원 {pos}", "what": "격리실에 진입했다", "consequence": "통신이 끊겼다"},
        "key_points": [],
        "emotional_beat": "tension",
        "estimated_duration_sec": 45,
        "hook_type": "shock" if pos == 1 else "none",
        "loops_planted": ["loop_a", "loop_b"] if pos == 1 else [],
        "loops_closed": ["loop_a", "loop_b"] if pos == total else [],
        "pattern_interrupt": "tone_shift" if pos % 3 == 1 else "none",
        "word_budget": budget,
        # Story 12.8: statement + the verbatim source span that supports it. The
        # quote is only located when a caller passes a `scp_text` containing it —
        # most callers here pass "" and get one `source_unavailable` note, which is
        # deliberately not a correctable failure.
        "fact_references": [
            {"statement": f"재단 기록에 사건 {pos}이 남아 있다", "quote": f"incident {pos} was recorded"}
        ],
        "mood": "dread",
        "title": f"제목 {pos}",
        "kicker": f"한 줄 {pos}",
    }
    return {**scene, **overrides}


def _retention_outline(total: int = 8) -> list[dict]:
    return [_retention_scene(pos, total) for pos in range(1, total + 1)]


def _retention_yaml(total: int = 8) -> str:
    return yaml.safe_dump({"scenes": _retention_outline(total)}, allow_unicode=True)


def _repair_structure(originals: list[dict]) -> list[dict]:
    """Positionally-paired structure subset for a `writing_scene_repair_step` call."""
    return [_retention_scene(idx + 1, max(4, len(originals))) for idx in range(len(originals))]


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
        return json.dumps({"core_identity": "x", "frozen_descriptor": "x", "dramatic_beats": "x", "environment": "x", "hooks": "x", **_ARCHETYPE_FIELDS}), {}, "stop"

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


def test_fallback_prompt_names_a_surface_not_an_absence():
    """Story 10.4b: the backfill used to end in "no visible subject" — a code-side absence
    subject that also matched `_NO_FIGURE_FRAMINGS`, so a placeholder phrase silently
    stripped the shot's cast. It now names the floor, which exists in every location.

    This is the ONLY part of Story 10.4b that survived. The story also rewrote
    `prompts/scenario/visual_breakdown.md` to forbid absence-as-subject, and that change
    was REVERTED after measurement: a blind text judge scored the BASELINE prompt at
    66/66 = 100% on "is the subject physically present", so there was nothing left to fix.
    Story 10.2's 2026-08-10 prompt edit had already removed the behaviour — three days
    AFTER the run whose 12 unreadable frames motivated 10.4b. Evidence and the reverted
    prompt text: `_bmad-output/implementation-artifacts/10-4b-live-validation/`.

    This bug is independent of that revert: it is a defect in code, not an instruction."""
    prompt = chain._fallback_prompt({"location": "containment cell", "atmosphere": "cold"})
    assert "no visible subject" not in prompt
    assert "floor" in prompt
    assert "containment cell" in prompt and "cold" in prompt


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
    scenes = await chain.structure_step("SCP-173", "", research, "guide", None, call)
    # 4, not 2: Story 12.6's distribution contract (opening/closing <= 20% each,
    # max/min >= 1.6) has no solution below four scenes, so the cassette grew.
    assert len(scenes) == 4
    assert scenes[0]["scene_num"] == 1
    assert scenes[0]["emotional_beat"] == "tension"


async def test_structure_step_rejects_empty_scene_list(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return json.dumps({"scenes": []}), {}, "stop"

    with pytest.raises(ValueError, match="scenes"):
        await chain.structure_step("SCP-173", "", {"frozen_descriptor": "d"}, "guide", None, call)


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
        await chain.structure_step("SCP-173", "", {"frozen_descriptor": "x"}, "guide", None, call, label="candidate")


async def test_structure_step_label_none_tolerates_missing_title(monkeypatch):
    # Variant A/None still reads the pre-promotion production prompt, which
    # doesn't emit title/kicker at all yet — absence must not crash the pipeline.
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        scenes = _retention_outline(4)
        for scene in scenes:
            scene.pop("title")
        return json.dumps({"scenes": scenes}), {}, "stop"

    scenes = await chain.structure_step("SCP-173", "", {"frozen_descriptor": "x"}, "guide", None, call)
    assert scenes[0]["scene_num"] == 1
    assert "title" not in scenes[0]


# --- Story 12.1: retention contract -------------------------------------------
# Deterministic outline validation. Mirrors the property/boundary/integration
# shape of the _enforce_camera_variety / _enforce_cast_diversity blocks, but the
# semantics are the opposite: a violation hard-fails instead of being repaired,
# because code cannot invent an actor, a consequence, or a missing payoff.


def _budget_outline(total: int, budget: int) -> list[dict]:
    return [_retention_scene(pos, total, word_budget=budget) for pos in range(1, total + 1)]


def _cadence_outline(interrupts: list[str]) -> list[dict]:
    total = len(interrupts)
    return [_retention_scene(pos, total, pattern_interrupt=interrupts[pos - 1]) for pos in range(1, total + 1)]


def _raises(outline: list[dict]) -> str:
    with pytest.raises(chain.RetentionError) as excinfo:
        chain._validate_retention_outline(outline)
    return excinfo.value.code


def test_retention_valid_outline_passes():
    chain._validate_retention_outline(_retention_outline(8))


@pytest.mark.parametrize("hook", chain.HOOK_TYPES)
def test_retention_scene1_accepts_every_library_hook(hook):
    outline = _retention_outline(4)
    outline[0]["hook_type"] = hook
    chain._validate_retention_outline(outline)


def test_retention_hook_library_is_exactly_the_format_guide_vocabulary():
    assert chain.HOOK_TYPES == ("question", "shock", "mystery", "contrast")


@pytest.mark.parametrize("hook", ["none", "cliffhanger", "question!", "", None, 3, ["shock"]])
def test_retention_scene1_rejects_anything_outside_the_library(hook):
    outline = _retention_outline(4)
    outline[0]["hook_type"] = hook
    assert _raises(outline) == "hook_invalid"


@pytest.mark.parametrize("hook", chain.HOOK_TYPES + ("tone_shift",))
def test_retention_later_scene_must_be_none(hook):
    outline = _retention_outline(4)
    outline[1]["hook_type"] = hook
    assert _raises(outline) == "hook_misplaced"


def test_retention_scene1_missing_hook_key_is_invalid():
    outline = _retention_outline(4)
    del outline[0]["hook_type"]
    assert _raises(outline) == "hook_invalid"


def test_retention_hook_and_interrupt_are_case_and_whitespace_canonicalized():
    outline = _retention_outline(4)
    outline[0]["hook_type"] = "  SHOCK  "
    outline[0]["pattern_interrupt"] = "Tone_Shift"
    chain._validate_retention_outline(outline)
    assert outline[0]["hook_type"] == "shock"
    assert outline[0]["pattern_interrupt"] == "tone_shift"


# --- event ---


@pytest.mark.parametrize("field", ["who", "what", "consequence"])
@pytest.mark.parametrize("bad", ["", "   ", None, 5, ["누군가"], {"who": "x"}])
def test_retention_event_field_must_be_a_non_empty_string(field, bad):
    outline = _retention_outline(4)
    outline[0]["event"][field] = bad
    assert _raises(outline) == "event_field_empty"


@pytest.mark.parametrize("field", ["who", "what", "consequence"])
def test_retention_event_field_may_not_be_absent(field):
    outline = _retention_outline(4)
    del outline[0]["event"][field]
    assert _raises(outline) == "event_field_empty"


@pytest.mark.parametrize("bad", [None, "연구원이 격리실에 들어갔다", ["who"], 3])
def test_retention_event_must_be_a_mapping(bad):
    outline = _retention_outline(4)
    outline[1]["event"] = bad
    assert _raises(outline) == "event_missing"


def test_retention_event_missing_entirely_is_rejected():
    outline = _retention_outline(4)
    del outline[2]["event"]
    assert _raises(outline) == "event_missing"


# --- fact_references (shape only — grounding is review/critic + Story 12.3) ---


@pytest.mark.parametrize("bad", [[], None, "사실 하나", ["", "  "], ["사실", 7], {"a": "b"}])
def test_retention_fact_references_must_be_non_empty_statements(bad):
    outline = _retention_outline(4)
    outline[1]["fact_references"] = bad
    assert _raises(outline) == "fact_references_invalid"


# --- open-loop ledger ---


def test_retention_loop_happy_path_plants_and_settles():
    chain._validate_retention_outline(_retention_outline(5))


def test_retention_three_planted_loops_is_the_upper_boundary():
    outline = _retention_outline(4)
    outline[0]["loops_planted"] = ["loop_a", "loop_b", "loop_c"]
    outline[3]["loops_closed"] = ["loop_a", "loop_b", "loop_c"]
    chain._validate_retention_outline(outline)


def test_retention_two_planted_loops_is_the_lower_boundary():
    outline = _retention_outline(4)
    assert len(outline[0]["loops_planted"]) == 2
    chain._validate_retention_outline(outline)


def test_retention_one_planted_loop_is_below_contract():
    outline = _retention_outline(4)
    outline[0]["loops_planted"] = ["loop_a"]
    outline[3]["loops_closed"] = ["loop_a"]
    assert _raises(outline) == "loop_count"


def test_retention_four_planted_loops_is_above_contract():
    outline = _retention_outline(4)
    outline[0]["loops_planted"] = ["loop_a", "loop_b", "loop_c", "loop_d"]
    outline[3]["loops_closed"] = ["loop_a", "loop_b", "loop_c", "loop_d"]
    assert _raises(outline) == "loop_count"


def test_retention_requires_a_plant_in_scene_one():
    outline = _retention_outline(4)
    outline[0]["loops_planted"] = []
    outline[1]["loops_planted"] = ["loop_a", "loop_b"]
    assert _raises(outline) == "loop_missing_scene1_plant"


def test_retention_unclosed_loop_is_a_violation():
    outline = _retention_outline(4)
    outline[3]["loops_closed"] = ["loop_a"]
    assert _raises(outline) == "loop_unclosed"


def test_retention_unclosed_message_names_the_loop_and_its_position():
    outline = _retention_outline(4)
    outline[3]["loops_closed"] = ["loop_a"]
    with pytest.raises(chain.RetentionError, match="loop_b planted at position 1"):
        chain._validate_retention_outline(outline)


def test_retention_unknown_closure_is_a_violation():
    outline = _retention_outline(4)
    outline[3]["loops_closed"] = ["loop_a", "loop_b", "loop_ghost"]
    assert _raises(outline) == "loop_unknown_close"


def test_retention_close_before_plant_is_a_violation():
    outline = _retention_outline(4)
    outline[2]["loops_planted"] = ["loop_c"]
    outline[1]["loops_closed"] = ["loop_c"]
    outline[3]["loops_closed"] = ["loop_a", "loop_b", "loop_c"]
    assert _raises(outline) == "loop_unknown_close"


def test_retention_duplicate_plant_is_a_violation():
    outline = _retention_outline(4)
    outline[1]["loops_planted"] = ["loop_a"]
    assert _raises(outline) == "loop_duplicate_plant"


def test_retention_duplicate_close_is_a_violation():
    outline = _retention_outline(4)
    outline[2]["loops_closed"] = ["loop_a"]
    assert _raises(outline) == "loop_duplicate_close"


def test_retention_same_scene_plant_and_close_is_a_violation():
    outline = _retention_outline(4)
    outline[0]["loops_closed"] = ["loop_a"]
    assert _raises(outline) == "loop_same_scene"


@pytest.mark.parametrize("field", ["loops_planted", "loops_closed"])
@pytest.mark.parametrize("bad", ["loop_a", None, {"loop_a": 1}, ["loop_a", 3], 7])
def test_retention_loop_fields_must_be_string_lists(field, bad):
    outline = _retention_outline(4)
    outline[1][field] = bad
    assert _raises(outline) == "loop_field_malformed"


@pytest.mark.parametrize(
    "bad_id",
    # "loop_a\n" is the regex trap: `$` matches before a trailing newline, so a
    # folded YAML scalar (`- >\n  loop_a`) would pass an `^...$` check and then
    # never match the closure's own id.
    ["Loop_A", "reveal", "loop-a", "loop_", "loop_긴장", " loop_a", "loop_a\n", "loop_a\nloop_b"],
)
def test_retention_loop_ids_must_match_the_syntax(bad_id):
    outline = _retention_outline(4)
    outline[0]["loops_planted"] = [bad_id, "loop_b"]
    outline[3]["loops_closed"] = [bad_id, "loop_b"]
    assert _raises(outline) == "loop_id_invalid"


def test_retention_atmospheric_ending_needs_no_ledger_entry():
    # An unresolved implication in the final act is legal — it just may not
    # masquerade as a tracked promise. Nothing extra is planted, so it passes.
    outline = _retention_outline(4)
    outline[3]["synopsis"] = "재단도 답을 모르는 질문 하나가 남는다"
    chain._validate_retention_outline(outline)


# --- pattern-interrupt cadence ---


def test_retention_cadence_constant_is_two():
    assert chain.MAX_SCENES_WITHOUT_PATTERN_INTERRUPT == 2


def test_retention_run_of_two_none_scenes_is_valid():
    chain._validate_retention_outline(_cadence_outline(["none", "none", "none", "tone_shift"]))


def test_retention_run_of_three_none_scenes_is_invalid():
    assert _raises(_cadence_outline(["none", "none", "none", "none"])) == "interrupt_cadence"


def test_retention_a_non_none_interrupt_resets_the_run():
    outline = _cadence_outline(["none", "none", "none", "pov_shift", "none", "none"])
    chain._validate_retention_outline(outline)


def test_retention_cadence_counts_from_after_the_scene1_hook():
    # Scene 1 is `none` here too; the hook is scene 1's interrupt, so the run
    # starts at scene 2 and scenes 2-3 are still legal.
    chain._validate_retention_outline(_cadence_outline(["none", "none", "none", "format_change"]))


@pytest.mark.parametrize("interrupt", sorted(chain._VALID_PATTERN_INTERRUPTS))
def test_retention_every_vocabulary_interrupt_is_accepted(interrupt):
    chain._validate_retention_outline(_cadence_outline([interrupt, "tone_shift", "none", "none"]))


@pytest.mark.parametrize("bad", ["cutaway", "NONE!", "", None, 4, ["tone_shift"]])
def test_retention_interrupt_outside_the_vocabulary_is_rejected(bad):
    outline = _retention_outline(4)
    outline[1]["pattern_interrupt"] = bad
    assert _raises(outline) == "interrupt_invalid"


def test_retention_interrupt_key_may_not_be_absent():
    outline = _retention_outline(4)
    del outline[1]["pattern_interrupt"]
    assert _raises(outline) == "interrupt_invalid"


# --- word budget ---


def test_retention_per_scene_budget_boundaries_are_inclusive():
    # Both ends of the per-scene band, in ONE outline that is otherwise legal — a
    # uniform outline at either bound is now rejected by `budget_uniform` instead,
    # so the boundary can only be probed on an uneven shape (Story 12.6).
    outline = _retention_outline(9)
    outline[0]["word_budget"] = chain.MIN_SCENE_WORD_BUDGET
    outline[4]["word_budget"] = chain.MAX_SCENE_WORD_BUDGET
    chain._validate_retention_outline(outline)


@pytest.mark.parametrize("budget", [chain.MIN_SCENE_WORD_BUDGET - 1, chain.MAX_SCENE_WORD_BUDGET + 1])
def test_retention_per_scene_budget_outside_the_range_is_rejected(budget):
    assert _raises(_budget_outline(6, budget)) == "budget_range"


def test_retention_total_budget_boundaries_are_inclusive():
    for total in (chain.MIN_TOTAL_WORD_BUDGET, chain.MAX_TOTAL_WORD_BUDGET):
        outline = _retention_outline(9)
        # Spread the difference over the middle scenes only: they are the ones with
        # headroom under the per-scene ceiling, and moving the ends would change the
        # opening/closing shares the same outline is meant to keep legal.
        for offset in range(abs(total - sum(s["word_budget"] for s in outline))):
            outline[1 + offset % 7]["word_budget"] += 1 if total > chain.MIN_TOTAL_WORD_BUDGET else -1
        assert sum(s["word_budget"] for s in outline) == total
        chain._validate_retention_outline(outline)


def test_retention_total_below_the_floor_is_rejected():
    outline = _budget_outline(8, chain.MIN_SCENE_WORD_BUDGET)  # every scene legal, total short
    assert sum(s["word_budget"] for s in outline) < chain.MIN_TOTAL_WORD_BUDGET
    assert _raises(outline) == "budget_total"


def test_retention_total_above_the_ceiling_is_rejected():
    outline = _budget_outline(6, chain.MAX_SCENE_WORD_BUDGET)  # every scene legal, total over
    assert sum(s["word_budget"] for s in outline) > chain.MAX_TOTAL_WORD_BUDGET
    assert _raises(outline) == "budget_total"


@pytest.mark.parametrize("bad", [True, False, 45.0, "45", None, [45]])
def test_retention_budget_must_be_a_real_int(bad):
    # `True` is the trap: bool subclasses int, so a naive isinstance check reads
    # `word_budget: true` as a budget of 1.
    outline = _retention_outline(6)
    outline[2]["word_budget"] = bad
    assert _raises(outline) == "budget_type"


def test_retention_zero_budget_is_rejected_by_range_not_type():
    outline = _retention_outline(6)
    outline[2]["word_budget"] = 0
    assert _raises(outline) == "budget_range"


# --- malformed scenes / positional authority ---


@pytest.mark.parametrize("bad", [None, "scene", ["scene"], 7])
def test_retention_non_mapping_scene_is_rejected(bad):
    outline = _retention_outline(4)
    outline[2] = bad
    assert _raises(outline) == "scene_malformed"


def test_retention_ignores_scene_num_and_uses_list_position():
    # Every scene claims to be scene 1 — a real, observed LLM misbehaviour. The
    # ledger and the hook rule must still read the list positionally.
    outline = _retention_outline(4)
    for scene in outline:
        scene["scene_num"] = 1
    chain._validate_retention_outline(outline)


def test_retention_non_contiguous_scene_num_does_not_break_validation():
    outline = _retention_outline(4)
    for scene, num in zip(outline, [7, 3, 99, 1], strict=True):
        scene["scene_num"] = num
    chain._validate_retention_outline(outline)


def test_retention_deceptive_scene_num_cannot_rescue_a_positional_violation():
    # Position 2 carries a hook and claims scene_num 1. Trusting the model's
    # number would legalize a second hook; position must win.
    outline = _retention_outline(4)
    outline[1]["hook_type"] = "mystery"
    outline[1]["scene_num"] = 1
    assert _raises(outline) == "hook_misplaced"


# --- determinism / idempotence / non-destructiveness ---


def test_retention_valid_outline_is_left_byte_equivalent():
    outline = _retention_outline(8)
    before = json.dumps(outline, ensure_ascii=False, sort_keys=True)
    chain._validate_retention_outline(outline)
    assert json.dumps(outline, ensure_ascii=False, sort_keys=True) == before


def test_retention_preserves_unknown_scene_fields_and_list_order():
    outline = _retention_outline(5)
    for idx, scene in enumerate(outline):
        scene["some_future_field"] = {"nested": [idx]}
    snapshot = copy.deepcopy(outline)
    chain._validate_retention_outline(outline)
    assert outline == snapshot


def test_retention_validation_is_idempotent():
    once, twice = _retention_outline(6), _retention_outline(6)
    once[0]["hook_type"] = twice[0]["hook_type"] = " SHOCK "
    chain._validate_retention_outline(once)
    chain._validate_retention_outline(twice)
    chain._validate_retention_outline(twice)  # second pass changes nothing
    assert once == twice


def test_retention_is_deterministic_across_repeated_runs():
    codes = set()
    for _ in range(5):
        outline = _retention_outline(4)
        outline[3]["loops_closed"] = []
        codes.add(_raises(outline))
    assert codes == {"loop_unclosed"}


def test_retention_does_not_mutate_a_rejected_outline_beyond_canonicalization():
    outline = _retention_outline(4)
    outline[3]["loops_closed"] = []
    snapshot = copy.deepcopy(outline)
    _raises(outline)
    assert outline == snapshot  # already-canonical scalars, so nothing was written


def test_retention_canonicalizes_enums_on_later_scenes_too():
    # AC3's canonicalization is not a scene-1 special case: `hook_type: "  NONE  "`
    # at position 2 is the same model slip, and rejecting it would fail a valid
    # outline on formatting alone.
    outline = _retention_outline(4)
    outline[1]["hook_type"] = "  NONE  "
    outline[2]["pattern_interrupt"] = " Pov_Shift "
    chain._validate_retention_outline(outline)
    assert outline[1]["hook_type"] == "none"
    assert outline[2]["pattern_interrupt"] == "pov_shift"


def test_retention_rejected_outline_is_mutated_only_by_canonicalization():
    """The stricter half of AC8's non-destructiveness claim. The existing sibling
    test uses already-canonical values, so it cannot distinguish "writes only the
    two enums" from "writes nothing at all"; this one puts a non-canonical enum
    ahead of the violation and pins the write to exactly that key."""
    outline = _retention_outline(4)
    outline[1]["hook_type"] = "  NONE  "
    outline[3]["loops_closed"] = []  # ledger never settles — fails after scene 2
    expected = copy.deepcopy(outline)
    expected[1]["hook_type"] = "none"
    assert _raises(outline) == "loop_unclosed"
    assert outline == expected


def test_retention_empty_outline_is_rejected():
    # `structure_step`'s base parser rejects an empty `scenes` list first, but the
    # validator is a public-by-convention pure function — it must not read an
    # empty outline as a vacuously satisfied contract.
    assert _raises([]) == "loop_count"


def test_retention_single_scene_outline_can_never_settle_its_ledger():
    # Two scenes is the structural minimum: a loop must close in a LATER scene, so
    # a one-scene outline either leaves the ledger open or plants-and-closes in
    # place. Both are violations; neither is a legal shortcut.
    unclosed = [_retention_scene(1, 1, loops_closed=[])]
    assert _raises(unclosed) == "loop_unclosed"
    assert _raises([_retention_scene(1, 1)]) == "loop_same_scene"


def test_retention_rejects_an_all_invalid_fake_llm_payload():
    # Every rule broken at once — the shape a model produces when it ignores the
    # contract entirely. It must fail, and it must fail with a rule code.
    payload = yaml.safe_load("""
scenes:
  - scene_num: 1
    synopsis: "긴장을 고조시킨다"
    event: "무서운 분위기를 만든다"
    hook_type: "cliffhanger"
    loops_planted: "loop_a"
    loops_closed: ["loop_zzz"]
    pattern_interrupt: "cutaway"
    word_budget: true
    fact_references: []
  - scene_num: 1
    synopsis: "더 무섭게 만든다"
    hook_type: "shock"
    loops_planted: []
    loops_closed: []
    pattern_interrupt: "none"
    word_budget: "많이"
    fact_references: ["fact_key_1"]
""")["scenes"]
    with pytest.raises(chain.RetentionError) as excinfo:
        chain._validate_retention_outline(payload)
    assert excinfo.value.code == "event_missing"


# --- structure_step integration: no LLM recall on a retention violation ---


async def test_structure_step_retention_failure_makes_no_second_call(monkeypatch):
    """AC7's load-bearing assertion. Two calls would mean the validator was placed
    inside `_call_stage_with_retry`'s parse callback, where a ValueError buys one
    DeepSeek regeneration — exactly the LLM recall this contract forbids."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    attempts = {"n": 0}

    async def call(rendered, s):
        attempts["n"] += 1
        outline = _retention_outline(4)
        outline[3]["loops_closed"] = []  # ledger never settles
        return json.dumps({"scenes": outline}), {}, "stop"

    with pytest.raises(chain.RetentionError) as excinfo:
        await chain.structure_step("SCP-173", "", {"frozen_descriptor": "d"}, "guide", None, call)
    assert excinfo.value.code == "loop_unclosed"
    assert attempts["n"] == 1, "retention validation must sit OUTSIDE the semantic-retry boundary"


async def test_structure_step_base_schema_error_still_gets_its_one_retry(monkeypatch):
    """The retention validator must not shorten the pre-existing retry for a base
    YAML/shape failure — that one is still worth a regeneration."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    attempts = {"n": 0}

    async def call(rendered, s):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return json.dumps({"scenes": []}), {}, "stop"
        return json.dumps({"scenes": _retention_outline(4)}), {}, "stop"

    scenes = await chain.structure_step("SCP-173", "", {"frozen_descriptor": "d"}, "guide", None, call)
    assert attempts["n"] == 2
    assert len(scenes) == 4


async def test_structure_step_returns_a_contract_valid_outline_untouched(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    expected = _retention_outline(6)

    async def call(rendered, s):
        return json.dumps({"scenes": _retention_outline(6)}), {}, "stop"

    outline = await chain.structure_step("SCP-173", "", {"frozen_descriptor": "d"}, "guide", None, call)
    # Story 12.7 annotates the validated outline in place; that write is the ONLY
    # difference, so with it removed the outline is still returned byte-identical.
    assert [scene.pop("assigned_devices") for scene in outline] == chain._allocate_devices(expected)
    assert outline == expected


async def test_writing_scene_repair_step_sends_the_paired_structure_subset(monkeypatch):
    captured = {}

    class CapturingPrompt:
        def compile(self, **variables):
            captured.update(variables)
            return "rendered"

    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: CapturingPrompt())
    originals = [{"scene_num": 2, "narration": "둘."}, {"scene_num": 5, "narration": "다섯."}]
    subset = [_retention_scene(2, 6), _retention_scene(5, 6)]

    async def call(rendered, s):
        return yaml.safe_dump({"scenes": originals}, allow_unicode=True), {}, "stop"

    await chain.writing_scene_repair_step("SCP-173", originals, subset, "feedback", "desc", "guide", None, call)
    assert json.loads(captured["scene_structure"]) == subset


def _derived_at(minutes: int) -> dict[str, int]:
    """The module's own budget derivation evaluated at another duration.

    The constants are computed at import, so a test that has to run the contract at
    a duration the module was never imported at monkeypatches these four onto it.
    """
    target = minutes * chain.TARGET_WPM
    return {
        "MIN_TOTAL_WORD_BUDGET": round(target * (1 - chain.WORD_BUDGET_TOLERANCE)),
        "MAX_TOTAL_WORD_BUDGET": round(target * (1 + chain.WORD_BUDGET_TOLERANCE)),
        "MIN_SCENE_WORD_BUDGET": round(target * chain.MIN_SCENE_WORD_SHARE),
        "MAX_SCENE_WORD_BUDGET": round(target * chain.MAX_SCENE_WORD_SHARE),
    }


def test_structure_cassette_satisfies_the_retention_contract():
    """The cassette is replayed by other stage tests as a *valid* DeepSeek reply.
    If it ever drifts out of contract, those tests fail with a RetentionError far
    from the edit that caused it — pin the contract at the fixture instead."""
    content = _load_cassette("deepseek_structure.json")["choices"][0]["message"]["content"]
    scenes = yaml.safe_load(content)["scenes"]
    chain._validate_retention_outline(scenes)
    # Solved on load, not frozen in the JSON — see `fakes._apply_retention_budgets`.
    assert [scene["word_budget"] for scene in scenes] == _budgets(len(scenes))


def test_structure_cassette_follows_the_target_duration(monkeypatch):
    """AC3's "one line, no second edit anywhere", asserted where it was false.

    As recorded, the cassette's four budgets summed to exactly
    MIN_TOTAL_WORD_BUDGET (370) — so `TARGET_DURATION_MINUTES = 4` made the FIXTURE
    violate `budget_total`, and the story's headline promise needed a second edit
    hiding in a JSON file.
    """
    for name, value in _derived_at(4).items():
        monkeypatch.setattr(chain, name, value)
    content = _load_cassette("deepseek_structure.json")["choices"][0]["message"]["content"]
    chain._validate_retention_outline(yaml.safe_load(content)["scenes"])


async def test_critic_step_sends_the_source_text_as_the_fact_sheet(monkeypatch):
    """AC12a wiring. The prompt-contract test only proves `{{scp_fact_sheet}}` is
    still in critic_agent.md; it cannot see whether the stage fills it. Without
    this, dropping `scp_text` from the compile leaves criteria 6/7 judging
    substance against the model's own SCP knowledge — silently."""
    captured: list[dict] = []

    class CapturingPrompt:
        def compile(self, **variables):
            captured.append(variables)
            return "rendered"

    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: CapturingPrompt())

    async def call(rendered, s):
        return yaml.safe_dump({"verdict": "pass", "feedback": "좋다", "scene_notes": []}), {}, "stop"

    await chain.critic_step("SCP-173 원문 전체", _ONE_SCENE, {}, "guide", None, call)
    assert [v["scp_fact_sheet"] for v in captured] == ["SCP-173 원문 전체"]


# --- prompt contract (AC 12): fact_references must resolve, not dangle ---


def _prompt_text(name: str) -> str:
    return (Path(__file__).parents[3] / "prompts" / "scenario" / name).read_text(encoding="utf-8")


def test_structure_prompt_no_longer_illustrates_placeholder_fact_keys():
    # The old example (`"fact_key_1"`) named a dictionary that exists nowhere in
    # the pipeline, so Stage 3 saw fact LABELS with no fact CONTENT. A later
    # prompt edit must not reintroduce the pattern.
    content = _prompt_text("structure.md")
    assert "fact_references" in content
    assert not re.search(r"fact_key_|fact_\d", content), "structure.md reintroduced a placeholder-key example"


def test_structure_prompt_carries_the_retention_contract():
    content = _prompt_text("structure.md")
    for field in ("event", "hook_type", "loops_planted", "loops_closed", "pattern_interrupt", "word_budget"):
        assert field in content, f"structure.md does not describe {field}"
    for hook in chain.HOOK_TYPES:
        assert hook in content


@pytest.mark.parametrize("name", ["writing.md", "writing_scene_repair.md"])
def test_writing_prompts_carry_the_fact_grounding_rule(name):
    content = _prompt_text(name)
    assert "fact_references" in content, f"{name} lost the fact-grounding rule"
    assert "사실 접지" in content, f"{name} lost the fact-grounding section"


def test_writing_scene_repair_prompt_receives_the_structure_subset():
    assert "{{scene_structure}}" in _prompt_text("writing_scene_repair.md")


def test_critic_prompt_judges_substance_against_the_fact_sheet():
    content = _prompt_text("critic_agent.md")
    assert "{{scp_fact_sheet}}" in content
    assert "Substance" in content and "Fidelity" in content


# --- Story 12.6: length as ONE decision -------------------------------------
# Before this story the band lived in three disagreeing places (the constant, the
# validator's literals, and `structure.md`'s prose). These tests exist so a fourth
# copy cannot be added without a red test naming it.


def test_word_budget_band_is_derived_from_duration_and_wpm():
    target = chain.TARGET_DURATION_MINUTES * chain.TARGET_WPM
    assert chain._TARGET_TOTAL_WORDS == round(target)
    assert chain.MIN_TOTAL_WORD_BUDGET == round(target * (1 - chain.WORD_BUDGET_TOLERANCE))
    assert chain.MAX_TOTAL_WORD_BUDGET == round(target * (1 + chain.WORD_BUDGET_TOLERANCE))
    assert chain.MIN_SCENE_WORD_BUDGET == round(target * chain.MIN_SCENE_WORD_SHARE)
    assert chain.MAX_SCENE_WORD_BUDGET == round(target * chain.MAX_SCENE_WORD_SHARE)
    # The band must actually contain the target it was derived from — a tolerance
    # sign slip would still satisfy every equality above.
    assert chain.MIN_TOTAL_WORD_BUDGET < target < chain.MAX_TOTAL_WORD_BUDGET


@pytest.mark.parametrize(
    "bound, formula",
    [
        ("MIN_TOTAL_WORD_BUDGET", lambda t, c: round(t * (1 - c.WORD_BUDGET_TOLERANCE))),
        ("MAX_TOTAL_WORD_BUDGET", lambda t, c: round(t * (1 + c.WORD_BUDGET_TOLERANCE))),
        ("MIN_SCENE_WORD_BUDGET", lambda t, c: round(t * c.MIN_SCENE_WORD_SHARE)),
        ("MAX_SCENE_WORD_BUDGET", lambda t, c: round(t * c.MAX_SCENE_WORD_SHARE)),
    ],
)
def test_each_bound_is_its_formula_over_duration_and_wpm(bound, formula):
    """AC3 as an identity, per bound: the SHIPPED constant equals its derivation from
    `TARGET_DURATION_MINUTES x TARGET_WPM` and the share/tolerance knobs, so editing
    the duration moves it with no second edit anywhere.

    This replaces a test that recomputed `round(minutes * TARGET_WPM * k)` in its own
    body at durations the module was never imported at and asserted the answer
    DIFFERED from the shipped constant. That is arithmetic ("3 != 8"), not a
    property of this module: it passed identically against a hardcoded literal,
    which is precisely the failure AC3 exists to catch.
    """
    target = chain.TARGET_DURATION_MINUTES * chain.TARGET_WPM
    assert getattr(chain, bound) == formula(target, chain)


@pytest.mark.parametrize("literal", ["180~360", "20~90", "3분 파이프라인"])
def test_structure_prompt_no_longer_hardcodes_a_budget_band(literal):
    assert literal not in _prompt_text("structure.md"), (
        f"structure.md re-typed the budget band as the literal {literal!r} — "
        "it must read the derived value through a template variable instead"
    )


def test_structure_prompt_reads_the_derived_budget_variables():
    content = _prompt_text("structure.md")
    for variable in ("total_word_budget_min", "total_word_budget_max", "scene_word_budget_min",
                     "scene_word_budget_max", "max_opening_word_pct", "max_closing_word_pct",
                     "min_budget_spread"):
        assert "{{" + variable + "}}" in content, f"structure.md does not read {{{{{variable}}}}}"
    # The instruction that produced run e5ed4b3a's flat 9-scene outline.
    assert "씬 수로 나눠" not in content
    for code in ("budget_opening_share", "budget_closing_share", "budget_uniform"):
        assert code in content, f"structure.md does not name the {code} rejection"


async def test_structure_step_passes_the_derived_budget_band(monkeypatch):
    captured = {}

    class CapturingPrompt:
        def compile(self, **variables):
            captured.update(variables)
            return "rendered"

    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: CapturingPrompt())

    async def call(rendered, s):
        return json.dumps({"scenes": _retention_outline(6)}), {}, "stop"

    await chain.structure_step("SCP-173", "", {"frozen_descriptor": "d"}, "guide", None, call)
    assert captured["target_duration"] == chain.TARGET_DURATION_MINUTES
    assert captured["total_word_budget_min"] == chain.MIN_TOTAL_WORD_BUDGET
    assert captured["total_word_budget_max"] == chain.MAX_TOTAL_WORD_BUDGET
    assert captured["scene_word_budget_min"] == chain.MIN_SCENE_WORD_BUDGET
    assert captured["scene_word_budget_max"] == chain.MAX_SCENE_WORD_BUDGET
    assert captured["max_opening_word_pct"] == round(chain.MAX_OPENING_WORD_SHARE * 100)
    assert captured["max_closing_word_pct"] == round(chain.MAX_CLOSING_WORD_SHARE * 100)
    assert captured["min_budget_spread"] == chain.MIN_BUDGET_SPREAD


class _SeededPrompt:
    """A Langfuse TextPromptClient stand-in: `.prompt` is the raw template text, which
    is what `.compile()` renders and what a stale `production` version would differ in."""

    def __init__(self, template: str, version: int = 7):
        self.prompt = template
        self.version = version

    def compile(self, **variables):
        return "rendered"


_SEEDED_12_6 = " ".join(
    "{{" + name + "}}"
    for name in (*chain._STRUCTURE_BUDGET_VARIABLES, chain._STRUCTURE_SOURCE_VARIABLE)
)
_SEEDED_PRE_12_6 = "씬당 20~90 어절, 총합 180~360 (현재 3분 파이프라인 기준)"


async def test_structure_step_rejects_a_prompt_version_that_predates_the_derived_band(monkeypatch):
    """The runtime prompt body comes from Langfuse, not from the repo file, and
    `compile()` silently ignores variables the template never mentions. A rolled-back
    `production` would tell the model "총합 180~360" while the validator enforces
    370-500: every outline fails `budget_total`, the one re-roll fails identically,
    and nothing in the failure names the prompt version. Fail at the fetch instead.
    """
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: _SeededPrompt(_SEEDED_PRE_12_6)
    )

    async def call(rendered, s):
        raise AssertionError("the provider must not be called on a stale prompt")

    with pytest.raises(RuntimeError) as excinfo:
        await chain.structure_step("SCP-173", "", {"frozen_descriptor": "d"}, "guide", None, call)
    message = str(excinfo.value)
    assert "total_word_budget_min" in message
    assert "version=7" in message
    assert "migrate_prompts.py" in message  # the operator's next command, spelled out


async def test_structure_step_accepts_a_prompt_that_reads_the_derived_band(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: _SeededPrompt(_SEEDED_12_6)
    )

    async def call(rendered, s):
        return json.dumps({"scenes": _retention_outline(6)}), {}, "stop"

    assert len(await chain.structure_step("SCP-173", "", {"frozen_descriptor": "d"}, "guide", None, call)) == 6


def test_the_repo_prompt_would_pass_the_seeding_check():
    """The check is only useful if the file `migrate_prompts.py` seeds satisfies it —
    otherwise re-seeding as instructed leaves the run failing the same way."""
    content = _prompt_text("structure.md")
    assert all("{{" + name + "}}" in content for name in chain._STRUCTURE_BUDGET_VARIABLES)


# --- Story 12.6: distribution is enforced, not requested ---------------------


def test_retention_uneven_outline_passes():
    # The helper's own shape: short ends, fat middle. If this ever fails, every
    # other retention test is being judged on an outline that is already illegal.
    chain._validate_retention_outline(_retention_outline(9))


def test_retention_uniform_distribution_is_rejected():
    # Exactly the run e5ed4b3a shape: every scene the same budget, total in band.
    budget = round(chain._TARGET_TOTAL_WORDS / 9)
    outline = _budget_outline(9, budget)
    assert chain.MIN_TOTAL_WORD_BUDGET <= budget * 9 <= chain.MAX_TOTAL_WORD_BUDGET
    assert _raises(outline) == "budget_uniform"


def _outline_with_budgets(budgets: list[int]) -> list[dict]:
    """An outline whose word_budgets are EXACTLY ``budgets``.

    Ledger fields come from the standard helper; the numbers do not. A boundary test
    has to place the outline ON the bound, and ``_budgets``' solver lands wherever it
    lands — the previous spread-boundary test believed it was probing 1.6 and was
    actually validating an outline at spread 5.0.
    """
    return [_retention_scene(pos, len(budgets), word_budget=b) for pos, b in enumerate(budgets, start=1)]


def test_retention_spread_boundary_is_inclusive():
    # 80/50 is EXACTLY MIN_BUDGET_SPREAD (and 50 * 1.6 == 80.0 with no float slack),
    # so this outline sits on the bound: the check is `max < min * spread`, not `<=`.
    outline = _outline_with_budgets([50, 80, 80, 80, 80, 50])
    assert max(b["word_budget"] for b in outline) / min(b["word_budget"] for b in outline) == (
        chain.MIN_BUDGET_SPREAD
    )
    chain._validate_retention_outline(outline)


def test_retention_one_word_under_the_spread_boundary_is_rejected():
    # The half the old test never asserted. Same shape, largest scene one 어절 lower:
    # 79/50 = 1.58. Total (416) and both end shares stay legal, so `budget_uniform`
    # is the only rule that can fire.
    outline = _outline_with_budgets([50, 79, 79, 79, 79, 50])
    assert chain.MIN_TOTAL_WORD_BUDGET <= sum(b["word_budget"] for b in outline) <= chain.MAX_TOTAL_WORD_BUDGET
    assert _raises(outline) == "budget_uniform"


def _over_share(outline: list[dict], index: int, share: float) -> None:
    """Push one scene just past ``share`` of the outline's total — computed against
    the OTHER scenes, because raising this scene also raises the denominator."""
    rest = sum(scene["word_budget"] for scene in outline) - outline[index]["word_budget"]
    outline[index]["word_budget"] = math.floor(rest * share / (1 - share)) + 1


def test_retention_front_loaded_opening_is_rejected():
    outline = _retention_outline(9)
    _over_share(outline, 0, chain.MAX_OPENING_WORD_SHARE)
    assert _raises(outline) == "budget_opening_share"


def test_budget_uniform_message_states_only_what_it_checks():
    """The message used to promise "give the central beats the largest budgets",
    which this check cannot see: [74] + [42] * 8 has spread 1.76 and an 18% opening,
    so it passes while being maximally front-loaded. An error that describes a rule
    nobody enforces sends the next reader looking for the enforcement."""
    outline = _outline_with_budgets([74] + [42] * 8)
    chain._validate_retention_outline(outline)  # front-loaded, and legal today

    with pytest.raises(chain.RetentionError) as excinfo:
        chain._validate_retention_outline(_outline_with_budgets([50, 79, 79, 79, 79, 50]))
    message = str(excinfo.value)
    assert "largest scene budget must be at least" in message
    assert "central beats" not in message


def test_retention_outline_shorter_than_four_scenes_names_the_scene_count():
    """Below 4 scenes the distribution rules have NO common solution (≤20% opening
    + ≤20% closing leaves the lone middle past the 30% per-scene ceiling), so a
    3-scene outline used to die on `budget_opening_share` — reporting the first
    budget as the problem when the problem is that there are three scenes."""
    outline = _outline_with_budgets([130, 130, 130])
    assert chain.MIN_TOTAL_WORD_BUDGET <= 390 <= chain.MAX_TOTAL_WORD_BUDGET  # volume is legal
    assert _raises(outline) == "scene_count"


def test_retention_four_scenes_is_still_admitted():
    # The bound is "fewer than 4", not "fewer than 8": `structure.md`'s 8-12 ceiling
    # has never been validated against a run, and rejecting a legal 4- or 6-scene
    # outline on it would be a new failure rather than a fixed one.
    chain._validate_retention_outline(_retention_outline(4))


def test_retention_back_loaded_closing_is_rejected():
    outline = _retention_outline(9)
    _over_share(outline, -1, chain.MAX_CLOSING_WORD_SHARE)
    assert _raises(outline) == "budget_closing_share"


def test_retention_opening_share_boundary_is_inclusive():
    # 80 of 400 is EXACTLY MAX_OPENING_WORD_SHARE, so this probes `>` vs `>=` for
    # real. `_over_share` could only ever land NEAR the cap (19.86% on the previous
    # fixture), which cannot tell the two operators apart.
    outline = _outline_with_budgets([80, 70, 70, 70, 60, 50])
    assert outline[0]["word_budget"] / sum(b["word_budget"] for b in outline) == chain.MAX_OPENING_WORD_SHARE
    chain._validate_retention_outline(outline)


def test_retention_one_word_over_the_opening_share_boundary_is_rejected():
    # The same outline with one 어절 more on the opening: 81/401 = 20.2%.
    outline = _outline_with_budgets([81, 70, 70, 70, 60, 50])
    assert outline[0]["word_budget"] / sum(b["word_budget"] for b in outline) > chain.MAX_OPENING_WORD_SHARE
    assert _raises(outline) == "budget_opening_share"


# --- Story 12.6: the critic's closed issue vocabulary ------------------------


def test_critic_prompt_names_every_issue_type():
    content = _prompt_text("critic_agent.md")
    assert "issue_type" in content
    for issue_type in state.CRITIC_ISSUE_TYPES:
        assert issue_type in content, f"critic_agent.md does not describe issue_type {issue_type!r}"


def test_critic_prompt_declares_the_three_permitted_adaptations():
    content = _prompt_text("critic_agent.md")
    assert "허용되는 각색" in content
    # Each prohibition ships with its replacement in the same block.
    assert "✅" in content and "❌" in content


def test_writing_prompt_declares_the_three_permitted_adaptations():
    content = _prompt_text("writing.md")
    assert "허용되는 각색" in content
    # The exact regression the story cites, with a positive counter-example.
    assert "재단 공식 기록을 낭독합니다" in content
    assert "✅" in content


def test_review_prompt_exempts_sensory_addition_from_invented_content():
    content = _prompt_text("review.md")
    assert "invented_content" in content
    assert "허용되는 각색" in content


@pytest.mark.parametrize(
    "raw, expected",
    [("ungrounded_claim", "ungrounded_claim"), ("  PACING ", "pacing"), ("report_tone", "report_tone"),
     ("Fact Problem!!", "other"), ("", "other"), (None, "other"), (7, "other")],
)
def test_critic_parse_coerces_issue_type_to_the_closed_vocabulary(monkeypatch, raw, expected):
    payload = {"verdict": "retry", "scene_notes": [{"scene_num": 1, "issue": "문제", "suggestion": "고쳐"}]}
    if raw is not None:
        payload["scene_notes"][0]["issue_type"] = raw
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    async def call(rendered, s):
        return yaml.safe_dump(payload, allow_unicode=True), {}, "stop"

    report = asyncio.run(chain.critic_step("원문", _ONE_SCENE, {}, "guide", None, call))
    assert report["scene_notes"][0]["issue_type"] == expected


def test_critic_parse_logs_a_rejected_issue_type(monkeypatch, caplog):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    payload = {"verdict": "retry",
               "scene_notes": [{"scene_num": 1, "issue_type": "Fact Problem!!", "issue": "x", "suggestion": "y"}]}

    async def call(rendered, s):
        return yaml.safe_dump(payload, allow_unicode=True), {}, "stop"

    with caplog.at_level(logging.WARNING):
        asyncio.run(chain.critic_step("원문", _ONE_SCENE, {}, "guide", None, call))
    assert "Fact Problem!!" in caplog.text


@pytest.mark.parametrize("raw, recorded", [("PACING", "pacing"), ("  report_tone\n", "report_tone")])
def test_critic_parse_is_silent_when_it_only_normalized_the_case(monkeypatch, caplog, raw, recorded):
    """`issue_type: "PACING"` is recorded as `pacing` — correctly. The log used to
    fire on `!= raw_type`, so it also fired here and announced "is not in [...] —
    recorded as 'other'" about a value that WAS in the vocabulary and was NOT
    recorded as other. A rejection log that cries wolf on legal input is worse than
    none: it trains the reader to skip the line that matters."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    payload = {"verdict": "retry",
               "scene_notes": [{"scene_num": 1, "issue_type": raw, "issue": "x", "suggestion": "y"}]}

    async def call(rendered, s):
        return yaml.safe_dump(payload, allow_unicode=True), {}, "stop"

    with caplog.at_level(logging.WARNING):
        report = asyncio.run(chain.critic_step("원문", _ONE_SCENE, {}, "guide", None, call))
    assert report["scene_notes"][0]["issue_type"] == recorded
    assert caplog.text == ""


def test_critic_parse_is_silent_when_the_model_names_the_fallback_itself(monkeypatch, caplog):
    """`issue_type: "other"` is a legal member, not a rejection."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    payload = {"verdict": "retry",
               "scene_notes": [{"scene_num": 1, "issue_type": "Other", "issue": "x", "suggestion": "y"}]}

    async def call(rendered, s):
        return yaml.safe_dump(payload, allow_unicode=True), {}, "stop"

    with caplog.at_level(logging.WARNING):
        asyncio.run(chain.critic_step("원문", _ONE_SCENE, {}, "guide", None, call))
    assert caplog.text == ""


def test_critic_parse_is_silent_when_the_field_is_simply_absent(monkeypatch, caplog):
    """A pre-12.6 prompt version emits no `issue_type` at all. Coerce, do not shout —
    otherwise every note of every legacy run logs a warning that names nothing."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    payload = {"verdict": "retry", "scene_notes": [{"scene_num": 1, "issue": "x", "suggestion": "y"}]}

    async def call(rendered, s):
        return yaml.safe_dump(payload, allow_unicode=True), {}, "stop"

    with caplog.at_level(logging.WARNING):
        report = asyncio.run(chain.critic_step("원문", _ONE_SCENE, {}, "guide", None, call))
    assert report["scene_notes"][0]["issue_type"] == state.CRITIC_ISSUE_TYPE_FALLBACK
    assert "issue_type" not in caplog.text


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


_VISUALS = {"location": "underground containment chamber", "color_palette": "grey", "atmosphere": "tense"}


@pytest.mark.parametrize("field", chain._REQUIRED_WRITING_VISUAL_FIELDS)
@pytest.mark.parametrize("bad", ["__missing__", "", "   ", None])
async def test_writing_step_rejects_missing_or_empty_visual_field(monkeypatch, field, bad):
    """Live run cd2f1fb8 (SCP-999): one scene came back with no `location` and the
    image stage died on a bare KeyError — `color_palette`/`atmosphere` sat on the
    adjacent lines with the same hard index. All three are REQUIRED by the prompt,
    so the model gets the one corrective retry rather than a silent fallback."""
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    calls = []

    async def call(rendered, s):
        calls.append(rendered)
        scene = {"scene_num": 1, "narration": "문장 하나.", **_VISUALS}
        if bad == "__missing__":
            scene.pop(field)
        else:
            scene[field] = bad
        return json.dumps({"scenes": [scene]}), {}, "stop"

    with pytest.raises(ValueError, match=field):
        await chain.writing_step("SCP-173", [{"scene_num": 1}], "desc", "guide", "", None, call)
    assert len(calls) == 2  # initial + the one semantic-correction retry, then it gives up


@pytest.mark.parametrize("field", chain._REQUIRED_WRITING_VISUAL_FIELDS)
async def test_writing_step_visual_field_retry_feeds_the_error_back_and_accepts_the_fix(monkeypatch, field):
    class CapturingPrompt:
        def __init__(self):
            self.errors = []

        def compile(self, **kwargs):
            self.errors.append(kwargs.get("parse_error", ""))
            return "rendered"

    captured = CapturingPrompt()
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: captured
    )

    async def call(rendered, s):
        scene = {"scene_num": 1, "narration": "문장 하나.", **_VISUALS}
        if len(captured.errors) < 2:  # omitted on the first attempt, corrected on the retry
            scene.pop(field)
        return json.dumps({"scenes": [scene]}), {}, "stop"

    result = await chain.writing_step("SCP-173", [{"scene_num": 1}], "desc", "guide", "", None, call)
    assert result["scenes"][0][field] == _VISUALS[field]
    assert captured.errors[0] == ""
    assert field in captured.errors[1]


async def test_writing_step_passes_valid_visual_fields_through_unchanged(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    calls = []

    async def call(rendered, s):
        calls.append(rendered)
        payload = {"scenes": [{"scene_num": 1, "narration": "문장 하나.", **_VISUALS}]}
        return json.dumps(payload), {}, "stop"

    result = await chain.writing_step("SCP-173", [{"scene_num": 1}], "desc", "guide", "", None, call)
    assert {k: result["scenes"][0][k] for k in _VISUALS} == _VISUALS
    assert len(calls) == 1  # no corrective retry


async def test_writing_step_collapses_embedded_newlines_in_narration(monkeypatch):
    """Live golden-set eval (Story 6.4) caught DeepSeek writing one sentence
    per physical line inside a YAML ``narration: |`` block literal — collapse
    it back to the single flowing line JSON output always produced."""
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return "scenes:\n  - scene_num: 1\n    narration: |\n      첫 문장.\n      둘째 문장.\n    location: chamber\n    color_palette: grey\n    atmosphere: tense\n", {}, "stop"

    result = await chain.writing_step("SCP-173", [{"scene_num": 1}], "desc", "guide", "", None, call)
    assert result["scenes"][0]["narration"] == "첫 문장. 둘째 문장."


# ── writing_step per-scene batching (2026-08-05) ───────────────────────────────


class EchoPrompt:
    """Compiles to its variables so a fake DeepSeek can see which scene it was asked for."""

    def compile(self, **variables):
        return json.dumps(variables, ensure_ascii=False)


def _structure(n: int) -> list[dict]:
    return [
        {"scene_num": i + 1, "act": f"act{i + 1}", "emotional_beat": f"beat{i + 1}",
         "synopsis": f"syn{i + 1}", "mood": "dread"}
        for i in range(n)
    ]


def _requested_scene(rendered: str) -> int:
    """The 1-based scene index ``_writing_scene_brief`` steered this call to."""
    match = re.search(r"SCENE (\d+) OF", rendered)
    assert match is not None, f"brief carries no scene steer: {rendered[:200]}"
    return int(match.group(1))


async def test_writing_step_makes_one_call_per_scene(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())
    calls = []

    async def call(rendered, s):
        n = _requested_scene(rendered)
        calls.append(n)
        return f"scenes:\n  - scene_num: {n}\n    narration: narr {n}.\n    location: chamber\n    color_palette: grey\n    atmosphere: tense\n", {}, "stop"

    result = await chain.writing_step("SCP-173", _structure(8), "desc", "guide", "", None, call)
    assert sorted(calls) == list(range(1, 9))
    assert len(result["scenes"]) == 8


async def test_writing_step_preserves_scene_order_when_calls_finish_out_of_order(monkeypatch):
    """The batched calls run concurrently, so completion order is not argument
    order — assembly must key on position, never on arrival."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())
    structure = _structure(5)
    completed = []

    async def call(rendered, s):
        n = _requested_scene(rendered)
        await asyncio.sleep((len(structure) - n) * 0.01)  # the LAST scene answers first
        completed.append(n)
        # a model answering one scene in isolation has no idea of its index — it
        # says "1" (or anything); the position it was asked for is the truth
        return f"scenes:\n  - scene_num: 1\n    narration: narr {n}.\n    location: chamber\n    color_palette: grey\n    atmosphere: tense\n", {}, "stop"

    result = await chain.writing_step("SCP-173", structure, "desc", "guide", "", None, call)
    assert completed == [5, 4, 3, 2, 1], "test is void unless the calls really finished out of order"
    assert [s["narration"] for s in result["scenes"]] == [f"narr {n}." for n in range(1, 6)]
    assert [s["scene_num"] for s in result["scenes"]] == [1, 2, 3, 4, 5]


async def test_writing_step_passes_neighbour_context_but_only_one_scene_to_write(monkeypatch):
    """Continuity context is the neighbours' one-line role, not their narration —
    a per-scene call with no context repeats or pre-empts an adjacent beat."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())
    seen = {}

    async def call(rendered, s):
        variables = json.loads(rendered)
        brief = variables["scene_structure"]
        n = _requested_scene(brief)
        seen[n] = json.loads(brief.split("\n", 1)[1])
        return f"scenes:\n  - scene_num: {n}\n    narration: narr {n}.\n    location: chamber\n    color_palette: grey\n    atmosphere: tense\n", {}, "stop"

    await chain.writing_step("SCP-173", _structure(3), "desc", "guide", "", None, call)

    assert seen[2]["write_only_this_scene"]["synopsis"] == "syn2"
    assert seen[2]["previous_scene_context"] == "act1 / beat1: syn1"
    assert seen[2]["next_scene_context"] == "act3 / beat3: syn3"
    assert seen[1]["previous_scene_context"] is None  # nothing before the hook
    assert seen[3]["next_scene_context"] is None
    # the whole point of batching: one scene's worth of payload per call
    assert set(seen[2]) == {
        "write_only_this_scene", "previous_scene_context", "next_scene_context", "loops_to_close_context",
    }
    assert seen[2]["loops_to_close_context"] == {}  # this fixture plants no loops


async def test_writing_step_carries_the_plant_context_for_every_loop_it_must_close(monkeypatch):
    """Story 12.1 review: the contract forbids closing a loop in the scene that
    planted it, so every closure is non-adjacent — and neighbour context only
    reaches ±1 scene. Given just the id `loop_a`, the writer of the closing scene
    has to invent the question it is answering, which is precisely the ungrounded
    assertion critic criterion 7 exists to catch."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())
    structure = _structure(5)
    structure[0]["loops_planted"] = ["loop_a"]
    structure[1]["loops_planted"] = ["loop_b"]
    structure[4]["loops_closed"] = ["loop_a", "loop_b"]
    seen = {}

    async def call(rendered, s):
        brief = json.loads(rendered)["scene_structure"]
        n = _requested_scene(brief)
        seen[n] = json.loads(brief.split("\n", 1)[1])
        return (
            f"scenes:\n  - scene_num: {n}\n    narration: narr {n}.\n"
            "    location: containment room\n"
            "    color_palette: cold gray\n"
            "    atmosphere: tense\n"
        ), {}, "stop"

    await chain.writing_step("SCP-173", structure, "desc", "guide", "", None, call)

    # scene 5 closes both; the plant is 4 and 3 scenes back, far outside neighbour range
    assert seen[5]["loops_to_close_context"] == {
        "loop_a": "scene 1: act1 / beat1: syn1",
        "loop_b": "scene 2: act2 / beat2: syn2",
    }
    assert seen[1]["loops_to_close_context"] == {}  # planting scenes owe nothing yet


def test_loops_to_close_context_ignores_a_plant_that_is_not_earlier():
    # A same-scene or later "plant" is already a contract violation upstream; the
    # brief must not paper over it by resolving forwards.
    structure = _structure(3)
    structure[1]["loops_planted"] = ["loop_a"]
    structure[1]["loops_closed"] = ["loop_a"]
    structure[2]["loops_planted"] = ["loop_b"]
    structure[0]["loops_closed"] = ["loop_b"]
    assert chain._loops_to_close_context(structure, 1) == {}
    assert chain._loops_to_close_context(structure, 0) == {}


@pytest.mark.parametrize("bad", [None, "loop_a", 7, {"loop_a": 1}])
def test_loops_to_close_context_tolerates_a_malformed_ledger(bad):
    # `_writing_scene_brief` runs on structure entries that the retention validator
    # already accepted, but it is also reachable on resumed/edited outlines — it
    # must degrade to no context, never raise inside the writing stage.
    structure = _structure(2)
    structure[1]["loops_closed"] = bad
    assert chain._loops_to_close_context(structure, 1) == {}


async def test_writing_step_rejects_a_call_that_answers_more_than_its_own_scene(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())
    attempts = []

    async def call(rendered, s):
        attempts.append(_requested_scene(rendered))
        return "scenes:\n  - narration: a.\n  - narration: b.\n", {}, "stop"

    with pytest.raises(ValueError, match="exactly 1 scene"):
        await chain.writing_step("SCP-173", _structure(1), "desc", "guide", "", None, call)
    assert attempts == [1, 1], "the existing semantic self-correction retry must still fire"


async def test_writing_step_still_rejects_empty_narration_per_scene(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())

    async def call(rendered, s):
        n = _requested_scene(rendered)
        narration = "" if n == 2 else f"narr {n}."
        return f"scenes:\n  - scene_num: {n}\n    narration: '{narration}'\n    location: chamber\n    color_palette: grey\n    atmosphere: tense\n", {}, "stop"

    with pytest.raises(ValueError, match=r"scene\[2\] has empty narration"):
        await chain.writing_step("SCP-173", _structure(3), "desc", "guide", "", None, call)


async def test_writing_step_rerolls_only_the_truncated_scene(monkeypatch, tmp_path):
    """Story 6.9's fallback, extended to the initial writing generation: a
    truncated scene costs one small re-call, not the run."""
    monkeypatch.chdir(tmp_path)  # the truncation dump lands under cwd/tmp
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())
    attempts = {}

    async def call(rendered, s):
        n = _requested_scene(rendered)
        attempts[n] = attempts.get(n, 0) + 1
        if n == 2 and attempts[n] == 1:
            return "scenes:\n  - narration: runaway", {"completion_tokens": 32768}, "length"
        return f"scenes:\n  - scene_num: 1\n    narration: narr {n}.\n    location: chamber\n    color_palette: grey\n    atmosphere: tense\n", {}, "stop"

    result = await chain.writing_step("SCP-173", _structure(3), "desc", "guide", "", None, call)
    assert attempts == {1: 1, 2: 2, 3: 1}
    assert [s["narration"] for s in result["scenes"]] == ["narr 1.", "narr 2.", "narr 3."]
    assert [s["scene_num"] for s in result["scenes"]] == [1, 2, 3]


async def test_writing_step_propagates_a_second_truncation(monkeypatch, tmp_path):
    """Recovery stays one re-roll: truncation is variance, and a scene that
    truncates twice is a real capacity shortfall that must fail loudly."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())

    async def call(rendered, s):
        return "runaway", {"completion_tokens": 32768}, "length"

    with pytest.raises(chain.TruncationError):
        await chain.writing_step("SCP-173", _structure(2), "desc", "guide", "", None, call)


def _truncatable_stages():
    """(stage, valid payload, invoker) for EVERY scenario stage that issues a
    DeepSeek call. The re-roll is wired once in `_call_stage_with_retry`, so this
    is the list of stages that must inherit it — `scenario/cast_decision` is the
    one live run ce0a455a died at (already per-scene, so batching was never the
    gap). `scenario/writing` is covered by the per-scene tests above.
    """
    scene = {"scene_num": 1, "location": "site19", "color_palette": "cold",
             "atmosphere": "dread", "characters_present": [], "narration": "문장 하나."}
    writing = {"scp_id": "SCP-173", "scenes": [{"scene_num": 1, "narration": "문장 하나."}]}
    return [
        ("research", "frozen_descriptor: desc\n" + _ARCHETYPE_YAML,
         lambda call: chain.research_step("SCP-173", "text", "guide", None, call)),
        # the re-rolled structure payload must satisfy the retention contract, or
        # the stage fails after the successful re-roll for an unrelated reason
        ("structure", _retention_yaml(4),
         lambda call: chain.structure_step("SCP-173", "", {"frozen_descriptor": "desc"}, "guide", None, call)),
        ("cast_decision", "shots:\n  - sentence: 1\n    cast: []\n",
         lambda call: chain.cast_decision_step("SCP-173", scene, ["문장 하나."], None, call)),
        ("visual_breakdown", "visual_descriptions:\n  - sentence_start: 1\n    image_prompt: p\n",
         lambda call: chain.visual_breakdown_step(
             "SCP-173", scene, ["문장 하나."], {1: []}, "desc", "sheet", "log", scene, None, call)),
        ("review", "overall_pass: true\n",
         lambda call: chain.review_step("text", writing, {}, "desc", "guide", None, call)),
        ("critic_agent", "verdict: pass\n",
         lambda call: chain.critic_step("원문", writing, {}, "guide", None, call)),
        ("writing_scene_repair", "scenes:\n  - scene_num: 1\n    narration: 고친 문장.\n",
         lambda call: chain.writing_scene_repair_step(
             "SCP-173", writing["scenes"], _repair_structure(writing["scenes"]), "feedback", "desc", "guide",
             None, call)),
        ("tts_normalize", "scenes:\n  - scene_num: 1\n    narration: 읽는 문장.\n",
         lambda call: chain.tts_normalize_step(writing, "guide", None, call)),
    ]


@pytest.mark.parametrize(
    "payload,invoke",
    [(payload, invoke) for _, payload, invoke in _truncatable_stages()],
    ids=[name for name, _, _ in _truncatable_stages()],
)
async def test_every_stage_rerolls_once_on_truncation(monkeypatch, tmp_path, payload, invoke):
    """Truncation is stochastic reasoning-token exhaustion, so recovery must be a
    property of the whole chain, not of whichever stage last blew up in a live run."""
    monkeypatch.chdir(tmp_path)  # the truncation dump lands under cwd/tmp
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    attempts = {"n": 0}

    async def call(rendered, s):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return "runaway", {"completion_tokens": 32768}, "length"
        return payload, {}, "stop"

    await invoke(call)
    assert attempts["n"] == 2, "one truncation, one re-roll"


async def test_cast_decision_propagates_a_second_truncation(monkeypatch, tmp_path):
    """The stage live run ce0a455a died at: it re-rolls once, and a second
    truncation is a real shortfall that must still fail the run loudly."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    attempts = {"n": 0}

    async def call(rendered, s):
        attempts["n"] += 1
        return "runaway", {"completion_tokens": 32768}, "length"

    with pytest.raises(chain.TruncationError):
        await chain.cast_decision_step("SCP-173", {"characters_present": []}, ["문장 하나."], None, call)
    assert attempts["n"] == 2, "recovery is exactly one re-roll, not a retry loop"


async def test_structure_and_writing_are_not_double_rerolled(monkeypatch, tmp_path):
    """Both carried their own re-roll wrapper before it moved into
    `_call_stage_with_retry` — a leftover wrapper would show up as 4 attempts."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    attempts = {"n": 0}

    async def call(rendered, s):
        attempts["n"] += 1
        return "runaway", {"completion_tokens": 32768}, "length"

    with pytest.raises(chain.TruncationError):
        await chain.structure_step("SCP-173", "", {"frozen_descriptor": "desc"}, "guide", None, call)
    assert attempts["n"] == 2

    attempts["n"] = 0
    with pytest.raises(chain.TruncationError):
        await chain.writing_step("SCP-173", _structure(1), "desc", "guide", "", None, call)
    assert attempts["n"] == 2


async def test_a_non_truncation_stage_failure_never_rerolls(monkeypatch, tmp_path):
    """Only truncation re-rolls. A semantic failure keeps its existing single
    self-correcting retry (2 calls), not a re-roll on top of it (4)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    attempts = {"n": 0}

    async def call(rendered, s):
        attempts["n"] += 1
        return "shots: []\n", {}, "stop"  # wrong sentence count → ValueError, forever

    with pytest.raises(ValueError):
        await chain.cast_decision_step("SCP-173", {"characters_present": []}, ["문장 하나."], None, call)
    assert attempts["n"] == 2, "the pre-existing semantic retry, and nothing more"


async def test_reroll_on_truncation_reraises_a_non_truncation_error():
    async def call():
        raise ValueError("semantic")

    with pytest.raises(ValueError, match="semantic"):
        await chain.reroll_on_truncation("structure", call)


async def test_truncation_dump_records_the_raw_response(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    async def call(rendered, s):
        return "scenes:\n  - narration: 잘린 응답", {"completion_tokens": 16384}, "length"

    with pytest.raises(chain.TruncationError):
        await chain._call_stage("scenario/structure", {}, None, call)

    dump = next((tmp_path / "tmp" / "truncations").glob("scenario_structure-*.txt"))
    text = dump.read_text(encoding="utf-8")
    assert "잘린 응답" in text
    assert "completion_tokens=16384" in text


async def test_truncation_dump_is_never_zero_bytes(monkeypatch, tmp_path):
    """Every dump from the 2026-08-05 runs was 0 bytes while the log claimed
    "full runaway raw -> <path>" — the evidence was destroyed on every failure
    and an empty response was indistinguishable from a failed capture."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    async def call(rendered, s):
        return "", {"completion_tokens": 32768}, "length"

    with pytest.raises(chain.TruncationError):
        await chain._call_stage("scenario/structure", {}, None, call)

    dump = next((tmp_path / "tmp" / "truncations").glob("scenario_structure-*.txt"))
    assert dump.stat().st_size > 0
    assert "raw_chars=0" in dump.read_text(encoding="utf-8")


async def test_writing_scene_repair_requires_exact_ordered_coverage(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    originals = [
        {"scene_num": 2, "narration": "old 2"},
        {"scene_num": 4, "narration": "old 4"},
    ]

    async def call(rendered, s):
        return "scenes:\n  - scene_num: 2\n    narration: fixed\n", {}, "stop"

    with pytest.raises(chain.SceneCoverageError, match="expected 2 scenes"):
        await chain.writing_scene_repair_step("SCP-173", originals, _repair_structure(originals), "feedback", "desc", "guide", None, call)


async def test_writing_scene_repair_reorders_permutation_to_expected(monkeypatch):
    # Story 6.10: the observed SCP-049 habit is the model returning the requested
    # scenes in a different order (sorted by scene_num). That is the same scene
    # set, so it recovers by reordering to the requested positional order — it is
    # NOT a coverage failure and must not raise.
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    originals = [{"scene_num": 4, "narration": "old 4"}, {"scene_num": 2, "narration": "old 2"}]

    async def call(rendered, s):
        return "scenes:\n  - scene_num: 2\n    narration: fixed 2\n  - scene_num: 4\n    narration: fixed 4\n", {}, "stop"

    result = await chain.writing_scene_repair_step("SCP-173", originals, _repair_structure(originals), "feedback", "desc", "guide", None, call)
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
        await chain.writing_scene_repair_step("SCP-173", originals, _repair_structure(originals), "feedback", "desc", "guide", None, call)


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
        await chain.writing_scene_repair_step("SCP-173", originals, _repair_structure(originals), "feedback", "desc", "guide", None, call)


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
            "archetype_rationale: |\n  첫 줄.\n  둘째 줄.\n"
            'story_archetype: "incident_first"\n'
        )
        return raw, {}, "stop"

    result = await chain.research_step("SCP-173", "text", "guide", None, call)
    for key in ("core_identity", "frozen_descriptor", "entity_sheet", "story_logline", "hooks",
                "archetype_rationale"):  # Story 12.4 — same block-literal habit, same collapse
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


# ── Story 10.4: the ordered cover replaces the 1:1 bijection ────────────────
#
# A sentence with nothing to draw ("이게 SCP 재단입니다") used to be FORCED to own a
# frame, and the model invented an unrelated one — 2 of the 4 worst-scoring shots of
# the measured baseline. A shot may now span consecutive sentences and consecutive
# shots may split one; what is still absolute is that every sentence is covered and
# the ranges never move backwards, because subtitles and cuts are derived from them.


_SCENE = {"scene_num": 1, "location": "x", "atmosphere": "y", "color_palette": "z",
          "characters_present": []}


def _breakdown_call(*ranges, prompt="x"):
    """A visual_breakdown reply whose shots cover ``(start, end)`` pairs."""
    async def call(rendered, s):
        return json.dumps({"scene_num": 1, "visual_descriptions": [
            {"image_prompt": prompt, "negative_prompt": "n", "camera_type": "wide",
             "sentence_start": start, "sentence_end": end} for start, end in ranges
        ]}), {}, "stop"
    return call


async def _breakdown(monkeypatch, call, sentences, cast_by_sentence=None):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    return await chain.visual_breakdown_step(
        "SCP-173", _SCENE, sentences, cast_by_sentence or {}, "desc", "entity sheet",
        "logline", {}, None, call,
    )


async def test_visual_breakdown_accepts_a_shot_spanning_several_sentences(monkeypatch):
    """The merge that is the whole point of 10.4: three sentences, two frames."""
    result = await _breakdown(monkeypatch, _breakdown_call((1, 2), (3, 3)), ["일.", "이.", "삼."])

    assert [(s["sentence_start"], s["sentence_end"]) for s in result] == [(1, 2), (3, 3)]


async def test_visual_breakdown_accepts_two_shots_splitting_one_sentence(monkeypatch):
    """One sentence carrying two beats may own two frames — paid for by a merge, since
    the shot count may never exceed the sentence count."""
    result = await _breakdown(monkeypatch, _breakdown_call((1, 2), (3, 3), (3, 3)),
                              ["일.", "이.", "삼."])

    assert [(s["sentence_start"], s["sentence_end"]) for s in result] == [(1, 2), (3, 3), (3, 3)]


async def test_visual_breakdown_rejects_an_uncovered_sentence_and_names_it(monkeypatch):
    """A gap is a parse failure, not a warning — subtitles and cuts are derived from
    this cover, so a dropped sentence would silently lose its screen time."""
    with pytest.raises(ValueError, match=r"sentences \[2\] are covered by no shot"):
        await _breakdown(monkeypatch, _breakdown_call((1, 1), (3, 3)), ["일.", "이.", "삼."])


async def test_visual_breakdown_rejects_an_inverted_range(monkeypatch):
    with pytest.raises(ValueError, match="inverted or outside"):
        await _breakdown(monkeypatch, _breakdown_call((3, 1)), ["일.", "이.", "삼."])


async def test_visual_breakdown_rejects_a_range_outside_the_sentence_count(monkeypatch):
    with pytest.raises(ValueError, match="inverted or outside"):
        await _breakdown(monkeypatch, _breakdown_call((1, 1), (2, 9)), ["일.", "이."])


async def test_visual_breakdown_rejects_ranges_that_move_backwards(monkeypatch):
    """Every sentence is still covered here — the cover is nonetheless invalid, because
    an out-of-order shot list would cut the video backwards through the narration."""
    with pytest.raises(ValueError, match="moves backwards"):
        await _breakdown(monkeypatch, _breakdown_call((2, 3), (1, 1), (2, 3)),
                         ["일.", "이.", "삼."])


async def test_visual_breakdown_rejects_more_shots_than_sentences(monkeypatch):
    """The stated bound: an ordered cover with no ceiling lets one scene order 40
    renders. Splits are paid for out of merges, never minted."""
    with pytest.raises(ValueError, match="may never emit more shots than sentences"):
        await _breakdown(monkeypatch, _breakdown_call((1, 1), (1, 1), (2, 2)), ["일.", "이."])


async def test_visual_breakdown_rejects_an_empty_shot_list(monkeypatch):
    async def call(rendered, s):
        return json.dumps({"scene_num": 1, "visual_descriptions": []}), {}, "stop"

    with pytest.raises(ValueError, match="non-empty visual_descriptions"):
        await _breakdown(monkeypatch, call, ["일."])


@pytest.mark.parametrize("omit", [True, False],
                         ids=["sentence_end absent", "sentence_end null"])
async def test_visual_breakdown_treats_a_missing_sentence_end_as_a_single_sentence(
        monkeypatch, omit):
    """The pre-cover shape stays valid: ``sentence_end`` may simply be absent, and an
    explicit YAML ``null`` is the same statement — neither may cost the stage its one
    corrective retry."""
    async def call(rendered, s):
        extra = {} if omit else {"sentence_end": None}
        return json.dumps({"scene_num": 1, "visual_descriptions": [
            {"image_prompt": "x", "negative_prompt": "n", "sentence_start": 1,
             "camera_type": "wide", **extra},
            {"image_prompt": "y", "negative_prompt": "n", "sentence_start": 2,
             "camera_type": "medium", **extra},
        ]}), {}, "stop"

    result = await _breakdown(monkeypatch, call, ["일.", "이."])

    assert [s["sentence_end"] for s in result] == [1, 2]


async def test_visual_breakdown_rejects_a_non_int_sentence_end(monkeypatch):
    async def call(rendered, s):
        return json.dumps({"scene_num": 1, "visual_descriptions": [
            {"image_prompt": "x", "negative_prompt": "n", "sentence_start": 1,
             "sentence_end": "2", "camera_type": "wide"},
        ]}), {}, "stop"

    with pytest.raises(ValueError, match="invalid sentence_end"):
        await _breakdown(monkeypatch, call, ["일.", "이."])


async def test_an_uncovered_sentence_is_fed_back_to_the_model_via_parse_error(monkeypatch):
    """The cover errors are worded for a reader, because a reader gets them: the stage's
    one corrective retry re-renders the SAME prompt with the failure in ``parse_error``.
    A message that only said "invalid" would waste that retry."""
    seen: list[dict] = []

    class CapturingPrompt:
        def compile(self, **variables):
            seen.append(variables)
            return "rendered"

    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt",
                        lambda *a, **k: CapturingPrompt())

    async def call(rendered, s):
        ranges = [(1, 1), (3, 3)] if len(seen) == 1 else [(1, 2), (3, 3)]
        return json.dumps({"scene_num": 1, "visual_descriptions": [
            {"image_prompt": "x", "negative_prompt": "n", "camera_type": "wide",
             "sentence_start": a, "sentence_end": b} for a, b in ranges]}), {}, "stop"

    result = await chain.visual_breakdown_step(
        "SCP-173", _SCENE, ["일.", "이.", "삼."], {}, "desc", "entity sheet", "logline",
        {}, None, call)

    assert len(seen) == 2, "the cover failure must spend the stage's corrective retry"
    assert seen[0]["parse_error"] == ""
    assert "sentences [2] are covered by no shot" in seen[1]["parse_error"]
    assert [(s["sentence_start"], s["sentence_end"]) for s in result] == [(1, 2), (3, 3)]


async def test_a_spanning_shot_takes_the_union_of_its_sentences_cast(monkeypatch):
    """A merge must never drop whoever was in frame in the sentences it swallowed —
    dedup by card_key, and the FIRST occurrence's position/depth is the one staged."""
    cast = {
        1: [{"card_key": "SCP-049", "position": "left", "depth": "far", "pose": "standing"}],
        2: [{"card_key": "SCP-049", "position": "right", "depth": "near", "pose": "standing"},
            {"card_key": "STOCK-d-class", "position": "center", "depth": "mid", "pose": "sitting"}],
        3: [],
    }

    result = await _breakdown(monkeypatch, _breakdown_call((1, 2), (3, 3)),
                              ["일.", "이.", "삼."], cast)

    assert [c["card_key"] for c in result[0]["cast"]] == ["SCP-049", "STOCK-d-class"]
    assert result[0]["cast"][0]["position"] == "left"  # sentence 1's staging, not sentence 2's
    assert result[1]["cast"] == []


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


@pytest.mark.parametrize(
    "scene_extra",
    [
        {},
        {"location": ""},
        {"color_palette": ""},
        {"atmosphere": ""},
        {"location": "", "color_palette": "", "atmosphere": ""},
    ],
)
async def test_visual_breakdown_step_survives_a_scene_with_no_visual_fields(monkeypatch, scene_extra):
    """Live run cd2f1fb8 (SCP-999) died here on a bare KeyError. The stage must
    degrade to the SAME fallbacks `_fallback_prompt` already uses, not crash."""
    class CapturingPrompt:
        kwargs: dict = {}

        def compile(self, **kwargs):
            CapturingPrompt.kwargs = kwargs
            return "rendered"

    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: CapturingPrompt()
    )

    async def call(rendered, s):
        payload = {"scene_num": 1, "visual_descriptions": [
            {"image_prompt": "x", "negative_prompt": "x", "sentence_start": 1, "sentence_end": 1, "camera_type": "wide"}
        ]}
        return json.dumps(payload), {}, "stop"

    scene = {"scene_num": 1, "atmosphere": "y", "color_palette": "z", "characters_present": [], **scene_extra}
    result = await chain.visual_breakdown_step(
        "SCP-173", scene, ["문장1."], {1: []}, "desc", "entity sheet", "logline", {}, None, call,
    )
    fallbacks = {
        "location": chain._DEFAULT_LOCATION,
        "color_palette": chain._DEFAULT_COLOR_PALETTE,
        "atmosphere": chain._DEFAULT_ATMOSPHERE,
    }
    assert len(result) == 1
    for field, fallback in fallbacks.items():
        assert CapturingPrompt.kwargs[field] == (scene.get(field) or fallback)
    # the same constants the lenient sibling site already degrades to
    assert chain._DEFAULT_LOCATION in chain._fallback_prompt(scene)
    assert (scene.get("atmosphere") or chain._DEFAULT_ATMOSPHERE) in chain._fallback_prompt(scene)


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
        await chain.review_step("t", _ONE_SCENE, {}, "desc", "guide", None, call)


async def test_review_step_retries_non_boolean_overall_pass(monkeypatch):
    prompt = _CapturingPrompt()
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: prompt)
    responses = iter(["overall_pass: 'false'", "overall_pass: false"])

    async def call(rendered, s):
        return next(responses), {}, "stop"

    result = await chain.review_step("t", _ONE_SCENE, {}, "desc", "guide", None, call)
    assert result["overall_pass"] is False
    assert len(prompt.calls) == 2


async def test_critic_step_returns_verdict(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    call = _deepseek_from_cassette("deepseek_critic.json")
    writing = {"scenes": [{"scene_num": 1, "narration": "n"}]}
    result = await chain.critic_step("원문", writing, {1: []}, "guide", None, call)
    assert result["verdict"] == "pass"
    assert result["feedback"]


async def test_critic_step_collapses_embedded_newlines_in_feedback(monkeypatch):
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )

    async def call(rendered, s):
        return 'verdict: pass\nfeedback: |\n  첫 줄.\n  둘째 줄.\nscene_notes: []\n', {}, "stop"

    writing = {"scenes": [{"scene_num": 1, "narration": "n"}]}
    result = await chain.critic_step("원문", writing, {1: []}, "guide", None, call)
    assert result["feedback"] == "Scene 1: 첫 줄. 둘째 줄."


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

    result = await chain.review_step("t", _ONE_SCENE, {}, "desc", "guide", None, call)

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

    result = await chain.critic_step("원문", _ONE_SCENE, {}, "guide", None, call)

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
        await chain.critic_step("원문", _ONE_SCENE, {}, "guide", None, call)


# --- review/critic per-scene batching (live run 370666ba truncation) ------------

def _writing(count):
    return {
        "scp_id": "SCP-999",
        "scenes": [{"scene_num": i + 1, "narration": f"장면 {i + 1} 문장."} for i in range(count)],
    }


def _scene_num_of(rendered):
    """The 1-based scene the steering prefix claims this call is reviewing."""
    return int(re.search(r"SCENE (\d+) OF", rendered).group(1))


class _SceneAwarePrompt:
    """Renders the compiled variables so the fake DeepSeek can tell scenes apart."""

    def __init__(self):
        self.calls = []

    def compile(self, **variables):
        self.calls.append(variables)
        return json.dumps(variables, ensure_ascii=False)


async def test_review_step_calls_once_per_scene(monkeypatch):
    prompt = _SceneAwarePrompt()
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: prompt)

    async def call(rendered, s):
        return "overall_pass: true\n", {}, "stop"

    result = await chain.review_step("facts", _writing(4), {}, "desc", "guide", None, call)

    assert len(prompt.calls) == 4
    assert sorted(_scene_num_of(c["narration_script"]) for c in prompt.calls) == [1, 2, 3, 4]
    # Each call carries exactly its own scene, never the whole script.
    for c in prompt.calls:
        payload = json.loads(c["narration_script"].split("\n", 1)[1])
        assert [s["scene_num"] for s in payload["scenes"]] == [_scene_num_of(c["narration_script"])]
    assert result["overall_pass"] is True


async def test_review_step_overall_pass_is_and_across_scenes(monkeypatch):
    prompt = _SceneAwarePrompt()
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: prompt)

    async def call(rendered, s):
        passed = _scene_num_of(json.loads(rendered)["narration_script"]) != 2
        return f"overall_pass: {str(passed).lower()}\n", {}, "stop"

    result = await chain.review_step("facts", _writing(3), {}, "desc", "guide", None, call)
    assert result["overall_pass"] is False


async def test_review_step_aggregates_scene_indexed_issues_out_of_order(monkeypatch):
    """Scene 3 answers first and every scene reports `scene_num: 1` — the position,
    not the model, must decide the aggregated scene_num."""
    prompt = _SceneAwarePrompt()
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: prompt)

    async def call(rendered, s):
        num = _scene_num_of(json.loads(rendered)["narration_script"])
        await asyncio.sleep((3 - num) * 0.01)  # scene 3 completes first
        return (
            "overall_pass: false\ncoverage_pct: {}\nstorytelling_score: {}\n"
            "issues:\n  - scene_num: 1\n    description: 문제 {}\n    correction: 수정 {}\n"
            "corrections:\n  - scene_num: 1\n    original: 원 {}\n    corrected: 정 {}\n"
            "storytelling_issues:\n  - scene_num: 1\n    description: 이야기 {}\n"
        ).format(num * 10, num * 20, num, num, num, num, num), {}, "stop"

    result = await chain.review_step("facts", _writing(3), {}, "desc", "guide", None, call)

    assert [(i["scene_num"], i["description"]) for i in result["issues"]] == [
        (1, "문제 1"), (2, "문제 2"), (3, "문제 3"),
    ]
    assert [(c["scene_num"], c["original"]) for c in result["corrections"]] == [
        (1, "원 1"), (2, "원 2"), (3, "원 3"),
    ]
    assert [i["scene_num"] for i in result["storytelling_issues"]] == [1, 2, 3]
    assert result["coverage_pct"] == 30.0  # max — a fact covered anywhere counts once
    assert result["storytelling_score"] == 40.0  # mean of 20/40/60


@pytest.mark.parametrize(
    "verdicts,expected",
    [
        (["pass", "pass"], "pass"),
        (["pass", "accept_with_notes"], "accept_with_notes"),
        (["accept_with_notes", "retry"], "retry"),
        (["retry", "pass", "pass"], "retry"),
    ],
)
async def test_critic_step_aggregates_worst_verdict(monkeypatch, verdicts, expected):
    prompt = _SceneAwarePrompt()
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: prompt)

    async def call(rendered, s):
        num = _scene_num_of(json.loads(rendered)["scenario_json"])
        return f"verdict: {verdicts[num - 1]}\nfeedback: 의견 {num}\nscene_notes: []\n", {}, "stop"

    result = await chain.critic_step("원문", _writing(len(verdicts)), {}, "guide", None, call)

    assert len(prompt.calls) == len(verdicts)
    assert result["verdict"] == expected
    assert result["feedback"] == "\n".join(f"Scene {i + 1}: 의견 {i + 1}" for i in range(len(verdicts)))


async def test_critic_step_stamps_scene_notes_by_position(monkeypatch):
    prompt = _SceneAwarePrompt()
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: prompt)

    async def call(rendered, s):
        num = _scene_num_of(json.loads(rendered)["scenario_json"])
        await asyncio.sleep((3 - num) * 0.01)
        return (
            f"verdict: retry\nfeedback: f{num}\n"
            f"scene_notes:\n  - scene_num: 1\n    issue: 문제 {num}\n    suggestion: 제안 {num}\n"
        ), {}, "stop"

    result = await chain.critic_step("원문", _writing(3), {}, "guide", None, call)
    assert [(n["scene_num"], n["issue"]) for n in result["scene_notes"]] == [
        (1, "문제 1"), (2, "문제 2"), (3, "문제 3"),
    ]


async def test_aggregated_reports_feed_retry_scope_and_feedback():
    """The aggregated shape must still drive the REAL repair-loop consumers."""
    from yt_flow.pipeline.nodes import scenario

    reports = [
        {"overall_pass": False, "coverage_pct": 40.0, "storytelling_score": 60,
         "issues": [{"scene_num": 1, "description": f"d{n}", "correction": f"c{n}"}]}
        for n in (1, 2, 3)
    ]
    review = chain._aggregate_review(reports)
    critic = chain._aggregate_critic([
        {"verdict": "pass", "feedback": "좋다", "scene_notes": []},
        {"verdict": "retry", "feedback": "고쳐라", "scene_notes": [{"scene_num": 1, "issue": "x"}]},
        {"verdict": "pass", "feedback": "", "scene_notes": []},
    ])
    scenes = _writing(3)["scenes"]

    indexes, rejected = scenario._retry_scope(review, critic, scenes)
    assert indexes == [0, 1, 2]  # review scenes 1-3, critic scene 2 dedupes
    assert [r["reason"] for r in rejected] == ["duplicate"]

    feedback = scenario._format_feedback(review, critic)
    assert feedback.splitlines() == [
        "Scene 1: 좋다",
        "Scene 2: 고쳐라",
        "- Scene 1: d1 -> c1",
        "- Scene 2: d2 -> c2",
        "- Scene 3: d3 -> c3",
    ]
    # The critic note reaches scene 2's repair brief. (Its text is empty because
    # `_format_scene_feedback` reads feedback/note/description while the critic
    # prompt emits issue/suggestion — a pre-existing gap, unchanged by batching.)
    assert scenario._format_scene_feedback(review, critic, [1]).splitlines() == [
        "Review scene 2: d2 -> c2",
        "Critic scene 2: ",
    ]


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


def test_parse_yaml_strips_fence_preceded_by_prose():
    """Live run 64b6d9a8 (scenario/visual_breakdown): the model emitted a
    markdown heading first, so the fence opened on line 3 and ``re.match``
    stripped nothing — the backticks reached safe_load."""
    raw = "# Scene 7 — YAML Output\n\n```yaml\nscene_num: 7\n```\n\nDone."
    assert chain._parse_yaml(raw) == {"scene_num": 7}


def test_parse_yaml_takes_first_fenced_block():
    assert chain._parse_yaml("intro\n```yaml\nkey: a\n```\nmore\n```yaml\nkey: b\n```") == {"key": "a"}


def test_parse_yaml_strips_bare_fence_after_prose():
    assert chain._parse_yaml("here you go:\n```\nkey: value\n```") == {"key": "value"}


def test_parse_yaml_unterminated_fence_takes_the_remainder():
    assert chain._parse_yaml("blah\n```yaml\nkey: value") == {"key": "value"}


def test_yaml_text_without_fence_is_only_stripped():
    raw = "  key: value\nother: 1  "
    assert chain._yaml_text(raw) == "key: value\nother: 1"


def test_repair_alignment_holds_for_fence_after_prose():
    """Story 6.11 contract: ``problem_mark.line`` indexes the de-fenced text the
    repair rewrites. With prose before the fence the two must still agree —
    they do because both go through ``_yaml_text``."""
    broken = (
        "# Scene 7 — YAML Output\n\n"
        "```yaml\n"
        "scenes:\n"
        "  - scene_num: 1\n"
        "    narration: 박사가 말했다: 위험해\n"
        "```\n"
    )
    data = _repair(broken)
    assert data["scenes"][0]["narration"] == "박사가 말했다: 위험해"
    assert data["scenes"][0]["scene_num"] == 1  # sibling untouched, not shifted by the prose


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
    """A YAML-syntax failure the deterministic normalizer can't repair gets the
    ONE generic corrective retry; a second unparseable response propagates after
    exactly 2 model calls — bounded, no third attempt."""
    stage_prompt = _CapturingPrompt()
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: stage_prompt)
    call_count = 0

    async def call(rendered, s):
        nonlocal call_count
        call_count += 1
        return "key: [unterminated", {}, "stop"

    with pytest.raises(yaml.YAMLError):
        await chain._call_stage_with_retry("scenario/research", {}, None, call, chain._parse_yaml)
    assert call_count == 2  # one corrective retry, then it fails loudly
    assert "not valid YAML" in stage_prompt.calls[1]["parse_error"]


async def test_call_stage_with_retry_recovers_from_a_conversational_reply(monkeypatch, tmp_path):
    """Live run 23ce9a6a (SCP-999): ``scenario/visual_breakdown`` answered with
    prose about an invented ``1_0|260|640|760`` marker (finish_reason=stop, so
    NOT truncation). No line is block-ifiable, so the deterministic repair can't
    help — the error must be fed back for one corrective call instead of killing
    the run."""
    monkeypatch.chdir(tmp_path)  # the unfixed-raw dump lands under cwd/tmp
    stage_prompt = _CapturingPrompt()
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: stage_prompt)
    chatty = (
        "Noted—I see them now as interstitials rather than hallucinations. My earlier parse "
        "didn’t include any, so this is genuinely new textual structure: `1_0|260|640|760`. "
        "They read like timestamped step markers or scene transitions, and I’m treating them "
        "as part of the artifact’s content rather than as commands. Happy to log their "
        "placement and help track whether they’re consistent going forward."
    )
    responses = iter([chatty, "shots: []\n"])
    call_count = 0

    async def call(rendered, s):
        nonlocal call_count
        call_count += 1
        return next(responses), {}, "stop"

    result = await chain._call_stage_with_retry(
        "scenario/visual_breakdown", {"a": "b"}, None, call, chain._parse_yaml
    )

    assert result == {"shots": []}
    assert call_count == 2
    feedback = stage_prompt.calls[1]["parse_error"]
    assert "not valid YAML" in feedback
    assert "no prose" in feedback and "no markdown code fences" in feedback
    assert stage_prompt.calls[1]["a"] == "b"  # original variables preserved


async def test_call_stage_with_retry_truncation_short_circuits_ahead_of_the_syntax_path(
    monkeypatch, tmp_path
):
    """A truncated completion is never a syntax failure: it raises before any
    parse, so it reaches the re-roll (2 calls) — not the corrective retry, and
    no unfixed-YAML dump."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    call_count = 0

    async def call(rendered, s):
        nonlocal call_count
        call_count += 1
        return "shots:\n  - id: 1_0|260", {"completion_tokens": 16384}, "length"

    with pytest.raises(chain.TruncationError):
        await chain._call_stage_with_retry("scenario/visual_breakdown", {}, None, call, chain._parse_yaml)
    assert call_count == 2, "one re-roll, no corrective retry stacked on top"
    assert not (tmp_path / "tmp" / "yaml-failures").exists()


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
        payload = {"frozen_descriptor": "desc", **_ARCHETYPE_FIELDS}
        return yaml.dump(payload, allow_unicode=True), {"prompt_tokens": 7, "completion_tokens": 4}, "stop"

    usage_sink: list[dict] = []
    await chain.research_step("SCP-173", "text", "guide", None, call, usage_sink=usage_sink)
    assert usage_sink == [{"prompt_tokens": 7, "completion_tokens": 4}]


async def test_research_step_usage_sink_defaults_to_none_without_error(monkeypatch):
    """Existing callers that don't pass usage_sink keep working (Task 2's additive-only requirement)."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())

    async def call(rendered, s):
        payload = {"frozen_descriptor": "desc", **_ARCHETYPE_FIELDS}
        return yaml.dump(payload, allow_unicode=True), {"prompt_tokens": 7}, "stop"

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
            "dramatic_beats: x\nenvironment: x\nhooks: x\n" + _ARCHETYPE_YAML,
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
    # The cassette carries ONE scene: tts_normalize is batched per scene, so a
    # single call's response is one scene's normalization (like deepseek_writing.json).
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
            },
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
        return "scenes:\n  - scene_num: 1\n    narration: |\n      첫 문장.\n      둘째 문장.\n    location: chamber\n    color_palette: grey\n    atmosphere: tense\n", {}, "stop"

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


# ── tts_normalize_step per-scene batching (2026-08-06, live run bad091eb) ──────


def _tts_writing(n: int) -> dict:
    return {"scp_id": "SCP-999", "scenes": [{"scene_num": i + 1, "narration": f"원본 {i + 1}."} for i in range(n)]}


async def test_tts_normalize_step_makes_one_call_per_scene(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())
    calls = []

    async def call(rendered, s):
        n = _requested_scene(rendered)
        calls.append(n)
        # one scene's payload per call — the whole point of the batching
        return f"scenes:\n  - scene_num: {n}\n    narration: 정규화 {n}.\n", {}, "stop"

    result = await chain.tts_normalize_step(_tts_writing(8), "guide", None, call)
    assert sorted(calls) == list(range(1, 9))
    assert len(result["scenes"]) == 8  # aggregate count == len(original_scenes)


async def test_tts_normalize_step_keeps_scene_order_when_calls_finish_out_of_order(monkeypatch):
    """The calls run concurrently, so completion order is not argument order —
    aggregation must key on position, never on arrival (the writing_step trap)."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())
    writing = _tts_writing(5)
    completed = []

    async def call(rendered, s):
        n = _requested_scene(rendered)
        await asyncio.sleep((len(writing["scenes"]) - n) * 0.01)  # the LAST scene answers first
        completed.append(n)
        # a model normalizing one scene in isolation says "1" whatever it was asked
        return json.dumps({"scenes": [{"scene_num": 1, "narration": f"정규화 {n}."}]}), {}, "stop"

    result = await chain.tts_normalize_step(writing, "guide", None, call)
    assert completed == [5, 4, 3, 2, 1], "calls did not interleave; the ordering assert below is vacuous"
    assert [scene["narration"] for scene in result["scenes"]] == [f"정규화 {n}." for n in range(1, 6)]
    # scene_num identity comes from the ORIGINAL scene, never from the model's echo
    assert [scene["scene_num"] for scene in result["scenes"]] == [1, 2, 3, 4, 5]
    assert [scene["display_narration"] for scene in result["scenes"]] == [f"원본 {n}." for n in range(1, 6)]


async def test_tts_normalize_step_rejects_one_scenes_empty_narration(monkeypatch):
    """Scene 3 comes back blank while its siblings are fine — the per-scene
    validation must still fail the stage, exactly as the whole-script parse did."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())

    async def call(rendered, s):
        n = _requested_scene(rendered)
        narration = "   " if n == 3 else f"정규화 {n}."
        return json.dumps({"scenes": [{"scene_num": n, "narration": narration}]}), {}, "stop"

    with pytest.raises(ValueError, match=r"scene\[3\] has empty narration"):
        await chain.tts_normalize_step(_tts_writing(4), "guide", None, call)


async def test_tts_normalize_step_rejects_one_malformed_scene(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())

    async def call(rendered, s):
        n = _requested_scene(rendered)
        scene = "not-a-mapping" if n == 2 else {"scene_num": n, "narration": f"정규화 {n}."}
        return json.dumps({"scenes": [scene]}), {}, "stop"

    with pytest.raises(ValueError, match="malformed scene"):
        await chain.tts_normalize_step(_tts_writing(3), "guide", None, call)


async def test_tts_normalize_step_rejects_a_multi_scene_response(monkeypatch):
    """A per-scene call answering for more than its own scene is the failure the
    old whole-script "expected N scenes, got M" guard caught, now per call."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())

    async def call(rendered, s):
        return json.dumps({"scenes": [{"scene_num": 1, "narration": "가."}, {"scene_num": 2, "narration": "나."}]}), {}, "stop"

    with pytest.raises(ValueError, match="must return exactly 1 scene, got 2"):
        await chain.tts_normalize_step(_tts_writing(2), "guide", None, call)


async def test_tts_normalize_step_falls_back_per_scene_on_sentence_count_mismatch(monkeypatch):
    # Scene 1's normalized text adds a sentence boundary -> keep original.
    # Scene 2 normalizes cleanly -> accept it. One bad scene must not fail the rest.
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())

    async def call(rendered, s):
        narration = "첫 문장. 추가된 문장." if _requested_scene(rendered) == 1 else "정규화된 둘째 문장."
        return json.dumps({"scenes": [{"scene_num": 1, "narration": narration}]}), {}, "stop"

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


def test_build_scenes_expands_a_shots_sentence_range_into_indices():
    """Story 10.4: the cover's ``sentence_start..sentence_end`` becomes the shot's whole
    ``sentence_indices`` list — no new field, the existing ``list[int]`` carries it."""
    writing = {"scenes": [{"scene_num": 1, "narration": "첫 문장. 둘째 문장. 셋째 문장."}]}
    visual_by_scene = {0: [
        {"image_prompt": "merged", "negative_prompt": "n", "sentence_start": 1, "sentence_end": 2,
         "camera_type": "wide"},
        {"image_prompt": "last", "negative_prompt": "n", "sentence_start": 3, "sentence_end": 3,
         "camera_type": "close-up"},
    ]}

    shots = chain.build_scenes(writing, visual_by_scene, [{}])[0]["shots"]

    assert [s["sentence_indices"] for s in shots] == [[0, 1], [2]]


def test_build_scenes_keeps_both_shots_when_two_split_one_sentence():
    writing = {"scenes": [{"scene_num": 1, "narration": "첫 문장. 둘째 문장."}]}
    visual_by_scene = {0: [
        {"image_prompt": "a", "negative_prompt": "n", "sentence_start": 1, "sentence_end": 1,
         "camera_type": "wide"},
        {"image_prompt": "b", "negative_prompt": "n", "sentence_start": 2, "sentence_end": 2,
         "camera_type": "medium"},
        {"image_prompt": "c", "negative_prompt": "n", "sentence_start": 2, "sentence_end": 2,
         "camera_type": "close-up"},
    ]}

    shots = chain.build_scenes(writing, visual_by_scene, [{}])[0]["shots"]

    assert [s["shot_id"] for s in shots] == ["S00100", "S00101", "S00102"]
    assert [s["sentence_indices"] for s in shots] == [[0], [1], [1]]


def test_build_scenes_merges_an_empty_prompt_range_into_the_previous_shot():
    """The empty-``image_prompt`` merge still works when the empty shot spans a range —
    the previous shot inherits every sentence it was carrying, not just its first."""
    writing = {"scenes": [{"scene_num": 1, "narration": "첫 문장. (정적) (효과음) 넷째 문장."}]}
    visual_by_scene = {0: [
        {"image_prompt": "one", "negative_prompt": "n", "sentence_start": 1, "sentence_end": 1,
         "camera_type": "wide"},
        {"image_prompt": "", "negative_prompt": "", "sentence_start": 2, "sentence_end": 3,
         "camera_type": "wide"},
        {"image_prompt": "four", "negative_prompt": "n", "sentence_start": 4, "sentence_end": 4,
         "camera_type": "close-up"},
    ]}

    shots = chain.build_scenes(writing, visual_by_scene, [{}])[0]["shots"]

    assert [s["sentence_indices"] for s in shots] == [[0, 1, 2], [3]]


def test_build_scenes_treats_a_missing_or_inverted_sentence_end_as_one_sentence():
    """A pre-cover checkpoint (no ``sentence_end`` at all) must keep building the same
    one-element ``sentence_indices`` it always did."""
    writing = {"scenes": [{"scene_num": 1, "narration": "첫 문장. 둘째 문장."}]}
    visual_by_scene = {0: [
        {"image_prompt": "a", "negative_prompt": "n", "sentence_start": 1, "camera_type": "wide"},
        {"image_prompt": "b", "negative_prompt": "n", "sentence_start": 2, "sentence_end": 1,
         "camera_type": "medium"},
    ]}

    shots = chain.build_scenes(writing, visual_by_scene, [{}])[0]["shots"]

    assert [s["sentence_indices"] for s in shots] == [[0], [1]]


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


# ── pose_guide_key (Story 8.20, AC5) ───────────────────────────────────────


def _cast_entry(**extra):
    return [{"card_key": "SCP-049", "position": "left", "depth": "near", "pose": "standing", **extra}]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("humanoid_kneeling", "humanoid_kneeling"),
        ("  HUMANOID-KNEELING ", "humanoid_kneeling"),
        ("kneeling", "humanoid_kneeling"),                 # documented operator alias
        ("creature_prone_lunge", "creature_prone_lunge"),
        ("humanoid_backflip", None),                        # outside the closed catalog
        ("kneeling over a corpse", None),                   # a pose_hint is not a guide key
        ("", None),
        (42, None),
        (["humanoid_kneeling"], None),
    ],
)
def test_parse_cast_pose_guide_key_leniency_table(raw, expected):
    member = chain.parse_cast(_cast_entry(pose_hint="kneeling over a corpse", pose_guide_key=raw))[0]
    if expected is None:
        assert "pose_guide_key" not in member
    else:
        assert member["pose_guide_key"] == expected


def test_parse_cast_drops_pose_guide_key_without_a_pose_hint(caplog):
    """A guide constrains geometry for a requested action; with no action there is
    nothing to constrain, so it is dropped rather than silently conditioning the
    base pose."""
    with caplog.at_level(logging.WARNING):
        member = chain.parse_cast(_cast_entry(pose_guide_key="humanoid_kneeling"))[0]
    assert "pose_guide_key" not in member
    assert any("no pose_hint" in r.message for r in caplog.records)


def test_parse_cast_drops_pose_guide_key_when_the_hint_itself_was_rejected():
    """An over-long hint is dropped by _parse_pose_hint; the guide must not
    survive it and condition a pose nobody requested."""
    member = chain.parse_cast(_cast_entry(pose_hint="x" * 81, pose_guide_key="humanoid_kneeling"))[0]
    assert "pose_hint" not in member
    assert "pose_guide_key" not in member


def test_parse_cast_warns_on_an_out_of_catalog_pose_guide_key(caplog):
    with caplog.at_level(logging.WARNING):
        chain.parse_cast(_cast_entry(pose_hint="doing a backflip", pose_guide_key="humanoid_backflip"))
    assert any("approved catalog" in r.message for r in caplog.records)


def test_parse_cast_absent_pose_guide_key_is_silent(caplog):
    """Absence is the normal case (most hints need no guide) — it must not warn."""
    with caplog.at_level(logging.WARNING):
        member = chain.parse_cast(_cast_entry(pose_hint="head bowed"))[0]
    assert "pose_guide_key" not in member
    assert not [r for r in caplog.records if "pose_guide_key" in r.message]


def test_pose_guide_key_does_not_disturb_existing_cast_fields():
    """AC15: pose_guide_key is additive — no existing placement/motion semantics move."""
    entry = _cast_entry(
        pose_hint="reaching toward camera", pose_guide_key="humanoid_reaching_forward",
        motion_style="pulse", motion_energy="high",
        movement_mode="approach", movement_direction="left", movement_pace="fast",
    )
    member = chain.parse_cast(entry)[0]
    assert member["pose_guide_key"] == "humanoid_reaching_forward"
    assert member["motion_style"] == "pulse"
    assert member["motion_energy"] == "high"
    assert member["movement_mode"] == "approach"
    assert member["movement_direction"] == "in"   # 8.9 repair table, unchanged
    assert member["movement_pace"] == "fast"
    assert member["pose"] == "standing"
    assert member["position"] == "left"


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


# ── camera_angle (Story 14.0: the one sibling field with no validation) ─────────
#
# AC numbering below is ``_bmad-output/implementation-artifacts/spec-14-0-angle-conflict.md``.
#
# §4-4 of the 2026-08-17 research claimed the ``image_prompt`` body overwrites this
# field. Measured false — run 4b35c0ed agrees on 43/43 shots (see
# ``_bmad-output/implementation-artifacts/14-0-angle-conflict/``). What the code read
# did surface is that ``camera_type`` was an unvalidated passthrough, so a mis-cased
# value walked past R3's case-sensitive comparisons without a sound.


def test_camera_angles_constant_matches_the_prompt_vocabulary_line():
    """The vocabulary lives in the prompt file; the constant is a copy of it.

    ``gotcha_pinned-ffmpeg-arg-string-is-not-a-test``: every other test here
    parametrizes over ``chain._CAMERA_ANGLES``, so all of them stay green if the
    prompt adds/renames a value. This is the only test that can see that drift.
    Read-only on the prompt file.
    """
    prompt_path = Path(__file__).parents[3] / "prompts" / "scenario" / "visual_breakdown.md"
    if not prompt_path.exists():  # prompts live in the repo, not the installed package
        pytest.skip(f"{prompt_path} not present")
    lines = [
        line for line in prompt_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("One of: ")
    ]
    assert len(lines) == 1, f"expected exactly one `One of:` vocabulary line, got {lines}"
    assert {v.strip() for v in lines[0].removeprefix("One of: ").split(",")} == set(chain._CAMERA_ANGLES)


@pytest.mark.parametrize("value", chain._CAMERA_ANGLES)
def test_build_scenes_camera_angle_documented_spelling_round_trips(value):
    """AC4: the 43 measured values are all documented spellings, so normalization
    must be byte-identical to no normalization on this run — no regression."""
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    scenes = chain.build_scenes(writing, _one_shot_visual(camera_type=value), [{}])
    assert scenes[0]["shots"][0]["camera_angle"] == value


@pytest.mark.parametrize(
    "raw,expected",
    [("Wide", "wide"), (" pov ", "POV"), ("Close-Up", "close-up"), ("MEDIUM", "medium")],
)
def test_build_scenes_camera_angle_miscasing_normalizes_silently(raw, expected, caplog):
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    with caplog.at_level(logging.WARNING):
        scenes = chain.build_scenes(writing, _one_shot_visual(camera_type=raw), [{"mood": "clinical"}])
    assert scenes[0]["shots"][0]["camera_angle"] == expected
    assert not caplog.records  # normalization handled it; nothing for a human to act on


@pytest.mark.parametrize("raw", ["dutch angle", "bird's eye", "extreme close-up"])
def test_build_scenes_camera_angle_off_vocabulary_drops_with_one_warning(raw, caplog):
    """resolve_mood philosophy (AD-10): the stage never fails on a vocabulary
    violation, and the violation never passes silently either."""
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    with caplog.at_level(logging.WARNING):
        scenes = chain.build_scenes(writing, _one_shot_visual(camera_type=raw), [{}])
    assert scenes[0]["shots"][0]["camera_angle"] is None
    assert len([r for r in caplog.records if raw in r.message]) == 1


@pytest.mark.parametrize("raw", [None, 3, ["wide"], ""])
def test_build_scenes_camera_angle_absent_is_silent(raw, caplog):
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    with caplog.at_level(logging.WARNING):
        scenes = chain.build_scenes(writing, _one_shot_visual(camera_type=raw), [{"mood": "clinical"}])
    assert scenes[0]["shots"][0]["camera_angle"] is None
    assert not caplog.records  # absence is model variance, not a defect


def test_build_scenes_miscased_camera_angle_now_reaches_r3():
    """AC3: ``"Over-The-Shoulder"`` used to skip R3's exact-match comparison, so a
    lone ``far`` member kept a depth the vocabulary calls a never-pairing."""
    writing = {"scenes": [{"scene_num": 1, "narration": "문장."}]}
    cast = [{"card_key": "SCP-049", "position": "center", "depth": "far", "pose": "standing"}]
    scenes = chain.build_scenes(
        writing, _one_shot_visual(camera_type="Over-The-Shoulder", cast=cast), [{}]
    )
    shot = scenes[0]["shots"][0]
    assert shot["camera_angle"] == "over-the-shoulder"
    assert shot["cast"][0]["depth"] == "mid"  # R3 fired


def test_build_scenes_fallback_prompt_shot_declares_the_angle_it_hardcodes():
    """``_fallback_prompt`` opens with "static wide shot", so the field it ships
    with must say ``wide`` — this path was the pipeline's only guaranteed
    field↔body disagreement, and it is the LLM's value that gets dropped."""
    writing = {"scenes": [{"scene_num": 1, "narration": "(정적)", "location": "vault", "atmosphere": "silence"}]}
    visual_by_scene = {0: [{"image_prompt": "", "negative_prompt": "", "sentence_start": 1,
                            "sentence_end": 1, "camera_type": "close-up"}]}
    shot = chain.build_scenes(writing, visual_by_scene, [{}])[0]["shots"][0]
    assert shot["image_prompt"].startswith("static wide shot")
    assert shot["camera_angle"] == "wide"


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


# ── Story 12.3: deterministic rule metrics (AC5) ──────────────────────────────


def test_rule_metrics_counts_non_whitespace_chars_and_sentences():
    writing = {"scenes": [{"narration": "첫 문장 입니다. 둘째 문장."}]}
    m = chain.compute_rule_metrics(writing)
    # 8 non-whitespace chars in scene 1's first sentence + 6 in the second = 14
    assert m["aggregate"]["character_count"] == len("첫문장입니다.둘째문장.")
    assert m["aggregate"]["sentence_count"] == 2
    assert m["scenes"] == [{
        "scene_num": 1, "character_count": len("첫문장입니다.둘째문장."), "sentence_count": 2,
        "duplicate_sentence_count": 0, "repeated_4gram_count": 0,
    }]


def test_rule_metrics_report_the_written_total_eojeol():
    """Story 12.6: the contract is enforced on the DECLARED outline only, and
    `writing.md` grants each scene ±20% — wider than the ±15% the total is held to —
    so an outline declaring a legal 370 can ship 296 with every gate green. This is
    the only place the written length is measured. Whitespace split, the same unit
    `word_budget` and `measure_script.py` use, so the three are comparable."""
    writing = {"scenes": [{"narration": "가 나 다."}, {"narration": "라  마."}]}
    assert chain.compute_rule_metrics(writing)["total_words"] == 5


def test_rule_metrics_total_words_is_a_measurement_not_a_gate():
    """Deliberately no failure and no warning code: this is computed AFTER every
    writing call has been paid for, so failing on it would burn a whole run."""
    starved = {"scenes": [{"narration": "짧다."}]}
    metrics = chain.compute_rule_metrics(starved)
    assert metrics["total_words"] == 1 < chain.MIN_TOTAL_WORD_BUDGET
    assert "warning" not in metrics and "code" not in metrics


def test_rule_metrics_total_words_survives_a_malformed_scene():
    assert chain.compute_rule_metrics({"scenes": [{"narration": None}, "x", {}]})["total_words"] == 0


def test_rule_metrics_scene_num_is_positional_not_model_supplied():
    writing = {"scenes": [{"scene_num": 7, "narration": "가."}, {"scene_num": 7, "narration": "나."}]}
    m = chain.compute_rule_metrics(writing)
    assert [s["scene_num"] for s in m["scenes"]] == [1, 2]


def test_rule_metrics_duplicate_sentences_ignore_nfkc_whitespace_case_and_terminal_punctuation():
    # ｇｏｏｄ (fullwidth) NFKC-folds to "good"; the trailing '!' vs '.' and the
    # doubled space must not make these three read as distinct sentences.
    writing = {"scenes": [{"narration": "It is ｇｏｏｄ. It  is good! IT IS GOOD."}]}
    m = chain.compute_rule_metrics(writing)
    assert m["aggregate"]["sentence_count"] == 3
    assert m["aggregate"]["duplicate_sentence_count"] == 2  # occurrences beyond the first


def test_rule_metrics_duplicate_detection_spans_scenes():
    writing = {"scenes": [{"narration": "같은 문장."}, {"narration": "같은 문장."}]}
    m = chain.compute_rule_metrics(writing)
    assert [s["duplicate_sentence_count"] for s in m["scenes"]] == [0, 0]  # unique within each scene
    assert m["aggregate"]["duplicate_sentence_count"] == 1  # but recycled across the script


def test_rule_metrics_4gram_threshold_is_three_occurrences():
    twice = {"scenes": [{"narration": "가 나 다 라 마. 가 나 다 라 바."}]}
    assert chain.compute_rule_metrics(twice)["aggregate"]["repeated_4gram_count"] == 0
    thrice = {"scenes": [{"narration": "가 나 다 라 마. 가 나 다 라 바. 가 나 다 라 사."}]}
    metrics = chain.compute_rule_metrics(thrice)
    assert metrics["aggregate"]["repeated_4gram_count"] == 1
    assert metrics["repeated_ngrams"] == [{"phrase": "가 나 다 라", "count": 3}]


def test_rule_metrics_4grams_never_straddle_a_scene_boundary():
    """[review fix] The aggregate pools per-scene token RUNS, not one flat token list.

    Flattened, these six 3-token scenes manufacture three 4-grams ("가 나 다. 라", …)
    that occur nowhere in the script — phantom evidence the operator is asked to act
    on at the gate. A phrase repeated WITHIN a scene must still be caught (below).
    """
    alternating = {"scenes": [{"narration": "가 나 다."}, {"narration": "라 마 바."}] * 3}
    metrics = chain.compute_rule_metrics(alternating)
    assert metrics["repeated_ngrams"] == []
    assert metrics["aggregate"]["repeated_4gram_count"] == 0

    # The cross-scene signal the pooling exists for is unaffected: a 4-gram recycled
    # between scenes still counts, because the runs are pooled (just not concatenated).
    recycled = {"scenes": [{"narration": "가 나 다 라."}] * 3}
    assert chain.compute_rule_metrics(recycled)["repeated_ngrams"] == [
        {"phrase": "가 나 다 라.", "count": 3}
    ]


def test_rule_metrics_slop_hits_are_exact_normalized_matches_with_scene_evidence():
    phrase = chain.KOREAN_SLOP_PHRASES[0]
    writing = {"scenes": [{"narration": "평범한 문장."}, {"narration": f"{phrase} 그리고 {phrase}."}]}
    m = chain.compute_rule_metrics(writing)
    assert m["slop_phrase_hits"] == [{"scene_num": 2, "phrase": phrase, "count": 2}]
    assert m["slop_vocabulary_version"] == chain.SLOP_VOCABULARY_VERSION


def test_rule_metrics_slop_vocabulary_is_small_and_versioned():
    assert 0 < len(chain.KOREAN_SLOP_PHRASES) <= 16
    assert len(set(chain.KOREAN_SLOP_PHRASES)) == len(chain.KOREAN_SLOP_PHRASES)
    assert isinstance(chain.SLOP_VOCABULARY_VERSION, int)


def test_rule_metrics_tolerates_missing_and_malformed_narration():
    writing = {"scenes": [{}, {"narration": None}, "not-a-dict"]}
    m = chain.compute_rule_metrics(writing)
    assert m["aggregate"] == {
        "character_count": 0, "sentence_count": 0,
        "duplicate_sentence_count": 0, "repeated_4gram_count": 0,
    }
    assert len(m["scenes"]) == 3


def test_rule_metrics_empty_writing_is_all_zero():
    m = chain.compute_rule_metrics({})
    assert m["scenes"] == []
    assert m["aggregate"]["sentence_count"] == 0
    assert m["repeated_ngrams"] == []
    assert m["slop_phrase_hits"] == []


# ── Story 12.3: grounded contradictions in review (AC4) ───────────────────────


def _contradiction(**over) -> dict:
    base = {
        "scene_num": 1,
        "narration_quote": "개체는 파란 눈을 가지고 있습니다",
        "grounding_source": "entity_sheet",
        "grounding_quote": "눈은 검은색이다",
        "explanation": "눈 색이 접지 자료와 반대다",
        "correction": "개체는 검은 눈을 가지고 있습니다",
    }
    base.update(over)
    return base


def _review_yaml(**over) -> str:
    payload = {"overall_pass": True, "issues": [], "corrections": [], "storytelling_issues": []}
    payload.update(over)
    return yaml.safe_dump(payload, allow_unicode=True)


def _yaml_caller(*payloads):
    """A call_llm seam returning each payload in turn (the semantic retry gets the next)."""
    remaining = list(payloads)

    async def call(rendered, s):
        return remaining.pop(0), {}, "stop"

    return call


async def test_review_step_renders_entity_sheet(monkeypatch):
    captured = {}

    class CapturePrompt:
        def compile(self, **kwargs):
            captured.update(kwargs)
            return "rendered"

    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: CapturePrompt())
    await chain.review_step(
        "facts", _ONE_SCENE, {}, "desc", "guide", None, _yaml_caller(_review_yaml()),
        entity_sheet="개체 시트 본문",
    )
    assert captured["entity_sheet"] == "개체 시트 본문"
    assert captured["scp_visual_reference"] == "desc"  # frozen_descriptor preserved
    assert captured["scp_fact_sheet"] == "facts"       # scp_text preserved


async def test_review_step_keeps_valid_grounded_contradiction(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    result = await chain.review_step(
        "t", _ONE_SCENE, {}, "desc", "guide", None,
        _yaml_caller(_review_yaml(grounded_contradictions=[_contradiction()])),
    )
    assert len(result["grounded_contradictions"]) == 1
    assert result["grounded_contradictions"][0]["grounding_quote"] == "눈은 검은색이다"


async def test_review_step_forces_overall_pass_false_on_contradiction(monkeypatch):
    """The model claimed a pass while reporting a contradiction — code decides."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    result = await chain.review_step(
        "t", _ONE_SCENE, {}, "desc", "guide", None,
        _yaml_caller(_review_yaml(overall_pass=True, grounded_contradictions=[_contradiction()])),
    )
    assert result["overall_pass"] is False


async def test_review_step_synthesizes_matching_issue_for_contradiction(monkeypatch):
    """AC4: the contradiction must participate in the pass-1 repair decision, so it
    has to exist in issues[] even when the prompt forgot to emit it there."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    result = await chain.review_step(
        "t", _ONE_SCENE, {}, "desc", "guide", None,
        _yaml_caller(_review_yaml(grounded_contradictions=[_contradiction()])),
    )
    grounded = [i for i in result["issues"] if i["type"] == "grounded_contradiction"]
    assert len(grounded) == 1
    assert "눈은 검은색이다" in grounded[0]["description"]
    assert grounded[0]["correction"] == "개체는 검은 눈을 가지고 있습니다"
    assert grounded[0]["scene_num"] == 1  # positional stamp, feeds _retry_scope


async def test_review_step_does_not_duplicate_model_supplied_contradiction_issue(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    model_issue = {"scene_num": 1, "type": "grounded_contradiction", "severity": "critical",
                   "description": "모델이 직접 쓴 설명", "correction": "고쳐라"}
    other_issue = {"scene_num": 1, "type": "fact_error", "severity": "warning",
                   "description": "다른 문제", "correction": "고쳐라"}
    result = await chain.review_step(
        "t", _ONE_SCENE, {}, "desc", "guide", None,
        _yaml_caller(_review_yaml(issues=[model_issue, other_issue],
                                  grounded_contradictions=[_contradiction()])),
    )
    grounded = [i for i in result["issues"] if i["type"] == "grounded_contradiction"]
    assert len(grounded) == 1                              # exactly one per contradiction
    assert any(i["type"] == "fact_error" for i in result["issues"])  # siblings untouched


@pytest.mark.parametrize("missing", [
    "narration_quote", "grounding_source", "grounding_quote", "explanation", "correction",
])
async def test_review_step_rejects_contradiction_missing_required_evidence(monkeypatch, missing):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    bad = _contradiction()
    del bad[missing]
    # The FIRST payload is rejected outright, which buys the one prompt-level
    # correction. (What a second bad payload does is pinned separately below.)
    with pytest.raises(ValueError, match="grounded_contradiction"):
        chain._validate_grounded_contradictions({"grounded_contradictions": [bad]})

    result = await chain.review_step(
        "t", _ONE_SCENE, {}, "desc", "guide", None,
        _yaml_caller(_review_yaml(grounded_contradictions=[bad]),
                     _review_yaml(grounded_contradictions=[_contradiction()])),
    )
    assert len(result["grounded_contradictions"]) == 1  # the correction landed


async def test_review_step_rejects_blank_evidence(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    bad = _contradiction(grounding_quote="   ")
    with pytest.raises(ValueError, match="grounded_contradiction"):
        chain._validate_grounded_contradictions({"grounded_contradictions": [bad]})


@pytest.mark.parametrize("source", ["my own knowledge of SCP-096", "", "entity sheet"])
def test_contradiction_grounding_source_must_be_a_supplied_artifact(source):
    """[review fix] An evidence bar that accepts any source name lets the model grade
    the narration against its own SCP knowledge — the one thing the prompt forbids."""
    with pytest.raises(ValueError, match="grounded_contradiction"):
        chain._validate_grounded_contradictions(
            {"grounded_contradictions": [_contradiction(grounding_source=source)]}
        )
    for ok in chain.GROUNDING_SOURCES:
        entries = chain._validate_grounded_contradictions(
            {"grounded_contradictions": [_contradiction(grounding_source=ok)]}
        )
        assert entries[0]["grounding_source"] == ok


@pytest.mark.parametrize("bad", [
    [{"scene_num": 1, "narration_quote": "근거 없는 주장"}],  # missing every other field
    "없음",                                                    # not even a list
])
async def test_unevidenced_contradiction_is_dropped_not_fatal_after_the_retry(monkeypatch, bad, caplog):
    """[review fix] AD-10: a DIAGNOSTIC field must not be able to kill a scenario that
    is otherwise fine. The claim is still rejected — by dropping it, with a WARNING —
    once the model has had its one correction. Required contract fields still fail hard
    (see test_review_step_missing_overall_pass...)."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    with caplog.at_level(logging.WARNING):
        result = await chain.review_step(
            "t", _ONE_SCENE, {}, "desc", "guide", None,
            _yaml_caller(_review_yaml(overall_pass=True, grounded_contradictions=bad),
                         _review_yaml(overall_pass=True, grounded_contradictions=bad)),
        )
    assert result["grounded_contradictions"] == []
    assert result["overall_pass"] is True   # no unevidenced claim may fail the review
    assert any("grounded_contradiction" in r.getMessage() for r in caplog.records)


async def test_lenient_retry_state_is_per_scene_not_shared(monkeypatch):
    """Every scene gets its OWN parser, so its own attempt counter.

    Both scenes here need their one correction. With a single shared counter, scene 2's
    first attempt would already be in lenient mode and its contradiction would be
    dropped instead of corrected — a silently weaker evidence check for every scene
    after the first one that stumbled.
    """
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    writing = {"scenes": [{"scene_num": 1, "narration": "가."}, {"scene_num": 2, "narration": "나."}]}
    bad = {"scene_num": 1, "narration_quote": "근거 없음"}
    good = _review_yaml(grounded_contradictions=[_contradiction()])
    result = await chain.review_step(
        "t", writing, {}, "desc", "guide", None,
        _yaml_caller(_review_yaml(grounded_contradictions=[bad]), good,
                     _review_yaml(grounded_contradictions=[bad]), good),
    )
    assert len(result["grounded_contradictions"]) == 2
    assert sorted(c["scene_num"] for c in result["grounded_contradictions"]) == [1, 2]


async def test_review_step_retry_recovers_evidenced_contradiction(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    bad = _contradiction()
    del bad["grounding_quote"]
    result = await chain.review_step(
        "t", _ONE_SCENE, {}, "desc", "guide", None,
        _yaml_caller(_review_yaml(grounded_contradictions=[bad]),
                     _review_yaml(grounded_contradictions=[_contradiction()])),
    )
    assert len(result["grounded_contradictions"]) == 1
    assert result["overall_pass"] is False


async def test_review_step_absent_or_null_contradictions_is_clean(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    for payload in (_review_yaml(), _review_yaml(grounded_contradictions=None)):
        result = await chain.review_step("t", _ONE_SCENE, {}, "desc", "guide", None, _yaml_caller(payload))
        assert result["grounded_contradictions"] == []
        assert result["overall_pass"] is True


def test_review_rejects_malformed_contradictions_container():
    with pytest.raises(ValueError, match="grounded_contradiction"):
        chain._validate_grounded_contradictions({"grounded_contradictions": "없음"})


async def test_review_step_normalizes_contradiction_freetext(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    result = await chain.review_step(
        "t", _ONE_SCENE, {}, "desc", "guide", None,
        _yaml_caller(_review_yaml(grounded_contradictions=[
            _contradiction(explanation="첫 줄\n둘째  줄"),
        ])),
    )
    assert result["grounded_contradictions"][0]["explanation"] == "첫 줄 둘째 줄"


async def test_review_step_stamps_contradiction_scene_num_positionally(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    writing = {"scenes": [{"scene_num": 1, "narration": "가."}, {"scene_num": 2, "narration": "나."}]}
    # Both per-scene calls report scene_num 1 (the isolated-call habit) — position wins.
    result = await chain.review_step(
        "t", writing, {}, "desc", "guide", None,
        _yaml_caller(*[_review_yaml(grounded_contradictions=[_contradiction(scene_num=1)])] * 2),
    )
    assert sorted(c["scene_num"] for c in result["grounded_contradictions"]) == [1, 2]


def test_review_prompt_documents_entity_sheet_and_evidence_rules():
    content = (Path(__file__).parent.parent.parent.parent / "prompts" / "scenario" / "review.md").read_text(encoding="utf-8")
    assert "{{entity_sheet}}" in content
    assert "grounded_contradictions" in content
    for field in ("narration_quote", "grounding_source", "grounding_quote", "explanation", "correction"):
        assert field in content


# --- Story 12.4: story archetype selection ------------------------------------
# Selection lives in research and resolves deterministically. The catalogue is the
# closed vocabulary in domain.state; everything below either asserts lockstep with
# it or asserts that an unusable choice resolves to production's pre-12.4 template
# instead of failing the run or inventing a framing device the source lacks.

from yt_flow.domain import state as domain_state  # noqa: E402

_PROMPTS = Path(__file__).parent.parent.parent.parent / "prompts"
_ARCHETYPE_DIR = _PROMPTS / "scenario" / "archetypes"

_EVIDENCE_SATISFYING = {
    "incident_first": {},
    "discovery_log": {"recovery_report": True},
    "interview_testimony": {"interview_log": True},
    "containment_breach_realtime": {"incident_log": True},
}


def _research_yaml(**over) -> str:
    payload = {
        "core_identity": "x", "frozen_descriptor": "desc", "entity_sheet": "e",
        "story_logline": "l", "dramatic_beats": "x", "environment": "x", "hooks": "x",
        "story_archetype": "incident_first",
        "archetype_rationale": "사건 기록이 존재한다",
        "source_evidence": dict.fromkeys(domain_state.SOURCE_EVIDENCE_KEYS, True),
    }
    payload.update(over)
    return yaml.safe_dump(payload, allow_unicode=True)


def _scripted(*replies):
    """A call seam handing back `replies` in order; asserts it isn't over-called."""
    it = iter(replies)
    calls = {"n": 0}

    async def call(rendered, s):
        calls["n"] += 1
        return next(it), {}, "stop"

    return call, calls


# ── vocabulary + guide lockstep ───────────────────────────────────────────────


def test_archetype_vocabulary_is_the_four_closed_values():
    assert domain_state.STORY_ARCHETYPES == (
        "incident_first", "discovery_log", "interview_testimony", "containment_breach_realtime",
    )
    # researcher_descent is deferred on purpose (story AC1) — its absence is the contract.
    assert "researcher_descent" not in domain_state.STORY_ARCHETYPES
    assert domain_state.STORY_ARCHETYPE_FALLBACK in domain_state.STORY_ARCHETYPES


def test_critic_issue_vocabulary_is_closed_with_a_reachable_fallback():
    assert domain_state.CRITIC_ISSUE_TYPES == (
        "ungrounded_claim", "substance_gap", "report_tone", "pacing", "hook", "ending", "other",
    )
    assert domain_state.CRITIC_ISSUE_TYPE_FALLBACK in domain_state.CRITIC_ISSUE_TYPES


def test_review_issue_vocabulary_matches_the_prompt_enum():
    """The two must not drift. `issues[].type` is model free text clipped to 600
    chars — the tuple is the ONLY thing standing between a 600-character Korean
    sentence and a rendered "category" at the gate — so it is pinned against the
    prompt line the model is actually reading, not against a second hand-typed copy.
    """
    line = next(
        line for line in _prompt_text("review.md").splitlines()
        if line.lstrip().startswith("type:") and "fact_error" in line
    )
    from_prompt = tuple(line.split('"')[1].split("|"))
    assert domain_state.REVIEW_ISSUE_TYPES == from_prompt
    # No overlap with the critic's vocabulary is asserted on purpose: `categories`
    # is a merged namespace and the two judges name the same defect differently
    # (`invented_content` / `ungrounded_claim`). Both reach the gate; neither is
    # translated into the other.
    assert "other" not in domain_state.REVIEW_ISSUE_TYPES  # no reviewer fallback exists


@pytest.mark.parametrize(
    "raw, expected",
    [("ungrounded_claim", "ungrounded_claim"), ("Pacing", "pacing"), ("  report_tone\n", "report_tone"),
     ("fact_reference", "other"), ("", "other"), (None, "other"), ({"a": 1}, "other"), (3, "other")],
)
def test_normalize_critic_issue_type_is_total(raw, expected):
    assert domain_state.normalize_critic_issue_type(raw) == expected


def test_required_evidence_table_is_lockstep_with_the_vocabulary():
    assert set(domain_state.ARCHETYPE_REQUIRED_EVIDENCE) == set(domain_state.STORY_ARCHETYPES)
    for archetype, required in domain_state.ARCHETYPE_REQUIRED_EVIDENCE.items():
        assert set(required) <= set(domain_state.SOURCE_EVIDENCE_KEYS), archetype
    # Only incident_first may be unconditional: an archetype needing no evidence
    # could be selected for a source that cannot support its framing device.
    unconditional = [a for a, r in domain_state.ARCHETYPE_REQUIRED_EVIDENCE.items() if not r]
    assert unconditional == ["incident_first"]


def test_guide_files_match_the_vocabulary_exactly():
    on_disk = {p.stem for p in _ARCHETYPE_DIR.glob("*.md")}
    assert on_disk == set(domain_state.STORY_ARCHETYPES)


@pytest.mark.parametrize("archetype", domain_state.STORY_ARCHETYPES)
def test_every_guide_is_non_empty_and_carries_an_example(archetype):
    text = (_ARCHETYPE_DIR / f"{archetype}.md").read_text(encoding="utf-8")
    assert len(text.strip()) > 400, "a guide has to actually teach the beats"
    assert archetype in text  # names the value it belongs to
    assert "```yaml" in text, "AC5: at least one concise YAML beat-sheet example"
    example = text.split("```yaml", 1)[1].split("```", 1)[0]
    parsed = yaml.safe_load(example)
    assert isinstance(parsed, list) and parsed, "the example must parse as a scene list"
    assert all("scene_num" in entry for entry in parsed)
    # Examples teach structure, not SCP facts (AC5) — no real designation may leak in.
    assert not re.search(r"SCP-\d", text), "examples must stay source-neutral"


# ── the pure evidence map ─────────────────────────────────────────────────────


@pytest.mark.parametrize("archetype", domain_state.STORY_ARCHETYPES)
def test_satisfying_evidence_clears_every_archetype(archetype):
    assert domain_state.missing_archetype_evidence(archetype, _EVIDENCE_SATISFYING[archetype]) == ()


@pytest.mark.parametrize("archetype", [a for a in domain_state.STORY_ARCHETYPES if a != "incident_first"])
def test_absent_evidence_is_reported_for_every_non_default_archetype(archetype):
    missing = domain_state.missing_archetype_evidence(archetype, dict.fromkeys(domain_state.SOURCE_EVIDENCE_KEYS, False))
    assert missing == domain_state.ARCHETYPE_REQUIRED_EVIDENCE[archetype]


def test_discovery_log_accepts_either_of_its_two_evidence_keys():
    assert domain_state.missing_archetype_evidence("discovery_log", {"dated_chronology": True}) == ()
    assert domain_state.missing_archetype_evidence("discovery_log", {"recovery_report": True}) == ()
    assert domain_state.missing_archetype_evidence("discovery_log", {"interview_log": True}) != ()


def test_incident_first_needs_nothing_even_with_no_inventory():
    assert domain_state.missing_archetype_evidence("incident_first", None) == ()


def test_source_evidence_normalizes_to_the_closed_key_set():
    parsed = chain._parse_source_evidence({"interview_log": True, "made_up_key": True})
    assert set(parsed) == set(domain_state.SOURCE_EVIDENCE_KEYS)
    assert parsed["interview_log"] is True
    assert parsed["incident_log"] is False
    assert "made_up_key" not in parsed


def test_source_evidence_accepts_string_true_and_rejects_a_non_mapping():
    assert chain._parse_source_evidence({"incident_log": "TRUE"})["incident_log"] is True
    assert chain._parse_source_evidence("nope") == dict.fromkeys(domain_state.SOURCE_EVIDENCE_KEYS, False)


# ── research_step: selection, normalization, bounded correction ───────────────


@pytest.mark.parametrize("archetype", domain_state.STORY_ARCHETYPES)
async def test_research_step_accepts_every_catalogue_value_with_its_evidence(monkeypatch, archetype):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    evidence = dict.fromkeys(domain_state.SOURCE_EVIDENCE_KEYS, False)
    evidence.update(_EVIDENCE_SATISFYING[archetype])
    call, calls = _scripted(_research_yaml(story_archetype=archetype, source_evidence=evidence))
    result = await chain.research_step("SCP-173", "t", "guide", None, call)
    assert result["story_archetype"] == archetype
    assert result["story_archetype_fallback_used"] is False
    assert calls["n"] == 1  # no correction retry for a valid choice


async def test_research_step_normalizes_casing_and_whitespace(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    call, calls = _scripted(_research_yaml(story_archetype="  Interview_Testimony \n"))
    result = await chain.research_step("SCP-173", "t", "guide", None, call)
    assert result["story_archetype"] == "interview_testimony"
    assert result["story_archetype_fallback_used"] is False
    assert calls["n"] == 1


async def test_research_step_gives_an_unknown_archetype_exactly_one_correction(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    call, calls = _scripted(
        _research_yaml(story_archetype="researcher_descent"),   # not in the catalogue
        _research_yaml(story_archetype="discovery_log"),        # corrected
    )
    result = await chain.research_step("SCP-173", "t", "guide", None, call)
    assert (result["story_archetype"], result["story_archetype_fallback_used"]) == ("discovery_log", False)
    assert calls["n"] == 2


async def test_research_step_falls_back_after_a_second_invalid_archetype(monkeypatch, caplog):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    call, calls = _scripted(
        _research_yaml(story_archetype="researcher_descent"),
        _research_yaml(story_archetype="cosmic_horror_montage"),
    )
    with caplog.at_level(logging.WARNING):
        result = await chain.research_step("SCP-173", "t", "guide", None, call)
    assert result["story_archetype"] == "incident_first"
    assert result["story_archetype_fallback_used"] is True
    assert calls["n"] == 2  # bounded: never a third call
    assert "cosmic_horror_montage" in caplog.text  # the rejected value is named
    # the rest of the otherwise-valid packet survives the fallback
    assert result["frozen_descriptor"] == "desc" and result["entity_sheet"] == "e"


@pytest.mark.parametrize("bad", [None, 42, True, ["discovery_log"], {"pick": "x"}])
async def test_research_step_resolves_a_non_string_archetype(monkeypatch, bad):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    payload = _research_yaml() if bad is None else _research_yaml(story_archetype=bad)
    if bad is None:  # "missing" rather than "None-valued"
        payload = yaml.safe_dump(
            {k: v for k, v in yaml.safe_load(payload).items() if k != "story_archetype"},
            allow_unicode=True,
        )
    call, calls = _scripted(payload, payload)
    result = await chain.research_step("SCP-173", "t", "guide", None, call)
    assert result["story_archetype"] == "incident_first"
    assert result["story_archetype_fallback_used"] is True
    assert calls["n"] == 2


async def test_unrelated_schema_failure_is_never_salvaged_by_the_archetype_fallback(monkeypatch):
    """The callback replaces only `story_archetype` — a missing descriptor still fails."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    call, calls = _scripted(_research_yaml(frozen_descriptor=""), _research_yaml(frozen_descriptor=""))
    with pytest.raises(ValueError, match="frozen_descriptor"):
        await chain.research_step("SCP-173", "t", "guide", None, call)
    assert calls["n"] == 2


async def test_missing_rationale_is_fatal_even_with_a_valid_archetype(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    payload = yaml.safe_dump(
        {k: v for k, v in yaml.safe_load(_research_yaml()).items() if k != "archetype_rationale"},
        allow_unicode=True,
    )
    call, calls = _scripted(payload, payload)
    with pytest.raises(ValueError, match="archetype_rationale"):
        await chain.research_step("SCP-173", "t", "guide", None, call)
    assert calls["n"] == 2


async def test_blank_rationale_is_rejected(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    call, _ = _scripted(*[_research_yaml(archetype_rationale="   ")] * 2)
    with pytest.raises(ValueError, match="archetype_rationale"):
        await chain.research_step("SCP-173", "t", "guide", None, call)


def test_rationale_is_in_the_deterministic_freetext_repair_set():
    # Story 6.11 path: an inline rationale quoting "Addendum 173-1: ..." would
    # otherwise be an unrepairable YAMLError.
    assert "archetype_rationale" in chain.FREETEXT_KEYS
    raw = "frozen_descriptor: desc\narchetype_rationale: Addendum 173-1: 회수 기록이 있다\n"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(raw)
    repaired = chain._reparse_repairing_freetext(
        raw, chain._parse_yaml, _yaml_error(raw),
    )
    assert repaired["archetype_rationale"] == "Addendum 173-1: 회수 기록이 있다"


def _yaml_error(raw: str) -> yaml.YAMLError:
    try:
        yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return exc
    raise AssertionError("expected a YAMLError")


# ── the evidence gate: deterministic, and NOT an LLM retry ────────────────────


@pytest.mark.parametrize("archetype", [a for a in domain_state.STORY_ARCHETYPES if a != "incident_first"])
async def test_archetype_without_its_source_evidence_falls_back_without_a_second_call(
    monkeypatch, caplog, archetype,
):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    call, calls = _scripted(_research_yaml(
        story_archetype=archetype,
        source_evidence=dict.fromkeys(domain_state.SOURCE_EVIDENCE_KEYS, False),
    ))
    with caplog.at_level(logging.WARNING):
        result = await chain.research_step("SCP-173", "t", "guide", None, call)
    assert result["story_archetype"] == "incident_first"
    assert result["story_archetype_fallback_used"] is True
    # AC2: the grounding check reuses NO LLM call — one provider call total.
    assert calls["n"] == 1
    assert archetype in caplog.text
    for key in domain_state.ARCHETYPE_REQUIRED_EVIDENCE[archetype]:
        assert key in caplog.text  # the missing evidence key is named


async def test_absent_inventory_leaves_only_incident_first_eligible(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    payload = yaml.safe_dump(
        {**yaml.safe_load(_research_yaml(story_archetype="interview_testimony")), "source_evidence": None},
        allow_unicode=True,
    )
    call, _ = _scripted(payload)
    result = await chain.research_step("SCP-173", "t", "guide", None, call)
    assert (result["story_archetype"], result["story_archetype_fallback_used"]) == ("incident_first", True)


async def test_incident_first_on_a_bare_source_is_not_a_fallback(monkeypatch):
    """AC2: when the inventory supports only incident_first, staying there is the
    correct OUTCOME, not a degradation — the fallback flag must stay false."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    call, _ = _scripted(_research_yaml(
        story_archetype="incident_first",
        source_evidence=dict.fromkeys(domain_state.SOURCE_EVIDENCE_KEYS, False),
    ))
    result = await chain.research_step("SCP-173", "t", "guide", None, call)
    assert result["story_archetype_fallback_used"] is False


@pytest.mark.parametrize(
    ("replies", "trace"),
    [
        # missing evidence: one call, gate resolves in code
        ([_research_yaml(story_archetype="interview_testimony",
                         source_evidence={"incident_log": True, "interview_log": False},
                         archetype_rationale="Addendum 173-4의 심문 기록이 증언 서사를 지지함")], 1),
        # two invalid values in a row: the semantic_fallback seam
        ([_research_yaml(story_archetype="researcher_descent",
                         archetype_rationale="연구원 하강 서사가 이 문서에 맞음")] * 2, 2),
    ],
)
async def test_overridden_choice_does_not_leave_its_rationale_on_the_packet(monkeypatch, replies, trace):
    """`structure_step` dumps the whole packet into `{{research_packet}}`, so a
    rationale arguing for the REJECTED archetype would tell the structure model to
    reintroduce the framing device the gate just refused (AC3: no contradictory
    instruction; AC4: no invented framing device)."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    call, calls = _scripted(*replies)
    result = await chain.research_step("SCP-173", "t", "guide", None, call)

    assert result["story_archetype"] == "incident_first"
    assert result["story_archetype_fallback_used"] is True
    assert calls["n"] == trace  # the override still costs no extra provider call
    # still a non-empty rationale (AC2), but no longer the rejected argument
    assert result["archetype_rationale"].strip()
    assert "심문" not in result["archetype_rationale"]
    assert "연구원 하강" not in result["archetype_rationale"]
    assert "incident_first" in result["archetype_rationale"]


async def test_a_kept_choice_keeps_the_models_own_rationale(monkeypatch):
    """The override is scoped to the override — a valid selection is not rewritten."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    call, _ = _scripted(_research_yaml(
        story_archetype="interview_testimony",
        source_evidence={"interview_log": True},
        archetype_rationale="Addendum 173-4의 심문 기록이 증언 서사를 지지함",
    ))
    result = await chain.research_step("SCP-173", "t", "guide", None, call)
    assert result["archetype_rationale"] == "Addendum 173-4의 심문 기록이 증언 서사를 지지함"


async def test_normalized_inventory_is_kept_on_the_packet(monkeypatch):
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    call, _ = _scripted(_research_yaml(source_evidence={"interview_log": True, "junk": True}))
    result = await chain.research_step("SCP-173", "t", "guide", None, call)
    assert result["source_evidence"] == {
        **dict.fromkeys(domain_state.SOURCE_EVIDENCE_KEYS, False), "interview_log": True,
    }


# ── structure_step: the selected guide, and only it ──────────────────────────


class _RecordingPrompt:
    def __init__(self, name, fetched, captured):
        self._name, self._fetched, self._captured = name, fetched, captured

    def compile(self, **variables):
        self._fetched.append(self._name)
        if self._name == "scenario/structure":
            self._captured.update(variables)
            return "rendered"
        return f"GUIDE_TEXT:{self._name}"


def _recording_prompt_service(monkeypatch):
    fetched: list[str] = []
    captured: dict = {}
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt",
        lambda name, **k: _RecordingPrompt(name, fetched, captured),
    )
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt_with_fallback",
        lambda name, **k: _RecordingPrompt(name, fetched, captured),
    )
    return fetched, captured


@pytest.mark.parametrize("archetype", domain_state.STORY_ARCHETYPES)
async def test_structure_step_injects_only_the_selected_guide(monkeypatch, archetype):
    fetched, captured = _recording_prompt_service(monkeypatch)
    call, _ = _scripted(_retention_yaml(4))
    await chain.structure_step(
        "SCP-173", "", {"frozen_descriptor": "d"}, "guide", None, call, story_archetype=archetype,
    )
    assert captured["story_archetype"] == archetype
    assert captured["archetype_guide"] == f"GUIDE_TEXT:scenario/archetypes/{archetype}"
    # exactly one guide compiled — not all four (AC5: no unrelated prompt bloat)
    guides = [n for n in fetched if n.startswith("scenario/archetypes/")]
    assert guides == [f"scenario/archetypes/{archetype}"]


async def test_structure_step_defaults_to_the_production_template(monkeypatch):
    """A caller that predates this story keeps producing incident-first outlines."""
    _, captured = _recording_prompt_service(monkeypatch)
    call, _ = _scripted(_retention_yaml(4))
    await chain.structure_step("SCP-173", "", {"frozen_descriptor": "d"}, "guide", None, call)
    assert captured["story_archetype"] == "incident_first"


async def test_structure_step_never_infers_the_choice_from_the_research_packet(monkeypatch):
    """AC3: the explicit argument wins. The packet still travels whole (it carries
    every other research field), but it is not where the decision is read from."""
    _, captured = _recording_prompt_service(monkeypatch)
    call, _ = _scripted(_retention_yaml(4))
    await chain.structure_step(
        "SCP-173", "", {"frozen_descriptor": "d", "story_archetype": "discovery_log"}, "guide", None, call,
        story_archetype="interview_testimony",
    )
    assert captured["story_archetype"] == "interview_testimony"
    assert captured["archetype_guide"].endswith("interview_testimony")


async def test_unknown_archetype_reaching_structure_uses_the_default_guide(monkeypatch, caplog):
    _, captured = _recording_prompt_service(monkeypatch)
    call, _ = _scripted(_retention_yaml(4))
    with caplog.at_level(logging.WARNING):
        await chain.structure_step(
            "SCP-173", "", {"frozen_descriptor": "d"}, "guide", None, call, story_archetype="nonsense",
        )
    assert captured["archetype_guide"].endswith("incident_first")
    assert "nonsense" in caplog.text


def test_archetype_guide_is_label_aware(monkeypatch):
    """AC7: the suspended candidate workflow must keep working without redesign."""
    seen: list[tuple[str, str | None]] = []

    class P:
        def compile(self, **v):
            return "text"

    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt_with_fallback",
        lambda name, **k: (seen.append((name, k.get("label"))), P())[1],
    )
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt",
        lambda name, **k: (seen.append((name, None)), P())[1],
    )
    chain.archetype_guide("discovery_log", label="candidate")
    chain.archetype_guide("discovery_log")
    assert seen == [
        ("scenario/archetypes/discovery_log", "candidate"),
        ("scenario/archetypes/discovery_log", None),
    ]


# ── prompt contract: no shared prompt may re-impose one template ──────────────


def test_structure_prompt_is_driven_by_the_selected_archetype():
    text = (_PROMPTS / "scenario" / "structure.md").read_text(encoding="utf-8")
    assert "{{story_archetype}}" in text
    assert "{{archetype_guide}}" in text


@pytest.mark.parametrize("name", ["structure.md", "writing.md", "format_guide.md"])
def test_common_prompts_no_longer_force_incident_first_universally(name):
    """The Story 12.4 defect was three prompts each independently reasserting the
    same reveal grammar. This fails if any of them starts doing it again."""
    text = (_PROMPTS / "scenario" / name).read_text(encoding="utf-8")
    assert "INCIDENT-FIRST format" not in text
    # The old fixed act ladder, in any of the three prompts' phrasings.
    for banned in ("Act 1 - 사건으로 시작", "Act 1: 사건으로 시작", "**앞부분 (Act 1-2)**"):
        assert banned not in text, f"{name} re-imposes a fixed act order"


def test_format_guide_points_at_the_archetype_guide_for_act_authority():
    text = (_PROMPTS / "scenario" / "format_guide.md").read_text(encoding="utf-8")
    assert "scenario/archetypes/" in text
    # the universal retention principles it owns are still there (AC4)
    for kept in ("Hook Type Library", "Progressive Disclosure", "Emotional Curve", "Viewer Immersion"):
        assert kept in text


def test_research_prompt_documents_the_closed_catalogue_and_inventory():
    text = (_PROMPTS / "scenario" / "research.md").read_text(encoding="utf-8")
    for archetype in domain_state.STORY_ARCHETYPES:
        assert archetype in text
    for key in domain_state.SOURCE_EVIDENCE_KEYS:
        assert key in text
    assert "archetype_rationale" in text
    assert "researcher_descent" not in text  # deferred, must not be offered


# ── SCP designation spelling (live run e5ed4b3a) ──────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("대상은 SCP-049입니다.", "대상은 에스씨피 공사구입니다."),
        ("오싹한 SCP-049-2의 탄생입니다.", "오싹한 에스씨피 공사구 이의 탄생입니다."),
        ("SCP-682와 SCP-096.", "에스씨피 육팔이와 에스씨피 공구육."),
        ("scp-049 소문자도 잡는다.", "에스씨피 공사구 소문자도 잡는다."),
        ("SCP–049 엔대시.", "에스씨피 공사구 엔대시."),
        ("정규화할 것이 없는 문장.", "정규화할 것이 없는 문장."),
    ],
)
def test_spell_scp_designations(raw, expected):
    """One narrator must not say the subject's name four different ways.

    Live run e5ed4b3a produced `에스씨피 공사구` / `에스시피-049-2` /
    `에스시피 공사구 이` / `에스씨피 공사 구` for the same object across nine
    scenes, because the prompt asked the LLM to spell acronyms without naming a
    canonical form. The designation is a closed token class, so it is spelled here.
    """
    assert chain.spell_scp_designations(raw) == expected


def test_spell_scp_designations_preserves_sentence_count():
    """Applied after the sentence-count invariant check — it must not perturb it."""
    raw = "SCP-049입니다. 키 1.9m. SCP-049-2가 일어섭니다."
    out = chain.spell_scp_designations(raw)
    assert len(chain.split_sentences(raw)) == len(chain.split_sentences(out))


async def test_tts_normalize_spells_designations_even_on_sentence_mismatch(monkeypatch):
    """The degraded single-track path is still spoken aloud, so it still gets spelled."""
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt()
    )
    writing = {"scenes": [{"scene_num": 1, "narration": "SCP-049는 의사를 자처한다. 그는 기다린다."}]}

    async def call(*a, **k):  # returns a DIFFERENT sentence count -> mismatch branch
        return "scenes:\n  - scene_num: 1\n    narration: 하나로 합쳐진 문장이다\n", {}, "stop"

    out = await chain.tts_normalize_step(writing, "guide", None, call)
    scene = out["scenes"][0]
    assert "에스씨피 공사구" in scene["narration"]
    assert "SCP-049" in scene["display_narration"]  # subtitles keep the readable form


# ── Story 12.7: script-wide device quotas become per-scene assignments ────────


def _alloc_outline(n: int, budgets: list[int] | None = None, **interrupts: str) -> list[dict]:
    """A minimal outline for allocation: only the fields `_allocate_devices` reads.

    `pattern_interrupt` is set per scene via `s<idx>=` kwargs (0-based), everything
    else is a uniform `none` — the allocation must not need anything the retention
    validator does not already constrain.
    """
    return [
        {
            "pattern_interrupt": interrupts.get(f"s{idx}", "none"),
            "word_budget": budgets[idx] if budgets else 45,
        }
        for idx in range(n)
    ]


def _owners(allocation: list[list[str]], device: str) -> list[int]:
    return [idx for idx, devices in enumerate(allocation) if device in devices]


@pytest.mark.parametrize("n", range(1, 13))
def test_allocate_devices_is_total_for_every_outline_length(n):
    """AC1/AC4. A device with no owner is a device the whole script lost — arm A of
    the ablation lost 상황 가정 that way (5 occurrences → 0), and its closing scene
    drew nothing at all because the second question followed the last loop-closer."""
    allocation = chain._allocate_devices(_alloc_outline(n))
    assert len(allocation) == n
    for device in chain.WRITING_DEVICES:
        assert _owners(allocation, device), f"n={n}: {device} has no owner"
    assert allocation[-1], f"n={n}: the closing scene drew no device"
    assert "dramatic_question" in allocation[0]


def test_allocate_devices_gives_the_question_to_the_hook_and_the_final_scene():
    # The ablation's rule sent the second question to the scene closing the LAST loop,
    # which in a 9-scene outline was scene 7 — leaving the closer bare. Position is now
    # the only input, so `loops_closed` is not set here: it would not be read.
    assert _owners(chain._allocate_devices(_alloc_outline(9)), "dramatic_question") == [0, 8]


def test_allocate_devices_sends_second_person_to_the_direct_address_scenes():
    # `structure.md` already plans where the viewer is addressed; the pre-12.7
    # prompt overrode that plan in every scene.
    allocation = chain._allocate_devices(_alloc_outline(8, s2="direct_address", s5="direct_address"))
    assert _owners(allocation, "second_person") == [2, 5]


def test_allocate_devices_takes_every_direct_address_scene_not_the_first_two():
    """`writing.md`'s `pattern_interrupt` bullet already orders a `direct_address`
    scene to address the viewer. Capping the list here would hand a third such scene
    "do it" and "do not do it" in the same prompt — the contradiction this story is
    about, reintroduced one layer down."""
    allocation = chain._allocate_devices(
        _alloc_outline(8, s1="direct_address", s3="direct_address", s6="direct_address")
    )
    assert _owners(allocation, "second_person") == [1, 3, 6]


def test_allocate_devices_sends_the_reaction_to_the_stance_shift_scenes():
    allocation = chain._allocate_devices(_alloc_outline(8, s1="pov_shift", s4="tone_shift"))
    assert _owners(allocation, "narrator_reaction") == [1, 4]


def test_allocate_devices_puts_the_hypothetical_on_the_first_second_person_scene():
    """AC4's second hole: 상황 가정 shared the `second_person` bullet and vanished.
    It owns its own slot now, and lands where the viewer is already being addressed."""
    allocation = chain._allocate_devices(_alloc_outline(8, s2="direct_address", s5="direct_address"))
    assert _owners(allocation, "hypothetical") == [2]
    assert set(_owners(allocation, "hypothetical")) <= set(_owners(allocation, "second_person"))


def test_allocate_devices_falls_back_to_the_largest_middle_scenes():
    # No `direct_address` anywhere: the two biggest middle scenes carry 2인칭, and
    # the hook/closer are never conscripted as a second device carrier.
    allocation = chain._allocate_devices(_alloc_outline(6, budgets=[40, 50, 90, 45, 80, 40]))
    assert _owners(allocation, "second_person") == [2, 4]
    assert _owners(allocation, "dramatic_question") == [0, 5]
    # ...and the reaction fallback steps aside rather than making scene 3 carry three
    # of the four devices. Clustering in one scene is the defect, not a smaller version
    # of the fix.
    assert _owners(allocation, "narrator_reaction") == [1]
    assert not set(_owners(allocation, "narrator_reaction")) & set(_owners(allocation, "second_person"))


def test_allocate_devices_returns_nothing_for_an_empty_outline():
    # `writing_step` and `_validate_retention_outline` both reject this before it can
    # arrive; the point is that allocation answers calmly instead of raising from
    # `min()` on an empty list.
    assert chain._allocate_devices([]) == []


@pytest.mark.parametrize(
    "scene",
    [{}, {"pattern_interrupt": None}, {"word_budget": None}, {"word_budget": "많이"},
     {"word_budget": True}, {"pattern_interrupt": ["direct_address"], "word_budget": [45]}],
)
def test_allocate_devices_never_raises_on_a_missing_or_garbage_field(scene):
    """Allocation is an ornament budget — it must never be the thing that kills a run.
    A missing `pattern_interrupt` reads as `none`, a non-numeric budget sorts as 0."""
    outline = _alloc_outline(5)
    outline[2] = scene
    allocation = chain._allocate_devices(outline)
    assert len(allocation) == 5
    for device in chain.WRITING_DEVICES:
        assert _owners(allocation, device)


async def test_structure_step_annotates_every_scene_with_its_assigned_devices(monkeypatch):
    """AC1: the whole-outline decision is made once, right after validation — the
    same seam `hook_type` uses. No LLM call is added to reach it."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    calls = {"n": 0}

    async def call(rendered, s):
        calls["n"] += 1
        return _retention_yaml(8), {}, "stop"

    outline = await chain.structure_step("SCP-173", "", {"frozen_descriptor": "d"}, "guide", None, call)
    assert calls["n"] == 1
    assert [scene["assigned_devices"] for scene in outline] == chain._allocate_devices(outline)
    assert outline[-1]["assigned_devices"]


async def test_writing_scene_brief_carries_this_scenes_assigned_devices(monkeypatch):
    """The delivery half of AC1: each per-scene call sees its own share and no other
    scene's — `{**scene}` in the payload is why one write reaches the prompt."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: EchoPrompt())
    structure = _structure(4)
    for scene, devices in zip(structure, [["dramatic_question"], [], ["second_person"], []], strict=True):
        scene["assigned_devices"] = devices
    seen = {}

    async def call(rendered, s):
        brief = json.loads(rendered)["scene_structure"]
        n = _requested_scene(brief)
        seen[n] = json.loads(brief.split("\n", 1)[1])["write_only_this_scene"]["assigned_devices"]
        assert "assigned_devices" in brief.split("\n", 1)[0], "the steering sentence must name it"
        return f"scenes:\n  - scene_num: {n}\n    narration: narr {n}.\n    location: chamber\n    color_palette: grey\n    atmosphere: tense\n", {}, "stop"

    await chain.writing_step("SCP-173", structure, "desc", "guide", "", None, call)
    assert seen == {1: ["dramatic_question"], 2: [], 3: ["second_person"], 4: []}


def test_writing_prompt_asks_only_for_the_devices_this_scene_was_assigned():
    content = _prompt_text("writing.md")
    assert "### 필수 몰입 기법 (전부 사용)" not in content, "the script-wide quota block is back"
    assert "배정되지 않은 기법은 쓰지 마세요" in content
    assert "assigned_devices" in content


def test_writing_prompt_no_longer_demands_a_question_in_every_scenes_rhythm():
    """AC3, source #2. The 종결어미 rhythm rule is scene-scoped by construction, so on
    its own it holds 질문 at 1.0 per scene — editing only the technique block yields a
    null result and the wrong conclusion that the hypothesis failed."""
    content = _prompt_text("writing.md")
    assert '2. 의문형 (-까요?/-을까요? — 위 "극적 질문" 기법과 동일)' not in content
    assert "이 씬에 `dramatic_question`이 배정된 경우에만" in content


def test_writing_prompt_lets_a_connective_sentence_run_long():
    """AC5/AC6: a flat 15~25자 ceiling forbids the subordinate clause that carries
    causation, which is why control opened 0 of 7 scenes on a link to the previous one."""
    content = _prompt_text("writing.md")
    assert "- 문장 길이: 15~25자 (TTS 최적화용 — 짧고 펀치있게)" not in content
    assert "40자까지" in content
    assert "첫 문장은 앞 씬과의 연결을 세우고 시작하세요" in content
    assert "드라마틱 포즈" in content, "short-sentence pauses must stay legal"


def test_writing_scene_repair_prompt_carries_the_allocation():
    """AC3, source #3. The repair pass runs a DIFFERENT prompt and fired in all three
    ablation runs — without this line it can hand back a device the allocation removed."""
    content = _prompt_text("writing_scene_repair.md")
    assert "assigned_devices" in content
    assert "새로 추가하지 마세요" in content


def test_every_allocated_device_name_appears_in_the_writing_prompt():
    # One vocabulary. A device the allocator can assign but the prompt cannot read
    # is an assignment that silently does nothing.
    content = _prompt_text("writing.md")
    for device in chain.WRITING_DEVICES:
        assert device in content, f"writing.md never mentions {device}"


class _SeededPrompt:
    """A Langfuse-ish text prompt: `.prompt` is the raw template `.compile()` renders."""

    def __init__(self, text: str):
        self.prompt = text
        self.version = 7

    def compile(self, **variables):
        return self.prompt


def test_writing_seeding_guard_rejects_a_prompt_that_predates_the_allocation(monkeypatch):
    """The allocation rides inside the free-text `scene_structure`, so an unseeded
    `scenario/writing` renders fine and simply ignores it — every prompt-text test in
    this file stays green while the shipped script goes back to a question per scene.
    The runtime text is the only place the two can be compared."""
    monkeypatch.setattr(
        chain.prompt_service, "get_prompt",
        lambda name, label=None: _SeededPrompt("### 필수 몰입 기법 (전부 사용)"),
    )
    with pytest.raises(RuntimeError, match="assigned_devices"):
        chain._require_seeded_device_allocation()


def test_writing_seeding_guard_passes_on_the_seeded_text_and_on_a_test_double(monkeypatch):
    seeded = _prompt_text("writing.md")
    monkeypatch.setattr(chain.prompt_service, "get_prompt", lambda name, label=None: _SeededPrompt(seeded))
    chain._require_seeded_device_allocation()
    # A double with no raw text claims nothing rather than failing the run.
    monkeypatch.setattr(chain.prompt_service, "get_prompt", lambda name, label=None: FakePrompt())
    chain._require_seeded_device_allocation()


# ── Story 12.8: outline grounding ────────────────────────────────────────────
#
# The gap this closes is an ownership vacuum: Story 12.1 deferred grounding to
# review/critic, and neither of them has ever been shown the outline. Every
# ungrounded claim in the 12.6 ablation, across all three arms, was minted here.

SOURCE = (
    "SCP-049 is a humanoid entity roughly 1.9 meters in height that bears the appearance "
    "of a medieval plague doctor, wearing a hooded black robe and a ceramic mask that "
    "appears fused to the being's head. Physical contact with its bare hands causes death "
    "in living humans within moments."
)


def _fact(statement: str, quote: str) -> dict:
    return {"statement": statement, "quote": quote}


def _evidence_scene(facts: list[dict], **event) -> list[dict]:
    """One scene, just enough shape for `_check_fact_evidence` — which runs BEFORE
    `_validate_retention_outline` and therefore may never assume a valid outline."""
    return [{"fact_references": facts, "event": {"who": "연구원", **event}}]


# --- _overlap: totality and bounds -------------------------------------------


@pytest.mark.parametrize("text,reference", [
    (None, "abc"), ("abc", None), ("", "abc"), ("abc", ""), ("ab", "abcd"),  # shorter than one trigram
    ({}, []), (0, 0), ("가나", "가나다"),
])
def test_overlap_returns_zero_for_anything_it_cannot_measure(text, reference):
    assert chain._overlap(text, reference) == 0.0


def test_overlap_is_bounded_and_identity_is_one():
    assert chain._overlap("격리 절차가 시작된다", "격리 절차가 시작된다") == 1.0
    assert chain._overlap("완전히 다른 문장", "격리 절차가 시작된다") < 0.2
    for text, reference in [("가면은 융합되어 있다", "가면이 융합된 것으로 보인다"), ("abc def", "xyz")]:
        assert 0.0 <= chain._overlap(text, reference) <= 1.0


def test_overlap_is_containment_not_similarity():
    """A short text fully inside a long reference scores 1.0 — the direction matters,
    because both callers ask "is this text supported by that one", never "are these
    two the same length"."""
    assert chain._overlap("bare hands", SOURCE) == 1.0
    assert chain._overlap(SOURCE, "bare hands") < 0.1


def test_overlap_normalizes_the_way_every_other_comparison_here_does():
    assert chain._overlap("격리  절차가\n시작된다", "격리 절차가 시작된다") == 1.0


# --- _check_fact_evidence: the I/O matrix ------------------------------------


def test_evidence_quote_located_in_the_source_produces_no_note():
    scenes = _evidence_scene(
        [_fact("맨손 접촉만으로 사람이 죽는다", "Physical contact with its bare hands causes death")],
        what="맨손 접촉만으로 사람이 죽는다", consequence="맨손 접촉으로 사람이 죽었다",
    )
    assert chain._check_fact_evidence(scenes, SOURCE) == []
    assert scenes[0]["fact_references"][0]["quote_verified"] is True


def test_evidence_quote_absent_from_the_source_is_named_with_its_scene():
    scenes = _evidence_scene([_fact("등급은 유클리드다", "SCP-049 is classified Euclid")])
    notes = [n for n in chain._check_fact_evidence(scenes, SOURCE) if n["code"] == "quote_not_found"]
    assert [n["scene"] for n in notes] == [1]
    assert "Euclid" in notes[0]["detail"]
    assert scenes[0]["fact_references"][0]["quote_verified"] is False


def test_evidence_hedge_dropped_names_the_scene_and_both_texts():
    """AC3, and the defect `ablation.md:288` traced through all three arms: the source
    says "appears fused" and the outline states it as settled fact."""
    scenes = _evidence_scene(
        [_fact("가면은 머리에 융합되어 있다", "a ceramic mask that appears fused to the being's head")],
        what="가면은 머리에 융합되어 있다", consequence="가면이 융합되어 있음이 확인됐다",
    )
    notes = chain._check_fact_evidence(scenes, SOURCE)
    assert [n["code"] for n in notes] == ["hedge_dropped"]
    assert notes[0]["scene"] == 1
    assert "appears fused" in notes[0]["detail"] and "융합되어 있다" in notes[0]["detail"]


@pytest.mark.parametrize("quote", [
    "A Ceramic Mask That Appears Fused To The Being's Head",   # retyped, not copied
    "a ceramic mask that appears fused to the being’s head",  # curly apostrophe
    "a ceramic  mask that appears fused\nto the being's head",  # re-wrapped
])
def test_evidence_locating_a_quote_survives_case_and_curly_punctuation(quote):
    """A model that retypes a span instead of pasting it has still pointed at the right
    evidence. Failing it costs the run's one corrective retry over a quotation mark —
    and NFKC folds neither case nor U+2019."""
    scenes = _evidence_scene([_fact("가면은 머리에 융합된 것으로 보인다", quote)])
    assert [n["code"] for n in chain._check_fact_evidence(scenes, SOURCE)] == []


def test_evidence_a_quote_too_short_to_be_evidence_is_rejected():
    """"the" is a verbatim span of every article in `data/scps.json`. Without a floor
    the locatability check passes vacuously on exactly the input it exists to catch."""
    scenes = _evidence_scene([_fact("등급은 유클리드다", "the")])
    notes = chain._check_fact_evidence(scenes, SOURCE)
    assert [n["code"] for n in notes] == ["quote_not_found"]
    assert "too short" in notes[0]["detail"]
    assert scenes[0]["fact_references"][0]["quote_verified"] is False


def test_evidence_a_hedge_just_outside_the_quote_is_still_a_dropped_hedge():
    """The defect this check exists for, quoted so as to hide from it: the source says
    "appears fused", the outline quotes only "fused to the being's head" and states it
    as settled fact. Reading the quote alone reports nothing."""
    scenes = _evidence_scene([_fact("가면은 머리에 융합되어 있다", "fused to the being's head")])
    notes = chain._check_fact_evidence(scenes, SOURCE)
    assert [n["code"] for n in notes] == ["hedge_dropped"]
    assert "appears" in notes[0]["detail"]


@pytest.mark.parametrize("statement", [
    "그는 일반적으로 협조적이며 말할 수 있다",       # "can speak" — a capability, not a hedge
    "재단은 개체를 표준 격리실에 수용할 수 있었다",   # "was able to" — a fact, not a doubt
])
def test_evidence_ordinary_korean_does_not_read_as_a_hedge(statement):
    """`수 있`/`듯` as bare substrings match extremely common non-hedging Korean, so a
    genuine certainty upgrade in the same sentence suppressed its own note."""
    assert not chain._HEDGE_IN_STATEMENT.search(statement)


def test_evidence_hedge_preserved_in_the_statement_is_not_flagged():
    scenes = _evidence_scene(
        [_fact("가면은 머리에 융합된 것으로 보인다", "a ceramic mask that appears fused to the being's head")],
        what="가면은 머리에 융합된 것으로 보인다", consequence="가면이 융합된 것으로 보인다고 기록됐다",
    )
    assert chain._check_fact_evidence(scenes, SOURCE) == []


def test_evidence_unsupported_event_is_a_note_never_an_exception():
    """Three of the ablation's four fabrications were `event` fields, not
    `fact_references` — B 씬8's "실패한 재활성화 기록" was `event.what` verbatim."""
    scenes = _evidence_scene(
        [_fact("맨손 접촉만으로 사람이 죽는다", "Physical contact with its bare hands causes death")],
        what="과거의 실패한 재활성화 기록을 열람했다", consequence="더 많은 환자를 요구하는 메모가 남았다",
    )
    notes = chain._check_fact_evidence(scenes, SOURCE)
    assert sorted(n["code"] for n in notes) == ["event_unsupported", "event_unsupported"]
    assert "event.what" in notes[0]["detail"]


def test_evidence_without_source_text_skips_every_check_and_says_so():
    scenes = _evidence_scene([_fact("아무 문장", "nothing at all")], what="x", consequence="y")
    assert chain._check_fact_evidence(scenes, "") == [
        {"scene": 0, "code": "source_unavailable",
         "detail": "no scp_text in scope — outline evidence was not checked at all"}
    ]
    assert chain._check_fact_evidence(scenes, None)[0]["code"] == "source_unavailable"
    # and nothing was stamped, because nothing was checked
    assert "quote_verified" not in scenes[0]["fact_references"][0]


@pytest.mark.parametrize("scenes", [
    None, "not a list", [], [None], ["scene"], [{}], [{"fact_references": "x"}],
    [{"fact_references": ["bare string"], "event": None}],
    [{"fact_references": [{"statement": 1, "quote": None}], "event": "x"}],
])
def test_check_fact_evidence_never_raises_on_a_malformed_outline(scenes):
    """It runs inside `parse`, BEFORE `_validate_retention_outline` has rejected
    anything, so every shape it touches is still untrusted."""
    assert isinstance(chain._check_fact_evidence(scenes, SOURCE), list)


def test_evidence_note_scene_numbers_are_positional():
    scenes = [
        {"fact_references": [_fact("a", "its bare hands causes death")],
         "event": {"what": "a", "consequence": "a"}},
        {"scene_num": 99, "fact_references": [_fact("b", "not in the source")], "event": {}},
    ]
    notes = chain._check_fact_evidence(scenes, SOURCE)
    assert [n["scene"] for n in notes if n["code"] == "quote_not_found"] == [2]


# --- structure_step: strict on attempt 1, notes on the last -------------------


def _grounded_outline(total: int, quote: str) -> str:
    outline = _retention_outline(total)
    for scene in outline:
        scene["fact_references"] = [_fact("맨손 접촉만으로 사람이 죽는다", quote)]
        scene["event"] = {"who": "연구원", "what": "맨손 접촉만으로 사람이 죽는다",
                          "consequence": "맨손 접촉으로 사람이 죽었다"}
    return yaml.safe_dump({"scenes": outline}, allow_unicode=True)


async def test_structure_step_rejects_an_ungrounded_quote_and_buys_one_retry(monkeypatch):
    """AC1: the rejection is a `ValueError` from `parse`, which `_parse_with_retry`
    turns into exactly ONE corrective regeneration with the error fed back. Not a
    `RetentionError` — that is raised after the await and would fail the run."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    bad = _grounded_outline(4, "SCP-049 is classified Euclid")
    good = _grounded_outline(4, "Physical contact with its bare hands causes death")
    payloads, errors = [bad, good], []

    async def call(rendered, s):
        errors.append(rendered)
        return payloads.pop(0), {}, "stop"

    sink: list[dict] = []
    outline = await chain.structure_step(
        "SCP-049", SOURCE, {"frozen_descriptor": "d"}, "guide", None, call, grounding_sink=sink,
    )
    assert len(errors) == 2, "exactly one corrective retry, no third pass"
    assert sink == [], "the retry grounded it, so nothing reaches the gate"
    assert len(outline) == 4


async def test_structure_step_keeps_the_outline_when_the_retry_also_fails(monkeypatch):
    """AC2: the run is never failed on an evidence verdict. The statement survives for
    the writer and the note reaches the gate payload instead."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    bad = _grounded_outline(4, "SCP-049 is classified Euclid")
    calls = {"n": 0}

    async def call(rendered, s):
        calls["n"] += 1
        return bad, {}, "stop"

    sink: list[dict] = []
    outline = await chain.structure_step(
        "SCP-049", SOURCE, {"frozen_descriptor": "d"}, "guide", None, call, grounding_sink=sink,
    )
    assert calls["n"] == 2, "no third pass"
    assert len(outline) == 4 and outline[0]["fact_references"][0]["statement"]
    assert {n["code"] for n in sink} == {"quote_not_found"}
    assert len(sink) == 4  # one per scene, all four of them


async def test_a_first_payload_that_dies_on_shape_does_not_make_the_retry_strict(monkeypatch):
    """The I/O matrix says "Quote absent, final attempt … run continues". A parse
    counter kept by the closure never saw attempt 1 (it dies above the counter), so the
    retry's payload looked like the FIRST one, raised, and failed the run on an
    evidence verdict — with no retry left to spend."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    shape_failure = yaml.safe_dump({"scenes": []}, allow_unicode=True)
    ungrounded = _grounded_outline(4, "SCP-049 is classified Euclid")
    call, calls = _scripted(shape_failure, ungrounded)

    sink: list[dict] = []
    outline = await chain.structure_step(
        "SCP-049", SOURCE, {"frozen_descriptor": "d"}, "guide", None, call, grounding_sink=sink,
    )
    assert calls["n"] == 2, "still exactly one corrective retry"
    assert len(outline) == 4, "the run survives — the notes go to the gate"
    assert {n["code"] for n in sink} == {"quote_not_found"}


async def test_a_yaml_repaired_payload_still_gets_its_corrective_retry(monkeypatch):
    """Story 6.11's deterministic repair calls `parse` again from inside the YAMLError
    handler, where a `ValueError` used to propagate straight out of `_parse_with_retry`
    — killing the run over an ungrounded quote that had an unspent retry sitting there,
    purely because the same payload had also needed a YAML fix."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    # An unquoted `: ` inside a free-text scalar — the exact class `_blockify_line` fixes.
    broken = _grounded_outline(4, "SCP-049 is classified Euclid").replace(
        "synopsis: scene 1", "synopsis: scene 1: 격리 실패"
    )
    good = _grounded_outline(4, "Physical contact with its bare hands causes death")
    call, calls = _scripted(broken, good)

    sink: list[dict] = []
    outline = await chain.structure_step(
        "SCP-049", SOURCE, {"frozen_descriptor": "d"}, "guide", None, call, grounding_sink=sink,
    )
    assert calls["n"] == 2 and len(outline) == 4
    assert sink == [], "the retry grounded it"


async def test_a_truncation_reroll_gets_a_fresh_correction_budget(monkeypatch):
    """`reroll_on_truncation` restarts `_parse_with_retry` whole, so the re-roll's first
    payload has a corrective retry again. A counter that outlives the re-roll would let
    that payload through leniently and skip the correction entirely."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    bad = _grounded_outline(4, "SCP-049 is classified Euclid")
    good = _grounded_outline(4, "Physical contact with its bare hands causes death")
    replies = [(bad, "stop"), ("", "length"), (bad, "stop"), (good, "stop")]
    calls = {"n": 0}

    async def call(rendered, s):
        calls["n"] += 1
        raw, finish = replies[calls["n"] - 1]
        return raw, {}, finish

    sink: list[dict] = []
    outline = await chain.structure_step(
        "SCP-049", SOURCE, {"frozen_descriptor": "d"}, "guide", None, call, grounding_sink=sink,
    )
    assert calls["n"] == 4, "call 1 rejected, call 2 truncated, then the re-roll's pair"
    assert len(outline) == 4 and sink == [], "the re-roll's own correction actually ran"


async def test_an_unsupported_event_never_spends_the_corrective_retry(monkeypatch):
    """The I/O matrix: "Note only — dramatization is legitimate, so this never
    hard-fails". Its measured precision is 2 정탐 / 2 경계 / 2 오탐 live, so making it
    buy a regeneration spends the run's one correction on a trigram artefact."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    outline_yaml = yaml.safe_dump({"scenes": [
        {**scene,
         "fact_references": [_fact("맨손 접촉만으로 사람이 죽는다",
                                   "Physical contact with its bare hands causes death")],
         "event": {"who": "연구원", "what": "무관한 사건이 벌어졌다", "consequence": "무관한 결과가 남았다"}}
        for scene in _retention_outline(4)
    ]}, allow_unicode=True)
    call, calls = _scripted(outline_yaml)

    sink: list[dict] = []
    await chain.structure_step(
        "SCP-049", SOURCE, {"frozen_descriptor": "d"}, "guide", None, call, grounding_sink=sink,
    )
    assert calls["n"] == 1, "no regeneration was bought"
    assert {n["code"] for n in sink} == {"event_unsupported"}


async def test_the_retry_feedback_carries_the_offending_quote_not_just_a_code(monkeypatch):
    """`s3 quote_not_found` names a scene and a code the model then has to guess the
    referent of, while ~280 of the 500-char budget went to rules the prompt already
    states. The text it must fix is the one thing it cannot re-derive."""
    _, captured = _recording_prompt_service(monkeypatch)
    call, _ = _scripted(
        _grounded_outline(4, "SCP-049 is classified Euclid"),
        _grounded_outline(4, "Physical contact with its bare hands causes death"),
    )
    await chain.structure_step("SCP-049", SOURCE, {"frozen_descriptor": "d"}, "guide", None, call)
    assert "SCP-049 is classified Euclid" in captured["parse_error"], "the retry never saw the quote"


async def test_structure_step_returns_a_plain_list_and_the_sink_is_optional(monkeypatch):
    """The live drivers monkeypatch this function and return a bare list; carrying the
    notes in the return value would break all three of them."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    call, _ = _scripted(_grounded_outline(4, "Physical contact with its bare hands causes death"))
    outline = await chain.structure_step("SCP-049", SOURCE, {"frozen_descriptor": "d"}, "guide", None, call)
    assert isinstance(outline, list) and all(isinstance(scene, dict) for scene in outline)


async def test_structure_step_with_no_source_text_does_not_spend_the_retry(monkeypatch):
    """`source_unavailable` is the caller's gap, not the model's: no regeneration could
    conjure an article, so it degrades to a gate note without buying an attempt."""
    monkeypatch.setattr("yt_flow.services.prompt_service.get_prompt", lambda *a, **k: FakePrompt())
    calls = {"n": 0}

    async def call(rendered, s):
        calls["n"] += 1
        return _retention_yaml(4), {}, "stop"

    sink: list[dict] = []
    await chain.structure_step("SCP-049", "", {"frozen_descriptor": "d"}, "guide", None, call,
                               grounding_sink=sink)
    assert calls["n"] == 1
    assert [n["code"] for n in sink] == ["source_unavailable"]


async def test_structure_step_passes_the_source_article_to_the_prompt(monkeypatch):
    """AC1's precondition: the outline cannot quote a source it has never seen."""
    _, captured = _recording_prompt_service(monkeypatch)
    call, _ = _scripted(_grounded_outline(4, "Physical contact with its bare hands causes death"))
    await chain.structure_step("SCP-049", SOURCE, {"frozen_descriptor": "d"}, "guide", None, call)
    assert captured["scp_source_text"] == SOURCE


# --- fact_references shape ---------------------------------------------------


@pytest.mark.parametrize("bad", [
    ["bare string"],                                   # the pre-12.8 shape
    [{"statement": "사실"}],                            # no evidence
    [{"quote": "evidence"}],                           # nothing for the writer to read
    [{"statement": "", "quote": "evidence"}],
    [{"statement": "사실", "quote": "  "}],
    [{"statement": ["사실"], "quote": "evidence"}],
    [], None, "x",
])
def test_retention_fact_references_must_be_statement_quote_pairs(bad):
    outline = _retention_outline(8)
    outline[1]["fact_references"] = bad
    assert _raises(outline) == "fact_references_invalid"


def test_retention_fact_references_accepts_the_pair_and_ignores_extra_keys():
    outline = _retention_outline(8)
    outline[1]["fact_references"] = [{"statement": "사실", "quote": "evidence", "quote_verified": False}]
    chain._validate_retention_outline(outline)  # does not raise


# --- the writer's blindfold (AC6) --------------------------------------------


def test_writer_facts_flattens_the_pair_to_the_statements_the_writer_always_read():
    scene = {"synopsis": "x", "fact_references": [
        _fact("맨손 접촉만으로 사람이 죽는다", "Physical contact with its bare hands causes death"),
        {"statement": "두 번째 사실", "quote": "q2", "quote_verified": False},
    ]}
    out = chain._writer_facts(scene)
    assert out["fact_references"] == ["맨손 접촉만으로 사람이 죽는다", "두 번째 사실"]
    assert out["synopsis"] == "x"
    assert scene["fact_references"][0]["quote"], "the original outline entry is not mutated"


@pytest.mark.parametrize("scene", [None, "x", 3, {}, {"fact_references": "x"}, {"fact_references": None}])
def test_writer_facts_never_raises_on_a_scene_it_cannot_read(scene):
    assert isinstance(chain._writer_facts(scene), dict)


def test_writing_brief_carries_no_source_quote(monkeypatch):
    """Writer boundary #1. Story 8.8 measured `article_fidelity -1.00` when the writer
    had the article; this story hands it to the OUTLINE, and the quote comes off here."""
    outline = _retention_outline(4)
    for scene in outline:
        scene["fact_references"] = [_fact("맨손 접촉만으로 사람이 죽는다", "bare hands causes death")]
    brief = chain._writing_scene_brief(outline, 1)
    assert "bare hands causes death" not in brief
    assert "맨손 접촉만으로 사람이 죽는다" in brief
    assert json.loads(brief[brief.index("{"):])["write_only_this_scene"]["fact_references"] == [
        "맨손 접촉만으로 사람이 죽는다"
    ]


def test_writing_brief_hides_the_verification_flag_too():
    """`quote_verified` is an operator signal. A writer told a fact is unconfirmed
    would hedge narration the outline meant as fact."""
    outline = _retention_outline(4)
    outline[1]["fact_references"] = [
        {"statement": "사실", "quote": "evidence", "quote_verified": False}
    ]
    assert "quote_verified" not in chain._writing_scene_brief(outline, 1)


# --- the seeding guard (a prompt-shape decision that only reaches prompts/) ---


_SEEDED_PRE_12_8 = " ".join("{{" + name + "}}" for name in chain._STRUCTURE_BUDGET_VARIABLES)


async def test_structure_step_rejects_a_prompt_version_that_never_reads_the_source(monkeypatch):
    """An unseeded template renders without error and emits bare-string
    `fact_references`, so both attempts die on `fact_references_invalid` and the
    failure names the model rather than the prompt version. Fail at the fetch."""
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt", lambda *a, **k: _SeededPrompt(_SEEDED_PRE_12_8)
    )

    async def call(rendered, s):
        raise AssertionError("the provider must not be called on a stale prompt")

    with pytest.raises(RuntimeError) as excinfo:
        await chain.structure_step("SCP-049", SOURCE, {"frozen_descriptor": "d"}, "guide", None, call)
    message = str(excinfo.value)
    assert "scp_source_text" in message
    assert "12.8" in message
    assert "migrate_prompts.py" in message


def test_the_repo_structure_prompt_would_pass_the_12_8_seeding_check(monkeypatch):
    """The guard is only useful if the file `migrate_prompts.py` seeds satisfies it."""
    monkeypatch.setattr(
        "yt_flow.services.prompt_service.get_prompt",
        lambda *a, **k: _SeededPrompt(_prompt_text("structure.md")),
    )
    chain._require_seeded_budget_variables()


# --- prompt-text pins --------------------------------------------------------


def test_structure_prompt_reads_the_source_article_and_demands_a_quote():
    content = _prompt_text("structure.md")
    assert "{{scp_source_text}}" in content, "the outline still cannot see the source"
    assert "quote:" in content and "statement:" in content
    # Ported verbatim from `critic_agent.md:42` — the rule that existed for the writer
    # and not for the outline, which is where the certainty is actually being raised.
    assert "'~로 보인다'를 '~이다'로 올리는 것도 단언" in content
    assert "appears" in content, "the hedge markers the check looks for are not named"


def test_structure_prompt_no_longer_shows_a_bare_string_fact_reference():
    """The old exemplar is now a rejected shape; leaving it would teach the model to
    emit exactly what `fact_references_invalid` rejects."""
    content = _prompt_text("structure.md")
    assert '  - "재단 인원 14명이 목이 꺾인 채 사망했다"' not in content
    assert re.search(r"fact_references:\n\s*- statement:", content), "the pair exemplar is gone"


def _real_articles() -> list[str]:
    path = Path(__file__).parents[3] / "data" / "scps.json"
    return [chain._evidence_text(r["scp_text"]) for r in json.loads(path.read_text(encoding="utf-8"))]


def test_every_exemplar_quote_in_the_prompt_is_a_real_span_of_a_real_article():
    """A few-shot exemplar is copied. An invented `quote:` in the prompt teaches the
    model to invent one — producing exactly the `quote_not_found` this check exists to
    catch, from the instruction that was supposed to prevent it."""
    quotes = re.findall(r'^\s*quote: "([^"]+)"', _prompt_text("structure.md"), re.M)
    assert quotes, "the exemplar pairs are gone"
    articles = _real_articles()
    for quote in quotes:
        assert any(chain._evidence_text(quote) in article for article in articles), \
            f"{quote!r} appears in no article in data/scps.json"


def test_the_structure_cassette_quotes_are_real_spans_of_its_own_article():
    """Same trap in the fixture: the cassette is an SCP-173 outline, so its quotes have
    to be locatable in SCP-173. Recorded quotes that are not make the fixture a
    demonstration of the defect."""
    content = _load_cassette("deepseek_structure.json")["choices"][0]["message"]["content"]
    scenes = yaml.safe_load(content)["scenes"]
    path = Path(__file__).parents[3] / "data" / "scps.json"
    article = next(r["scp_text"] for r in json.loads(path.read_text(encoding="utf-8"))
                   if r["id"] == "SCP-173")
    notes = [n for n in chain._check_fact_evidence(scenes, article) if n["code"] == "quote_not_found"]
    assert notes == []


def test_structure_prompt_disciplines_the_event_fields_too():
    content = _prompt_text("structure.md")
    assert "event.what" in content and "event.consequence" in content
    assert "fact_references" in content.split("`what`과 `consequence`")[1][:400]


# AC8: every grounding criterion, threshold and issue type the two judges carried
# before this story, named one by one. The previous version of this test asserted that
# two substrings existed SOMEWHERE in the file, which it still would after deleting
# essentially every criterion below — a story whose entire thesis is "the judges were
# right, the bill went to the wrong floor" cannot be guarded by that.
_UNLOOSENED = {
    "critic_agent.md": (
        # criterion 7 itself, and the one-line boundary that defines it
        "**Fidelity**: 나레이션이 **아래 SCP Fact Sheet에 없는 사실을 단언하는가?**",
        "**경계선은 하나입니다: 새 사실을 단언했는가.**",
        # the certainty-escalation rule this story ported into `structure.md`
        '원문이 "~로 보인다"라고 한 것을 "~이다"로 올리는 것도 **단언**입니다.',
        # the verdict threshold — one occurrence is enough to fail the whole script
        '**Fact Sheet에 없는 사실을 단언한 곳이 하나라도 있으면 ALWAYS "retry"**',
        # the typed vocabulary the gate's categories are computed from
        *(f"`{issue_type}`" for issue_type in domain_state.CRITIC_ISSUE_TYPES if issue_type != "other"),
    ),
    "review.md": (
        "A contradiction is only reportable with **quoted evidence on both sides**.",
        # all five required evidence fields — dropping any one makes the claim uncheckable
        "`narration_quote`", "`grounding_source`", "`grounding_quote`",
        "`explanation`", "`correction`",
        "Any grounded contradiction fails the review.",
        "Do not report `overall_pass: true` alongside one.",
        # the same certainty-upgrade rule, on the review side
        "확실성을 올린 **새 단언**입니다.",
        *domain_state.REVIEW_ISSUE_TYPES,
    ),
}


@pytest.mark.parametrize(
    "name,pin",
    [(name, pin) for name, pins in _UNLOOSENED.items() for pin in pins],
    ids=lambda v: v[:40],
)
def test_the_judging_prompts_were_not_loosened(name, pin):
    """AC7/AC8: the ablation's findings were all correct — the bill was addressed to
    the wrong floor. Nothing here may be weakened to make the attribution look better,
    so every criterion, evidence requirement, threshold and issue type is pinned."""
    assert pin in _prompt_text(name), f"{name} no longer carries: {pin}"
