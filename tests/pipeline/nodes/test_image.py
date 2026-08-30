"""Unit tests for src/yt_flow/pipeline/nodes/image.py (Story 1.6, background-only
since Story 8.3).

No live ComfyUI / Langfuse: the HTTP client, settings, trace sink, and (for
mock mode) the fixtures dir are all monkeypatched. Tests assert the node's
PipelineState contract (image_path set on every shot, error handling, purity),
prompt injection into the nodes resolved from their ``ytflow:`` manifest titles
(including the AC2 negative-prompt suffix), the mock/real branch behaviour, and
shot-level resume/health-check.
"""

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

import yt_flow.pipeline.nodes.image as img
from yt_flow.services.comfyui_client import ComfyUIError

# Story 13.3: injection targets are resolved by exact ``_meta.title``, so every
# fixture workflow must declare them. The node ids stay "6"/"7" purely so the
# assertions below still read naturally — nothing in the code looks at them.
GOOD_WF = {
    "6": {"class_type": "CLIPTextEncode", "_meta": {"title": img.POSITIVE_KEY},
          "inputs": {"text": "placeholder"}},
    "7": {"class_type": "CLIPTextEncode", "_meta": {"title": img.NEGATIVE_KEY},
          "inputs": {"text": "placeholder"}},
}
GOOD_NODES = {img.POSITIVE_KEY: "6", img.NEGATIVE_KEY: "7"}

RGB_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class FakeSettings:
    def __init__(
        self, *, mock, workflow_path,
        health_poll_every_n_shots=20, crash_recovery_poll_sec=15.0, crash_recovery_timeout_sec=300.0,
        # DELIBERATELY DIVERGES FROM THE SHIPPED DEFAULT, which is True since Story
        # 14.8. This said "mirrors the real Settings default" until then, and the comment
        # was load-bearing for nothing: flipping the real default would not have failed a
        # single test here. `False` is kept because ~25 pre-14.1 tests below are about the
        # generation path and would silently start copying plates instead; the plate tests
        # opt in with `stock_plate_substitution=True`, exactly as the guard tests opt into
        # `guard_attempts`. The shipped value is NOT pinned by a test on purpose — CLAUDE.md
        # forbids asserting a decided value equals its default (it turns the drift report
        # into a gate by proxy); `scripts/report_decision_drift.py` is the reader.
        stock_plate_substitution=False,
        # DELIBERATELY DIVERGES FROM THE SHIPPED DEFAULT, which is 2 since Story 14.4.
        # 0 here keeps the ~25 pre-10.2 tests below asserting exactly one render per
        # shot, which is what they are actually about; raising it to 2 would rewrite
        # their render-count expectations for no gain. The guard tests opt in through
        # `_guard_settings`, and the shipped value is pinned where it belongs —
        # `tests/test_config.py::test_background_person_guard_default_ships_the_decision`.
        guard_attempts=0, vision_api_key="",
        # MATCHES the shipped default, which Story 14.2's review loop 1 settled at OFF
        # (unreachable pre-registration bar + Jay's 33-pair adjudication still open). The
        # 14.2 tests opt in through `_affordance_settings`, exactly as the guard tests opt
        # into `guard_attempts`; the shipped value is pinned where it belongs,
        # `tests/test_config.py::test_plate_affordance_gate_default_ships_the_decision`.
        plate_affordance_gate=False,
    ):
        self.stock_plate_substitution_enabled = stock_plate_substitution
        self.plate_affordance_gate_enabled = plate_affordance_gate
        self.background_person_guard_attempts = guard_attempts
        self.character_vision_api_key = vision_api_key
        self.workspace_path = "workspace"  # relative → isolated by monkeypatch.chdir(tmp_path)
        self.comfyui_url = "http://comfy.test:8188"
        self.comfyui_workflow_path = workflow_path
        self.comfyui_mock = mock
        self.comfyui_health_poll_every_n_shots = health_poll_every_n_shots
        self.comfyui_crash_recovery_poll_sec = crash_recovery_poll_sec
        self.comfyui_crash_recovery_timeout_sec = crash_recovery_timeout_sec


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
                     "image_path": None, "cast": []},
                    {"shot_id": "S002", "sentence_indices": [0, 1], "image_prompt": "an agent",
                     "negative_prompt": "text", "camera_angle": None, "camera_movement": None,
                     "image_path": None, "cast": []},
                ],
            },
            {
                "scene_num": 2, "narration": "n2", "audio_path": None, "audio_duration": None,
                "word_timings": [], "subtitle_path": None,
                "shots": [
                    {"shot_id": "S003", "sentence_indices": [2], "image_prompt": "a corridor",
                     "negative_prompt": "watermark", "camera_angle": None, "camera_movement": "pan",
                     "image_path": None, "cast": []},
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


FAKE_STATS = {
    "system": {"comfyui_version": "0.12.3", "pytorch_version": "2.11.0.dev+rocm7.1"},
    "devices": [{"name": "cuda:0 AMD Radeon Graphics : native", "vram_free": 13569163776}],
}


@pytest.fixture(autouse=True)
def _fake_system_stats(monkeypatch):
    """Story 13.3: real mode reads /system_stats once per run for provenance.

    Stubbed by default so no test opens a socket to comfy.test; the provenance
    tests below override it to assert the recorded shape and the failure path.
    """
    async def stats(*a, **k):
        return FAKE_STATS
    monkeypatch.setattr(img.comfyui_client, "get_system_stats", stats)


# ── Prompt injection (AC1, AC2) — pure, no ComfyUI ──────────────────────────

def test_inject_prompts_targets_the_resolved_nodes():
    # Story 11.1: _inject_prompts grew a required seed arg (single call site).
    # Story 13.3: and a resolved {manifest key: node id} map.
    out = img._inject_prompts(GOOD_WF, GOOD_NODES, "positive text", "negative text", 1)
    assert out["6"]["inputs"]["text"] == "positive text"
    # template is untouched — one loaded workflow is safely reused per shot
    assert GOOD_WF["6"]["inputs"]["text"] == "placeholder"


def test_inject_prompts_appends_negative_suffix():
    """AC2: code-side entity exclusion belt, on top of the prompt-side (8.1) suspenders."""
    out = img._inject_prompts(GOOD_WF, GOOD_NODES, "a corridor", "watermark", 1)
    assert out["7"]["inputs"]["text"] == "watermark" + img.BG_NEGATIVE_SUFFIX
    for term in ("person", "human", "character", "silhouette"):
        assert term in out["7"]["inputs"]["text"]


# ── Per-shot deterministic seed (Story 11.1 AC1) ────────────────────────────

def test_shot_seed_deterministic_and_distinct():
    a = img._shot_seed("run-1", 1, "S001")
    assert a == img._shot_seed("run-1", 1, "S001")  # same shot → same seed
    assert a != img._shot_seed("run-1", 1, "S002")  # different shot → different seed
    assert a != img._shot_seed("run-2", 1, "S001")  # different run → different seed
    assert 0 <= a < 2**32


def test_shot_seed_is_sha256_not_builtin_hash():
    """Builtin hash() is salted per process (PYTHONHASHSEED) — a resumed run is a
    new process, so the seed must come from sha256 to survive restarts."""
    import hashlib
    expected = int(hashlib.sha256(b"run-1:1:S001").hexdigest(), 16) % 2**32
    assert img._shot_seed("run-1", 1, "S001") == expected


def test_inject_prompts_seeds_every_ksampler_by_class_type():
    """AC1: all KSampler nodes matched by class_type, never by node ID."""
    wf = {
        **GOOD_WF,
        "3": {"class_type": "KSampler", "inputs": {"seed": 0}},
        "42": {"class_type": "KSampler", "inputs": {"seed": 0}},
    }
    out = img._inject_prompts(wf, GOOD_NODES, "p", "n", 1234)
    assert out["3"]["inputs"]["seed"] == 1234
    assert out["42"]["inputs"]["seed"] == 1234
    # template purity holds for the seed too
    assert wf["3"]["inputs"]["seed"] == 0


def test_inject_prompts_harmless_without_ksampler():
    out = img._inject_prompts(GOOD_WF, GOOD_NODES, "p", "n", 99)  # GOOD_WF has no KSampler
    assert out["6"]["inputs"]["text"] == "p"


def test_load_workflow_rejects_missing_prompt_nodes(tmp_path):
    bad = {"6": GOOD_WF["6"]}  # no ytflow:negative_prompt anywhere
    with pytest.raises(ValueError) as exc:
        img._load_workflow(_wf_file(tmp_path, bad))
    # AC1: the operator must be able to fix a UI rename without reading code.
    assert img.NEGATIVE_KEY in str(exc.value)
    assert img.POSITIVE_KEY in str(exc.value)  # ...listed among the titles present


def test_load_workflow_resolves_by_title_not_by_node_id(tmp_path):
    """Story 13.3: renumbering the graph must not move the injection target."""
    renumbered = {"41": GOOD_WF["7"], "99": GOOD_WF["6"]}
    workflow, nodes = img._load_workflow(_wf_file(tmp_path, renumbered))
    assert nodes == {img.POSITIVE_KEY: "99", img.NEGATIVE_KEY: "41"}
    out = img._inject_prompts(workflow, nodes, "a corridor", "watermark", 7)
    assert out["99"]["inputs"]["text"] == "a corridor"
    assert out["41"]["inputs"]["text"].startswith("watermark")


def test_load_workflow_rejects_a_title_pasted_onto_the_wrong_class(tmp_path):
    """The class-type check survives the switch to titles, on the resolved node."""
    bad = {**GOOD_WF, "6": {"class_type": "LoraLoader", "_meta": {"title": img.POSITIVE_KEY},
                            "inputs": {"lora_name": "x.safetensors"}}}
    with pytest.raises(ValueError, match="CLIPTextEncode"):
        img._load_workflow(_wf_file(tmp_path, bad))


# ── Mock mode (AC4) ─────────────────────────────────────────────────────────

def _mock_settings(monkeypatch, tmp_path, **over):
    """Wire mock mode: chdir to tmp so workspace/ is isolated, point fixtures at tmp."""
    monkeypatch.chdir(tmp_path)
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "mock.png").write_bytes(b"\x89PNG\r\n\x1a\n fake image bytes")
    monkeypatch.setattr(img, "MOCK_FIXTURES_DIR", fixtures)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=True, workflow_path="unused", **over))


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


async def test_mock_mode_never_checks_health(monkeypatch, tmp_path):
    """AC4: mock mode never checks health (no HTTP client instantiated at all)."""
    _mock_settings(monkeypatch, tmp_path)

    async def boom(*a, **k):
        raise AssertionError("check_health must not be called in mock mode")
    monkeypatch.setattr(img.comfyui_client, "check_health", boom)

    out = await img.image_node(_state())
    assert out.get("error") is None


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
    # per-shot prompt injection reached the client, in order, negative suffix applied
    assert seen_prompts[0] == ("a dark room", "blurry" + img.BG_NEGATIVE_SUFFIX)
    assert seen_prompts[2] == ("a corridor", "watermark" + img.BG_NEGATIVE_SUFFIX)
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


# ── Shot-level resume + health check (Story 5.14) ───────────────────────────

def _resume_settings(tmp_path):
    return FakeSettings(mock=False, workflow_path=_wf_file(tmp_path))


def _shot_seed_for(base, run_id="run-img-1"):
    """Seed the node itself would compute for a `scene_NNN_SHOTID` base name."""
    _, scene, shot_id = base.split("_")
    return img._shot_seed(run_id, int(scene), shot_id)


def _write_complete_shot(d, base, image_prompt, negative_prompt, *, seed=None):
    (d / f"{base}.png").write_bytes(RGB_PNG + b"\x00" * 1200)
    (d / f"{base}_done.json").write_text(
        json.dumps({
            "image_prompt": image_prompt,
            "negative_prompt": img._effective_negative_prompt(negative_prompt),
            # Story 11.1 AC2: sidecars pin the deterministic per-shot seed
            "seed": _shot_seed_for(base) if seed is None else seed,
        })
    )


async def test_resume_skips_complete_shot(monkeypatch, tmp_path):
    """AC3: a shot whose .png (>1KB) + matching sidecar exist is skipped."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    _write_complete_shot(d, "scene_001_S001", "a dark room", "blurry")

    call_count = 0

    async def fake_fetch(url, workflow):
        nonlocal call_count
        call_count += 1
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert call_count == 2  # only S002/S003 submitted

    s001 = [s for scene in out["scenes"] for s in scene["shots"]][0]
    assert s001["image_path"] == "workspace/run-img-1/images/scene_001_S001.png"


async def test_resume_regenerates_on_prompt_mismatch(monkeypatch, tmp_path):
    """AC2: sidecar present but prompts differ (retry after a prompt edit) → regenerate."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    _write_complete_shot(d, "scene_001_S001", "OLD PROMPT", "blurry")

    call_count = 0

    async def fake_fetch(url, workflow):
        nonlocal call_count
        call_count += 1
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert call_count == 3  # stale sidecar rejected — all shots regenerate


async def test_resume_regenerates_legacy_sidecar_without_bg_suffix(monkeypatch, tmp_path):
    """Story 8.3 AC2: pre-8.3 sidecars lacked the background-only negative suffix,
    so they must not resume images generated without the code-side entity guard."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    base = "scene_001_S001"
    (d / f"{base}.png").write_bytes(RGB_PNG + b"\x00" * 1200)
    (d / f"{base}_done.json").write_text(
        json.dumps({"image_prompt": "a dark room", "negative_prompt": "blurry"})
    )

    call_count = 0

    async def fake_fetch(url, workflow):
        nonlocal call_count
        call_count += 1
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert call_count == 3


async def test_resume_regenerates_on_seed_mismatch(monkeypatch, tmp_path):
    """Story 11.1 AC2: matching prompts but a different pinned seed → regenerate."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    _write_complete_shot(d, "scene_001_S001", "a dark room", "blurry", seed=12345)

    call_count = 0

    async def fake_fetch(url, workflow):
        nonlocal call_count
        call_count += 1
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert call_count == 3  # seed mismatch rejected — all shots regenerate


async def test_resume_regenerates_legacy_sidecar_without_seed(monkeypatch, tmp_path):
    """Story 11.1 AC2: pre-11.1 sidecars have no seed key → mismatch → regenerate
    (intended one-time cache invalidation; the AR change made old images stale anyway)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    base = "scene_001_S001"
    (d / f"{base}.png").write_bytes(RGB_PNG + b"\x00" * 1200)
    (d / f"{base}_done.json").write_text(json.dumps({
        "image_prompt": "a dark room",
        "negative_prompt": img._effective_negative_prompt("blurry"),
    }))

    call_count = 0

    async def fake_fetch(url, workflow):
        nonlocal call_count
        call_count += 1
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert call_count == 3


async def test_generated_sidecar_records_shot_seed(monkeypatch, tmp_path):
    """Story 11.1 AC1+AC2: the submitted workflow carries the deterministic seed
    and the sidecar written afterwards pins the same value (real generation path;
    the mock path shares the same sidecar write at the loop bottom)."""
    monkeypatch.chdir(tmp_path)
    wf = {**GOOD_WF, "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path, wf)))

    submitted_seeds = []

    async def fake_fetch(url, workflow):
        submitted_seeds.append(workflow["3"]["inputs"]["seed"])
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert submitted_seeds == [
        img._shot_seed("run-img-1", 1, "S001"),
        img._shot_seed("run-img-1", 1, "S002"),
        img._shot_seed("run-img-1", 2, "S003"),
    ]
    assert len(set(submitted_seeds)) == 3  # per-shot, not shared
    d = tmp_path / "workspace" / "run-img-1" / "images"
    sidecar = json.loads((d / "scene_001_S001_done.json").read_text())
    assert sidecar["seed"] == img._shot_seed("run-img-1", 1, "S001")


async def test_resume_regenerates_on_missing_sidecar(monkeypatch, tmp_path):
    """AC3: a .png on disk without a matching sidecar regenerates (no false resume)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    (d / "scene_001_S001.png").write_bytes(RGB_PNG + b"\x00" * 1200)  # no sidecar

    call_count = 0

    async def fake_fetch(url, workflow):
        nonlocal call_count
        call_count += 1
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert call_count == 3  # every shot regenerates


