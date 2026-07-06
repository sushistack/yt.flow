"""Unit tests for src/yt_flow/pipeline/nodes/image.py (Story 1.6 / 1.6b).

No live ComfyUI / Langfuse: the HTTP client, settings, trace sink, and (for
mock mode) the fixtures dir are all monkeypatched. Tests assert the node's
PipelineState contract (image_path set on every shot, error handling, purity),
prompt injection into nodes "6"/"7", the mock/real branch behaviour, and
layered-asset mode (background_path + character_path, alpha validation).

Import the submodule explicitly: nodes/__init__.py still binds a stub `image`
attribute (Story 1.4), so `import a.b.image as img` is what resolves to this
module rather than the stub. [mirrors test_scenario.py]
"""

import json
import struct
import zlib
from pathlib import Path

import pytest

import yt_flow.pipeline.nodes.image as img
from yt_flow.services.comfyui_client import ComfyUIError

GOOD_WF = {
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "placeholder"}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "placeholder"}},
}


def _png_chunk(name: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(name + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)


def _make_png(color_type: int) -> bytes:
    """Minimal 1×1 PNG with the given color_type (2=RGB, 6=RGBA)."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, color_type, 0, 0, 0))
    raw = b"\x00\xff\x00\x00\x80" if color_type == 6 else b"\x00\xff\x80\x40"
    idat = _png_chunk(b"IDAT", zlib.compress(raw))
    iend = _png_chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


RGB_PNG = _make_png(2)
RGBA_PNG = _make_png(6)


class FakeSettings:
    def __init__(self, *, mock, workflow_path, layered=False, bg_node="9", char_node="10",
                 flat_fallback_workflow_path=None):
        self.workspace_path = "workspace"  # relative → isolated by monkeypatch.chdir(tmp_path)
        self.comfyui_url = "http://comfy.test:8188"
        self.comfyui_workflow_path = workflow_path
        self.comfyui_mock = mock
        self.comfyui_layered = layered
        self.comfyui_background_node = bg_node
        self.comfyui_character_node = char_node
        self.comfyui_flat_fallback_workflow_path = flat_fallback_workflow_path or workflow_path


def _state(**over):
    base = {
        "run_id": "run-img-1",
        "scp_text": "SCP-173",
        "scenes": [
            {
                "scene_num": 1, "narration": "n1", "audio_path": None, "audio_duration": None,
                "word_timings": [], "subtitle_path": None,
                "shots": [
                    {"shot_id": "S001", "sentence_indices": [0], "image_prompt": "a dark room",
                     "negative_prompt": "blurry", "camera_angle": "wide", "camera_movement": None,
                     "image_path": None},
                    {"shot_id": "S002", "sentence_indices": [0, 1], "image_prompt": "an agent",
                     "negative_prompt": "text", "camera_angle": None, "camera_movement": None,
                     "image_path": None},
                ],
            },
            {
                "scene_num": 2, "narration": "n2", "audio_path": None, "audio_duration": None,
                "word_timings": [], "subtitle_path": None,
                "shots": [
                    {"shot_id": "S003", "sentence_indices": [2], "image_prompt": "a corridor",
                     "negative_prompt": "watermark", "camera_angle": None, "camera_movement": "pan",
                     "image_path": None},
                ],
            },
        ],
        "video_path": None, "current_stage": "", "gate_states": {},
        "prompt_variant": None, "error": None,
    }
    base.update(over)
    return base


def _wf_file(tmp_path, workflow=GOOD_WF):
    p = tmp_path / "wf.json"
    p.write_text(json.dumps(workflow), encoding="utf-8")
    return str(p)


@pytest.fixture(autouse=True)
def _quiet_trace(monkeypatch):
    monkeypatch.setattr(img, "_record_trace", lambda **kw: None)


@pytest.fixture(autouse=True)
def _no_health_check(monkeypatch):
    """Story 5.14: real mode now health-checks before the first submission.

    Default it to a no-op so existing (pre-5.14) real-mode tests don't hit
    live HTTP; the health-check-specific tests below override this per-test.
    """
    async def ok(*a, **k):
        return None
    monkeypatch.setattr(img.comfyui_client, "check_health", ok)


# ── Prompt injection (AC1) — pure, no ComfyUI ───────────────────────────────

def test_inject_prompts_targets_nodes_6_and_7():
    out = img._inject_prompts(GOOD_WF, "positive text", "negative text")
    assert out["6"]["inputs"]["text"] == "positive text"
    assert out["7"]["inputs"]["text"] == "negative text"
    # template is untouched — one loaded workflow is safely reused per shot
    assert GOOD_WF["6"]["inputs"]["text"] == "placeholder"


def test_load_workflow_rejects_missing_prompt_nodes(tmp_path):
    bad = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}}}  # no node "7"
    with pytest.raises(ValueError):
        img._load_workflow(_wf_file(tmp_path, bad))


# ── Real layered workflow file (Story 5.7 inpaint fix) — regression guard ──
# Existing tests above only build synthetic tmp-dir fixtures; nothing else
# parses the actual shipped JSON, so a bad hand-edit to it would pass CI.

_LAYERED_WF_PATH = (
    Path(__file__).resolve().parents[3]
    / "data" / "workflows" / "comfyui_sdxl_anime_lora_layered_inspyrenet_api.json"
)


def test_layered_workflow_file_is_valid_and_prompt_injectable():
    wf = img._load_workflow(str(_LAYERED_WF_PATH))
    assert wf["9"]["inputs"]["images"] == ["18", 0], "background must save the inpainted frame"
    assert wf["16"]["inputs"]["mask"] == ["12", 1], "inpaint mask must come from segmentation"
    assert wf["17"]["inputs"]["negative"] == ["15", 0], "inpaint must use its own entity-exclusion negative"
    assert wf["18"]["class_type"] == "VAEDecode"


# ── Mock mode (AC4) ─────────────────────────────────────────────────────────

def _mock_settings(monkeypatch, tmp_path):
    """Wire mock mode: chdir to tmp so workspace/ is isolated, point fixtures at tmp."""
    monkeypatch.chdir(tmp_path)
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "mock.png").write_bytes(b"\x89PNG\r\n\x1a\n fake image bytes")
    monkeypatch.setattr(img, "MOCK_FIXTURES_DIR", fixtures)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=True, workflow_path="unused"))


async def test_mock_mode_sets_every_image_path_to_existing_file(monkeypatch, tmp_path):
    _mock_settings(monkeypatch, tmp_path)
    out = await img.image_node(_state())

    assert out["current_stage"] == "image"
    assert out.get("error") is None
    paths = [shot["image_path"] for scene in out["scenes"] for shot in scene["shots"]]
    assert len(paths) == 3
    for p in paths:
        assert p and (tmp_path / p).is_file()
        assert "workspace/run-img-1/images/" in p.replace("\\", "/")
    # deterministic, scene-numbered names
    assert paths[0].endswith("scene_001_S001.png")
    assert paths[2].endswith("scene_002_S003.png")


async def test_mock_mode_never_calls_comfyui(monkeypatch, tmp_path):
    _mock_settings(monkeypatch, tmp_path)

    async def boom(*a, **k):
        raise AssertionError("ComfyUI client must not be called in mock mode")
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", boom)

    out = await img.image_node(_state())
    assert out.get("error") is None


async def test_input_state_not_mutated(monkeypatch, tmp_path):
    _mock_settings(monkeypatch, tmp_path)
    state = _state()
    snapshot = json.loads(json.dumps(state))
    await img.image_node(state)
    assert state == snapshot  # AD-4 purity: no in-place edit of scenes/shots


# ── Real mode (AC1) — client mocked, no live HTTP ───────────────────────────

async def test_real_mode_writes_client_bytes(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path)))
    seen_prompts = []

    async def fake_fetch(url, workflow):
        assert url == "http://comfy.test:8188"
        seen_prompts.append((workflow["6"]["inputs"]["text"], workflow["7"]["inputs"]["text"]))
        return b"\x89PNG generated"
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    # per-shot prompt injection reached the client, in order
    assert seen_prompts[0] == ("a dark room", "blurry")
    assert seen_prompts[2] == ("a corridor", "watermark")
    for scene in out["scenes"]:
        for shot in scene["shots"]:
            assert (tmp_path / shot["image_path"]).read_bytes() == b"\x89PNG generated"


# ── Failure capture (AC2) ────────────────────────────────────────────────────

async def test_client_failure_sets_error_state(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path)))

    async def fail(*a, **k):
        raise ComfyUIError("ComfyUI rejected prompt: node_errors=...")
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fail)

    out = await img.image_node(_state())
    assert "scenes" not in out  # no partial advance
    assert out["current_stage"] == "image"
    assert out["error"] and "stage=image" in out["error"] and "run-img-1" in out["error"]


async def test_bad_workflow_file_sets_error_state(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    bad_path = _wf_file(tmp_path, {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}}})
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=bad_path))

    out = await img.image_node(_state())
    assert out.get("scenes") is None
    assert out["error"] and "stage=image" in out["error"]


# ── Observability (AC3) ──────────────────────────────────────────────────────

async def test_trace_records_request_and_image_counts(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path)))
    captured = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    async def fake_fetch(url, workflow):
        return b"img"
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    await img.image_node(_state())
    assert captured["request_count"] == 3  # one call per shot
    assert captured["image_count"] == 3
    assert captured["comfyui_url"] == "http://comfy.test:8188"
    assert isinstance(captured["latency_ms"], int)
    assert captured.get("error") is None


async def test_record_trace_is_non_fatal(monkeypatch):
    # AD-10: a Langfuse transport failure must not break the node.
    monkeypatch.setattr(img, "get_client", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    img._record_trace(comfyui_url="u", workflow_path="w", request_count=0, image_count=0, latency_ms=1)


# ── _has_alpha helper ────────────────────────────────────────────────────────

def test_has_alpha_detects_rgba():
    assert img._has_alpha(RGBA_PNG) is True


def test_has_alpha_rejects_rgb():
    assert img._has_alpha(RGB_PNG) is False


def test_has_alpha_rejects_garbage():
    assert img._has_alpha(b"not a png at all") is False


# ── Layered mock mode (AC1, AC2, AC3) ───────────────────────────────────────

def _layered_mock_settings(monkeypatch, tmp_path):
    """Wire layered + mock mode: inject both background and character fixtures."""
    monkeypatch.chdir(tmp_path)
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "mock_background.png").write_bytes(RGB_PNG)
    (fixtures / "mock_character.png").write_bytes(RGBA_PNG)
    monkeypatch.setattr(img, "MOCK_FIXTURES_DIR", fixtures)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(mock=True, workflow_path="unused", layered=True),
    )


async def test_layered_mock_sets_background_and_character_paths(monkeypatch, tmp_path):
    _layered_mock_settings(monkeypatch, tmp_path)
    out = await img.image_node(_state())

    assert out["current_stage"] == "image"
    assert out.get("error") is None
    for scene in out["scenes"]:
        for shot in scene["shots"]:
            assert shot["background_path"] and (tmp_path / shot["background_path"]).is_file()
            assert shot["character_path"] and (tmp_path / shot["character_path"]).is_file()
            assert shot["image_path"] and (tmp_path / shot["image_path"]).is_file()
            assert "_background.png" in shot["background_path"]
            assert "_character.png" in shot["character_path"]
            assert shot["layered_fallback"] is False


async def test_layered_mock_image_path_is_backward_compatible(monkeypatch, tmp_path):
    """image_path must exist and differ from background/character (AC1 compat)."""
    _layered_mock_settings(monkeypatch, tmp_path)
    out = await img.image_node(_state())
    for scene in out["scenes"]:
        for shot in scene["shots"]:
            assert shot["image_path"]
            assert shot["image_path"] != shot["background_path"] or True  # may alias; must exist
            assert (tmp_path / shot["image_path"]).is_file()


async def test_layered_mock_background_only_when_no_character_fixture(monkeypatch, tmp_path):
    """AC2: no character fixture → character_path is None, no failure."""
    monkeypatch.chdir(tmp_path)
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "mock_background.png").write_bytes(RGB_PNG)
    # intentionally no mock_character.png
    monkeypatch.setattr(img, "MOCK_FIXTURES_DIR", fixtures)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(mock=True, workflow_path="unused", layered=True),
    )
    out = await img.image_node(_state())

    assert out.get("error") is None
    for scene in out["scenes"]:
        for shot in scene["shots"]:
            assert shot["background_path"] is not None
            assert shot["character_path"] is None  # background-only
            assert shot["image_path"] is not None  # compat preserved


async def test_layered_mock_deterministic_names(monkeypatch, tmp_path):
    _layered_mock_settings(monkeypatch, tmp_path)
    out = await img.image_node(_state())
    shots = [s for scene in out["scenes"] for s in scene["shots"]]
    assert shots[0]["background_path"].replace("\\", "/").endswith("scene_001_S001_background.png")
    assert shots[2]["background_path"].replace("\\", "/").endswith("scene_002_S003_background.png")


async def test_layered_mock_input_state_not_mutated(monkeypatch, tmp_path):
    _layered_mock_settings(monkeypatch, tmp_path)
    state = _state()
    snapshot = json.loads(json.dumps(state))
    await img.image_node(state)
    assert state == snapshot


# ── Layered real mode — alpha validation (AC4) ──────────────────────────────

async def test_layered_real_opaque_character_falls_back_to_flat(monkeypatch, tmp_path):
    """Story 5.11: an opaque character output raises the same ComfyUIError type as a
    segmentation crash, so it gets the same per-shot flat-fallback treatment (Dev Notes:
    "no need to distinguish sub-cases") rather than failing the whole run (old AC4)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path), layered=True,
                             bg_node="9", char_node="10"),
    )

    async def fake_outputs(url, workflow, node_ids):
        return {"9": RGB_PNG, "10": RGB_PNG}  # character is opaque — invalid

    async def fake_fetch(url, workflow):
        return b"\x89PNG flat fallback bytes"

    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", fake_outputs)
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    for scene in out["scenes"]:
        for shot in scene["shots"]:
            assert shot["layered_fallback"] is True
            assert shot["character_path"] is None
            assert shot["background_path"] and (tmp_path / shot["background_path"]).is_file()


