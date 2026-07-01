"""image_node — the ComfyUI image-generation stage (Story 1.6 / 1.6b).

Consumes ``SceneState.shots`` from ``scenario_node`` and, per shot, submits the
configured ComfyUI workflow with the shot's prompts injected into workflow nodes
``"6"`` (positive) and ``"7"`` (negative), writing each output under
``workspace/{run_id}/images/``. Pure function of state: reads a few fields and
returns only the changed ones (``scenes``, ``current_stage``, and ``error`` on
failure). No DB / SSE writes and no ``interrupt()`` — gate behaviour stays in
``gates.py``. [AD-1, AD-4]

The image-generation unit is a *shot*, not a scene: every shot gets its own
image. [AD-5]

Layered-asset mode (``YTFLOW_COMFYUI_LAYERED=true``, Story 1.6b): each shot
produces a separate opaque background PNG and an optional transparent character
PNG, enabling independent Ken-Burns + overlay animation in video_node (1.9c).
``image_path`` is preserved as a backward-compatible preview.

Mock mode (``YTFLOW_COMFYUI_MOCK=true``) never instantiates the HTTP client: a
fixture image from ``tests/fixtures/images/`` is materialized into the run
workspace so downstream code sees an identical artifact layout in mock and real
runs.
"""

import copy
import json
import shutil
import time
from pathlib import Path

from langfuse import get_client, observe

from yt_flow.config import Settings
from yt_flow.domain.state import PipelineState, SceneState, ShotData
from yt_flow.services import comfyui_client

POSITIVE_NODE = "6"
NEGATIVE_NODE = "7"

# ponytail: mock fixtures live in the test tree per the story contract; a module
# constant keeps the node dependency-free and lets tests monkeypatch the source.
MOCK_FIXTURES_DIR = Path("tests/fixtures/images")
MOCK_BACKGROUND_NAME = "mock_background.png"
MOCK_CHARACTER_NAME = "mock_character.png"


def _settings() -> Settings:
    # ponytail: one seam so unit tests can inject fake settings without a real .env.
    return Settings()


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _load_workflow(path: str) -> dict:
    """Load and validate the API-format workflow, asserting the prompt nodes exist."""
    try:
        workflow = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # JSONDecodeError is a ValueError subclass
        raise ValueError(f"cannot load ComfyUI workflow at {path!r}: {exc}") from exc
    if not isinstance(workflow, dict):
        raise ValueError(f"ComfyUI workflow at {path!r} is not an API-format object")
    for node_id in (POSITIVE_NODE, NEGATIVE_NODE):
        node = workflow.get(node_id)
        if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode" \
                or not isinstance(node.get("inputs"), dict):
            raise ValueError(
                f"workflow node {node_id!r} must be a CLIPTextEncode with an 'inputs' dict"
            )
    return workflow


def _inject_prompts(template: dict, image_prompt: str, negative_prompt: str) -> dict:
    """Return a deep copy of the workflow with prompts injected into nodes 6/7.

    Pure: never mutates ``template`` so one loaded workflow can be reused per shot.
    """
    workflow = copy.deepcopy(template)
    workflow[POSITIVE_NODE]["inputs"]["text"] = image_prompt
    workflow[NEGATIVE_NODE]["inputs"]["text"] = negative_prompt
    return workflow


def _mock_source() -> Path:
    """First fixture image to stand in for a real ComfyUI render."""
    for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        matches = sorted(MOCK_FIXTURES_DIR.glob(pattern))
        if matches:
            return matches[0]
    raise ValueError(f"no fixture images under {MOCK_FIXTURES_DIR} for mock mode")


def _mock_background_source() -> Path:
    """Opaque background fixture; prefer mock_background.png, fall back to first image."""
    p = MOCK_FIXTURES_DIR / MOCK_BACKGROUND_NAME
    return p if p.exists() else _mock_source()


def _mock_character_source() -> Path | None:
    """Transparent character fixture; None if absent (background-only mock)."""
    p = MOCK_FIXTURES_DIR / MOCK_CHARACTER_NAME
    return p if p.exists() else None


def _has_alpha(png_bytes: bytes) -> bool:
    """Check PNG color_type byte to detect RGBA or grayscale+alpha channel.

    Offset 25 in a valid PNG is color_type in the IHDR chunk:
    4=grayscale+alpha, 6=RGBA. No Pillow needed. [ponytail: stdlib-only]
    """
    if len(png_bytes) < 26 or png_bytes[:8] != b'\x89PNG\r\n\x1a\n':
        return False
    return png_bytes[25] in (4, 6)


def _record_trace(
    *,
    comfyui_url,
    workflow_path,
    request_count,
    image_count,
    latency_ms,
    layered_assets_enabled=False,
    background_count=0,
    character_count=0,
    error=None,
) -> None:
    """Best-effort enrich the current ``image`` span. [AD-10 — tracing is non-fatal]"""
    try:
        get_client().update_current_span(
            metadata={
                "comfyui_url": comfyui_url,
                "workflow_path": workflow_path,
                "comfyui_request_count": request_count,
                "image_count": image_count,
                "layered_assets_enabled": layered_assets_enabled,
                "background_count": background_count,
                "character_count": character_count,
                "latency_ms": latency_ms,
                **({"error": repr(error)} if error is not None else {}),
            },
        )
    except Exception:  # noqa: BLE001 — a tracing failure must never break the pipeline
        pass


