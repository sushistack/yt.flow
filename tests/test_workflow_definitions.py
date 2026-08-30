"""Structural guards on the shipped ComfyUI workflow JSONs (Story 10.3).

A dangling node reference is otherwise only discoverable as a live HTTP 400 from
ComfyUI, and a base-model-mismatched LoRA is only discoverable as a silent storm
of `lora key not loaded` in ComfyUI's own log. Story 10.3 measured that
`horror.safetensors` is SD1.5-layout (342 unloaded keys + 73 shape errors per
patch against AnimagineXL v3.1, a genuine SDXL checkpoint) while
`darkness_xl_v2.safetensors` loads clean (0 + 0), and removed the former from all
five workflows. The allowlist below is what keeps it from coming back.

ponytail: pure stdlib, table-driven over a glob, no fixtures.
"""

import ast
import functools
import importlib.util
import json
from pathlib import Path

import pytest

from yt_flow.pipeline.nodes import image
from yt_flow.pipeline.nodes.composite_harmonization import ICLIGHT_NODE_KEYS
from yt_flow.services import character_image_provider
from yt_flow.services.comfyui_client import resolve_nodes


@functools.cache
def _plate_node_keys() -> tuple[str, ...]:
    """The seed script is a script, not a package — load it by path like its own
    test module does, so its key tuple cannot drift from this table.

    Called from inside the test, never at module import: executing a 679-line
    script during collection makes any unrelated failure in it fail *every* test
    in this file, and that script re-runs its own top-level ``sys.path.insert``
    on each exec. ``functools.cache`` keeps it to one exec per session here.
    """
    spec = importlib.util.spec_from_file_location(
        "seed_location_plates", Path(__file__).resolve().parents[1] / "scripts" / "seed_location_plates.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.PLATE_NODE_KEYS


WORKFLOW_DIR = Path(__file__).resolve().parents[1] / "data" / "workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.json"))

# base model -> LoRAs whose tensor layout was verified against *that* base on live
# ComfyUI. Adding a name here means "measured", not "the file exists". A global
# list would let an SDXL-verified LoRA into a Qwen graph and vice versa, which is
# the same mismatch class Story 10.3 was opened for.
# See _bmad-output/implementation-artifacts/10-3-live-validation/.
ALLOWED_LORAS = {
    "AnimagineXL_v31.safetensors": {"darkness_xl_v2.safetensors"},
    "qwen-image-edit-2511-Q4_K_M.gguf": {
        "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
    },
}

API2 = "comfyui_sdxl_anime_lora_workflow_api2.json"
PLATE = "comfyui_location_plate_api.json"
ICLIGHT = "comfyui_iclight_relight_api.json"
MULTI_ANGLE = "comfyui_character_multi_angle_api.json"
POSE_GUIDE = Path(character_image_provider._POSE_GUIDE_WORKFLOW_PATH).name

# Story 13.3: the manifest keys each consumer resolves at load. This table is the
# only net that catches a ComfyUI-UI re-export — the UI rewrites `_meta.title`
# happily, and every one of these lookups is exact-match with no id fallback, so a
# rename fails a live render at the first shot. Sourced from the consumers, not
# retyped: a key added in code with no title in the JSON fails here. Each value's
# key tuple is a zero-arg callable so nothing is imported at collection time.
CONSUMER_KEYS = {
    API2: ("src/yt_flow/pipeline/nodes/image.py", lambda: (image.POSITIVE_KEY, image.NEGATIVE_KEY)),
    PLATE: ("scripts/seed_location_plates.py", _plate_node_keys),
    ICLIGHT: ("src/yt_flow/pipeline/nodes/composite_harmonization.py", lambda: ICLIGHT_NODE_KEYS),
    MULTI_ANGLE: (
        "src/yt_flow/services/character_image_provider.py",
        lambda: (
            character_image_provider._POSITIVE_NODE_TITLE,
            character_image_provider._NEGATIVE_NODE_TITLE,
        ),
    ),
    # ``_is_guide_node`` is an EXACT match on ``ytflow:guide_image`` with no
    # fallback of any kind, and this is the only committed file declaring it.
    # Rename it in the UI and ``_inject_guide_image`` logs a warning and returns
    # the graph unconditioned — after which ``_drop_reference_only_nodes`` /
    # ``_remove_i2i_input`` delete the guide LoadImage out from under a live
    # ControlNetApplyAdvanced link, the hazard ``_is_guide_node``'s own docstring
    # documents. Story 13.3's first review pass rejected this row as "keyword-
    # scanned, degrades gracefully"; it is neither.
    POSE_GUIDE: (
        "src/yt_flow/services/character_image_provider.py",
        lambda: (
            character_image_provider._POSITIVE_NODE_TITLE,
            character_image_provider._NEGATIVE_NODE_TITLE,
            character_image_provider._GUIDE_NODE_TITLE,
        ),
    ),
}