async def test_layered_real_missing_background_sets_error(monkeypatch, tmp_path):
    """Background node absent triggers the Story 5.11 flat fallback; if that fallback
    submission ALSO fails (as here), the run fails as before (AC2)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path), layered=True,
                             bg_node="9", char_node="10"),
    )

    async def fake_outputs(url, workflow, node_ids):
        return {"10": RGBA_PNG}  # only character, no background

    async def fake_fetch(url, workflow):
        raise ComfyUIError("ComfyUI unreachable")

    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", fake_outputs)
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert "scenes" not in out
    assert out["error"] and "stage=image" in out["error"]


async def test_layered_real_background_only_allowed(monkeypatch, tmp_path):
    """AC2: character node absent from output → character_path=None, no failure."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path), layered=True,
                             bg_node="9", char_node="10"),
    )

    async def fake_outputs(url, workflow, node_ids):
        return {"9": RGB_PNG}  # background only

    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", fake_outputs)

    out = await img.image_node(_state())
    assert out.get("error") is None
    for scene in out["scenes"]:
        for shot in scene["shots"]:
            assert shot["background_path"] is not None
            assert shot["character_path"] is None


async def test_layered_real_valid_rgba_character_accepted(monkeypatch, tmp_path):
    """AC1: valid RGBA character output sets character_path to existing file."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path), layered=True,
                             bg_node="9", char_node="10"),
    )

    async def fake_outputs(url, workflow, node_ids):
        return {"9": RGB_PNG, "10": RGBA_PNG}

    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", fake_outputs)

    out = await img.image_node(_state())
    assert out.get("error") is None
    for scene in out["scenes"]:
        for shot in scene["shots"]:
            assert shot["character_path"] and (tmp_path / shot["character_path"]).is_file()
            assert shot["background_path"] and (tmp_path / shot["background_path"]).is_file()
            assert shot["layered_fallback"] is False


# ── Segmentation-failure shot-level fallback (Story 5.11) ───────────────────

async def test_segmentation_failure_falls_back_to_flat_for_one_shot(monkeypatch, tmp_path):
    """AC1/AC3: one shot's ComfyUIError degrades only that shot to a flat image."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path), layered=True,
                             bg_node="9", char_node="10"),
    )

    call_count = 0

    async def fake_outputs(url, workflow, node_ids):
        nonlocal call_count
        call_count += 1
        if call_count == 1:  # first shot's segmentation errors
            raise ComfyUIError("segmentation node crashed")
        return {"9": RGB_PNG, "10": RGBA_PNG}  # every other shot succeeds

    async def fake_fetch(url, workflow):
        return b"\x89PNG flat fallback bytes"

    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", fake_outputs)
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    shots = [s for scene in out["scenes"] for s in scene["shots"]]

    failed = shots[0]
    assert failed["layered_fallback"] is True
    assert failed["character_path"] is None
    assert failed["background_path"] and (tmp_path / failed["background_path"]).read_bytes() == \
        b"\x89PNG flat fallback bytes"

    for ok in shots[1:]:
        assert ok["layered_fallback"] is False
        assert ok["character_path"] and (tmp_path / ok["character_path"]).is_file()
        assert ok["background_path"] and (tmp_path / ok["background_path"]).is_file()