async def _generate_layered_shot(
    s: Settings, out_dir: Path, scene_num: int, shot: ShotData, template: dict | None
) -> tuple[str, str | None, str]:
    """Generate background + optional character for one shot; return (bg, char, image) paths."""
    base = f"scene_{scene_num:03d}_{shot['shot_id']}"
    bg_dest = out_dir / f"{base}_background.png"
    char_dest = out_dir / f"{base}_character.png"
    img_dest = out_dir / f"{base}.png"

    if s.comfyui_mock:
        shutil.copyfile(_mock_background_source(), bg_dest)
        char_src = _mock_character_source()
        char_path: str | None = None
        if char_src:
            shutil.copyfile(char_src, char_dest)
            char_path = str(char_dest)
        shutil.copyfile(bg_dest, img_dest)  # image_path = background for compat
    else:
        if template is None:
            raise ValueError("workflow must be loaded in real mode")
        outputs = await comfyui_client.submit_and_fetch_outputs(
            s.comfyui_url, template,
            [s.comfyui_background_node, s.comfyui_character_node],
        )
        bg_bytes = outputs.get(s.comfyui_background_node)
        if bg_bytes is None:
            raise comfyui_client.ComfyUIError(
                f"background node {s.comfyui_background_node!r} missing from ComfyUI output"
            )
        bg_dest.write_bytes(bg_bytes)
        char_bytes = outputs.get(s.comfyui_character_node)
        char_path = None
        if char_bytes is not None:
            if not _has_alpha(char_bytes):
                raise comfyui_client.ComfyUIError(
                    f"character output from node {s.comfyui_character_node!r} "
                    "is opaque (not an RGBA PNG)"
                )
            char_dest.write_bytes(char_bytes)
            char_path = str(char_dest)
        # ponytail: image_path = background; no compositing at this stage
        shutil.copyfile(bg_dest, img_dest)

    return str(bg_dest), char_path, str(img_dest)


@observe(name="image")
async def image_node(state: PipelineState) -> dict:
    run_id = state.get("run_id", "?")
    t0 = time.perf_counter()
    s: Settings | None = None
    request_count = 0
    image_count = 0
    background_count = 0
    character_count = 0
    try:
        s = _settings()  # inside try: a config/env failure surfaces as PipelineState.error too
        out_dir = Path("workspace") / run_id / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        template = None if s.comfyui_mock else _load_workflow(s.comfyui_workflow_path)

        new_scenes: list[SceneState] = []
        for scene in state.get("scenes", []):
            new_shots: list[ShotData] = []
            for shot in scene["shots"]:
                if s.comfyui_layered:
                    wf = _inject_prompts(template, shot["image_prompt"], shot["negative_prompt"]) \
                        if template is not None else None
                    bg_path, char_path, img_path = await _generate_layered_shot(
                        s, out_dir, scene["scene_num"], shot, wf
                    )
                    if not s.comfyui_mock:
                        request_count += 1
                    image_count += 1
                    background_count += 1
                    if char_path is not None:
                        character_count += 1
                    new_shots.append({
                        **shot,
                        "image_path": img_path,
                        "background_path": bg_path,
                        "character_path": char_path,
                    })
                else:
                    dest = out_dir / f"scene_{scene['scene_num']:03d}_{shot['shot_id']}.png"
                    if s.comfyui_mock:
                        shutil.copyfile(_mock_source(), dest)
                    else:
                        if template is None:
                            raise ValueError("workflow must be loaded in real mode")
                        workflow = _inject_prompts(template, shot["image_prompt"], shot["negative_prompt"])
                        image_bytes = await comfyui_client.submit_and_fetch(s.comfyui_url, workflow)
                        dest.write_bytes(image_bytes)
                        request_count += 1
                    image_count += 1
                    # Copy the shot; set only image_path — never mutate the input state. [AD-4]
                    new_shots.append({
                        **shot,
                        "image_path": str(dest),
                        "background_path": None,
                        "character_path": None,
                    })
            new_scenes.append({**scene, "shots": new_shots})

        _record_trace(
            comfyui_url=s.comfyui_url, workflow_path=s.comfyui_workflow_path,
            request_count=request_count, image_count=image_count,
            layered_assets_enabled=s.comfyui_layered,
            background_count=background_count, character_count=character_count,
            latency_ms=_ms(t0),
        )
        return {"scenes": new_scenes, "current_stage": "image"}
    except Exception as exc:  # noqa: BLE001 — surfaced as PipelineState.error, never raised past the node
        _record_trace(
            comfyui_url=s.comfyui_url if s else "?",
            workflow_path=s.comfyui_workflow_path if s else "?",
            request_count=request_count, image_count=image_count,
            layered_assets_enabled=s.comfyui_layered if s else False,
            background_count=background_count, character_count=character_count,
            latency_ms=_ms(t0), error=exc,
        )
        return {"current_stage": "image", "error": f"stage=image run_id={run_id}: {exc}"}