async def test_resume_regenerates_undersized_files(monkeypatch, tmp_path):
    """AC2: matching sidecar but the image ≤1KB (truncated write) → regenerates."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    base = "scene_001_S001"
    (d / f"{base}.png").write_bytes(RGB_PNG)  # under the 1KB floor
    (d / f"{base}_done.json").write_text(json.dumps({
        "image_prompt": "a dark room",
        "negative_prompt": img._effective_negative_prompt("blurry"),
        "seed": _shot_seed_for(base),
    }))

    call_count = 0

    async def fake_fetch(url, workflow):
        nonlocal call_count
        call_count += 1
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

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
        _write_complete_shot(d, base, prompt, neg)

    async def boom_health(*a, **k):
        raise AssertionError("check_health must not be called when every shot is resumed")

    async def boom_fetch(*a, **k):
        raise AssertionError("submit_and_fetch must not be called when every shot is resumed")
    monkeypatch.setattr(img.comfyui_client, "check_health", boom_health)
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

    async def boom_fetch(*a, **k):
        raise AssertionError("submit_and_fetch must not be called after a failed health check")
    monkeypatch.setattr(img.comfyui_client, "check_health", dead)
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", boom_fetch)

    out = await img.image_node(_state())
    assert "scenes" not in out
    assert out["error"] and "stage=image" in out["error"] and "run-img-1" in out["error"]


async def test_health_check_called_once_across_multiple_shots(monkeypatch, tmp_path):
    """AC4 dedup: the lazy health_checked flag fires check_health once per image_node
    call, not once per shot needing generation."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))

    health_calls = 0

    async def count_health(*a, **k):
        nonlocal health_calls
        health_calls += 1
    monkeypatch.setattr(img.comfyui_client, "check_health", count_health)

    async def fake_fetch(url, workflow):
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())  # no pre-existing files → all 3 shots generate
    assert out.get("error") is None
    assert health_calls == 1


async def test_resume_skipped_count_in_trace(monkeypatch, tmp_path):
    """AC6: skipped_count appears in trace metadata; request_count still counts only
    real submissions."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    _write_complete_shot(d, "scene_001_S001", "a dark room", "blurry")

    async def fake_fetch(url, workflow):
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    captured = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert captured["skipped_count"] == 1
    assert captured["request_count"] == 2  # S001 skip=0, S002/S003 normal=1 each


# ── Sustained-load crash mitigation (Story 5.23) ────────────────────────────

def _many_shots_state(n):
    shots = [
        {"shot_id": f"S{i:03d}", "sentence_indices": [i], "image_prompt": f"prompt {i}",
         "negative_prompt": "neg", "camera_angle": None, "camera_movement": None,
         "image_path": None, "cast": []}
        for i in range(n)
    ]
    return {
        "run_id": "run-img-1", "scp_text": "SCP-173",
        "scenes": [{
            "scene_num": 1, "narration": "n1", "audio_path": None, "audio_duration": None,
            "word_timings": [], "subtitle_path": None, "shots": shots,
        }],
        "video_path": None, "current_stage": "", "gate_states": {},
        "prompt_variant": None, "error": None,
    }


async def test_periodic_health_check_triggers_mid_batch(monkeypatch, tmp_path):
    """AC1/AC7: check_health re-runs every N generated shots, not only at shot 0."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path), health_poll_every_n_shots=2),
    )
    calls = 0

    async def count_health(url):
        nonlocal calls
        calls += 1
    monkeypatch.setattr(img.comfyui_client, "check_health", count_health)

    async def fake_fetch(url, workflow):
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_many_shots_state(4))
    assert out.get("error") is None
    assert calls == 2  # shot 0's initial check + one periodic re-check before shot index 2


async def test_recovery_loop_continues_after_transient_failure(monkeypatch, tmp_path):
    """AC2: a mid-batch health-check failure waits and rechecks instead of failing the stage."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(
            mock=False, workflow_path=_wf_file(tmp_path),
            health_poll_every_n_shots=2, crash_recovery_poll_sec=0.01, crash_recovery_timeout_sec=5.0,
        ),
    )
    calls = 0

    async def flaky_health(url):
        nonlocal calls
        calls += 1
        if calls in (2, 3):  # the periodic check + first recovery poll both fail
            raise ComfyUIError("down")
    monkeypatch.setattr(img.comfyui_client, "check_health", flaky_health)

    fetch_calls = 0

    async def fake_fetch(url, workflow):
        nonlocal fetch_calls
        fetch_calls += 1
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_many_shots_state(3))
    assert out.get("error") is None
    assert fetch_calls == 3  # every shot still generated after recovery
    assert calls == 4  # initial + failed periodic + failed poll + recovered poll


async def test_recovery_loop_times_out_and_fails_stage(monkeypatch, tmp_path):
    """AC3: recovery window expiring fails the stage with the existing error format."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(
            mock=False, workflow_path=_wf_file(tmp_path),
            health_poll_every_n_shots=2, crash_recovery_poll_sec=0.01, crash_recovery_timeout_sec=0.05,
        ),
    )
    first_call = True

    async def always_down(url):
        nonlocal first_call
        if first_call:  # shot 0's fail-fast check must still pass
            first_call = False
            return None
        raise ComfyUIError("ComfyUI unreachable: refused")
    monkeypatch.setattr(img.comfyui_client, "check_health", always_down)

    async def fake_fetch(url, workflow):
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_many_shots_state(3))
    assert "scenes" not in out
    assert out["error"] and "stage=image" in out["error"] and "run-img-1" in out["error"]


async def test_submit_and_fetch_failure_recovers_via_same_helper(monkeypatch, tmp_path):
    """AC4: a submit_and_fetch failure (not a health-check failure) reuses the same
    recovery loop before failing, and the shot succeeds once ComfyUI is healthy again."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        img, "_settings",
        lambda: FakeSettings(
            mock=False, workflow_path=_wf_file(tmp_path),
            crash_recovery_poll_sec=0.01, crash_recovery_timeout_sec=5.0,
        ),
    )

    async def healthy(url):
        return None  # ComfyUI itself is fine — only submit_and_fetch hiccups once
    monkeypatch.setattr(img.comfyui_client, "check_health", healthy)

    fetch_calls = 0

    async def flaky_fetch(url, workflow):
        nonlocal fetch_calls
        fetch_calls += 1
        if fetch_calls == 1:
            raise ComfyUIError("connection refused")
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", flaky_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert fetch_calls == 4  # shot 1: fail + retry, shots 2/3: succeed first try


# ── STOCK location plate fast path (Story 8.5) ──────────────────────────────

@pytest.fixture(autouse=True)
def _reset_location_service():
    img._location_service = None
    yield
    img._location_service = None


@pytest.fixture(autouse=True)
def _reset_depth_resolver():
    """Story 11.5: no depth resolver by default, so every pre-11.5 test keeps its
    exact shot dicts (no depth_map_path key at all)."""
    img._depth_resolver = None
    yield
    img._depth_resolver = None


def _plate(variant, path, viewpoint="EYE", **over):
    """A resolved plate exactly as ``LocationService.resolve_stock_plates`` hands it to
    image_node since Story 14.1: the measurement merged in, ``variant``/``path`` last.

    ``EYE`` + ``standing_room`` by default because ``_stock_state``'s shot is ``wide``, so
    the default fixture is a HIT — the pre-14.1 tests below are about what happens after
    the pick, and an unmeasured plate is deliberately never picked at all.
    """
    return {"viewpoint": viewpoint, "standing_room": True,
            **over, "variant": variant, "path": str(path)}


def _stock_state(location_key="corridor", **shot_over):
    shot = {
        "shot_id": "S001", "sentence_indices": [0], "image_prompt": "a dark room",
        "negative_prompt": "blurry", "camera_angle": "wide", "camera_movement": None,
        "image_path": None, "cast": [], "location_key": location_key,
    }
    shot.update(shot_over)
    return {
        "run_id": "run-stock-1", "scp_text": "SCP-173",
        "scenes": [{
            "scene_num": 1, "narration": "n1", "audio_path": None, "audio_duration": None,
            "word_timings": [], "subtitle_path": None, "shots": [shot],
        }],
        "video_path": None, "current_stage": "", "gate_states": {},
        "prompt_variant": None, "error": None,
    }


async def test_stock_plate_hit_copies_file_and_skips_generation(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(
        mock=False, workflow_path=_wf_file(tmp_path), stock_plate_substitution=True))
    plate_src = tmp_path / "plate.png"
    plate_src.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve(location_key):
        assert location_key == "corridor"
        return [_plate("a", plate_src)]
    img.inject_location_service(resolve)

    async def boom_fetch(*a, **k):
        raise AssertionError("submit_and_fetch must not be called on a STOCK plate hit")
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", boom_fetch)

    async def boom_health(*a, **k):
        raise AssertionError("check_health must not be called on a STOCK plate hit")
    monkeypatch.setattr(img.comfyui_client, "check_health", boom_health)

    out = await img.image_node(_stock_state())
    assert out.get("error") is None
    shot = out["scenes"][0]["shots"][0]
    assert shot["image_path"] and (tmp_path / shot["image_path"]).is_file()


@pytest.mark.parametrize("enabled", [False, True])
async def test_stock_plate_substitution_flag_gates_the_plate_path(monkeypatch, tmp_path, enabled):
    """Approved plates exist for the location_key, so the ONLY thing deciding
    plate-copy vs generation is the flag. Off (the default) must render
    image_prompt — 8.17's substitution discarded it and collapsed background
    variety run-wide."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(
        mock=False, workflow_path=_wf_file(tmp_path), stock_plate_substitution=enabled))
    plate_src = tmp_path / "plate.png"
    plate_src.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve(location_key):
        return [_plate("a", plate_src)]
    img.inject_location_service(resolve)

    prompts = []

    async def fake_fetch(url, workflow):
        prompts.append(workflow["6"]["inputs"]["text"])
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_stock_state())
    assert out.get("error") is None
    rendered = (tmp_path / out["scenes"][0]["shots"][0]["image_path"]).read_bytes()
    if enabled:
        assert prompts == []
        assert rendered == plate_src.read_bytes()
    else:
        assert prompts == ["a dark room"]


async def test_stock_plate_miss_falls_through_to_generation(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(
        mock=False, workflow_path=_wf_file(tmp_path), stock_plate_substitution=True))

    async def resolve(location_key):
        return []
    img.inject_location_service(resolve)

    fetch_called = False

    async def fake_fetch(url, workflow):
        nonlocal fetch_called
        fetch_called = True
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_stock_state())
    assert out.get("error") is None
    assert fetch_called


async def test_stock_plate_no_service_injected_falls_through_to_generation(monkeypatch, tmp_path):
    """No injection wired (e.g. a fresh test process) — location_key must not crash the node."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path)))

    async def fake_fetch(url, workflow):
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_stock_state())
    assert out.get("error") is None
    assert out["scenes"][0]["shots"][0]["image_path"]


async def test_stock_plate_hit_in_mock_mode_still_copies_plate(monkeypatch, tmp_path):
    _mock_settings(monkeypatch, tmp_path, stock_plate_substitution=True)
    plate_src = tmp_path / "plate.png"
    plate_src.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve(location_key):
        return [_plate("a", plate_src)]
    img.inject_location_service(resolve)

    out = await img.image_node(_stock_state())
    assert out.get("error") is None
    shot = out["scenes"][0]["shots"][0]
    assert (tmp_path / shot["image_path"]).read_bytes() == plate_src.read_bytes()


async def test_stock_variant_selection_is_deterministic_across_processes(monkeypatch, tmp_path):
    """Story 14.1 replaces 8.17's `(run, scene, location) % count`. What has to survive is
    the DETERMINISM, and specifically its survival of a process restart: the digest is
    sha256, not builtin `hash()`, which CPython salts per process — with `hash()` a resumed
    run picks a different plate and re-copies every background it already has.

    Asserted as a subprocess rather than by calling the helper twice in one interpreter,
    because the salt is what is under test and one interpreter has one salt
    (`gotcha_pinned-ffmpeg-arg-string-is-not-a-test`: a value pinned to itself proves
    nothing).
    """
    plates = [{"viewpoint": "EYE", "variant": v, "path": f"/p/{v}.png"} for v in "abc"]
    shot = {"camera_angle": "wide", "cast": [], "location_key": "corridor"}
    script = (
        "import json,sys; sys.path.insert(0,'src');"
        "from yt_flow.pipeline.nodes.image import _select_plate;"
        f"plate,_=_select_plate({shot!r}, {plates!r}, 'run-stock-1', 1, affordance_gate=False);"
        "print(plate['variant'])"
    )
    picks = {subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True,
        env={"PYTHONHASHSEED": seed, "PATH": os.environ.get("PATH", "")},
    ).stdout.strip() for seed in ("1", "2", "random")}
    assert len(picks) == 1, f"the pick moved with PYTHONHASHSEED: {picks}"


async def test_stock_variant_selection_matches_plate_bytes(monkeypatch, tmp_path):
    """The pick reaches the copied file — the selector is not consulted and then ignored."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(
        mock=False, workflow_path=_wf_file(tmp_path), stock_plate_substitution=True))
    plates = []
    for v, marker in (("a", b"AAAA"), ("b", b"BBBB"), ("c", b"CCCC")):
        p = tmp_path / f"plate_{v}.png"
        p.write_bytes(RGB_PNG + marker + b"\x00" * 1200)
        plates.append(_plate(v, p))

    async def resolve(location_key):
        return plates
    img.inject_location_service(resolve)

    expected, reason = img._select_plate(
        _stock_state()["scenes"][0]["shots"][0], plates, "run-stock-1", 1, affordance_gate=False)
    assert reason == "match"
    out = await img.image_node(_stock_state())
    shot = out["scenes"][0]["shots"][0]
    assert pathlib.Path(shot["image_path"]).read_bytes() == pathlib.Path(expected["path"]).read_bytes()


async def test_stock_plate_count_recorded_in_trace(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(
        mock=False, workflow_path=_wf_file(tmp_path), stock_plate_substitution=True))
    plate_src = tmp_path / "plate.png"
    plate_src.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve(location_key):
        return [_plate("a", plate_src)]
    img.inject_location_service(resolve)

    captured = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_stock_state())
    assert out.get("error") is None
    assert captured["stock_plate_count"] == 1
    assert captured["request_count"] == 0