# Any class whose name starts with this patches a LoRA into the model/clip chain
# (`LoraLoader`, `LoraLoaderModelOnly`, ...). Matching the exact string once let
# `LoraLoaderModelOnly` through unchecked.
LORA_PREFIX = "LoraLoader"
BASE_MODEL_FIELDS = ("ckpt_name", "unet_name")


def nodes(path: Path) -> dict:
    """Node id -> node.

    Some workflows carry `ytflow_verified_*` / `_ytflow_note` scalars alongside
    the graph as provenance markers; the nodes that consume those workflows strip
    them before submitting. Requiring `class_type` keeps such a key from being
    scanned as a node *or* accepted as a valid link target.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if isinstance(v, dict) and "class_type" in v}


def lora_names(graph: dict) -> set[str]:
    return {
        name
        for node in graph.values()
        if str(node.get("class_type", "")).startswith(LORA_PREFIX)
        if isinstance(name := (node.get("inputs") or {}).get("lora_name"), str)
    }


def base_models(graph: dict) -> set[str]:
    return {
        value
        for node in graph.values()
        for field in BASE_MODEL_FIELDS
        if isinstance(value := (node.get("inputs") or {}).get(field), str)
    }


def model_chain_sources(graph: dict, node_id: str) -> list[str]:
    """class_types feeding `node_id`'s `model` input, nearest first."""
    chain, seen = [], set()
    current = graph.get(node_id, {}).get("inputs", {}).get("model")
    while isinstance(current, list) and len(current) == 2 and str(current[0]) not in seen:
        nid = str(current[0])
        seen.add(nid)
        node = graph.get(nid)
        if node is None:
            break
        chain.append(node.get("class_type"))
        current = (node.get("inputs") or {}).get("model")
    return chain


def test_workflows_found():
    assert WORKFLOWS, f"no workflow JSONs under {WORKFLOW_DIR}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_node_reference_resolves(path: Path):
    graph = nodes(path)
    dangling = [
        (nid, field, value)
        for nid, node in graph.items()
        for field, value in (node.get("inputs") or {}).items()
        # ComfyUI exports link ids as strings, but hand-edited graphs sometimes
        # carry ints; str() so an int id is checked rather than skipped.
        if isinstance(value, list) and len(value) == 2 and str(value[0]) not in graph
    ]
    assert not dangling, f"{path.name} references missing node ids: {dangling}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_only_allowlisted_loras(path: Path):
    graph = nodes(path)
    used = lora_names(graph)
    if not used:
        return
    bases = base_models(graph)
    assert len(bases) == 1, f"{path.name} loads LoRAs but has base models {sorted(bases)}"
    base = bases.pop()
    allowed = ALLOWED_LORAS.get(base, set())
    assert used <= allowed, (
        f"{path.name} loads {sorted(used - allowed)} onto {base}; verify the tensor "
        "layout against that base model on live ComfyUI before allowlisting"
    )


@pytest.mark.parametrize("name", sorted(CONSUMER_KEYS), ids=lambda n: n)
def test_committed_workflow_resolves_every_key_its_consumer_needs(name: str):
    """The data test Story 13.3 exists for.

    Every unit test above works on hand-built fixtures; nothing else asserts that
    the JSON actually shipped still declares the titles the code looks up. A
    ComfyUI-UI round-trip that renames or drops one would otherwise surface as a
    failed live render, hours in.
    """
    consumer, read_keys = CONSUMER_KEYS[name]
    keys = read_keys()
    workflow = json.loads((WORKFLOW_DIR / name).read_text(encoding="utf-8"))
    resolved = resolve_nodes(workflow, keys)  # raises, naming the missing key
    assert sorted(resolved) == sorted(keys), consumer
    assert len(set(resolved.values())) == len(resolved), f"{name}: two keys resolved to one node"


