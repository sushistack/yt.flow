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

import json
from pathlib import Path

import pytest

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


def test_api2_satisfies_image_node_contract():
    """image.py injects into "6"/"7" by id and seeds every KSampler by class."""
    graph = nodes(WORKFLOW_DIR / API2)
    assert graph["6"]["class_type"] == "CLIPTextEncode"
    assert graph["7"]["class_type"] == "CLIPTextEncode"
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


def test_plate_workflow_keeps_the_node_id_the_seed_script_hardcodes():
    """scripts/seed_location_plates.py pins MODEL_NODE = "11"."""
    graph = nodes(WORKFLOW_DIR / PLATE)
    assert str(graph["11"]["class_type"]).startswith(LORA_PREFIX)