async def test_no_location_key_shot_unaffected_by_injected_service(monkeypatch, tmp_path):
    """A shot without location_key must never consult _location_service (AD-10:
    plate lookup is opt-in per-shot, not global)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path)))

    async def boom(location_key):
        raise AssertionError("must not be called for a shot without location_key")
    img.inject_location_service(boom)

    async def fake_fetch(url, workflow):
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_stock_state(location_key=None))
    assert out.get("error") is None


# ── Story 14.1: _select_plate — per-shot, framing-matched plate assignment ───
#
# The selector is a PURE function, so the I/O matrix is tested against it directly and
# only the wiring (warning, fallback, sidecar, tally) goes through image_node. Same
# reason `14-1-approved-plate-sets/replay_coverage.py` can replay a finished run offline.


def _shot(angle="wide", cast=(), key="corridor"):
    return {"shot_id": "S001", "image_prompt": "x", "negative_prompt": "y",
            "camera_angle": angle, "cast": list(cast), "location_key": key}


def _measured(variant="a", viewpoint="EYE", **over):
    return {"viewpoint": viewpoint, "standing_room": True, "variant": variant,
            "path": f"/p/{variant}.png", **over}


def test_the_angle_map_is_a_checked_subset_of_the_scenario_vocabulary():
    """`_ANGLE_VIEWPOINT` is a hand-copied second view of `scenario_chain._CAMERA_ANGLES`.
    Nothing kept the two in step, so an eighth angle added upstream would have arrived here
    as a silent `unservable_framing` — a permanent, documented refusal standing in for a
    vocabulary the map has simply never heard of.

    Both halves are asserted, because the absence is the decision: the mapped five, and
    the unmapped two that a room plate genuinely cannot serve.
    """
    from yt_flow.pipeline.nodes.scenario_chain import _CAMERA_ANGLES

    assert set(img._ANGLE_VIEWPOINT) <= set(_CAMERA_ANGLES)
    assert set(_CAMERA_ANGLES) - set(img._ANGLE_VIEWPOINT) == {"close-up", "POV"}
    assert set(img._ANGLE_VIEWPOINT) - set(_CAMERA_ANGLES) == set()
    # …and the two that are out are out for a REASON, not by omission: they are the
    # documented `unservable_framing` set, and a third silently-dropped angle must not
    # inherit that reason.
    assert img._UNSERVABLE_ANGLES == {"close-up", "POV"}


@pytest.mark.parametrize("angle", ["wide", "medium", "over-the-shoulder",
                                  "low-angle", "high-angle"])
@pytest.mark.parametrize("viewpoint", ["EYE", "LOW", "HIGH"])
def test_matrix_every_servable_framing_hits_whatever_the_plate_viewpoint(angle, viewpoint):
    """THE Story 14.8 axis change, stated as a cross product: all 15 combinations hit.

    14.1 required `_ANGLE_VIEWPOINT[angle] == plate["viewpoint"]` and refused the other 10.
    That axis was retired on measurement — `y_h` reproduces to 0.072 mean / 0.12 max
    between judges against an EYE band 0.20 wide, so the refusals near a boundary were a
    coin toss (`14-8-plate-reuse-shipping/AXIS-CANDIDATES.md` ④). The axis is now
    `location_key` alone, whose reproduction error is 0 by construction: it is a closed
    14-value enum field compared with string equality, and `plates` arrives already keyed.

    This test is deliberately the widest one in the block, because the cost of the change
    is exactly the 10 combinations it now accepts and 14.1 refused."""
    plate, reason = img._select_plate(
        _shot(angle), [_measured(viewpoint=viewpoint)], "r", 1, affordance_gate=True)
    assert (plate["variant"], reason) == ("a", "match")


def test_matrix_cast_with_standing_room_is_a_hit_and_counts_as_judged():
    """Matrix row 2. The verdict rides the asset, so the shot is judged at zero runtime
    cost — the accounting half of that claim is asserted through image_node below."""
    plate, reason = img._select_plate(
        _shot("wide", CAST), [_measured(standing_room=True)], "r", 1, affordance_gate=True)
    assert (plate["variant"], reason) == ("a", "match")


def test_matrix_cast_without_standing_room_falls_back():
    plate, reason = img._select_plate(
        _shot("wide", CAST), [_measured(standing_room=False)], "r", 1, affordance_gate=True)
    assert (plate, reason) == (None, "no_standing_room")


def test_an_undecidable_standing_room_is_not_room():
    """`is True`, not truthiness: the vision endpoint rejects corpse/medical plates
    deterministically (14.2), and those come back with the key ABSENT. Reading that as
    room would put a card in the one class of plate nobody could judge."""
    plate, reason = img._select_plate(
        _shot("wide", CAST), [_measured()], "r", 1, affordance_gate=True)
    assert reason == "match"  # control: the same plate WITH a verdict is a hit
    del plate["standing_room"]
    assert img._select_plate(_shot("wide", CAST), [plate], "r", 1, affordance_gate=True) == (
        None, "no_standing_room")


def test_a_cast_free_shot_does_not_need_standing_room():
    plate, reason = img._select_plate(
        _shot("wide"), [_measured(standing_room=False)], "r", 1, affordance_gate=True)
    assert (plate["variant"], reason) == ("a", "match")


@pytest.mark.parametrize("angle", ["close-up", "POV"])
def test_matrix_unservable_framing_never_takes_a_plate(angle):
    """A room plate is a photograph of a whole room; no framing of it is an instrument
    close-up or a ceiling POV. 7/31 shots of run 4b35c0ed — permanent by design."""
    assert img._select_plate(_shot(angle), [_measured()], "r", 1, affordance_gate=True) == (
        None, "unservable_framing")


@pytest.mark.parametrize("angle", [None, "", "dutch angle", "extreme close up"])
def test_matrix_an_angle_outside_the_vocabulary_is_unknown_not_unservable(angle):
    """`unservable_framing` is documented as "close-up/POV, permanent by design". Lending
    it to a string we merely failed to parse — a pre-14.0 checkpoint holds raw prose in
    this field — would file a parser gap under a designed refusal and hide it forever."""
    assert img._select_plate(_shot(angle), [_measured()], "r", 1, affordance_gate=True) == (
        None, "unknown_framing")


def test_the_retired_reasons_cannot_fire_and_are_gone_from_the_vocabulary():
    """`no_viewpoint_match` and `partial_metadata` named the step 14.8 removed.

    The input that produced each of them in 14.1 is replayed here and must now be a hit —
    the first is the run-4b35c0ed shape (a HIGH-angle shot over an all-EYE pool: 7 such
    shots, `replay_coverage.py`'s C4'), the second is a half-measured key. Neither string
    may survive anywhere in the reason vocabulary, because a reason that cannot fire
    documents a retired axis as though it shipped."""
    plate, reason = img._select_plate(
        _shot("high-angle"), [_measured(viewpoint="EYE"), _measured("b", "LOW")],
        "r", 1, affordance_gate=True)
    assert reason == "match" and plate["viewpoint"] in {"EYE", "LOW"}
    half = [_measured(viewpoint="EYE"), {"variant": "b", "path": "/p/b.png"}]
    plate, reason = img._select_plate(_shot("high-angle"), half, "r", 1, affordance_gate=True)
    # ...and the unmeasured plate is STILL never picked: `no_metadata` fails open, it does
    # not fail into 8.17's "take anything approved".
    assert (plate["variant"], reason) == ("a", "match")
    # The two names still appear in `image.py`'s PROSE (the docstring records why they
    # went), so the check is for the returnable literal — a quoted string — not the word.
    source = pathlib.Path(img.__file__).read_text(encoding="utf-8")
    assert '"no_viewpoint_match"' not in source and '"partial_metadata"' not in source


def test_matrix_an_unmeasured_key_fails_open_to_generation():
    """FAIL OPEN, and note which way open is: an unmeasured plate is never picked.
    Picking anything approved is exactly what 8.17 did and what this story undoes."""
    assert img._select_plate(
        _shot("wide"), [{"variant": "a", "path": "/p/a.png"}], "r", 1, affordance_gate=True) == (
        None, "no_metadata")


@pytest.mark.parametrize("field", ["has_person", "depicts_person"])
def test_d1_a_plate_with_a_person_in_it_is_never_assigned(field):
    """The plate branch `continue`s past the Story 10.2/14.4 people-free guard, so this
    filter is the only thing between `entrance-checkpoint/b` — labelled `has_person: true`
    in 2026-08-02 and approved anyway — and a cast card composited over two real people.

    Not gated on any knob (a body in the room is not an affordance question), and NOT an
    un-approval: the asset dict comes back untouched and its `status` is not this
    function's business (Block-If).
    """
    plate = _measured(**{field: True})
    before = dict(plate)
    assert img._select_plate(_shot("wide", CAST), [plate], "r", 1, affordance_gate=False) == (
        None, "plate_shows_person")
    assert plate == before  # the selector refuses the ASSIGNMENT, it does not touch the asset


def test_d1_fires_on_a_person_bearing_plate_whatever_its_viewpoint():
    """14.1 answered this input `no_viewpoint_match`, because the viewpoint step ran first
    and the person never got looked at. With that step gone, the person IS the finding —
    which is the more actionable of the two warnings anyway: `entrance-checkpoint/b` is
    approved with two people in it and the plate branch skips the 10.2/14.4 runtime
    guard, so D1 is the only thing between it and a cast card on top of them."""
    assert img._select_plate(
        _shot("high-angle"), [_measured(viewpoint="EYE", has_person=True)],
        "r", 1, affordance_gate=True) == (None, "plate_shows_person")


def test_d1_prefers_the_people_free_candidate_rather_than_falling_back():
    plate, reason = img._select_plate(
        _shot("wide"), [_measured("a", has_person=True), _measured("b")],
        "r", 1, affordance_gate=True)
    assert (plate["variant"], reason) == ("b", "match")


def test_d2_the_affordance_filter_honours_the_knob():
    """14.2 shipped knob-down as the ONE recovery path for its measured 1/25 false
    positive. A second hard filter that ignores the knob takes that back — and with the
    knob down the `no_standing_room` fallback trades a MEASURED bad plate for a generated
    frame carrying no affordance verdict at all, which is the wrong direction."""
    plates = [_measured(standing_room=False)]
    assert img._select_plate(_shot("wide", CAST), plates, "r", 1, affordance_gate=True) == (
        None, "no_standing_room")
    plate, reason = img._select_plate(_shot("wide", CAST), plates, "r", 1, affordance_gate=False)
    assert (plate["variant"], reason) == ("a", "match")


def test_d2_the_knob_does_not_switch_off_the_person_filter():
    """A person in the plate is not an affordance question, so D1 survives knob-down."""
    assert img._select_plate(
        _shot("wide", CAST), [_measured(has_person=True)], "r", 1, affordance_gate=False) == (
        None, "plate_shows_person")


def test_d3_a_cast_shot_and_a_cast_free_shot_in_one_scene_agree():
    """The tie-break's digest key contains the candidate pool it indexes into. The older
    form hashed (run, scene, location) and took a modulo over a list the cast filter had
    already shortened, so these two shots could land on different plates while the
    docstring claimed one plate per scene. Today 40/42 plates measure `standing_room=true`,
    which is why this was latent rather than visible."""
    plates = [_measured(v) for v in "abc"]
    with_cast, r1 = img._select_plate(_shot("wide", CAST), plates, "r", 3, affordance_gate=True)
    without, r2 = img._select_plate(_shot("wide"), plates, "r", 3, affordance_gate=True)
    assert (r1, r2) == ("match", "match")
    assert with_cast["variant"] == without["variant"]


def test_d3_a_pool_the_filters_really_did_split_may_diverge_and_says_so():
    """The honest other half: when one shot genuinely cannot use what the other took, they
    take different plates — and the docstring's claim is scoped to the candidate set, not
    to the scene, so it stays true."""
    plates = [_measured("a", standing_room=False), _measured("b")]
    with_cast, _ = img._select_plate(_shot("wide", CAST), plates, "r", 3, affordance_gate=True)
    assert with_cast["variant"] == "b"  # 'a' has no room; the cast-free shot may take it


def test_camera_angle_left_the_digest_key_with_the_axis():
    """14.1 hashed the derived viewpoint too, so two shots of ONE scene and room with
    different `camera_angle`s took different plates. 14.8 removed it: keeping a retired
    measurement in the digest would make continuity within a room depend on a value
    nothing else in the function reads. Two angles, one scene, one room -> ONE plate."""
    plates = [_measured("a", "EYE"), _measured("b", "HIGH")]
    eye, _ = img._select_plate(_shot("medium"), plates, "r", 1, affordance_gate=True)
    high, _ = img._select_plate(_shot("high-angle"), plates, "r", 1, affordance_gate=True)
    assert eye["variant"] == high["variant"]


def test_the_new_axis_is_deterministic_within_and_across_processes():
    """Same inputs twice -> byte-identical output, and the digest is reproduced here from
    the documented key so a switch back to builtin `hash()` (salted per process, so a
    resumed run re-copies every background) fails instead of merely drifting."""
    plates = [_measured(v) for v in "abc"]
    first = img._select_plate(_shot("wide"), plates, "run-42", 7, affordance_gate=True)
    second = img._select_plate(_shot("wide"), plates, "run-42", 7, affordance_gate=True)
    assert first == second
    key = ":".join(["run-42", "7", "corridor", "a", "b", "c"])
    want = plates[int(hashlib.sha256(key.encode()).hexdigest(), 16) % 3]
    assert first == (want, "match")


async def test_an_unfit_plate_warns_with_its_reason_and_generates(monkeypatch, tmp_path):
    """`stock_plate_unfit` stays a separate code from `stock_plate_missing`: "this key has
    no approved plate" and "this key's plates cannot serve this shot" have different fixes,
    and the second is the normal permanent outcome for 7/31 shots.

    The unfit case used to be built from a viewpoint mismatch; Story 14.8 made that a HIT,
    so the wiring is exercised through D1 instead — which is also the reason a human most
    needs to see, since the plate branch skips the runtime people-free guard."""
    async def resolve(location_key):
        return [_measured(has_person=True)]

    warnings = await _plate_warnings(monkeypatch, tmp_path, resolver=resolve)
    assert [w["code"] for w in warnings] == ["stock_plate_unfit"]
    assert warnings[0]["context"] == {
        "scene_num": 1, "shot_id": "S001", "location_key": "corridor",
        "reason": "plate_shows_person"}


async def test_an_empty_key_still_reports_missing_not_unfit(monkeypatch, tmp_path):
    """Regression guard on the split: an empty candidate list must not be reported through
    whatever the selector says about an empty list."""
    async def resolve(location_key):
        return []

    warnings = await _plate_warnings(monkeypatch, tmp_path, resolver=resolve)
    assert [w["code"] for w in warnings] == ["stock_plate_missing"]
    assert "reason" not in warnings[0]["context"]


async def test_substitution_off_never_touches_the_resolver(monkeypatch, tmp_path):
    """The shipped default, and the matrix's "0 calls, 0 warnings, byte-identical" row.
    The manifest read now lives behind this same resolver call, so proving the call count
    is 0 proves the manifest is not read either."""
    calls = []

    async def resolve(location_key):
        calls.append(location_key)
        return [_measured()]

    warnings = await _plate_warnings(
        monkeypatch, tmp_path, resolver=resolve, substitution=False)
    assert (calls, warnings) == ([], [])


# ── Story 11.5: depth companion resolution (AC1, AC2, AC10) ──────────────────


def _depth_resolver(calls, *, path="/depth/x.png", cached=False, boom=False):
    async def resolve(image_path):
        calls.append(image_path)
        if boom:
            raise RuntimeError("estimator down")
        return {"path": path, "cached": cached}

    return resolve


async def test_no_depth_resolver_leaves_shots_exactly_as_before(monkeypatch, tmp_path):
    """The kill switch / no wiring must not add the key at all — a `None` value
    would still change every checkpoint and every downstream dict comparison."""
    _mock_settings(monkeypatch, tmp_path)
    out = await img.image_node(_state())
    for scene in out["scenes"]:
        for shot in scene["shots"]:
            assert "depth_map_path" not in shot


async def test_generated_shot_gets_a_depth_companion(monkeypatch, tmp_path):
    _mock_settings(monkeypatch, tmp_path)
    calls: list[str] = []
    img.inject_depth_resolver(_depth_resolver(calls))
    out = await img.image_node(_state())
    shots = [s for sc in out["scenes"] for s in sc["shots"]]
    assert len(shots) == 3
    assert all(s["depth_map_path"] == "/depth/x.png" for s in shots)
    assert calls == [s["image_path"] for s in shots]


async def test_stock_plate_shot_gets_a_depth_companion(monkeypatch, tmp_path):
    """AC2: the STOCK image and its depth come from ONE variant — the depth key is
    the copied file's bytes, which ARE that variant's bytes."""
    _mock_settings(monkeypatch, tmp_path, stock_plate_substitution=True)
    plate = tmp_path / "plate.png"
    plate.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve_loc(key):
        return [_plate("a", plate)]

    img.inject_location_service(resolve_loc)
    calls: list[str] = []
    img.inject_depth_resolver(_depth_resolver(calls))
    out = await img.image_node(_stock_state())
    shot = out["scenes"][0]["shots"][0]
    assert shot["depth_map_path"] == "/depth/x.png"
    assert calls == [shot["image_path"]]


async def test_resumed_shot_with_missing_depth_regenerates_only_the_depth(monkeypatch, tmp_path):
    """AC2: a cached image whose depth map is missing or stale regenerates the
    DEPTH ONLY — never the source image."""
    _mock_settings(monkeypatch, tmp_path)
    out_dir = tmp_path / "run-img-1" / "images"
    out_dir.mkdir(parents=True)
    _write_complete_shot(out_dir, "scene_001_S001", "a dark room", "blurry")
    _write_complete_shot(out_dir, "scene_001_S002", "an agent", "text")
    _write_complete_shot(out_dir, "scene_002_S003", "a corridor", "watermark")
    before = {p.name: p.read_bytes() for p in out_dir.glob("*.png")}

    async def boom(*a, **k):
        raise AssertionError("a resumed shot must not regenerate its image")

    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", boom)
    calls: list[str] = []
    img.inject_depth_resolver(_depth_resolver(calls))
    out = await img.image_node(_state())
    assert out.get("error") is None
    assert len(calls) == 3  # depth resolved for every resumed shot
    assert {p.name: p.read_bytes() for p in out_dir.glob("*.png")} == before
    assert all(s["depth_map_path"] for sc in out["scenes"] for s in sc["shots"])


async def test_unavailable_depth_leaves_the_key_absent_and_the_stage_green(monkeypatch, tmp_path):
    """AC9: no depth is a valid outcome — the video stage then falls back."""
    _mock_settings(monkeypatch, tmp_path)
    img.inject_depth_resolver(_depth_resolver([], path=None))
    out = await img.image_node(_state())
    assert out.get("error") is None
    assert all("depth_map_path" not in s for sc in out["scenes"] for s in sc["shots"])


async def test_a_raising_depth_resolver_is_non_fatal(monkeypatch, tmp_path, caplog):
    _mock_settings(monkeypatch, tmp_path)
    img.inject_depth_resolver(_depth_resolver([], boom=True))
    out = await img.image_node(_state())
    assert out.get("error") is None
    assert all("depth_map_path" not in s for sc in out["scenes"] for s in sc["shots"])
    assert "depth resolution failed" in caplog.text


async def test_depth_counts_reach_the_trace(monkeypatch, tmp_path):
    """AC10: hit/miss/unavailable is the only signal that says whether 2.5D had
    real depth to work from."""
    _mock_settings(monkeypatch, tmp_path)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))
    img.inject_depth_resolver(_depth_resolver([], cached=True))
    await img.image_node(_state())
    assert captured["depth_counts"] == {"hit": 3, "miss": 0, "unavailable": 0}


async def test_one_resolve_per_distinct_image_path(monkeypatch, tmp_path):
    _mock_settings(monkeypatch, tmp_path)
    calls: list[str] = []
    img.inject_depth_resolver(_depth_resolver(calls))
    state = _state()
    await img.image_node(state)
    assert len(calls) == len(set(calls))


# ── Background-person guard (Story 10.2) ────────────────────────────────────
#
# The guard is the only enforcement that looks at pixels, and its whole design
# constraint is that it may degrade a shot but never a run. Every test below is
# written against that: a detector that says nothing, breaks, or hates the shot
# still leaves error=None and an image on disk.

GUARD_WF = {**GOOD_WF, "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}


def _guard_settings(tmp_path, **over):
    over.setdefault("guard_attempts", 2)
    over.setdefault("vision_api_key", "vision-key")
    return FakeSettings(mock=False, workflow_path=_wf_file(tmp_path, GUARD_WF), **over)


def _one_shot_state(run_id="run-img-1"):
    state = _state(run_id=run_id)
    state["scenes"] = [{**state["scenes"][0], "shots": state["scenes"][0]["shots"][:1]}]
    return state


def _fake_detector(monkeypatch, verdicts, *, calls=None):
    """Detector returning `verdicts` in order, then its last value forever."""
    seq = list(verdicts)

    async def detector(image_bytes, settings):
        if calls is not None:
            calls.append(image_bytes)
        return seq.pop(0) if len(seq) > 1 else seq[0]
    monkeypatch.setattr(img.vision_check, "background_has_person", detector)


def _counting_fetch(monkeypatch, seeds=None):
    """submit_and_fetch stub recording the KSampler seed of every submission."""
    seeds = [] if seeds is None else seeds

    async def fake_fetch(url, workflow):
        seeds.append(workflow["3"]["inputs"]["seed"])
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)
    return seeds


def _read_sidecar(tmp_path, run_id="run-img-1", base="scene_001_S001"):
    return json.loads(
        (tmp_path / "workspace" / run_id / "images" / f"{base}_done.json").read_text(encoding="utf-8"))


def test_bg_negative_suffix_is_frozen():
    """Story 10.2 closes WITHOUT growing any negative prompt — negative
    accumulation has backfired three times (gotcha_negative-prompt-overstuffing).
    Pinning the literal makes that a test rather than a claim."""
    assert img.BG_NEGATIVE_SUFFIX == ", person, people, human, character, creature, figure, silhouette"


def test_attempt_zero_seed_is_byte_identical_to_pre_10_2():
    """Existing workspaces must keep resuming: rung 0 hashes the old string."""
    import hashlib
    expected = int(hashlib.sha256(b"run-1:1:S001").hexdigest(), 16) % 2**32
    assert img._shot_seed("run-1", 1, "S001") == expected
    assert img._shot_seed("run-1", 1, "S001", 0) == expected
    assert img._shot_seed("run-1", 1, "S001", 1) != expected


def test_seed_ladder_length_is_fixed_and_starts_at_attempt_zero():
    from yt_flow.config import BACKGROUND_PERSON_GUARD_MAX_ATTEMPTS as MAX
    ladder = img._seed_ladder("run-1", 1, "S001")
    assert len(ladder) == MAX + 1
    assert ladder[0] == img._shot_seed("run-1", 1, "S001")
    assert len(set(ladder)) == len(ladder)


async def test_guard_accepts_clean_render_on_attempt_zero(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    seeds = _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [False])

    out = await img.image_node(_one_shot_state())
    assert out.get("error") is None
    assert seeds == [img._shot_seed("run-img-1", 1, "S001")]  # one render, rung 0
    assert _read_sidecar(tmp_path)["seed"] == seeds[0]


async def test_guard_regenerates_then_accepts_and_pins_the_accepted_seed(monkeypatch, tmp_path):
    """The accepted rung — not rung 0 — is what the sidecar records, otherwise
    every resume regenerates the shot forever."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    seeds = _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [True, False])
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_one_shot_state())
    assert out.get("error") is None
    assert seeds == [img._shot_seed("run-img-1", 1, "S001", a) for a in (0, 1)]
    assert _read_sidecar(tmp_path)["seed"] == img._shot_seed("run-img-1", 1, "S001", 1)
    assert captured["guard_counts"] == {
        "regenerated": 1, "exhausted": 0, "unavailable": 0, "unscreened": 0}