def test_api2_satisfies_image_node_contract():
    """image.py resolves its prompt nodes by title and seeds every KSampler by class."""
    graph = nodes(WORKFLOW_DIR / API2)
    resolved = resolve_nodes(graph, (image.POSITIVE_KEY, image.NEGATIVE_KEY))
    for node_id in resolved.values():
        assert graph[node_id]["class_type"] == "CLIPTextEncode"
    assert any(node.get("class_type") == "KSampler" for node in graph.values())


@pytest.mark.parametrize("name", [API2, PLATE])
def test_style_lora_still_reaches_the_sampler(name: str):
    """An allowlist alone passes vacuously once the LoRA is deleted or bypassed.

    Silently losing the style LoRA is the same class of defect as silently failing
    to apply it, so assert it is still wired into the sampler's model input.
    """
    graph = nodes(WORKFLOW_DIR / name)
    sampler = next(nid for nid, n in graph.items() if n.get("class_type") == "KSampler")
    chain = model_chain_sources(graph, sampler)
    assert any(str(c).startswith(LORA_PREFIX) for c in chain), (
        f"{name}: KSampler model input no longer passes through a LoraLoader ({chain})"
    )


def test_plate_t2i_fallback_target_is_still_a_lora_loader():
    """The seed script rewires the sampler's model input to `ytflow:model` when it
    strips the IPAdapter. Story 13.3 replaced the hardcoded "11" with the title, but
    the node behind it must still be the LoRA loader or the fallback loses the style.
    """
    graph = nodes(WORKFLOW_DIR / PLATE)
    model_id = resolve_nodes(graph, ("ytflow:model",))["ytflow:model"]
    assert str(graph[model_id]["class_type"]).startswith(LORA_PREFIX)


# ── Story 14.3: the art-style contract ───────────────────────────────────────
# Jay's viewing verdict ⑦ ("화풍 유지 안 됨") has two candidate layers, and only one of
# them is written down anywhere: the graphs themselves. A 43-shot sweep of run
# 4b35c0ed's `image_prompt`s found no neon/foreign-style vocabulary to constrain (2/7
# drift-labelled shots vs 2/36 others, the single term being `LED`, a light fixture),
# so the prescription "constrain the palette to a closed vocabulary" has nothing to
# delete. What IS declarable is which model each graph loads and at what LoRA strength.
# This turns that from prose into an executable record.
#
# Read the record before quoting "one style": the graphs do NOT all agree on a base
# model, and the disagreement is on the majority surface. The SDXL trio (background,
# plate, card) share AnimagineXL v3.1 + darkness_xl_v2 and differ only in strength
# (0.5/0.5/0.3, pinned as an xfail below) — but they drew 10 of run 4b35c0ed's 43
# delivered frames. The other 33 were drawn by the recompose graph, which is
# UnetLoaderGGUF on qwen-image-edit-2511-Q4_K_M with a Lightning-4steps LoRA at 1.0: a
# different base model entirely. That is by far the largest style divergence in the
# shipped pipeline, and it is encoded here as a PASSING assertion
# (`test_recompose_is_held_to_a_different_contract...`) because it is intended, not
# because it is small. A different contract is not the same as no divergence.
#
# The population is swept, not enumerated (`gotcha_closing-a-class-needs-a-population-sweep`):
# an earlier draft of this contract listed background/plate/card and silently omitted the
# recompose graph, which ships ON since 10.1e and drew 33 of that run's 43 delivered
# frames. Every graph a shipped default points at must be classified here or the sweep
# below fails.
RECOMPOSE = Path(  # the graph that drew 33/43 delivered frames of run 4b35c0ed
    "data/workflows/comfyui_shot_recompose_qwen_api.json").name

