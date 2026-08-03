"""Unit tests for src/yt_flow/pipeline/nodes/image.py (Story 1.6, background-only
since Story 8.3).

No live ComfyUI / Langfuse: the HTTP client, settings, trace sink, and (for
mock mode) the fixtures dir are all monkeypatched. Tests assert the node's
PipelineState contract (image_path set on every shot, error handling, purity),
prompt injection into nodes "6"/"7" (including the AC2 negative-prompt
suffix), the mock/real branch behaviour, and shot-level resume/health-check.

Import the submodule explicitly: nodes/__init__.py still binds a stub `image`
attribute (Story 1.4), so `import a.b.image as img` is what resolves to this
module rather than the stub. [mirrors test_scenario.py]
"""

import json

import pytest

import yt_flow.pipeline.nodes.image as img
from yt_flow.services.comfyui_client import ComfyUIError

GOOD_WF = {
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "placeholder"}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "placeholder"}},
}

RGB_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class FakeSettings:
    def __init__(
        self, *, mock, workflow_path,
        health_poll_every_n_shots=20, crash_recovery_poll_sec=15.0, crash_recovery_timeout_sec=300.0,
    ):
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


# ── Prompt injection (AC1, AC2) — pure, no ComfyUI ──────────────────────────

def test_inject_prompts_targets_nodes_6_and_7():
    # Story 11.1: _inject_prompts grew a required seed arg (single call site).
    out = img._inject_prompts(GOOD_WF, "positive text", "negative text", 1)
    assert out["6"]["inputs"]["text"] == "positive text"
    # template is untouched — one loaded workflow is safely reused per shot
    assert GOOD_WF["6"]["inputs"]["text"] == "placeholder"


def test_inject_prompts_appends_negative_suffix():
    """AC2: code-side entity exclusion belt, on top of the prompt-side (8.1) suspenders."""
    out = img._inject_prompts(GOOD_WF, "a corridor", "watermark", 1)
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
    out = img._inject_prompts(wf, "p", "n", 1234)
    assert out["3"]["inputs"]["seed"] == 1234
    assert out["42"]["inputs"]["seed"] == 1234
    # template purity holds for the seed too
    assert wf["3"]["inputs"]["seed"] == 0


def test_inject_prompts_harmless_without_ksampler():
    out = img._inject_prompts(GOOD_WF, "p", "n", 99)  # GOOD_WF has no KSampler
    assert out["6"]["inputs"]["text"] == "p"


def test_load_workflow_rejects_missing_prompt_nodes(tmp_path):
    bad = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}}}  # no node "7"
    with pytest.raises(ValueError):
        img._load_workflow(_wf_file(tmp_path, bad))


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
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path)))
    plate_src = tmp_path / "plate.png"
    plate_src.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve(location_key):
        assert location_key == "corridor"
        return [{"variant": "a", "path": str(plate_src)}]
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


async def test_stock_plate_miss_falls_through_to_generation(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path)))

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
    _mock_settings(monkeypatch, tmp_path)
    plate_src = tmp_path / "plate.png"
    plate_src.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve(location_key):
        return [{"variant": "a", "path": str(plate_src)}]
    img.inject_location_service(resolve)

    out = await img.image_node(_stock_state())
    assert out.get("error") is None
    shot = out["scenes"][0]["shots"][0]
    assert (tmp_path / shot["image_path"]).read_bytes() == plate_src.read_bytes()


async def test_stock_variant_selection_matches_plate_bytes(monkeypatch, tmp_path):
    """AC5: variant-select via hash(run_id:scene_num:location_key) % count."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path)))
    plates = []
    for v, marker in (("a", b"AAAA"), ("b", b"BBBB"), ("c", b"CCCC")):
        p = tmp_path / f"plate_{v}.png"
        p.write_bytes(RGB_PNG + marker + b"\x00" * 1200)
        plates.append({"variant": v, "path": str(p)})

    async def resolve(location_key):
        return plates
    img.inject_location_service(resolve)

    expected_idx = img._plate_variant_index("run-stock-1", 1, "corridor", len(plates))
    out = await img.image_node(_stock_state())
    shot = out["scenes"][0]["shots"][0]
    from pathlib import Path
    assert Path(shot["image_path"]).read_bytes() == Path(plates[expected_idx]["path"]).read_bytes()


async def test_stock_plate_count_recorded_in_trace(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(img, "_settings", lambda: FakeSettings(mock=False, workflow_path=_wf_file(tmp_path)))
    plate_src = tmp_path / "plate.png"
    plate_src.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve(location_key):
        return [{"variant": "a", "path": str(plate_src)}]
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
    _mock_settings(monkeypatch, tmp_path)
    plate = tmp_path / "plate.png"
    plate.write_bytes(RGB_PNG + b"\x00" * 1200)

    async def resolve_loc(key):
        return [{"variant": "a", "path": str(plate)}]

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