async def test_guard_exhausted_keeps_the_last_render_and_warns(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    seeds = _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [True])
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    with caplog.at_level("WARNING"):
        out = await img.image_node(_one_shot_state())

    assert out.get("error") is None
    assert len(seeds) == 3  # attempts=2 → rungs 0,1,2
    shot = out["scenes"][0]["shots"][0]
    assert (tmp_path / shot["image_path"]).is_file()
    assert _read_sidecar(tmp_path)["seed"] == seeds[-1]  # the kept render's rung
    assert captured["guard_counts"]["exhausted"] == 1
    assert "still populated after 3 attempt(s)" in caplog.text
    assert "NOT verified unpopulated" in caplog.text  # run-level summary


async def test_guard_budget_bounds_the_number_of_renders(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path, guard_attempts=1))
    seeds = _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [True])

    out = await img.image_node(_one_shot_state())
    assert out.get("error") is None
    assert len(seeds) == 2


async def test_undecidable_verdict_accepts_the_frame_and_is_counted(monkeypatch, tmp_path, caplog):
    """None is 'not checked', never 'clean' — it accepts, but it must show up."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    seeds = _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [None])
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    with caplog.at_level("WARNING"):
        out = await img.image_node(_one_shot_state())

    assert out.get("error") is None
    assert len(seeds) == 1
    assert captured["guard_counts"]["unavailable"] == 1
    assert "NOT verified unpopulated" in caplog.text


async def test_a_raising_detector_cannot_fail_the_image_stage(monkeypatch, tmp_path):
    """AD-10 + this story's Boundaries: no exception from the detector may reach
    image_node's error boundary, and the image is still produced."""
    async def boom(image_bytes, settings):
        raise RuntimeError("detector exploded")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _counting_fetch(monkeypatch)
    monkeypatch.setattr(img.vision_check, "background_has_person", boom)

    out = await img.image_node(_one_shot_state())
    assert out["error"] is None
    shot = out["scenes"][0]["shots"][0]
    assert shot["image_path"] and (tmp_path / shot["image_path"]).is_file()


async def test_guard_disables_itself_after_consecutive_undecidable_verdicts(monkeypatch, tmp_path, caplog):
    """A dead detector costs a 120s timeout per call; the breaker stops calling it."""
    from yt_flow.config import BACKGROUND_PERSON_GUARD_BREAKER_STREAK as STREAK
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _counting_fetch(monkeypatch)
    calls: list = []
    _fake_detector(monkeypatch, [None], calls=calls)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    with caplog.at_level("WARNING"):
        out = await img.image_node(_state(run_id="run-breaker"))  # 3 shots

    assert out.get("error") is None
    assert len(calls) == STREAK  # 3 shots, 3 calls, then off — the 4th never happens
    assert captured["guard_counts"]["unavailable"] == STREAK
    assert "disabled for the rest of the run" in caplog.text


async def test_missing_vision_key_disables_the_guard_with_one_warning(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path, vision_api_key=""))
    seeds = _counting_fetch(monkeypatch)

    async def boom(image_bytes, settings):
        raise AssertionError("detector must not be called without a key")
    monkeypatch.setattr(img.vision_check, "background_has_person", boom)

    with caplog.at_level("WARNING"):
        out = await img.image_node(_state())  # 3 shots

    assert out.get("error") is None
    assert len(seeds) == 3  # one render per shot, exactly as before this story
    assert caplog.text.count("YTFLOW_CHARACTER_VISION_API_KEY is unset") == 1


async def test_guard_knob_zero_never_calls_the_detector(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path, guard_attempts=0))
    seeds = _counting_fetch(monkeypatch)

    async def boom(image_bytes, settings):
        raise AssertionError("detector must not be called when the guard is off")
    monkeypatch.setattr(img.vision_check, "background_has_person", boom)

    out = await img.image_node(_one_shot_state())
    assert out.get("error") is None
    assert len(seeds) == 1


async def test_guard_not_invoked_in_mock_mode(monkeypatch, tmp_path):
    _mock_settings(monkeypatch, tmp_path, guard_attempts=2, vision_api_key="vision-key")

    async def boom(image_bytes, settings):
        raise AssertionError("mock mode renders nothing to screen")
    monkeypatch.setattr(img.vision_check, "background_has_person", boom)

    out = await img.image_node(_state())
    assert out.get("error") is None


async def test_guard_not_invoked_on_the_stock_plate_path(monkeypatch, tmp_path):
    """Plates are screened for has_person at seeding; re-screening them would
    burn a vision call on an already-approved asset."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(
        tmp_path, stock_plate_substitution=True))
    plate_src = tmp_path / "plate.png"
    plate_src.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve(location_key):
        return [_plate("a", plate_src)]
    img.inject_location_service(resolve)

    async def boom(image_bytes, settings):
        raise AssertionError("the guard must not screen a stock plate")
    monkeypatch.setattr(img.vision_check, "background_has_person", boom)

    out = await img.image_node(_stock_state())
    assert out.get("error") is None
    assert out["scenes"][0]["shots"][0]["image_path"].endswith("scene_001_S001.png")


async def test_resume_accepts_a_bumped_seed_after_the_knob_is_lowered_to_zero(monkeypatch, tmp_path):
    """The ladder's length is the config MAXIMUM, not the run's current knob:
    turning the guard off (or losing the key) must not invalidate a shot a prior
    run accepted on a bumped rung and regenerate it forever."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(
        tmp_path, guard_attempts=0, vision_api_key=""))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    _write_complete_shot(d, "scene_001_S001", "a dark room", "blurry",
                         seed=img._shot_seed("run-img-1", 1, "S001", 2))
    seeds = _counting_fetch(monkeypatch)

    out = await img.image_node(_one_shot_state())
    assert out.get("error") is None
    assert seeds == []  # skipped, not regenerated


# ── Guard accounting / cadence / breaker fixes (review pass 2) ──────────────


async def test_regenerated_counts_only_rungs_a_render_actually_follows(monkeypatch, tmp_path):
    """attempts=2 + an always-populated detector is 3 renders = 2 regenerations.
    Counting the last rung too would report one more regeneration than happened."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    seeds = _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [True])
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_one_shot_state())
    assert out.get("error") is None
    assert len(seeds) == 3
    assert captured["guard_counts"]["regenerated"] == len(seeds) - 1 == 2
    assert captured["guard_counts"]["exhausted"] == 1


async def test_unscreened_counts_every_shot_the_guard_never_looked_at(monkeypatch, tmp_path, caplog):
    """AC(d): a dead guard must not read as a clean pass. With the knob at 0 the
    trace must say the backgrounds were never screened, not stay silent."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path, guard_attempts=0))
    _counting_fetch(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    with caplog.at_level("WARNING"):
        out = await img.image_node(_state())  # 3 shots

    assert out.get("error") is None
    assert captured["guard_counts"]["unscreened"] == 3
    assert "3 shot(s) never screened" in caplog.text
    assert "NOT verified unpopulated" in caplog.text


async def test_unscreened_counts_the_shots_after_the_breaker_trips(monkeypatch, tmp_path):
    """The breaker leaves the rest of the run unverified; those shots are the ones
    the 'unavailable' count cannot see, because the detector is no longer called."""
    from yt_flow.config import BACKGROUND_PERSON_GUARD_BREAKER_STREAK as STREAK
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _counting_fetch(monkeypatch)
    calls: list = []
    _fake_detector(monkeypatch, [None], calls=calls)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_many_shots_state(6))
    assert out.get("error") is None
    assert len(calls) == STREAK
    # the shot that tripped it + the 3 that followed it were never screened
    assert captured["guard_counts"]["unscreened"] == 6 - STREAK + 1
    assert captured["guard_counts"]["unavailable"] == STREAK


