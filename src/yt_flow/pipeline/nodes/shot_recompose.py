"""Shot recompose — regenerate the frame from plate + cards + a placement instruction.

Story 10.1c. This replaces the overlay path, it does not decorate it: the plate and the
character cards go in as *inputs* and the model draws one image. Nothing is pasted, so there
is no seam to harmonize and no ground line to compute.

Why the old path is gone (Epic 10 "⛳ 확정 방향", Jay 2026-08-08/09): compositing a card onto
a plate made placement a property of code constants — `_POSITION_X_FRAC`, `_DEPTH_SCALE`,
`ground_y` from a depth map — and on a plate with no floor no constant can stand a figure up,
so characters kept floating. Story 10.1b activated IC-Light relighting on top of that and Jay
judged it worse, because lighting was never the reason a cutout reads as a cutout.

Two live-established rules this module encodes:

* **One character per pass.** Passing two cards to `TextEncodeQwenImageEditPlus` at once makes
  the model blow the first one up to a face close-up regardless of the instruction — measured
  against three prompt phrasings and both card orderings. Inserting one at a time, far band
  first, is correct 4/4 and also gives natural depth ordering: the nearer figure is drawn last,
  in front.
* **The instruction carries the placement.** `position`/`depth`/`pose` are already decided by
  `visual_breakdown`; the old path flattened them into fixed fractions. Here they become the
  sentence, so nothing is discarded and no extra LLM call is made.

Layer rule: domain and config only; no db/, api/, services/. [AD-1] — `comfyui_client` is
duck-typed, same posture as `composite_harmonization`.
"""

import copy
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from yt_flow.domain.png import dimensions

logger = logging.getLogger(__name__)

PLATE_NODE = "plate"
CARD_A_NODE = "card_a"
CARD_B_NODE = "card_b"
PROMPT_NODE = "positive"
SAMPLER_NODE = "sampler"

# Natural-language renderings of the closed CastMember vocabularies. Every band says
# "whole body ... visible": without it `near` was read as a face close-up (live, S00403).
_POSITION_PHRASE = {
    "left": "on the left side of the frame",
    "center": "in the centre of the frame",
    "right": "on the right side of the frame",
}
_DEPTH_PHRASE = {
    "near": "in the foreground close to camera, his whole body from head to feet visible in frame",
    "mid": "at mid distance, his whole body from head to feet visible in frame",
    "far": "far from camera, small in the frame, whole body visible",
}
# Insert far figures first so nearer ones are drawn over them.
_DEPTH_ORDER = {"far": 0, "mid": 1, "near": 2}


def placement_instruction(look: str, position: str, depth: str, pose: str | None = None) -> str:
    """One character's placement sentence.

    `look` is an appearance description, NOT "the second image": the model does not resolve
    ordinal references to its own inputs. With ordinals, a two-card shot put the wrong figure
    on the wrong side at the wrong scale; with appearance descriptions it was correct.
    """
    action = f", {pose}" if pose and pose not in ("standing", "") else ", standing"
    return (
        f"Place {look} {_POSITION_PHRASE.get(position, _POSITION_PHRASE['center'])}, "
        f"{_DEPTH_PHRASE.get(depth, _DEPTH_PHRASE['mid'])}{action}, "
        "into the scene of the first image. "
        # NOT "keep the room, its camera angle and framing, and everyone...": adding the
        # framing clause made pass 1 draw the character TWICE (live, S00403 — two plague
        # doctors side by side, and pass 2 then faithfully preserved both). The short form
        # is what the 43-plate sweep and the 1-character 4/4 slate were verified on.
        "Keep the room and everyone already in it exactly as they are. "
        "Feet firmly on the ground with a contact shadow, lit by the same light as the room, "
        "rendered in the same illustration style as the background. Single cohesive illustration."
    )


def order_cast(cast: list[dict]) -> list[dict]:
    """Far band first — the nearer figure is inserted last and lands in front."""
    return sorted(cast, key=lambda c: _DEPTH_ORDER.get(c.get("depth", "mid"), 1))


