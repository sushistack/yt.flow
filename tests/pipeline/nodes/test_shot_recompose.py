"""Tests for shot_recompose (Story 10.1c).

Every assertion here pins something that was established live on 2026-08-09 and cost a
render to learn. They are regression guards for prompt/wiring rules, not unit trivia.
"""

import json

import pytest

from yt_flow.pipeline.nodes.shot_recompose import (
    CARD_A_NODE,
    CARD_B_NODE,
    PLATE_NODE,
    PROMPT_NODE,
    _load_workflow,
    _upload_name,
    build_single_pass,
    order_cast,
    placement_instruction,
    recompose_digest,
)


def _template(verified=True):
    return {
        "ytflow_verified_recompose_qwen": verified,
        "_ytflow_note": "not a node",
        "plate": {"class_type": "LoadImage", "inputs": {"image": "p.png"}},
        "card_a": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
        "card_b": {"class_type": "LoadImage", "inputs": {"image": "b.png"}},
        "positive": {"class_type": "TextEncodeQwenImageEditPlus",
                     "inputs": {"prompt": "x", "image1": ["plate", 0],
                                "image2": ["card_a", 0], "image3": ["card_b", 0]}},
        "sampler": {"class_type": "KSampler", "inputs": {"denoise": 1.0}},
    }


# ── placement instruction ────────────────────────────────────────────────────


def test_instruction_uses_appearance_not_ordinal():
    """"the second image" does not resolve. Live: two-card shots put the wrong figure on the
    wrong side at the wrong scale until the reference became an appearance description."""
    s = placement_instruction("the man in the orange prison jumpsuit", "left", "mid")
    assert "the man in the orange prison jumpsuit" in s
    assert "second image" not in s and "third image" not in s


@pytest.mark.parametrize("depth", ["near", "mid", "far"])
def test_every_depth_band_demands_whole_body(depth):
    """`near` without this was rendered as a face close-up filling half the frame."""
    assert "whole body" in placement_instruction("a figure", "center", depth)


def test_instruction_preserves_existing_figures_without_a_framing_clause():
    """Pass 2 must not disturb pass 1 — but the framing clause is NOT the way to say it.

    Adding "its camera angle and framing" to this sentence made pass 1 draw the character
    TWICE (live, S00403: two plague doctors side by side), and pass 2 then faithfully
    preserved both. The short form is what the 43-plate sweep was verified on.
    """
    s = placement_instruction("a figure", "right", "near")
    assert "everyone already in it" in s
    assert "camera angle and framing" not in s


def test_pose_is_carried_when_not_default():
    assert "kneeling" in placement_instruction("a figure", "left", "mid", pose="kneeling")
    assert placement_instruction("a figure", "left", "mid", pose="standing").count("standing") == 1


def test_unknown_position_and_depth_fall_back_to_centre_mid():
    s = placement_instruction("a figure", "nonsense", "nonsense")
    assert "centre of the frame" in s and "mid distance" in s


# ── insertion order ──────────────────────────────────────────────────────────


def test_far_band_is_inserted_first_so_near_lands_in_front():
    cast = [{"depth": "near", "k": 1}, {"depth": "far", "k": 2}, {"depth": "mid", "k": 3}]
    assert [c["k"] for c in order_cast(cast)] == [2, 3, 1]


def test_missing_depth_sorts_as_mid():
    assert [c["k"] for c in order_cast([{"k": 1}, {"depth": "far", "k": 2}])] == [2, 1]


# ── workflow assembly ────────────────────────────────────────────────────────


def test_single_pass_drops_second_card_slot_and_non_node_keys():
    """One character per pass — passing both cards at once is what broke scale control.
    The marker bool must not reach ComfyUI: validate_prompt walks every top-level key and 500s."""
    wf = build_single_pass(_template(), "plate.png", "card.png", "PROMPT")
    assert wf[PLATE_NODE]["inputs"]["image"] == "plate.png"
    assert wf[CARD_A_NODE]["inputs"]["image"] == "card.png"
    assert CARD_B_NODE not in wf
    assert "image3" not in wf[PROMPT_NODE]["inputs"]
    assert wf[PROMPT_NODE]["inputs"]["prompt"] == "PROMPT"
    assert "ytflow_verified_recompose_qwen" not in wf and "_ytflow_note" not in wf


def test_single_pass_does_not_mutate_the_template():
    tpl = _template()
    build_single_pass(tpl, "p.png", "c.png", "x")
    assert tpl["card_b"]["inputs"]["image"] == "b.png"
    assert "image3" in tpl["positive"]["inputs"]


def test_unverified_workflow_is_refused(tmp_path):
    p = tmp_path / "wf.json"
    p.write_text(json.dumps(_template(verified=False)))
    with pytest.raises(ValueError, match="ytflow_verified_recompose_qwen"):
        _load_workflow(str(p))


def test_verified_workflow_loads(tmp_path):
    p = tmp_path / "wf.json"
    p.write_text(json.dumps(_template()))
    assert _load_workflow(str(p))["plate"]["class_type"] == "LoadImage"


def test_shipped_recompose_workflow_is_wellformed():
    """Guard the real file: nothing else loads it in tests."""
    wf = json.loads(open("data/workflows/comfyui_shot_recompose_qwen_api.json").read())
    for node_id in (PLATE_NODE, CARD_A_NODE, CARD_B_NODE):
        assert wf[node_id]["class_type"] == "LoadImage"
    # the plate is the canvas: the latent must be encoded from it, not an empty one
    assert wf["latent"]["inputs"]["pixels"] == ["plate", 0]
    # fp8 text encoder, NOT the GGUF one — the Q4 GGUF ships no vision tower and every
    # prompt died on "mat1 and mat2 shapes cannot be multiplied"
    assert wf["clip"]["inputs"]["clip_name"].endswith(".safetensors")


# ── upload naming ────────────────────────────────────────────────────────────


def test_upload_names_disambiguate_shared_basenames_and_passes():
    from pathlib import Path

    a = Path("/assets/characters/SCP-049/epoch_1/front_candidate_1.png")
    b = Path("/assets/characters/SCP-049-2/epoch_1/front_candidate_1.png")
    assert a.name == b.name                              # the hazard
    assert _upload_name(a, "s:0") != _upload_name(b, "s:0")   # different cards
    assert _upload_name(a, "s:0") != _upload_name(a, "s:1")   # different passes
    assert _upload_name(a, "s:0") == _upload_name(a, "s:0")   # stable


def test_digest_changes_with_prompt_and_card():
    base = recompose_digest(b"plate", ["c1"], ["p1"])
    assert base != recompose_digest(b"plate", ["c1"], ["p2"])
    assert base != recompose_digest(b"plate", ["c2"], ["p1"])
    assert base != recompose_digest(b"other", ["c1"], ["p1"])