async def test_error_path_still_reports_guard_and_depth_counts(monkeypatch, tmp_path):
    """A stage that fails mid-run must not lose its guard accounting — otherwise
    the only trace of an exhausted ladder disappears with the exception."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _fake_detector(monkeypatch, [True])
    fetches = 0

    async def fetch_then_die(url, workflow):
        nonlocal fetches
        fetches += 1
        if fetches > 3:  # shot 1 exhausted its 3 rungs; shot 2 explodes
            raise RuntimeError("comfy went away")
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fetch_then_die)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_state())
    assert out["error"] and "stage=image" in out["error"]
    assert captured["guard_counts"] == {
        "regenerated": 2, "exhausted": 1, "unavailable": 0, "unscreened": 0}
    assert captured["depth_counts"] == {"hit": 0, "miss": 0, "unavailable": 0}


async def test_exhausted_shot_is_recorded_in_the_sidecar_and_refires_on_resume(monkeypatch, tmp_path):
    """A known-populated frame kept by the guard must not resume as a clean pass."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [True])

    assert (await img.image_node(_one_shot_state())).get("error") is None
    assert _read_sidecar(tmp_path)["guard_exhausted"] is True

    # Second pass over the same workspace: the shot is skipped, and the run-level
    # warning still fires because the sidecar remembers the verdict.
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))
    seeds = _counting_fetch(monkeypatch)
    out = await img.image_node(_one_shot_state())
    assert out.get("error") is None
    assert seeds == []  # resumed, not regenerated
    assert captured["guard_counts"]["exhausted"] == 1


async def test_guard_exhausted_key_does_not_participate_in_the_resume_match(monkeypatch, tmp_path):
    """Sidecars written before this key existed must keep resuming."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    _write_complete_shot(d, "scene_001_S001", "a dark room", "blurry")  # no guard_exhausted key
    assert "guard_exhausted" not in json.loads((d / "scene_001_S001_done.json").read_text())
    seeds = _counting_fetch(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_one_shot_state())
    assert out.get("error") is None
    assert seeds == []
    assert captured["guard_counts"]["exhausted"] == 0


async def test_health_check_cadence_holds_when_the_guard_retries(monkeypatch, tmp_path):
    """A shot now fires 1..N submissions, so `request_count % N == 0` evaluated once
    per shot steps over its multiples: 3 shots × 3 renders with N=4 crossed 4 and 8
    but fired one check. The bound is 'requests since the last check', not a modulo."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(
        tmp_path, health_poll_every_n_shots=4))
    _fake_detector(monkeypatch, [True])  # every shot exhausts → 3 submissions per shot
    submissions: list[int] = []
    checks: list[int] = []

    async def count_health(url):
        checks.append(len(submissions))
    monkeypatch.setattr(img.comfyui_client, "check_health", count_health)

    async def fake_fetch(url, workflow):
        submissions.append(workflow["3"]["inputs"]["seed"])
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())  # 3 shots × 3 rungs = 9 submissions
    assert out.get("error") is None
    assert len(submissions) == 9
    assert checks == [0, 6]  # initial, then the first shot boundary past 4 requests
    # the real invariant: never more than N submissions between two health checks
    boundaries = [*checks, len(submissions)]
    assert max(b - a for a, b in zip(boundaries, boundaries[1:])) <= 4 + 3


def test_importing_the_image_node_does_not_pull_in_the_db_layer():
    """vision_check duplicates the DashScope URL instead of importing it from
    character_service precisely so this stays true: pipeline/ must not reach the
    DB layer (AD-1). A fresh interpreter is the only honest way to ask."""
    probe = (
        "import importlib, sys;"
        "importlib.import_module('yt_flow.pipeline.nodes.image');"
        "print([m for m in sys.modules if m == 'sqlmodel' or m.startswith('yt_flow.db')])"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]", out.stdout


async def test_breaker_trips_on_total_undecidables_not_only_consecutive(monkeypatch, tmp_path, caplog):
    """An intermittent detector (fail, ok, fail, ok…) resets the streak every other
    call and would never trip a consecutive-only breaker — the exact 120s-per-shot
    cost the breaker exists to bound."""
    from yt_flow.config import BACKGROUND_PERSON_GUARD_BREAKER_TOTAL as TOTAL
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _counting_fetch(monkeypatch)
    calls: list = []

    async def alternating(image_bytes, settings):
        calls.append(image_bytes)
        return None if len(calls) % 2 else False
    monkeypatch.setattr(img.vision_check, "background_has_person", alternating)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    with caplog.at_level("WARNING"):
        out = await img.image_node(_many_shots_state(20))

    assert out.get("error") is None
    assert captured["guard_counts"]["unavailable"] == TOTAL
    assert len(calls) == 2 * TOTAL - 1  # the TOTAL-th undecidable is the last call
    assert "total undecidable verdicts" in caplog.text


# ── Story 13.1: plate fallbacks become gate-visible warnings ─────────────────

async def _plate_warnings(monkeypatch, tmp_path, *, resolver, substitution=True, state=None):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(
        mock=False, workflow_path=_wf_file(tmp_path), stock_plate_substitution=substitution))
    if resolver is not None:
        img.inject_location_service(resolver)

    async def fake_fetch(url, workflow):
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)
    out = await img.image_node(state or _stock_state())
    assert out.get("error") is None
    # The fallback still produced an image — a warning is never a failure (AC3).
    for scene in out["scenes"]:
        for shot in scene["shots"]:
            assert shot["image_path"]
    return out["run_warnings"]


async def test_plate_missing_warns_per_affected_shot(monkeypatch, tmp_path):
    """One lookup per location key, but one warning per SHOT: "which shots lost the
    plate" is unanswerable from a per-key record."""
    async def resolve(location_key):
        return []

    state = _stock_state()
    state["scenes"][0]["shots"].append({
        **state["scenes"][0]["shots"][0], "shot_id": "S002",
    })
    warnings = await _plate_warnings(monkeypatch, tmp_path, resolver=resolve, state=state)
    assert [w["code"] for w in warnings] == ["stock_plate_missing"] * 2
    assert [w["context"]["shot_id"] for w in warnings] == ["S001", "S002"]
    assert all(w["stage"] == "image" for w in warnings)
    assert warnings[0]["context"] == {"scene_num": 1, "shot_id": "S001", "location_key": "corridor"}


async def test_plate_resolution_failure_warns_with_bounded_detail(monkeypatch, tmp_path):
    async def resolve(location_key):
        raise RuntimeError("plate db is down")

    warnings = await _plate_warnings(monkeypatch, tmp_path, resolver=resolve)
    assert [w["code"] for w in warnings] == ["stock_plate_resolution_failed"]
    assert warnings[0]["context"]["location_key"] == "corridor"
    assert warnings[0]["context"]["detail"] == "RuntimeError: plate db is down"


async def test_uninjected_resolver_warns_once_per_shot(monkeypatch, tmp_path):
    warnings = await _plate_warnings(monkeypatch, tmp_path, resolver=None)
    assert [w["code"] for w in warnings] == ["stock_plate_resolver_unavailable"]
    assert warnings[0]["context"]["shot_id"] == "S001"


async def test_substitution_disabled_is_warning_free(monkeypatch, tmp_path):
    """The shipped default. A config-disabled subsystem is not a degradation (AC2)."""
    async def resolve(location_key):
        return []

    assert await _plate_warnings(monkeypatch, tmp_path, resolver=resolve, substitution=False) == []


async def test_shot_without_location_key_is_warning_free(monkeypatch, tmp_path):
    async def resolve(location_key):
        raise AssertionError("no location_key means no lookup at all")

    warnings = await _plate_warnings(
        monkeypatch, tmp_path, resolver=resolve, state=_stock_state(location_key=None),
    )
    assert warnings == []


async def test_warnings_merge_with_the_checkpoint_and_do_not_duplicate(monkeypatch, tmp_path):
    """AC6: a retried image stage re-derives the same records and must not grow the list."""
    async def resolve(location_key):
        return []

    prior = {"code": "character_provisioning_failed", "stage": "scenario",
             "message": "이전 경고", "context": {"card_key": "SCP-173"}}
    state = {**_stock_state(), "run_warnings": [prior]}
    first = await _plate_warnings(monkeypatch, tmp_path, resolver=resolve, state=state)
    assert first[0] == prior                      # earlier stages' history is preserved
    assert len(first) == 2

    # Re-run the stage for real (retry deletes the resume artifacts, run_service
    # ._delete_image_artifacts) over the state as the checkpoint now holds it.
    shutil.rmtree(tmp_path / "workspace")
    again = await _plate_warnings(
        monkeypatch, tmp_path, resolver=resolve, state={**_stock_state(), "run_warnings": first},
    )
    assert again == first


# ── Story 13.1: the background-person guard's unscreened outcomes ─────────────
#
# `attempts = 0` still does not warn, but the REASON changed with Story 14.4: it is no
# longer the shipped default (that is 2 now), it is an OPERATOR OVERRIDE. 13.1 AC2's
# "intentionally non-applicable" still covers it — the operator asked for no guard and
# got no guard, which is not a runtime degradation — and the place a knob deviating
# from a recorded decision becomes visible is `scripts/report_decision_drift.py`, not
# the run's warning list. What warns here is the guard being ASKED for and not
# delivered: no key, a single undecidable verdict, the breaker, an exhausted ladder.


async def test_guard_without_a_vision_key_warns_once_for_the_run(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path, vision_api_key=""))
    _counting_fetch(monkeypatch)

    out = await img.image_node(_many_shots_state(3))

    assert out.get("error") is None
    # Run-level cause, one row — not one per unscreened shot.
    assert [w["code"] for w in out["run_warnings"]] == ["background_guard_unscreened"]
    assert out["run_warnings"][0]["stage"] == "image"
    assert out["run_warnings"][0]["context"] == {"reason": "vision_api_key_missing", "attempts": 2}


async def test_an_operator_override_to_zero_is_still_warning_free(monkeypatch, tmp_path):
    """An operator who sets `background_person_guard_attempts = 0` gets no guard and no
    warning — that is 13.1 AC2's "intentionally non-applicable", and it is the SAME
    policy as before Story 14.4 even though 0 is no longer the shipped default (2 is).
    The deviation from the recorded decision surfaces in the drift report instead.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(
        tmp_path, guard_attempts=0, vision_api_key=""))
    _counting_fetch(monkeypatch)

    out = await img.image_node(_one_shot_state())
    assert out["run_warnings"] == []


async def test_a_single_undecidable_verdict_warns_for_that_shot(monkeypatch, tmp_path):
    """Story 14.4. Run 4b35c0ed had exactly ONE undecidable verdict, well below the
    breaker, and it produced zero warnings — so one unscreened frame was
    indistinguishable in the UI from 42 verified-clean ones. The frame is still
    ACCEPTED and still consumes no rung (re-rendering on no information spends ~17s to
    learn nothing); only its visibility changes.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    seeds = _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [None, False])

    out = await img.image_node(_one_shot_state())

    assert out.get("error") is None
    assert len(seeds) == 1  # accepted on rung 0: no rung consumed
    assert [w["code"] for w in out["run_warnings"]] == ["background_guard_unscreened"]
    assert out["run_warnings"][0]["stage"] == "image"
    assert out["run_warnings"][0]["context"] == {
        "scene_num": 1, "shot_id": "S001", "reason": "detector_undecidable_shot"}


async def test_guard_breaker_warns_once_and_carries_its_tallies(monkeypatch, tmp_path):
    from yt_flow.config import BACKGROUND_PERSON_GUARD_BREAKER_STREAK as STREAK
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [None])

    out = await img.image_node(_many_shots_state(6))

    assert out.get("error") is None
    breaker = [w for w in out["run_warnings"] if w["context"].get("reason") == "detector_undecidable"]
    assert len(breaker) == 1  # the closure short-circuits after it trips
    assert breaker[0]["context"]["undecidable_streak"] == STREAK
    assert breaker[0]["context"]["undecidable_total"] == STREAK
    # Story 14.4: the per-shot rows ride ALONGSIDE it and do not multiply it. One per
    # detector call, and the breaker is what bounds how many calls there can be — so a
    # dead detector over 6 shots still yields STREAK named shots, not 6.
    per_shot = [w for w in out["run_warnings"]
                if w["context"].get("reason") == "detector_undecidable_shot"]
    assert [w["context"]["shot_id"] for w in per_shot] == ["S000", "S001", "S002"]


async def test_exhausted_ladder_warns_per_shot_with_scene_and_shot(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [True])  # never clean → every shot exhausts its ladder

    out = await img.image_node(_one_shot_state())

    assert out.get("error") is None
    assert [w["code"] for w in out["run_warnings"]] == ["background_guard_unscreened"]
    assert out["run_warnings"][0]["context"] == {
        "scene_num": 1, "shot_id": "S001", "reason": "ladder_exhausted"}


async def test_a_resumed_exhausted_shot_still_warns(monkeypatch, tmp_path):
    """The sidecar remembers the verdict, so a resume must not present a known-populated
    frame as a clean pass — the guard count already worked this way, the warning follows."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [True])
    assert (await img.image_node(_one_shot_state())).get("error") is None

    seeds = _counting_fetch(monkeypatch)
    out = await img.image_node(_one_shot_state())

    assert seeds == []  # resumed, not regenerated
    assert out["run_warnings"][0]["context"] == {
        "scene_num": 1, "shot_id": "S001", "reason": "ladder_exhausted_earlier_run"}


async def test_a_clean_guarded_run_is_warning_free(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [False])

    out = await img.image_node(_one_shot_state())
    assert out["run_warnings"] == []


async def test_error_path_keeps_the_warnings_the_run_already_earned(monkeypatch, tmp_path):
    """Same reason the guard counters are declared outside the try: a stage that dies on
    shot 2 must still report what shot 1 degraded into."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _fake_detector(monkeypatch, [True])
    fetches = 0

    async def fetch_then_die(url, workflow):
        nonlocal fetches
        fetches += 1
        if fetches > 3:  # shot 1 exhausted its 3 rungs; shot 2 explodes
            raise RuntimeError("comfy went away")
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fetch_then_die)

    out = await img.image_node(_state())

    assert out["error"] and "stage=image" in out["error"]
    assert [w["context"]["shot_id"] for w in out["run_warnings"]] == ["S001"]


async def test_per_shot_warnings_are_bounded_by_the_shared_sample_cap(monkeypatch, tmp_path):
    """These rows ride a checkpoint into every gate payload and render one line each
    above the Approve button; a 155-shot run must not put 155 of them there."""
    from yt_flow.domain.warnings import MAX_SAMPLE_RECORDS
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [True])
    n = MAX_SAMPLE_RECORDS + 5

    out = await img.image_node(_many_shots_state(n))

    named = [w for w in out["run_warnings"] if "shot_id" in w["context"]]
    assert len(named) == MAX_SAMPLE_RECORDS
    # …and the true total is still on screen, on one aggregate row that NAMES the reason
    # it counted — the cap is per (code, reason), so a bare tally would be ambiguous.
    assert {"reason": "ladder_exhausted", "total_count": n} in [
        w["context"] for w in out["run_warnings"]]