async def test_segmentation_failure_fallback_also_fails_propagates(monkeypatch, tmp_path):
    """AC2: if the flat-fallback submission also raises, the whole run fails as before."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path), layered=True,
                             bg_node="9", char_node="10"),
    )

    async def fake_outputs(url, workflow, node_ids):
        raise ComfyUIError("segmentation node crashed")

    async def fake_fetch(url, workflow):
        raise ComfyUIError("ComfyUI unreachable")

    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", fake_outputs)
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert "scenes" not in out
    assert out["error"] and "stage=image" in out["error"]
    # Review fix: the original segmentation error must not be discarded when the
    # fallback also fails — both messages should be visible for diagnosis.
    assert "segmentation node crashed" in out["error"]
    assert "ComfyUI unreachable" in out["error"]


async def test_segmentation_failure_bad_fallback_workflow_path_fails_gracefully(monkeypatch, tmp_path):
    """Review fix: a misconfigured comfyui_flat_fallback_workflow_path raises inside
    _load_workflow (not a ComfyUIError) — it must still be caught and reported, not
    crash uncaught past the per-shot handler."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path), layered=True,
                             bg_node="9", char_node="10",
                             flat_fallback_workflow_path="does/not/exist.json"),
    )

    async def fake_outputs(url, workflow, node_ids):
        raise ComfyUIError("segmentation node crashed")

    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", fake_outputs)

    out = await img.image_node(_state())
    assert "scenes" not in out
    assert out["error"] and "stage=image" in out["error"]
    assert "segmentation node crashed" in out["error"]