def _load_workflow(path: str) -> dict:
    """Load and validate the recompose workflow's interchange nodes."""
    try:
        workflow = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot load recompose workflow at {path!r}: {exc}") from exc
    if not isinstance(workflow, dict):
        raise ValueError(f"recompose workflow at {path!r} is not an API-format object")
    for node_id in (PLATE_NODE, CARD_A_NODE):
        node = workflow.get(node_id)
        if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
            raise ValueError(f"recompose workflow node {node_id!r} must be a LoadImage node")
    if workflow.get("ytflow_verified_recompose_qwen") is not True:
        raise ValueError(
            "recompose workflow is not marked ytflow_verified_recompose_qwen=true; "
            "an unverified graph is treated as a non-fatal skip"
        )
    return workflow


def _upload_name(path: Path, salt: str) -> str:
    """Collision-proof name for ComfyUI's shared input dir.

    ComfyUI keys inputs on the basename and `LoadImage` reads at node-execution time, so
    same-named uploads clobber each other mid-queue. Card basenames are not unique —
    `front_candidate_1.png` belongs to eight characters — and plates repeat across shots.
    """
    digest = hashlib.sha1(f"{path.resolve()}|{salt}".encode("utf-8")).hexdigest()[:12]
    return f"ytflow_recompose_{digest}{path.suffix or '.png'}"


def build_single_pass(template: dict, plate_name: str, card_name: str, prompt: str) -> dict:
    """One character into one scene. The second card slot is removed, not left dangling.

    ComfyUI's `validate_prompt` walks every top-level key, so the marker bool and the note
    string must not survive into the submission (live-verified: they return a 500).
    """
    workflow = {k: copy.deepcopy(v) for k, v in template.items() if isinstance(v, dict) and "class_type" in v}
    workflow[PLATE_NODE]["inputs"]["image"] = plate_name
    workflow[CARD_A_NODE]["inputs"]["image"] = card_name
    workflow.pop(CARD_B_NODE, None)
    workflow[PROMPT_NODE]["inputs"].pop("image3", None)
    workflow[PROMPT_NODE]["inputs"]["prompt"] = prompt
    return workflow


RECOMPOSED_DIR = "recomposed"
"""Named, not inlined: the caller reads it back off a path to detect re-entry."""


def recompose_cache_path(workspace: Path, shot_id: str, digest: str) -> Path:
    """Content-addressed: the frame is a pure function of plate, cards and instructions."""
    return workspace / RECOMPOSED_DIR / f"{shot_id}_{digest}.png"


def recompose_digest(plate_bytes: bytes, card_paths: list[str], prompts: list[str]) -> str:
    h = hashlib.sha256(plate_bytes)
    for c, p in zip(card_paths, prompts):
        h.update(f"|{c}|{p}".encode("utf-8"))
    return h.hexdigest()[:16]


async def recompose_shot(
    plate_path: Path,
    cast: list[dict],
    looks: dict[str, str],
    comfyui_client: Any,
    workflow_path: str,
    comfyui_url: str,
    *,
    shot_id: str = "",
) -> bytes | None:
    """Insert each character in turn; return the final frame, or ``None``.

    Non-fatal by contract: a failure leaves the caller with the untouched plate rather than
    killing the run, the same posture every ComfyUI path in this pipeline takes.
    """
    try:
        template = _load_workflow(workflow_path)
        current = plate_path.read_bytes()
        for i, card in enumerate(order_cast(cast)):
            card_path = Path(card["path"])
            look = looks.get(card.get("card_key", ""))
            if not look:
                logger.warning("No appearance description for %r; skipping insert", card.get("card_key"))
                continue
            prompt = placement_instruction(
                look, card.get("position", "center"), card.get("depth", "mid"), card.get("pose"),
            )
            salt = f"{shot_id}:{i}"
            plate_name = await comfyui_client.upload_image(comfyui_url, current, _upload_name(plate_path, salt))
            card_name = await comfyui_client.upload_image(
                comfyui_url, card_path.read_bytes(), _upload_name(card_path, salt),
            )
            workflow = build_single_pass(template, plate_name, card_name, prompt)
            result = await comfyui_client.submit_and_fetch(comfyui_url, workflow)
            if not result or dimensions(result) is None:
                logger.warning("Recompose pass %d returned no usable image for shot %s", i, shot_id)
                return None
            current = result
        return current
    except Exception as exc:  # noqa: BLE001 — recompose failure is never fatal
        logger.warning("Recompose failed for shot %s: %s", shot_id, exc)
        return None
