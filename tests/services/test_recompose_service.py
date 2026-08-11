"""Tests for recompose_service (Story 10.1c close-out).

The prompt/workflow half is covered by tests/pipeline/nodes/test_shot_recompose.py; what
this half owns is the *state edit* it makes to the graph — which shots get their frame
replaced, and what has to be taken away from them at the same time.
"""

import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from yt_flow.services import recompose_service
from yt_flow.services.recompose_service import recompose_run_shots

# Only `dimensions()` inspects the bytes, and it reads the IHDR alone.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 8, 8)
RECOMPOSED = PNG + b"recomposed"


class _StubClient:
    """Duck-typed stand-in for services.comfyui_client (the module, not a class)."""

    def __init__(self, result: bytes | None = RECOMPOSED):
        self.result = result
        self.uploads: list[str] = []
        self.submits = 0

    async def upload_image(self, url, data, name):
        self.uploads.append(name)
        return name

    async def submit_and_fetch(self, url, workflow):
        self.submits += 1
        return self.result


def _workflow(tmp_path: Path) -> str:
    p = tmp_path / "wf.json"
    p.write_text(json.dumps({
        "ytflow_verified_recompose_qwen": True,
        "plate": {"class_type": "LoadImage", "inputs": {"image": "p.png"}},
        "card_a": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
        "card_b": {"class_type": "LoadImage", "inputs": {"image": "b.png"}},
        "positive": {"class_type": "TextEncodeQwenImageEditPlus",
                     "inputs": {"prompt": "x", "image1": ["plate", 0],
                                "image2": ["card_a", 0], "image3": ["card_b", 0]}},
    }))
    return str(p)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """One run dir with a plate, a depth map and a card, plus the stub client wired in."""
    images = tmp_path / "run" / "images"
    images.mkdir(parents=True)
    plate = images / "S001.png"
    plate.write_bytes(PNG + b"plate")
    depth = images / "S001_depth.png"
    depth.write_bytes(PNG + b"depth")
    card = tmp_path / "card.png"
    card.write_bytes(PNG + b"card")

    client = _StubClient()
    monkeypatch.setattr(recompose_service, "comfyui_client", client)
    scenes = [{"scene_num": 1, "shots": [
        {"shot_id": "S001", "image_path": str(plate), "depth_map_path": str(depth)},
    ]}]
    cast = {"1:S001": [{"path": str(card), "card_key": "SCP-049",
                        "position": "left", "depth": "mid"}]}
    settings = SimpleNamespace(
        workspace_path=str(tmp_path), comfyui_url="http://stub",
        shot_recompose_workflow_path=_workflow(tmp_path),
    )
    return SimpleNamespace(
        scenes=scenes, cast=cast, settings=settings, client=client,
        shot=scenes[0]["shots"][0], plate=plate, depth=depth, tmp_path=tmp_path,
    )


async def test_recomposed_shot_swaps_the_frame_and_drops_the_stale_depth_map(env):
    """The frame is new; the depth map still describes the empty plate.

    Keeping it would warp the characters the model just drew against their own
    background. parallax_service degrades to NO_DEPTH, which is recorded, so dropping
    the key is a visible downgrade rather than a silent wrong render.
    """
    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert env.shot["image_path"] != str(env.plate)
    assert Path(env.shot["image_path"]).read_bytes() == RECOMPOSED
    assert "depth_map_path" not in env.shot
    assert remaining == {}          # nothing left to overlay onto the new frame
    assert stats == {"recomposed": 1, "skipped": 0, "failed": 0}


async def test_recomposed_frame_lands_beside_the_run_that_owns_it(env):
    await recompose_run_shots(env.scenes, env.cast, env.settings)
    assert Path(env.shot["image_path"]).parent == env.tmp_path / "run" / "recomposed"


async def test_cached_frame_is_reused_without_a_second_render(env):
    """Content-addressed by plate+cards+instructions: the same plate must not re-render.

    The shot is reset to the plate on purpose — this covers the cache, not re-entry.
    The state the pipeline actually presents on a video retry is the next test.
    """
    await recompose_run_shots(env.scenes, env.cast, env.settings)
    first = env.shot["image_path"]
    env.shot["image_path"] = str(env.plate)
    env.shot["depth_map_path"] = str(env.depth)

    await recompose_run_shots(env.scenes, dict(env.cast), env.settings)

    assert env.shot["image_path"] == first
    assert env.client.submits == 1


async def test_rerunning_over_an_already_recomposed_shot_is_a_no_op(env):
    """The video stage is retryable and the frame swap is in place, so the second run
    sees a "plate" that already contains the characters. Recomposing it again would
    insert every figure a second time, and the run-dir derivation would miss besides.
    """
    await recompose_run_shots(env.scenes, env.cast, env.settings)
    recomposed = env.shot["image_path"]

    remaining, stats = await recompose_run_shots(env.scenes, dict(env.cast), env.settings)

    assert env.shot["image_path"] == recomposed   # untouched
    assert env.client.submits == 1                # no second render
    assert remaining == {}                        # still nothing to overlay
    assert stats == {"recomposed": 0, "skipped": 1, "failed": 0}


async def test_write_failure_leaves_the_shot_renderable(env, monkeypatch):
    """ENOSPC mid-loop must not escape: the caller's blanket except would keep the
    original cast_cards while the shots already swapped have the characters baked in.
    """
    def boom(self, *a, **kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_bytes", boom)

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert env.shot["image_path"] == str(env.plate)
    assert env.shot["depth_map_path"] == str(env.depth)
    assert remaining == env.cast
    assert stats == {"recomposed": 0, "skipped": 0, "failed": 1}


async def test_undescribed_card_leaves_the_shot_on_the_overlay_path(env):
    """No entry in CARD_LOOKS means no way to name the figure in the instruction.

    The shot must stay fully intact — depth map included — because the overlay path is
    what will render it, and 11.5 parallax needs that map.
    """
    env.cast["1:S001"][0]["card_key"] = "STOCK-nobody"

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert env.shot["image_path"] == str(env.plate)
    assert env.shot["depth_map_path"] == str(env.depth)
    assert remaining == env.cast
    assert stats == {"recomposed": 0, "skipped": 1, "failed": 0}
    assert env.client.submits == 0


async def test_unreadable_plate_leaves_the_shot_on_the_overlay_path(env):
    env.shot["image_path"] = str(env.tmp_path / "run" / "images" / "gone.png")

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert env.shot["depth_map_path"] == str(env.depth)
    assert remaining == env.cast
    assert stats["skipped"] == 1


async def test_failed_render_keeps_both_paths_and_the_cards(env, monkeypatch):
    """A ComfyUI failure is non-fatal, so the shot must be left renderable as it was."""
    monkeypatch.setattr(recompose_service, "comfyui_client", _StubClient(result=None))

    remaining, stats = await recompose_run_shots(env.scenes, env.cast, env.settings)

    assert env.shot["image_path"] == str(env.plate)
    assert env.shot["depth_map_path"] == str(env.depth)
    assert remaining == env.cast
    assert stats == {"recomposed": 0, "skipped": 0, "failed": 1}