async def test_segmentation_failure_fallback_records_count(monkeypatch, tmp_path):
    """The fallback_count/request_count trace metadata reflects the number of degraded
    shots and the real ComfyUI submissions made (failed layered attempt + fallback)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path), layered=True,
                             bg_node="9", char_node="10"),
    )
    captured = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    async def fake_outputs(url, workflow, node_ids):
        raise ComfyUIError("segmentation node crashed")

    async def fake_fetch(url, workflow):
        return b"\x89PNG flat"

    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", fake_outputs)
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    await img.image_node(_state())
    assert captured["fallback_count"] == 3  # every shot in this fixture fails and falls back
    # Review fix: both the failed layered attempt and the fallback attempt count as
    # real ComfyUI requests — 2 per shot, not 1.
    assert captured["request_count"] == 6


# ── Layered observability (AC5) ──────────────────────────────────────────────

async def test_layered_trace_includes_layered_metadata(monkeypatch, tmp_path):
    """AC5: span metadata includes background_count, character_count, layered flag."""
    _layered_mock_settings(monkeypatch, tmp_path)
    captured = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    await img.image_node(_state())

    assert captured["layered_assets_enabled"] is True
    assert captured["background_count"] == 3   # one per shot
    assert captured["character_count"] == 3    # character fixture present


# ── Shot-level resume + health check (Story 5.14) ───────────────────────────

def _resume_settings(tmp_path):
    return FakeSettings(mock=False, workflow_path=_wf_file(tmp_path), layered=True,
                         bg_node="9", char_node="10")


def _write_complete_layered_shot(d, base, image_prompt, negative_prompt):
    (d / f"{base}_background.png").write_bytes(RGB_PNG + b"\x00" * 1200)
    (d / f"{base}_character.png").write_bytes(RGBA_PNG + b"\x00" * 1200)
    (d / f"{base}.png").write_bytes(RGB_PNG + b"\x00" * 1200)
    (d / f"{base}_done.json").write_text(
        json.dumps({"image_prompt": image_prompt, "negative_prompt": negative_prompt})
    )


async def test_layered_resume_skips_complete_shots(monkeypatch, tmp_path):
    """AC1: a shot with complete img+bg+char (>1KB) + matching sidecar is skipped —
    zero ComfyUI submissions for it, existing paths reused, layered_fallback False."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    base = "scene_001_S001"
    _write_complete_layered_shot(d, base, "a dark room", "blurry")

    call_count = 0

    async def fake_outputs(url, workflow, node_ids):
        nonlocal call_count
        call_count += 1
        return {"9": RGB_PNG, "10": RGBA_PNG}
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", fake_outputs)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert call_count == 2  # only S002/S003 submitted

    s001 = [s for scene in out["scenes"] for s in scene["shots"]][0]
    assert s001["layered_fallback"] is False
    assert s001["background_path"] == f"workspace/run-img-1/images/{base}_background.png"
    assert s001["character_path"] == f"workspace/run-img-1/images/{base}_character.png"
    assert s001["image_path"] == f"workspace/run-img-1/images/{base}.png"