async def test_an_undecidable_frame_is_recorded_in_the_sidecar_and_refires_on_resume(
        monkeypatch, tmp_path):
    """The warning alone is not durable: `run_warnings` ride the LangGraph checkpoint, and
    a crash inside `image_node` (or a resume after its error path) comes back with the
    images on disk and the accounting gone, so the second pass skips every completed shot.
    Without the sidecar flag the never-screened frame comes back indistinguishable from a
    verified-clean one — the exact defect this story removes. NOT `full_restart_run`: that
    restarts from `scenario` and regenerates `scenes`, so the new `image_prompt` misses the
    resume cache anyway and the frame is re-rendered and re-screened.
    Mirrors `guard_exhausted`'s contract, which already survives this.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [None])

    first = await img.image_node(_one_shot_state())
    assert [w["context"]["reason"] for w in first["run_warnings"]] == [
        "detector_undecidable_shot"]
    assert _read_sidecar(tmp_path)["guard_undecidable"] is True

    # Second pass: the shot resumes off disk, nothing is re-rendered, and the row returns.
    seeds = _counting_fetch(monkeypatch)
    again = await img.image_node(_one_shot_state())
    assert seeds == []
    assert [w["context"]["reason"] for w in again["run_warnings"]] == [
        "detector_undecidable_earlier_run"]


async def test_a_clean_frame_is_not_marked_undecidable(monkeypatch, tmp_path):
    """The flag has to be per shot, not per run: one undecidable verdict must not stamp
    every later frame as unscreened."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [None, False])

    out = await img.image_node(_many_shots_state(2))

    assert out.get("error") is None
    # `_many_shots_state` numbers from S000.
    assert _read_sidecar(tmp_path, base="scene_001_S000")["guard_undecidable"] is True
    assert _read_sidecar(tmp_path, base="scene_001_S001")["guard_undecidable"] is False


async def test_undecidable_rows_cannot_evict_the_exhausted_ones(monkeypatch, tmp_path):
    """`gotcha_summary-from-a-capped-list-drops-the-severest-item`. Both reasons ride the
    code `background_guard_unscreened`, and "the guard KNEW this frame was populated and
    shipped it" is the severest of the family. Capping per CODE let the cheap undecidable
    rows eat slots the exhausted rows needed (5 + 7 named instead of 5 + 12); capping per
    (code, reason) gives each failure mode its own MAX_SAMPLE_RECORDS.

    The verdict script alternates one undecidable shot with one exhausted shot, so the
    streak resets every time and the running total stops one short of the breaker — the
    only shape in which both reasons can coexist in one run at all.
    """
    from yt_flow.config import BACKGROUND_PERSON_GUARD_BREAKER_TOTAL as TOTAL
    from yt_flow.domain.warnings import MAX_SAMPLE_RECORDS
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(tmp_path))
    _counting_fetch(monkeypatch)
    undecidable_shots = TOTAL - 1  # 5: one short of tripping the breaker
    # An undecidable shot costs 1 detector call, an exhausted shot exactly 3 (attempts=2).
    _fake_detector(monkeypatch, [None, True, True, True] * undecidable_shots + [True])
    shots = undecidable_shots * 2 + 10  # 5 undecidable + 15 exhausted

    out = await img.image_node(_many_shots_state(shots))

    # Named rows only: the aggregate row now carries `reason` too, so counting every row
    # with that reason would count the tally as a sample.
    named = [w["context"].get("reason") for w in out["run_warnings"] if "shot_id" in w["context"]]
    assert named.count("detector_undecidable_shot") == undecidable_shots
    assert named.count("ladder_exhausted") == MAX_SAMPLE_RECORDS
    assert "detector_undecidable" not in named  # the breaker never tripped
    # The aggregate names the reason it counted, so `총 N건` cannot span two failure modes.
    assert {"reason": "ladder_exhausted", "total_count": shots - undecidable_shots} in [
        w["context"] for w in out["run_warnings"]]


# ── Render provenance (Story 13.3 AC7, AC8) ─────────────────────────────────

def _provenance(tmp_path, base="scene_001_S001", run_id="run-img-1"):
    d = tmp_path / "workspace" / run_id / "images"
    return json.loads((d / f"{base}_done.json").read_text())["provenance"]


def _seed_env_snapshot(root, monkeypatch, payload: bytes):
    """Write the snapshot where the SHIPPED repo-relative constant says it lives.

    Monkeypatching ``ENV_SNAPSHOT_PATH`` to an *absolute* Path used to pass only
    because ``Path(root) / <absolute>`` discards ``root`` — so the join production
    actually performs was never exercised. Point ``YTFLOW_PROJECT_ROOT`` at a fake
    checkout instead and leave the constant alone.
    """
    snapshot = root / img.ENV_SNAPSHOT_PATH
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(payload)
    monkeypatch.setenv("YTFLOW_PROJECT_ROOT", str(root))
    return snapshot


async def test_generated_sidecar_records_provenance(monkeypatch, tmp_path):
    """AC7: workflow hash, resolved node map, env snapshot and ComfyUI versions."""
    monkeypatch.chdir(tmp_path)
    path = _wf_file(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=path))
    snapshot = _seed_env_snapshot(tmp_path, monkeypatch, b'{"comfyui": "deadbeef"}')

    async def fake_fetch(url, workflow):
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    prov = _provenance(tmp_path)
    assert prov["workflow_path"] == path
    assert prov["nodes"] == GOOD_NODES
    assert prov["comfyui"] == {
        "comfyui_version": "0.12.3",
        "pytorch_version": "2.11.0.dev+rocm7.1",
        "device": "cuda:0 AMD Radeon Graphics : native",
    }
    assert prov["env_snapshot_sha256"] == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    # The hash is of the *template*, before per-shot injection — otherwise it
    # differs for every shot and cannot be compared across runs.
    assert prov["workflow_sha256"] == hashlib.sha256(
        json.dumps(GOOD_WF, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert _provenance(tmp_path, "scene_002_S003")["workflow_sha256"] == prov["workflow_sha256"]


async def test_provenance_records_null_snapshot_when_absent(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path)))
    # A checkout with no snapshot committed: the shipped repo-relative path simply
    # is not there under this root.
    monkeypatch.setenv("YTFLOW_PROJECT_ROOT", str(tmp_path / "no-snapshot-here"))

    async def fake_fetch(url, workflow):
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    assert (await img.image_node(_state())).get("error") is None
    assert _provenance(tmp_path)["env_snapshot_sha256"] is None


async def test_system_stats_failure_is_null_and_does_not_fail_the_stage(monkeypatch, tmp_path):
    """AC7 [AD-10]: provenance is observability — an unreachable ComfyUI records
    null rather than losing the stage."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path)))

    async def no_stats(*a, **k):
        return None
    monkeypatch.setattr(img.comfyui_client, "get_system_stats", no_stats)

    async def fake_fetch(url, workflow):
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert len(out["scenes"][0]["shots"]) == 2
    prov = _provenance(tmp_path)
    assert prov["comfyui"] is None
    assert prov["workflow_sha256"] is not None  # the graph half is still recorded


async def test_system_stats_is_fetched_once_per_run(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path)))
    calls = []

    async def stats(url):
        calls.append(url)
        return FAKE_STATS
    monkeypatch.setattr(img.comfyui_client, "get_system_stats", stats)

    async def fake_fetch(url, workflow):
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    await img.image_node(_state())  # three shots
    assert calls == ["http://comfy.test:8188"]


async def test_mock_mode_provenance_is_null_and_never_touches_comfyui(monkeypatch, tmp_path):
    """AC7: the mock path loads no workflow, so workflow_*/comfyui are null."""
    _mock_settings(monkeypatch, tmp_path)

    async def boom(*a, **k):
        raise AssertionError("mock mode must not call /system_stats")
    monkeypatch.setattr(img.comfyui_client, "get_system_stats", boom)

    out = await img.image_node(_state())
    assert out.get("error") is None
    prov = _provenance(tmp_path)
    assert prov["workflow_path"] is None
    assert prov["workflow_sha256"] is None
    assert prov["nodes"] is None
    assert prov["comfyui"] is None


async def test_differing_provenance_is_still_a_resume_hit(monkeypatch, tmp_path):
    """AC8 — the one change in Story 13.3 that could silently re-render 155 shots.

    A sidecar written by an older ComfyUI (or before a snapshot refresh) carries
    different provenance. `_existing_complete_shot` compares only image_prompt /
    negative_prompt / seed, and must keep doing so.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    for base, prompt, negative in (
        ("scene_001_S001", "a dark room", "blurry"),
        ("scene_001_S002", "an agent", "text"),
        ("scene_002_S003", "a corridor", "watermark"),
    ):
        (d / f"{base}.png").write_bytes(RGB_PNG + b"\x00" * 1200)
        (d / f"{base}_done.json").write_text(json.dumps({
            "image_prompt": prompt,
            "negative_prompt": img._effective_negative_prompt(negative),
            "seed": _shot_seed_for(base),
            "provenance": {"workflow_sha256": "an-older-graph", "env_snapshot_sha256": "an-older-env",
                           "comfyui": {"comfyui_version": "0.9.0"}},
        }))

    async def fake_fetch(url, workflow):
        raise AssertionError("provenance drift must not trigger a re-render")
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    assert [pathlib.Path(s["image_path"]).name for s in out["scenes"][0]["shots"]] == [
        "scene_001_S001.png", "scene_001_S002.png",
    ]
    # the sidecars were not rewritten either — a resume hit writes nothing
    assert json.loads((d / "scene_001_S001_done.json").read_text())["provenance"][
        "workflow_sha256"] == "an-older-graph"


# ── Provenance review fixes (Story 13.3 review pass) ────────────────────────

async def test_stock_plate_provenance_does_not_claim_this_run_s_graph(monkeypatch, tmp_path):
    """A plate was rendered weeks ago by the plate script, from a different graph.

    Stamping this run's ``workflow_path``/``workflow_sha256`` and today's ComfyUI
    version onto its sidecar is provenance that actively lies — worse than absent
    provenance, which is the premise of Epic 13. The env-snapshot pin stays (a fact
    about the checkout that wrote the sidecar), and the ``stock_plate`` block says
    what actually produced the image: nulling everything else and stopping there
    made this object byte-identical to a mock-mode sidecar's, so a reader could not
    tell a real plate from a fixture.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(
        mock=False, workflow_path=_wf_file(tmp_path), stock_plate_substitution=True))
    snapshot = _seed_env_snapshot(tmp_path, monkeypatch, b'{"comfyui": "deadbeef"}')
    plate_src = tmp_path / "plate.png"
    plate_src.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve(location_key):
        return [_plate("a", plate_src)]
    img.inject_location_service(resolve)

    out = await img.image_node(_stock_state())
    assert out.get("error") is None
    prov = _provenance(tmp_path, run_id="run-stock-1")
    assert prov["workflow_path"] is None
    assert prov["workflow_sha256"] is None
    assert prov["nodes"] is None
    assert prov["comfyui"] is None
    assert prov["env_snapshot_sha256"] == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert prov["stock_plate"] == {
        "location_key": "corridor", "variant": "a", "path": str(plate_src),
        # Story 14.1: why THIS plate, and the verdict that rode along with it. The
        # resume path reads `standing_room` back rather than re-counting the shot as
        # never-judged, so it has to be on disk, not only in the checkpoint.
        "viewpoint": "EYE", "standing_room": True, "reason": "match",
    }


async def test_a_fully_resumed_run_pays_for_stats_at_most_once(monkeypatch, tmp_path):
    """Story 5.14 made the health check lazy so an all-resume run never touches
    ComfyUI. The provenance probe is awaited before any resume decision, so the
    guarantee it can still give is "bounded, once" — and the timeout that bounds
    it is asserted in test_comfyui_client.py.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    for base, prompt, negative in (
        ("scene_001_S001", "a dark room", "blurry"),
        ("scene_001_S002", "an agent", "text"),
        ("scene_002_S003", "a corridor", "watermark"),
    ):
        _write_complete_shot(d, base, prompt, negative)

    calls = []

    async def stats(url):
        calls.append(url)
        return FAKE_STATS
    monkeypatch.setattr(img.comfyui_client, "get_system_stats", stats)

    async def fake_fetch(url, workflow):
        raise AssertionError("a fully resumed run must render nothing")
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())
    assert out.get("error") is None
    # Exactly one, not "at most one": `<= 1` also passes at zero, so it would have
    # held just as well if the probe were deleted — defending nothing.
    assert calls == [_resume_settings(tmp_path).comfyui_url]


async def test_env_snapshot_resolves_against_the_project_root_not_the_cwd(monkeypatch, tmp_path, caplog):
    """``character_image_provider._load_workflow`` exists because the app does not
    always run from the repo root. A pin resolved against the CWD silently stops
    pinning; a pin that misses must at least say so."""
    root = tmp_path / "repo"
    (root / "data" / "comfyui").mkdir(parents=True)
    snapshot = root / "data" / "comfyui" / "env-snapshot.json"
    snapshot.write_bytes(b'{"comfyui": "cafe"}')
    monkeypatch.chdir(tmp_path)  # NOT the repo root
    monkeypatch.setenv("YTFLOW_PROJECT_ROOT", str(root))

    assert img._env_snapshot_sha256() == hashlib.sha256(snapshot.read_bytes()).hexdigest()

    monkeypatch.setenv("YTFLOW_PROJECT_ROOT", str(tmp_path / "elsewhere"))
    with caplog.at_level("WARNING"):
        assert img._env_snapshot_sha256() is None
    assert "env snapshot unreadable" in caplog.text


@pytest.mark.parametrize("stats", [
    {"system": ["not", "a", "dict"], "devices": {"not": "a list"}},
    {"system": None, "devices": None},
    {"devices": ["a bare string, not a device dict"]},
    ["the whole payload is a list"],
    # A server that answers `{}` is REACHABLE. Recording null for it made it
    # indistinguishable from unreachable, contradicting the defensive read two
    # lines up in `_build_provenance` — the reason the guard is `is not None`.
    {},
])
def test_build_provenance_survives_any_system_stats_shape(stats):
    """The key set differs across ComfyUI versions — which is the reason to record
    it at all. An unexpected shape must produce nulls, never an AttributeError that
    kills the image stage [AD-10]."""
    prov = img._build_provenance("wf.json", GOOD_WF, GOOD_NODES, stats, "sha")
    assert prov["comfyui"] == {"comfyui_version": None, "pytorch_version": None, "device": None}
    assert prov["workflow_sha256"] is not None


def test_an_unreachable_comfyui_is_the_only_null_comfyui_block():
    """The counterpart of the `{}` case above: only ``None`` — the value
    ``get_system_stats`` returns when it could not read the server at all — records
    a null block."""
    assert img._build_provenance("wf.json", GOOD_WF, GOOD_NODES, None, "sha")["comfyui"] is None


# ── Story 14.2: plate affordance gate ───────────────────────────────────────
#
# The gate asks ONE question — can a whole body stand in this plate? — once, about
# the render the 10.2 ladder already accepted, and only when a card is going to land
# on it. A `false` verdict empties that shot's `cast`; undecidable keeps both the
# frame and the cast, because the endpoint refuses corpse/medical plates
# deterministically and that class of shot is standing output of this pipeline.

CAST = [{"card_key": "SCP-049", "position": "center", "depth": "mid", "pose": "standing"}]