# workflow -> the style contract it is held to. Two contracts, not one contract plus an
# exemption: the recompose graph is a Qwen-Image-Edit editor and cannot load an SDXL
# checkpoint or an SDXL LoRA, so holding it to the SDXL row would be incoherent, and
# leaving it out of the table would be the omission described above.
STYLE_FAMILY = {
    API2: "sdxl-animagine",         # shot backgrounds (image_node)
    PLATE: "sdxl-animagine",        # approved stock location plates (seed script)
    MULTI_ANGLE: "sdxl-animagine",  # character cards
    POSE_GUIDE: "sdxl-animagine",   # pose-conditioned character cards
    RECOMPOSE: "qwen-image-edit",   # shot recompose — plate + cards -> one frame
}
FAMILY_BASE = {
    "sdxl-animagine": "AnimagineXL_v31.safetensors",
    "qwen-image-edit": "qwen-image-edit-2511-Q4_K_M.gguf",
}
# Shipped graphs that draw no art style, with the reason. Being on this list is a
# decision, which is the point: an unclassified graph fails `test_every_shipped_...`.
NON_STYLE_WORKFLOWS = {
    "comfyui_iclight_relight_api.json":
        "relights a sprite that already exists; reachable only at "
        "composite_harmonization_tier >= 3 and the shipped default is 1",
    "comfyui_depth_anything_v2_api.json":
        "produces a depth map, not a picture",
}
# The set the spec's weight divergence is about. POSE_GUIDE is in the family above (and
# asserted there) but not here: it is a second card graph, so it adds no third value.
SDXL_STYLE_SET = [API2, PLATE, MULTI_ANGLE]
STYLE_LORA = "darkness_xl_v2.safetensors"


SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def _module_constant_workflows() -> set[str]:
    """Every `data/workflows/...` path assigned at module level anywhere under `src/`.

    `Settings` is not the only place a shipped graph is declared — `_POSE_GUIDE_WORKFLOW_PATH`
    is a plain module constant — and naming those one at a time is the enumeration this
    file's sweep exists to replace (`gotcha_closing-a-class-needs-a-population-sweep`): a
    constant added tomorrow escapes the sweep, and an unclassified shipped graph then
    PASSES the test whose whole job is to make that impossible.

    Parsed rather than imported: importing every module under `src/` to read its constants
    would execute their import-time side effects inside a JSON contract test. Module level
    only — a literal inside a function is a call site, and every one in the tree today
    duplicates a `Settings` default this sweep already has.
    """
    found = set()
    for path in SRC_DIR.rglob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8"), str(path)).body:
            targets = ([node.value] if isinstance(node, (ast.Assign, ast.AnnAssign))
                       and node.value is not None else [])
            found |= {v.value for v in targets
                      if isinstance(v, ast.Constant) and isinstance(v.value, str)
                      and v.value.startswith("data/workflows/")}
    return found


def _shipped_workflow_names() -> set[str]:
    """Every ComfyUI graph a SHIPPED DEFAULT points at.

    Read off `Settings.model_fields` rather than an instance: constructing `Settings()`
    pulls in `.env` and the credential guards, and the question here is what the code
    ships with, not what this box is configured for. Module-level constants are swept
    alongside them — see `_module_constant_workflows`.
    """
    from yt_flow.config import Settings

    paths = {
        field.default
        for field in Settings.model_fields.values()
        if isinstance(field.default, str) and field.default.startswith("data/workflows/")
    }
    return {Path(p).name for p in paths | _module_constant_workflows()}


def test_the_sweep_sees_a_workflow_declared_outside_settings():
    """The pose-guide graph is a module constant, not a `Settings` default. It used to be
    added to the sweep by name; if the discovery ever narrows back to declared fields,
    this fails instead of the sweep going quietly blind."""
    assert POSE_GUIDE in _shipped_workflow_names()
    assert character_image_provider._POSE_GUIDE_WORKFLOW_PATH in _module_constant_workflows()


def lora_strengths(graph: dict, lora_name: str) -> set[float]:
    """Every numeric strength `lora_name` is applied at, across every loader applying it.

    A set over all loaders, not one node's field: a graph may patch the same LoRA in
    twice (`LoraLoaderModelOnly` for the model, `LoraLoader` for both), and picking "the"
    node would be picking whichever `dict` order handed over first. Non-numeric values are
    dropped rather than coerced — a strength wired from another node is the list
    `["3", 0]`, and `float()` on it raises `TypeError` inside a contract test that is
    supposed to REPORT the graph, not crash on it.
    """
    return {
        float(value)
        for node in graph.values()
        if str(node.get("class_type", "")).startswith(LORA_PREFIX)
        if (node.get("inputs") or {}).get("lora_name") == lora_name
        for field in ("strength_model", "strength_clip")
        if isinstance(value := (node.get("inputs") or {}).get(field), (int, float))
        if not isinstance(value, bool)
    }


def test_every_shipped_workflow_is_classified_by_the_style_contract():
    """The sweep. Add a graph to a shipped default and this fails until it is classified."""
    unclassified = _shipped_workflow_names() - set(STYLE_FAMILY) - set(NON_STYLE_WORKFLOWS)
    assert not unclassified, (
        f"{sorted(unclassified)} render for shipped code paths but are in neither "
        "STYLE_FAMILY nor NON_STYLE_WORKFLOWS — decide which, do not delete the row"
    )