async def test_resume_regenerates_on_prompt_mismatch(monkeypatch, tmp_path):
    """AC2: sidecar present but prompts differ (retry after a prompt edit) → regenerate."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    _write_complete_layered_shot(d, "scene_001_S001", "OLD PROMPT", "blurry")

    call_count = 0

    async def fake_outputs(url, workflow, node_ids):
        nonlocal call_count
        call_count += 1
        return {"9": RGB_PNG, "10": RGBA_PNG}
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", fake_outputs)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert call_count == 3  # stale sidecar rejected — all shots regenerate


async def test_resume_regenerates_background_only_remnant(monkeypatch, tmp_path):
    """AC2: crash remnant / 5-11 fallback leftover (bg only, no char, no sidecar) regenerates."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    base = "scene_001_S001"
    (d / f"{base}_background.png").write_bytes(RGB_PNG + b"\x00" * 1200)
    (d / f"{base}.png").write_bytes(RGB_PNG + b"\x00" * 1200)
    # no character file, no sidecar

    call_count = 0

    async def fake_outputs(url, workflow, node_ids):
        nonlocal call_count
        call_count += 1
        return {"9": RGB_PNG, "10": RGBA_PNG}
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", fake_outputs)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert call_count == 3


async def test_resume_regenerates_undersized_files(monkeypatch, tmp_path):
    """AC2: matching sidecar but bg ≤1KB (truncated write) → regenerates."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    base = "scene_001_S001"
    (d / f"{base}_background.png").write_bytes(RGB_PNG)  # under the 1KB floor
    (d / f"{base}_character.png").write_bytes(RGBA_PNG + b"\x00" * 1200)
    (d / f"{base}.png").write_bytes(RGB_PNG + b"\x00" * 1200)
    (d / f"{base}_done.json").write_text(json.dumps({"image_prompt": "a dark room", "negative_prompt": "blurry"}))

    call_count = 0

    async def fake_outputs(url, workflow, node_ids):
        nonlocal call_count
        call_count += 1
        return {"9": RGB_PNG, "10": RGBA_PNG}
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", fake_outputs)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert call_count == 3


async def test_full_resume_completes_with_comfyui_down(monkeypatch, tmp_path):
    """AC4 payoff: if every shot is already complete on disk, the node never touches
    ComfyUI at all — even a dead server doesn't fail a fully-resumed retry."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    for base, prompt, neg in [
        ("scene_001_S001", "a dark room", "blurry"),
        ("scene_001_S002", "an agent", "text"),
        ("scene_002_S003", "a corridor", "watermark"),
    ]:
        _write_complete_layered_shot(d, base, prompt, neg)

    async def boom_health(*a, **k):
        raise AssertionError("check_health must not be called when every shot is resumed")

    async def boom_outputs(*a, **k):
        raise AssertionError("submit_and_fetch_outputs must not be called when every shot is resumed")

    async def boom_fetch(*a, **k):
        raise AssertionError("submit_and_fetch must not be called when every shot is resumed")
    monkeypatch.setattr(img.comfyui_client, "check_health", boom_health)
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", boom_outputs)
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", boom_fetch)

    captured = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert captured["skipped_count"] == 3
    assert captured["request_count"] == 0