def _cast_state(run_id="run-img-1", cast=CAST, shots=1):
    """One scene of `shots` shots, every one carrying a card — the only shape the gate asks about."""
    state = _many_shots_state(shots)
    state["run_id"] = run_id
    state["scenes"] = [{
        **state["scenes"][0],
        "shots": [{**shot, "cast": list(cast)} for shot in state["scenes"][0]["shots"]],
    }]
    return state


def _fake_affordance(monkeypatch, verdicts, *, calls=None):
    """Affordance detector returning `verdicts` in order, then its last value forever."""
    seq = list(verdicts)

    async def detector(image_bytes, settings):
        if calls is not None:
            calls.append(image_bytes)
        return seq.pop(0) if len(seq) > 1 else seq[0]
    monkeypatch.setattr(img.vision_check, "plate_has_standing_room", detector)


def _no_affordance_calls(monkeypatch):
    async def boom(image_bytes, settings):
        raise AssertionError("the affordance gate must not be called here")
    monkeypatch.setattr(img.vision_check, "plate_has_standing_room", boom)


def _affordance_settings(tmp_path, **over):
    """Real mode, affordance gate ON (opt-in — the shipped default is off), 10.2's ladder
    OFF unless a test asks for it.

    The two guards are deliberately isolated: a test about the affordance verdict
    must not also depend on how many rungs the person guard burned.
    """
    over.setdefault("guard_attempts", 0)
    over.setdefault("plate_affordance_gate", True)
    return _guard_settings(tmp_path, **over)


async def test_a_cast_free_shot_never_asks_the_affordance_question(monkeypatch, tmp_path):
    """AC1 + matrix row 1: affordance is a question about a card that is about to land.
    `cast == []` means downstream does no overlay work at all, so there is nothing to
    ask about and the run must not pay a vision call for it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _no_affordance_calls(monkeypatch)

    out = await img.image_node(_state())  # 3 shots, every one cast-free

    assert out.get("error") is None
    assert out["run_warnings"] == []


async def test_standing_room_keeps_the_cast_and_costs_one_call(monkeypatch, tmp_path):
    """Matrix row 2: a plate that passes is asked about exactly once — the gate lives
    OUTSIDE the ladder, so the call count is per shot, never per rung."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    calls: list = []
    _fake_affordance(monkeypatch, [True], calls=calls)

    out = await img.image_node(_cast_state())

    assert out.get("error") is None
    assert out["scenes"][0]["shots"][0]["cast"] == CAST
    assert len(calls) == 1
    assert out["run_warnings"] == []
    assert _read_sidecar(tmp_path, base="scene_001_S000")["affordance_unusable"] is False


async def test_no_standing_room_empties_the_cast_and_warns(monkeypatch, tmp_path, caplog):
    """AC2: the shot in the RETURNED state loses its cast, the warning names scene and
    shot, and the input state is untouched (AD-4)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_affordance(monkeypatch, [False])
    state = _cast_state()
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    with caplog.at_level("WARNING"):
        out = await img.image_node(state)

    assert out.get("error") is None
    shot = out["scenes"][0]["shots"][0]
    assert shot["cast"] == []
    assert shot["image_path"] and (tmp_path / shot["image_path"]).is_file()  # frame kept
    assert state["scenes"][0]["shots"][0]["cast"] == CAST  # [AD-4] input not mutated
    assert [w["context"] for w in out["run_warnings"]] == [
        {"scene_num": 1, "shot_id": "S000", "reason": "no_standing_room",
         "card_keys": "SCP-049"}]
    assert out["run_warnings"][0]["code"] == "plate_affordance_unusable"
    assert out["run_warnings"][0]["stage"] == "image"
    assert captured["affordance_counts"]["unusable"] == 1
    assert "no standing room" in caplog.text


async def test_an_undecidable_verdict_keeps_the_frame_and_the_cast(monkeypatch, tmp_path):
    """AC3 + matrix rows 5/6. `data_inspection_failed` is a REPRODUCIBLE refusal on
    corpse/medical plates (report §5), so reading undecidable as "no standing room"
    would delete the cast of that whole class of shot on every run. It is also not
    counted clean: the row is the only thing that says the plate was never judged."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_affordance(monkeypatch, [None])
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_cast_state())

    assert out.get("error") is None
    shot = out["scenes"][0]["shots"][0]
    assert shot["cast"] == CAST
    assert (tmp_path / shot["image_path"]).is_file()
    assert [w["context"] for w in out["run_warnings"]] == [
        {"scene_num": 1, "shot_id": "S000", "reason": "detector_undecidable"}]
    assert captured["affordance_counts"] == {"unusable": 0, "undecidable": 1, "unjudged": 0}
    # Never written as a verdict: the sidecar flag means "cast dropped", not "unjudged".
    assert _read_sidecar(tmp_path, base="scene_001_S000")["affordance_unusable"] is False


async def test_a_raising_affordance_detector_cannot_fail_the_image_stage(monkeypatch, tmp_path):
    """AD-10 boundary, same belt-and-braces as `_populated`: the detector's contract is
    not to raise, and this survives it breaking that contract."""
    async def boom(image_bytes, settings):
        raise RuntimeError("data_inspection_failed leaked")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    monkeypatch.setattr(img.vision_check, "plate_has_standing_room", boom)

    out = await img.image_node(_cast_state())

    assert out["error"] is None
    shot = out["scenes"][0]["shots"][0]
    assert shot["cast"] == CAST  # a raise is undecidable, and undecidable keeps the cast
    assert (tmp_path / shot["image_path"]).is_file()
    assert [w["context"]["reason"] for w in out["run_warnings"]] == ["detector_undecidable"]


async def test_a_dropped_cast_is_recorded_in_the_sidecar_and_refires_on_resume(
        monkeypatch, tmp_path):
    """AC4: the emptied cast rides the LangGraph checkpoint, and a crash inside `image_node`
    (or a resume after its error path) comes back without it while the images survive, so
    the second pass resumes off disk and returns the shot straight from the early-return
    path. Without the sidecar flag the card comes BACK — the frame is cached, the deletion
    was not. NOT `full_restart_run`: that restarts from `scenario`, regenerates `scenes`,
    and the fresh `image_prompt` misses the resume cache entirely."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_affordance(monkeypatch, [False])

    first = await img.image_node(_cast_state())
    assert first["scenes"][0]["shots"][0]["cast"] == []
    assert _read_sidecar(tmp_path, base="scene_001_S000")["affordance_unusable"] is True

    # Second pass: nothing re-renders, nothing is re-judged, and the card stays gone.
    seeds = _counting_fetch(monkeypatch)
    _no_affordance_calls(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    again = await img.image_node(_cast_state())

    assert again.get("error") is None
    assert seeds == []
    assert again["scenes"][0]["shots"][0]["cast"] == []
    assert [w["context"] for w in again["run_warnings"]] == [
        {"scene_num": 1, "shot_id": "S000", "reason": "no_standing_room_earlier_run",
         "card_keys": "SCP-049"}]
    assert captured["affordance_counts"]["unusable"] == 1


async def test_a_resumed_shot_that_passed_the_gate_keeps_its_cast(monkeypatch, tmp_path):
    """The mirror of the test above: the flag is per shot, so a plate that passed must
    not be stamped by a neighbour that failed."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_affordance(monkeypatch, [False, True])

    first = await img.image_node(_cast_state(shots=2))
    assert [s["cast"] for s in first["scenes"][0]["shots"]] == [[], CAST]

    _no_affordance_calls(monkeypatch)
    again = await img.image_node(_cast_state(shots=2))
    assert [s["cast"] for s in again["scenes"][0]["shots"]] == [[], CAST]
    assert [w["context"]["shot_id"] for w in again["run_warnings"]] == ["S000"]


async def test_a_pre_14_2_sidecar_still_resumes_and_keeps_its_cast(monkeypatch, tmp_path):
    """AC6: the flag is additive and uncompared. `_existing_complete_shot` still compares
    exactly three keys, so every shot cached before this story existed is still a hit —
    adding a compared key would regenerate every workspace on earth once."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    _write_complete_shot(d, "scene_001_S000", "prompt 0", "neg",
                         seed=img._shot_seed("run-img-1", 1, "S000"))
    sidecar = json.loads((d / "scene_001_S000_done.json").read_text())
    assert "affordance_unusable" not in sidecar
    seeds = _counting_fetch(monkeypatch)
    _no_affordance_calls(monkeypatch)

    out = await img.image_node(_cast_state())

    assert out.get("error") is None
    assert seeds == []  # resumed, not regenerated
    assert out["scenes"][0]["shots"][0]["cast"] == CAST
    assert out["run_warnings"] == []


async def test_the_gate_knob_off_never_calls_the_detector(monkeypatch, tmp_path):
    """AC5 + matrix: off is an operator choice, so it costs 0 calls and changes no cast.
    It is still COUNTED — an unjudged cast-bearing shot must not read like one that
    passed (`gotcha_a-decision-that-only-reaches-env-never-ships`'s sibling lesson)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(
        tmp_path, plate_affordance_gate=False))
    _counting_fetch(monkeypatch)
    _no_affordance_calls(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_cast_state(shots=2))

    assert out.get("error") is None
    assert [s["cast"] for s in out["scenes"][0]["shots"]] == [CAST, CAST]
    assert out["run_warnings"] == []
    assert captured["affordance_counts"] == {"unusable": 0, "undecidable": 0, "unjudged": 2}


async def test_the_gate_is_not_invoked_in_mock_mode_but_the_shot_counts_as_unjudged(
        monkeypatch, tmp_path):
    """Mock mode materialises a FIXTURE, not this shot's plate. Judging it would drop a
    real cast over an image the run never rendered — the same reason the 10.2 guard skips
    mock mode. It is still an UNJUDGED cast-bearing shot, in the tally and in the sidecar:
    a mock frame that a later real pass resumes off disk must not read as one that
    passed."""
    _mock_settings(monkeypatch, tmp_path, vision_api_key="vision-key",
                   plate_affordance_gate=True)
    _no_affordance_calls(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_cast_state())

    assert out.get("error") is None
    assert out["scenes"][0]["shots"][0]["cast"] == CAST
    assert captured["affordance_counts"] == {"unusable": 0, "undecidable": 0, "unjudged": 1}
    assert _read_sidecar(tmp_path, base="scene_001_S000")["affordance_undecidable"] is True


async def _stock_affordance(monkeypatch, tmp_path, plate_over):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(
        tmp_path, stock_plate_substitution=True))
    plate_src = tmp_path / "plate.png"
    plate_src.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve(location_key):
        return [_plate("a", plate_src, **plate_over)]
    img.inject_location_service(resolve)
    _no_affordance_calls(monkeypatch)

    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))
    out = await img.image_node(_stock_state(cast=CAST))
    assert out.get("error") is None
    return out, captured


async def test_a_stock_served_cast_shot_is_judged_by_the_asset_not_unjudged(
        monkeypatch, tmp_path):
    """Story 14.1 closes the gap 14.2 left open here. The gate is still not INVOKED — the
    verdict was bought once, per asset, at curation time — but the shot is no longer
    counted as never-judged, and its sidecar no longer claims it shipped without a verdict.
    The verdict itself goes into the sidecar so a resume can read it back (D4)."""
    out, captured = await _stock_affordance(monkeypatch, tmp_path, {"standing_room": True})

    assert out["scenes"][0]["shots"][0]["cast"] == CAST
    assert captured["affordance_counts"] == {"unusable": 0, "undecidable": 0, "unjudged": 0}
    sidecar = _read_sidecar(tmp_path, run_id="run-stock-1")
    assert sidecar["affordance_undecidable"] is False
    assert sidecar["provenance"]["stock_plate"]["standing_room"] is True


async def test_a_stock_plate_with_no_verdict_still_counts_as_unjudged(monkeypatch, tmp_path):
    """The other half, and the one that must not regress: a plate the vision endpoint
    refused (corpse/medical — 14.2's permanent blind spot) carries no `standing_room` key,
    so a cast shot served from it shipped with NO verdict and is counted as such.

    Knob DOWN, because that is the only configuration in which such a plate is served at
    all: with the knob up D2 refuses it and the shot generates. The absent key is the
    recorded shape — `del`, not `standing_room=None`.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(
        tmp_path, stock_plate_substitution=True, plate_affordance_gate=False))
    plate_src = tmp_path / "plate.png"
    plate_src.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve(location_key):
        plate = _plate("a", plate_src)
        del plate["standing_room"]
        return [plate]
    img.inject_location_service(resolve)
    _no_affordance_calls(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_stock_state(cast=CAST))

    assert out.get("error") is None
    assert captured["affordance_counts"] == {"unusable": 0, "undecidable": 0, "unjudged": 1}
    # `affordance_undecidable` stays False with the knob down — 14.2's existing policy
    # (the operator asked for no gate, which is a config state, not a degradation).
    sidecar = _read_sidecar(tmp_path, run_id="run-stock-1")
    assert sidecar["affordance_undecidable"] is False
    assert sidecar["provenance"]["stock_plate"]["standing_room"] is None


async def test_d4_a_resumed_stock_served_cast_shot_reads_its_verdict_off_disk(
        monkeypatch, tmp_path):
    """D4. Without this the resume path counts EVERY cached cast-bearing shot `unjudged`,
    which revives — in the opposite direction — the defect 14.2 exists to remove: judged
    and never-judged shots indistinguishable in the tally. And silently, because
    `affordance_undecidable` is `False` on exactly these sidecars, so no warning explains
    the count."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(
        tmp_path, stock_plate_substitution=True))
    plate_src = tmp_path / "plate.png"
    plate_src.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve(location_key):
        return [_plate("a", plate_src)]
    img.inject_location_service(resolve)
    _no_affordance_calls(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    first = await img.image_node(_stock_state(cast=CAST))
    assert first.get("error") is None
    second = await img.image_node(_stock_state(cast=CAST))

    assert second.get("error") is None
    assert second["scenes"][0]["shots"][0]["cast"] == CAST
    assert captured["skipped_count"] == 1  # resumed off disk, not re-copied
    assert captured["affordance_counts"] == {"unusable": 0, "undecidable": 0, "unjudged": 0}
    assert second["run_warnings"] == []


async def test_a_resumed_generated_cast_shot_is_still_unjudged(monkeypatch, tmp_path):
    """The control for the test above: D4 reads a verdict that is ON DISK, and a generated
    shot's sidecar has none (`provenance.stock_plate` is null on every non-plate path). A
    resume of one still counts unjudged, exactly as 14.2 shipped it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_affordance(monkeypatch, [True])  # there IS room: the cast survives the first pass
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    assert (await img.image_node(_cast_state())).get("error") is None
    assert (await img.image_node(_cast_state())).get("error") is None
    assert captured["affordance_counts"] == {"unusable": 0, "undecidable": 0, "unjudged": 1}


async def test_a_pre_14_1_stock_sidecar_still_resumes_and_stays_unjudged(monkeypatch, tmp_path):
    """The comparison keys are `image_prompt`/`negative_prompt`/`seed` and Story 14.1 did
    not touch them, so a sidecar written before this story — no `viewpoint`, no
    `standing_room`, no `reason` in its `stock_plate` block — still HITS rather than
    re-copying every background in the workspace. It also has no verdict to read, so the
    shot stays `unjudged`: D4 reads what is there, it does not assume."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(
        tmp_path, stock_plate_substitution=True))
    d = tmp_path / "workspace" / "run-stock-1" / "images"
    d.mkdir(parents=True)
    (d / "scene_001_S001.png").write_bytes(RGB_PNG + b"\x00" * 1200)
    (d / "scene_001_S001_done.json").write_text(json.dumps({
        "image_prompt": "a dark room",
        "negative_prompt": img._effective_negative_prompt("blurry"),
        "seed": img._shot_seed("run-stock-1", 1, "S001", 0),
        "provenance": {"stock_plate": {
            "location_key": "corridor", "variant": "a", "path": "/gone/a.png"}},
    }), encoding="utf-8")

    async def boom(location_key):
        raise AssertionError("a resumed shot must not re-resolve plates")
    img.inject_location_service(boom)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_stock_state(cast=CAST))

    assert out.get("error") is None
    assert captured["skipped_count"] == 1
    assert captured["affordance_counts"] == {"unusable": 0, "undecidable": 0, "unjudged": 1}