@pytest.mark.parametrize("name", sorted(STYLE_FAMILY), ids=lambda n: n)
def test_style_workflow_loads_its_declared_base_model(name: str):
    graph = nodes(WORKFLOW_DIR / name)
    assert base_models(graph) == {FAMILY_BASE[STYLE_FAMILY[name]]}


def test_the_sdxl_style_set_shares_one_checkpoint_and_one_style_lora():
    """The half of the art-style contract that already holds."""
    for name in SDXL_STYLE_SET:
        graph = nodes(WORKFLOW_DIR / name)
        assert base_models(graph) == {FAMILY_BASE["sdxl-animagine"]}, name
        assert lora_names(graph) == {STYLE_LORA}, name
        assert lora_strengths(graph, STYLE_LORA), f"{name}: no numeric strength to compare"


@pytest.mark.xfail(strict=True, reason=(
    "MEASURED DIVERGENCE, DELIBERATELY NOT FIXED (Story 14.3). The three SDXL graphs "
    "apply darkness_xl_v2 at 0.5 (background) / 0.5 (plate) / 0.3 (card). Recompose feeds "
    "the card in as a reference image and is asked to render it 'in the same illustration "
    "style as the background', so a card rendered at a different LoRA strength than the "
    "background is a DECLARATION-LEVEL candidate cause of the 'pasted-on' look Jay "
    "reported. It is not changed here for two reasons that are both blocking: (1) aligning "
    "the weight makes the 42 approved plates and 52 approved cards inconsistent with every "
    "new render, and asset_service has no epoch-archive path (`asset_service.py:58-61` "
    "`# ponytail:`), so a re-render overwrites them in place; (2) this box has no GPU, and "
    "no art-style default in this project has ever been changed without a human judging "
    "rendered frames. xfail(strict) rather than a comment: if someone aligns the weights "
    "this xpasses and FAILS, which surfaces the decision instead of burying it."))
def test_the_sdxl_style_set_applies_that_lora_at_one_strength():
    by_workflow = {
        name: lora_strengths(nodes(WORKFLOW_DIR / name), STYLE_LORA) for name in SDXL_STYLE_SET
    }
    assert len({frozenset(v) for v in by_workflow.values()}) == 1, by_workflow


def test_recompose_is_held_to_a_different_contract_not_exempted_from_this_one():
    """A Qwen-Image-Edit graph cannot satisfy the SDXL row, and must not be silently
    dropped for it — the omission that made an earlier draft of this contract miss the
    graph that drew 33 of run 4b35c0ed's 43 delivered frames."""
    assert STYLE_FAMILY[RECOMPOSE] != STYLE_FAMILY[API2]
    recompose, background = nodes(WORKFLOW_DIR / RECOMPOSE), nodes(WORKFLOW_DIR / API2)
    assert base_models(recompose).isdisjoint(base_models(background))
    assert lora_names(recompose).isdisjoint(lora_names(background))
    # EQUALITY, not `<=`. A subset bound is vacuously true on the empty set, so a
    # re-export that dropped the LoraLoaderModelOnly left this green while the graph
    # still sampled on a 4-step schedule — the SDXL trio get `==` plus a wiring test and
    # the Qwen row, which drew 33 of run 4b35c0ed's 43 delivered frames, got neither.
    assert lora_names(recompose) == ALLOWED_LORAS[FAMILY_BASE["qwen-image-edit"]]


def test_the_recompose_lightning_lora_still_reaches_its_sampler():
    """The other half of the same defect: an allowlist (even an equality one) says the
    node exists, not that it is still wired in. Lightning-4steps is what makes this graph
    viable at 4 steps; bypassed, the graph samples a 4-step schedule with no distilled
    LoRA behind it and every recomposed frame is undercooked — silently, at 33 frames a
    run. The SDXL graphs have had this assertion since 13.3."""
    graph = nodes(WORKFLOW_DIR / RECOMPOSE)
    sampler = next(nid for nid, n in graph.items() if n.get("class_type") == "KSampler")
    chain = model_chain_sources(graph, sampler)
    assert any(str(c).startswith(LORA_PREFIX) for c in chain), (
        f"{RECOMPOSE}: KSampler model input no longer passes through a LoraLoader ({chain})"
    )