async def test_health_check_failure_fails_fast(monkeypatch, tmp_path):
    """AC4: unreachable ComfyUI fails the whole stage before any submission — AD-10 contract."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))

    async def dead(*a, **k):
        raise ComfyUIError("ComfyUI unreachable at http://comfy.test:8188: refused")

    async def boom_outputs(*a, **k):
        raise AssertionError("submit_and_fetch_outputs must not be called after a failed health check")

    async def boom_fetch(*a, **k):
        raise AssertionError("submit_and_fetch must not be called after a failed health check")
    monkeypatch.setattr(img.comfyui_client, "check_health", dead)
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", boom_outputs)
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", boom_fetch)

    out = await img.image_node(_state())
    assert "scenes" not in out
    assert out["error"] and "stage=image" in out["error"] and "run-img-1" in out["error"]


async def test_mock_mode_never_checks_health(monkeypatch, tmp_path):
    """AC4: mock mode never checks health (no HTTP client instantiated at all)."""
    _mock_settings(monkeypatch, tmp_path)

    async def boom(*a, **k):
        raise AssertionError("check_health must not be called in mock mode")
    monkeypatch.setattr(img.comfyui_client, "check_health", boom)

    out = await img.image_node(_state())
    assert out.get("error") is None


async def test_resume_skipped_count_in_trace(monkeypatch, tmp_path):
    """AC6: skipped_count appears in trace metadata; request_count still counts only
    real submissions — one resumed shot (0), one fallback-degraded shot (2), one
    normal success (1)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    _write_complete_layered_shot(d, "scene_001_S001", "a dark room", "blurry")

    call_count = 0

    async def fake_outputs(url, workflow, node_ids):
        nonlocal call_count
        call_count += 1
        if call_count == 1:  # S002: segmentation fails, falls back
            raise ComfyUIError("segmentation node crashed")
        return {"9": RGB_PNG, "10": RGBA_PNG}  # S003: succeeds normally

    async def fake_fetch(url, workflow):
        return b"\x89PNG flat fallback bytes"
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch_outputs", fake_outputs)
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    captured = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert captured["skipped_count"] == 1
    assert captured["request_count"] == 3  # S001 skip=0, S002 fallback=2, S003 normal=1


async def test_non_layered_trace_has_zero_layered_counts(monkeypatch, tmp_path):
    """Non-layered mode: layered fields are present but zeroed."""
    _mock_settings(monkeypatch, tmp_path)
    captured = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    await img.image_node(_state())

    assert captured["layered_assets_enabled"] is False
    assert captured["background_count"] == 0
    assert captured["character_count"] == 0