async def test_the_gate_asks_once_per_shot_not_once_per_rung(monkeypatch, tmp_path):
    """The design note: the gate sits OUTSIDE the 10.2 ladder. Three renders for one
    shot is still one affordance call, on the render the ladder settled on — and 10.2's
    own accounting is untouched by it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(
        tmp_path, plate_affordance_gate=True))  # attempts=2
    seeds = _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [True])  # every render is populated -> ladder exhausts
    calls: list = []
    _fake_affordance(monkeypatch, [True], calls=calls)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_cast_state())

    assert out.get("error") is None
    assert len(seeds) == 3  # rungs 0,1,2 — unchanged by this story
    assert len(calls) == 1
    assert calls[0] == (tmp_path / out["scenes"][0]["shots"][0]["image_path"]).read_bytes()
    assert captured["guard_counts"] == {
        "regenerated": 2, "exhausted": 1, "unavailable": 0, "unscreened": 0}
    assert _read_sidecar(tmp_path, base="scene_001_S000")["seed"] == seeds[-1]


async def test_an_affordance_undecidable_does_not_touch_the_10_2_breaker(monkeypatch, tmp_path):
    """Two questions, two breakers, one set of thresholds. An affordance refusal must not
    silence the person guard — that question may still be answerable on the same frame,
    and 10.2's counters are how a populated background stays visible."""
    from yt_flow.config import BACKGROUND_PERSON_GUARD_BREAKER_STREAK as STREAK
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(
        tmp_path, guard_attempts=1, plate_affordance_gate=True))
    _counting_fetch(monkeypatch)
    person_calls: list = []
    _fake_detector(monkeypatch, [False], calls=person_calls)
    _fake_affordance(monkeypatch, [None])
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_cast_state(shots=STREAK + 2))

    assert out.get("error") is None
    # The person guard answered for EVERY shot, including the ones after the affordance
    # gate had switched itself off.
    assert len(person_calls) == STREAK + 2
    assert captured["guard_counts"]["unavailable"] == 0
    assert captured["affordance_counts"] == {
        "unusable": 0, "undecidable": STREAK, "unjudged": 2}


async def test_the_gate_disables_itself_after_consecutive_undecidable_verdicts(
        monkeypatch, tmp_path, caplog):
    """Matrix row 8: 10.2's thresholds, reused rather than re-invented — a dead detector
    costs a 120s timeout per call and the bound has to exist. The breaker's own row
    carries the tallies, which are excluded from warning identity so a retry with a
    different tally converges on the row already in the checkpoint."""
    from yt_flow.config import BACKGROUND_PERSON_GUARD_BREAKER_STREAK as STREAK
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    calls: list = []
    _fake_affordance(monkeypatch, [None], calls=calls)

    with caplog.at_level("WARNING"):
        out = await img.image_node(_cast_state(shots=STREAK + 2))

    assert out.get("error") is None
    assert len(calls) == STREAK  # then off — the remaining shots are never asked about
    assert [w["context"] for w in out["run_warnings"]][-1] == {
        "reason": "detector_undecidable_run",
        "undecidable_streak": STREAK, "undecidable_total": STREAK,
    }
    assert "plate affordance gate disabled for the rest of the run" in caplog.text
    # Every shot kept its cast: undecidable is not a verdict.
    assert all(s["cast"] == CAST for s in out["scenes"][0]["shots"])


async def test_the_summary_line_reads_for_both_guards(monkeypatch, tmp_path, caplog):
    """The 10.2 summary WARNING is untouched and the affordance tally is its own line —
    one line about two different predicates would say neither."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _guard_settings(
        tmp_path, guard_attempts=1, plate_affordance_gate=True))
    _counting_fetch(monkeypatch)
    _fake_detector(monkeypatch, [True])   # populated on both rungs -> exhausted
    _fake_affordance(monkeypatch, [False])

    with caplog.at_level("WARNING"):
        out = await img.image_node(_cast_state())

    assert out.get("error") is None
    assert "NOT verified unpopulated" in caplog.text          # Story 10.2's line
    assert "1 shot(s) lost their cast (no standing room)" in caplog.text
    assert {w["code"] for w in out["run_warnings"]} == {
        "background_guard_unscreened", "plate_affordance_unusable"}


async def test_error_path_still_reports_the_affordance_counts(monkeypatch, tmp_path):
    """A stage that dies mid-run must not lose the casts it already dropped — the same
    contract `guard_counts` and `depth_counts` have."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    calls = {"n": 0}

    async def fetch_then_die(url, workflow):
        calls["n"] += 1
        if calls["n"] > 1:
            raise ValueError("comfyui exploded")
        return RGB_PNG + b"\x00" * 1200
    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fetch_then_die)
    _fake_affordance(monkeypatch, [False])
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    out = await img.image_node(_cast_state(shots=2))

    assert out["error"] and "stage=image" in out["error"]
    assert captured["affordance_counts"]["unusable"] == 1
    assert [w["context"]["reason"] for w in out["run_warnings"]] == ["no_standing_room"]


async def test_dropped_cast_rows_are_bounded_by_the_shared_sample_cap(monkeypatch, tmp_path):
    """A plate family that fails everywhere (a whole scene of table macros) must not put
    a row per shot in front of the Approve button. The cap is per (code, reason), so the
    aggregate names the reason it counted."""
    from yt_flow.domain.warnings import MAX_SAMPLE_RECORDS
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_affordance(monkeypatch, [False])
    n = MAX_SAMPLE_RECORDS + 4

    out = await img.image_node(_cast_state(shots=n))

    named = [w for w in out["run_warnings"] if "shot_id" in (w.get("context") or {})]
    assert len(named) == MAX_SAMPLE_RECORDS
    assert {"reason": "no_standing_room", "total_count": n} in [
        w["context"] for w in out["run_warnings"]]
    # The verdict still applied to EVERY shot — the cap bounds the rows, not the effect.
    assert all(s["cast"] == [] for s in out["scenes"][0]["shots"])


async def test_a_missing_vision_key_is_one_run_level_row_not_a_dead_detector(
        monkeypatch, tmp_path, caplog):
    """The key is a RUN-level fact, so it files one row and switches the gate off before
    the first shot — not 33 doomed calls, 33 undecidable rows and then a breaker row all
    describing the same missing environment variable. Exactly what 10.2 does with the same
    condition, and the cast survives untouched."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(
        tmp_path, vision_api_key=""))
    _counting_fetch(monkeypatch)
    _no_affordance_calls(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    with caplog.at_level("WARNING"):
        out = await img.image_node(_cast_state(shots=3))

    assert out.get("error") is None
    assert [s["cast"] for s in out["scenes"][0]["shots"]] == [CAST, CAST, CAST]
    affordance = [w for w in out["run_warnings"] if w["code"] == "plate_affordance_unusable"]
    assert [w["context"] for w in affordance] == [{"reason": "vision_api_key_missing"}]
    assert captured["affordance_counts"] == {"unusable": 0, "undecidable": 0, "unjudged": 3}
    assert "YTFLOW_CHARACTER_VISION_API_KEY is unset" in caplog.text
    # The degradation rides the sidecar too: the frames shipped unscreened.
    assert _read_sidecar(tmp_path, base="scene_001_S000")["affordance_undecidable"] is True


async def test_the_knob_being_off_leaves_nothing_on_disk_to_refire(monkeypatch, tmp_path):
    """The mirror of the test above: a knob the operator turned down is a choice, not a
    degradation (10.2's policy for `attempts < 1`), so it warns nothing and stamps nothing
    — otherwise every resume of an off-gate workspace would file a row per cast-bearing
    shot forever."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(
        tmp_path, plate_affordance_gate=False))
    _counting_fetch(monkeypatch)
    _no_affordance_calls(monkeypatch)

    out = await img.image_node(_cast_state())

    assert out["run_warnings"] == []
    assert _read_sidecar(tmp_path, base="scene_001_S000")["affordance_undecidable"] is False


async def test_an_undecidable_shot_refires_as_unjudged_on_resume(monkeypatch, tmp_path):
    """Story 13.1's defect, in this gate's shape: the frame is cached and the emptied
    accounting is not, so without the sidecar flag a second pass over a shot nobody could
    judge reports a perfectly clean affordance tally. The row's reason says WHICH pass
    failed to judge it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_affordance(monkeypatch, [None])

    first = await img.image_node(_cast_state())
    assert first["scenes"][0]["shots"][0]["cast"] == CAST
    assert _read_sidecar(tmp_path, base="scene_001_S000")["affordance_undecidable"] is True

    seeds = _counting_fetch(monkeypatch)
    _no_affordance_calls(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    again = await img.image_node(_cast_state())

    assert again.get("error") is None
    assert seeds == []  # resumed off disk, nothing re-rendered and nothing re-judged
    assert again["scenes"][0]["shots"][0]["cast"] == CAST
    assert [w["context"] for w in again["run_warnings"]] == [
        {"scene_num": 1, "shot_id": "S000", "reason": "unjudged_earlier_run"}]
    assert captured["affordance_counts"] == {"unusable": 0, "undecidable": 0, "unjudged": 1}


async def test_turning_the_knob_off_brings_a_dropped_card_back_on_the_next_pass(
        monkeypatch, tmp_path):
    """The recovery path for the measured 1/25 false positive. The drop is re-applied from
    the sidecar only while the gate is ON, so an operator who looks at the frame and
    disagrees flips the knob down and the card returns on the next pass — no re-render, no
    hand-edited sidecar. Without this, one wrong verdict is permanent for that workspace."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_affordance(monkeypatch, [False])

    first = await img.image_node(_cast_state())
    assert first["scenes"][0]["shots"][0]["cast"] == []

    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(
        tmp_path, plate_affordance_gate=False))
    seeds = _counting_fetch(monkeypatch)
    _no_affordance_calls(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    again = await img.image_node(_cast_state())

    assert again.get("error") is None
    assert seeds == []  # the frame is still the cached one; only the cast came back
    assert again["scenes"][0]["shots"][0]["cast"] == CAST
    assert captured["affordance_counts"] == {"unusable": 0, "undecidable": 0, "unjudged": 1}


async def test_a_resumed_shot_with_no_cast_left_is_not_warned_about(monkeypatch, tmp_path):
    """A shot whose `cast` is already `[]` — 8.19's text marker fired, or the state was
    edited — has nothing to drop, so a row claiming a card was removed would be false.
    The unjudged tally stays out of it too: there was never a question to ask."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_affordance(monkeypatch, [False])

    await img.image_node(_cast_state())  # stamps affordance_unusable on the sidecar

    _no_affordance_calls(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(img, "_record_trace", lambda **kw: captured.update(kw))

    again = await img.image_node(_cast_state(cast=[]))

    assert again.get("error") is None
    assert again["scenes"][0]["shots"][0]["cast"] == []
    assert again["run_warnings"] == []
    assert captured["affordance_counts"] == {"unusable": 0, "undecidable": 0, "unjudged": 0}


async def test_the_warning_names_the_card_that_left_the_frame(monkeypatch, tmp_path):
    """`len(cast)` in a log line does not tell an operator WHICH character vanished, which
    is the only part of the row they can act on. The keys ride the context on both the
    judged row and the resumed one, and stay stable so the resume converges."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _affordance_settings(tmp_path))
    _counting_fetch(monkeypatch)
    _fake_affordance(monkeypatch, [False])
    cast = [*CAST, {"card_key": "Dr-Bright", "position": "left", "depth": "fg",
                    "pose": "standing"}]

    first = await img.image_node(_cast_state(cast=cast))
    assert first["run_warnings"][0]["context"]["card_keys"] == "SCP-049,Dr-Bright"

    _no_affordance_calls(monkeypatch)
    again = await img.image_node(_cast_state(cast=cast))
    assert again["run_warnings"][0]["context"] == {
        "scene_num": 1, "shot_id": "S000", "reason": "no_standing_room_earlier_run",
        "card_keys": "SCP-049,Dr-Bright",
    }


# ── Story 14.3: the recompose key ────────────────────────────────────────────


async def test_the_sidecar_declares_the_recompose_key_as_an_explicit_null(monkeypatch, tmp_path):
    """Written, not omitted. `null` says "this run did not recompose this shot"; an ABSENT
    key says "this sidecar predates Story 14.3".

    No code branches on the difference — `_stamp_sidecar` treats absent and null the same —
    so this pins a schema slot for whoever reads a sidecar, not a runtime behaviour. The
    test is here because the slot is easy to drop by accident and impossible to backfill.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings",
                        lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path)))

    async def fake_fetch(url, workflow):
        return RGB_PNG + b"\x00" * 1200

    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())

    assert out.get("error") is None
    sidecar = json.loads(
        (tmp_path / "workspace" / "run-img-1" / "images" / "scene_001_S001_done.json")
        .read_text())
    assert "recompose" in sidecar
    assert sidecar["recompose"] is None


async def test_a_sidecar_carrying_a_recompose_block_is_still_a_resume_hit(monkeypatch, tmp_path):
    """The invariant every checkpoint in the workspace depends on.

    `_existing_complete_shot` compares exactly three keys — image_prompt,
    negative_prompt, seed-in-ladder. recompose_service writes a fourth into the same
    file after the fact; if that became a compared key, every recomposed shot would
    re-render on the next resume, which is 33 of run 4b35c0ed's 43 shots.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: _resume_settings(tmp_path))
    d = tmp_path / "workspace" / "run-img-1" / "images"
    d.mkdir(parents=True)
    for base, prompt, negative in (
        ("scene_001_S001", "a dark room", "blurry"),
        ("scene_001_S002", "an agent", "text"),
        ("scene_002_S003", "a corridor", "watermark"),
    ):
        _write_complete_shot(d, base, prompt, negative)
        sidecar = d / f"{base}_done.json"
        record = json.loads(sidecar.read_text())
        record["recompose"] = {
            "recomposed_at": "2026-08-29T00:00:00+00:00", "source": "rendered",
            "workflow_path": "data/workflows/comfyui_shot_recompose_qwen_api.json",
            "workflow_sha256": "a" * 64, "digest": "0123456789abcdef",
            "output_path": str(d.parent / "recomposed" / "S001_0123456789abcdef.png"),
            "passes": [{"card_key": "SCP-049", "position": "left", "depth": "mid"}],
        }
        sidecar.write_text(json.dumps(record))

    async def fake_fetch(url, workflow):
        raise AssertionError("a recompose block must not trigger a re-render")

    monkeypatch.setattr(img.comfyui_client, "submit_and_fetch", fake_fetch)

    out = await img.image_node(_state())

    assert out.get("error") is None
    assert all(s["image_path"] for sc in out["scenes"] for s in sc["shots"])
