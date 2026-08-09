"""Run-level orchestration for Story 10.1c shot recompose.

The domain half lives in `pipeline/nodes/shot_recompose.py` (prompt construction, pass
ordering, workflow assembly). This half is what that module deliberately cannot reach: the
ComfyUI client, the workspace, and the character descriptions the instruction needs.

Contract with `video_node` (see `inject_recompose_resolver`): rewrite each recomposed shot's
``image_path`` in place and drop that shot from the returned cast map, so the composition
stage takes its background-only path and nothing is overlaid on a frame that already has
the characters in it.
"""

import logging
from pathlib import Path

from yt_flow.config import Settings
from yt_flow.pipeline.nodes.shot_recompose import (
    recompose_cache_path,
    recompose_digest,
    recompose_shot,
)
from yt_flow.services import comfyui_client

logger = logging.getLogger(__name__)

# How each card key is described to the model. An appearance description, never "the second
# image" — ordinal references to its own inputs are not resolved (live 2026-08-09: two-card
# shots put the wrong figure on the wrong side at the wrong scale until this changed).
# ponytail: a module constant. A card key without an entry is skipped rather than guessed at,
# because a wrong description silently redraws the wrong character.
CARD_LOOKS: dict[str, str] = {
    "SCP-049": "the figure in the long black hooded coat and white plague-doctor beak mask",
    "SCP-049-2": "the reanimated figure in torn surgical scrubs",
    "STOCK-d-class": "the man in the orange prison jumpsuit",
    "STOCK-researcher": "the person in a white lab coat over office clothes",
    "STOCK-security": "the guard in black tactical gear",
}


async def recompose_run_shots(
    scenes: list, cast_cards: dict, settings: Settings | None = None,
) -> tuple[dict, dict]:
    """Recompose every cast-bearing shot. Returns ``(remaining_cast_cards, stats)``."""
    s = settings or Settings()
    workspace = Path(s.workspace_path)
    remaining = dict(cast_cards)
    stats = {"recomposed": 0, "skipped": 0, "failed": 0}

    for scene in scenes:
        for shot in scene.get("shots") or []:
            shot_key = f"{scene['scene_num']}:{shot['shot_id']}"
            cast = [c for c in remaining.get(shot_key, []) if isinstance(c, dict) and c.get("path")]
            plate = shot.get("image_path")
            if not cast or not plate:
                continue
            if any(c.get("card_key") not in CARD_LOOKS for c in cast):
                # No description means no way to name the character in the instruction.
                # Leaving it to the overlay path is honest; guessing a description is not.
                logger.warning(
                    "Recompose skipped for %s: no appearance description for %s",
                    shot_key, [c.get("card_key") for c in cast if c.get("card_key") not in CARD_LOOKS],
                )
                stats["skipped"] += 1
                continue

            plate_path = Path(plate)
            try:
                plate_bytes = plate_path.read_bytes()
            except OSError as exc:
                logger.warning("Recompose skipped for %s: unreadable plate %s: %s", shot_key, plate, exc)
                stats["skipped"] += 1
                continue

            digest = recompose_digest(
                plate_bytes,
                [str(c["path"]) for c in cast],
                [f"{c.get('card_key')}|{c.get('position')}|{c.get('depth')}|{c.get('pose')}" for c in cast],
            )
            # Plates live at <run_dir>/images/<shot>.png, so the run dir is two up. Deriving
            # it from the plate keeps the output beside the run that owns it without
            # threading a run_id through a node that is a pure function of state.
            run_dir = plate_path.parent.parent if plate_path.parent.name == "images" else workspace
            out = recompose_cache_path(run_dir, shot["shot_id"], digest)

            if not out.exists():
                image = await recompose_shot(
                    plate_path, cast, CARD_LOOKS, comfyui_client,
                    s.shot_recompose_workflow_path, s.comfyui_url, shot_id=shot["shot_id"],
                )
                if not image:
                    stats["failed"] += 1
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                tmp = out.with_name(f"{out.name}.tmp")
                tmp.write_bytes(image)
                tmp.replace(out)

            shot["image_path"] = str(out)
            remaining.pop(shot_key, None)   # nothing to overlay: the frame already has them
            stats["recomposed"] += 1

    logger.info("Shot recompose: %s", stats)
    return remaining, stats
