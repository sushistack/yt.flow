"""Unit tests for scripts/compare_tts_providers.py (Story 12.5).

Asserts the *decision package*, not audio quality: identical source text and
post-processing across candidates, blind mapping completeness, manifest
redaction, preflight, cleanup on failure, and zero network in dry-run.

No live DashScope: `_synthesize` and `_run_ffmpeg` are monkeypatched, and a
guard test proves the dry-run path touches neither.
"""

import asyncio
import importlib.util
import json
import math
import shutil
import struct
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

_SPEC = importlib.util.spec_from_file_location(
    "compare_tts_providers", Path(__file__).parent.parent / "scripts" / "compare_tts_providers.py")
assert _SPEC and _SPEC.loader
ctp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ctp)

TEXT = "이 개체는 에스씨피-096으로 분류됐습니다. 키는 이점삼팔 미터, 얼굴은 볼 수 없습니다."

# Captured before any fixture patches it, so the real-ffmpeg E2E test can restore it.
_REAL_RUN_FFMPEG = ctp.tts._run_ffmpeg


class _Settings(SimpleNamespace):
    """Stand-in for pydantic Settings; only `model_copy` is used by the script."""

    def model_copy(self, *, update):
        return _Settings(**{**vars(self), **update})


def _settings(tmp_path, **over):
    base = dict(
        qwen_tts_api_key="sk-test",
        qwen_tts_endpoint="https://dashscope-intl.aliyuncs.com",
        qwen_tts_model="qwen3-tts-flash",
        qwen_tts_voice="Cherry",
        qwen_tts_clone_enabled=False,
        qwen_tts_clone_model="qwen3-tts-vc-2026-01-22",
        qwen_tts_clone_voice_id="voice-sutak-secret-id",
        qwen_tts_speed=1.2,
        workspace_path=str(tmp_path),
    )
    base.update(over)
    return _Settings(**base)


def _write_wav(path: Path, *, framerate=24000, channels=1, sampwidth=2, frames=2400):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(framerate)
        w.writeframes(b"\x00" * (frames * sampwidth * channels))


@pytest.fixture
def text_file(tmp_path):
    p = tmp_path / "scene.txt"
    p.write_text(TEXT, encoding="utf-8")
    return p


@pytest.fixture
def harness(monkeypatch, tmp_path, text_file):
    """Wire fake synthesis + ffmpeg and record every call the script makes."""
    calls = {"synth": [], "ffmpeg": []}

    async def fake_synth(text, s, path):
        calls["synth"].append({"text": text, "voice_mode": "clone" if s.qwen_tts_clone_enabled else "stock",
                               "model": s.qwen_tts_clone_model if s.qwen_tts_clone_enabled else s.qwen_tts_model,
                               "path": Path(path)})
        _write_wav(Path(path), framerate=16000)  # raw differs from the pinned final format

    async def fake_ffmpeg(*args):
        calls["ffmpeg"].append(list(args))
        _write_wav(Path(args[-1]))  # dest is the last positional arg
        return 0, ""

    monkeypatch.setattr(ctp.tts, "_synthesize", fake_synth)
    monkeypatch.setattr(ctp.tts, "_run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(ctp, "Settings", lambda: _settings(tmp_path))
    return SimpleNamespace(calls=calls, tmp_path=tmp_path, text_file=text_file)


def _run(harness, monkeypatch, *extra):
    monkeypatch.setattr(sys, "argv", [
        "compare_tts_providers.py", "--text-file", str(harness.text_file), "--seed", "7", *extra])
    import asyncio
    assert asyncio.run(ctp.main()) == 0
    root = harness.tmp_path / "tts-provider-comparison"
    assert root.is_dir(), "a successful run must write a timestamped package dir"
    return next(root.iterdir())


# ── Candidates and source text ──────────────────────────────────────────────

def test_both_candidates_get_byte_identical_text_and_distinct_voice_modes(harness, monkeypatch):
    _run(harness, monkeypatch)
    synth = harness.calls["synth"]
    assert len(synth) == 2
    assert {c["text"] for c in synth} == {TEXT}, "provider-specific text edits invalidate the comparison"
    assert {c["voice_mode"] for c in synth} == {"stock", "clone"}
    by_mode = {c["voice_mode"]: c for c in synth}
    assert by_mode["stock"]["model"] == "qwen3-tts-flash"
    assert by_mode["clone"]["model"] == "qwen3-tts-vc-2026-01-22"


def test_clone_enabled_flag_is_forced_not_inherited_from_env(harness, monkeypatch, tmp_path):
    """Ambient .env has clone ON; the stock candidate must still be rendered stock."""
    monkeypatch.setattr(ctp, "Settings", lambda: _settings(tmp_path, qwen_tts_clone_enabled=True))
    _run(harness, monkeypatch)
    assert {c["voice_mode"] for c in harness.calls["synth"]} == {"stock", "clone"}


def test_identical_post_processing_for_every_candidate(harness, monkeypatch):
    _run(harness, monkeypatch)
    filters = [a[a.index("-filter:a") + 1] for a in harness.calls["ffmpeg"]]
    assert len(filters) == 2
    assert len(set(filters)) == 1, "differing filters would let volume/speed reveal the provider"
    assert filters[0] == "atempo=1.2,loudnorm=I=-16:TP=-1.5:LRA=11"
    for args in harness.calls["ffmpeg"]:
        assert args[args.index("-ar") + 1] == "24000"
        assert args[args.index("-ac") + 1] == "1"
        assert args[args.index("-c:a") + 1] == "pcm_s16le"


# ── Blinding ────────────────────────────────────────────────────────────────

def test_listening_files_are_neutral_and_mapping_is_complete_and_separate(harness, monkeypatch):
    run_dir = _run(harness, monkeypatch)
    listen = sorted(p.name for p in (run_dir / "listen").glob("*.wav"))
    assert listen == ["A.wav", "B.wav"], "candidate filenames must not name the provider"
    mapping = json.loads((run_dir / "reveal" / "mapping.json").read_text())
    assert sorted(mapping) == ["A", "B"]
    assert sorted(mapping.values()) == ["qwen-clone", "qwen-stock"], "mapping must be a bijection"
    assert not (run_dir / "listen" / "mapping.json").exists(), "the reveal must not sit in the listening dir"


def test_stdout_never_reveals_the_mapping(harness, monkeypatch, capsys):
    """The operator who generates the package is usually the listener too -- terminal
    scrollback naming A.wav's engine defeats the blind test before it starts."""
    _run(harness, monkeypatch)
    out = capsys.readouterr().out
    assert "qwen-stock" not in out and "qwen-clone" not in out, f"stdout leaked the blind mapping:\n{out}"
    assert "A.wav" in out, "progress output should still confirm the files were produced"


def test_seed_pins_the_shuffle_and_different_seeds_can_differ(harness, monkeypatch):
    run_dir = _run(harness, monkeypatch)
    first = json.loads((run_dir / "reveal" / "mapping.json").read_text())
    import random
    orders = set()
    for seed in range(12):
        names = ["qwen-clone", "qwen-stock"]
        random.Random(seed).shuffle(names)
        orders.add(tuple(names))
    assert len(orders) == 2, "the shuffle must actually randomize, not always yield one order"
    assert first == json.loads((run_dir / "reveal" / "mapping.json").read_text())


def test_scorecard_covers_every_rubric_axis_and_all_four_verdicts(harness, monkeypatch):
    run_dir = _run(harness, monkeypatch)
    card = (run_dir / "listen" / "scorecard.md").read_text(encoding="utf-8")
    for axis in ("naturalness", "Normalization-sensitive", "Prosody", "Pace", "Voice fit", "Artifacts"):
        assert axis in card
    for verdict in ("qwen-stock", "qwen-clone", "naver", "inconclusive"):
        assert verdict in card
    assert "verdict:" in card and "by:" in card and "date:" in card
    assert "qwen-stock" not in card.split("## Verdict")[0], "the rubric must not name a candidate before the reveal"


# ── Manifest ────────────────────────────────────────────────────────────────

def test_manifest_records_text_hash_speed_and_provenance(harness, monkeypatch):
    import hashlib
    run_dir = _run(harness, monkeypatch)
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert m["text"] == TEXT
    assert m["text_sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()
    assert m["speed_factor"] == 1.2
    assert "tts_normalize" in m["tts_normalize_provenance"]
    assert "naver-ineligible" in m["excluded"]["naver-clova-voice"]


def test_manifest_leaks_no_secret_and_no_mapping(harness, monkeypatch):
    run_dir = _run(harness, monkeypatch)
    raw = (run_dir / "manifest.json").read_text(encoding="utf-8")
    assert "sk-test" not in raw, "API key must never reach the manifest"
    assert "voice-sutak-secret-id" not in raw, "account-scoped clone voice id must be redacted"
    m = json.loads(raw)
    assert m["candidates"]["qwen-clone"]["voice"] == "<redacted:clone-voice-id>"
    assert m["candidates"]["qwen-stock"]["voice"] == "Cherry"
    assert "mapping" not in raw, "the manifest must not reveal the blind mapping"


def test_manifest_records_identical_output_format_for_all_candidates(harness, monkeypatch):
    run_dir = _run(harness, monkeypatch)
    outputs = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["outputs"]
    fmt = [{k: v for k, v in o.items() if k != "duration_sec"} for o in outputs.values()]
    assert fmt[0] == fmt[1] == {"framerate": 24000, "channels": 1, "sampwidth": 2}


def test_format_drift_between_candidates_fails_the_run(harness, monkeypatch):
    """If post-processing silently yields different formats, blinding is broken -> refuse."""
    seen = []

    async def drifting_ffmpeg(*args):
        seen.append(args)
        _write_wav(Path(args[-1]), framerate=24000 if len(seen) == 1 else 48000)
        return 0, ""

    monkeypatch.setattr(ctp.tts, "_run_ffmpeg", drifting_ffmpeg)
    monkeypatch.setattr(sys, "argv", ["x", "--text-file", str(harness.text_file), "--seed", "7"])
    import asyncio
    with pytest.raises(RuntimeError, match="blinding is broken"):
        asyncio.run(ctp.main())


# ── Preflight, failure cleanup, dry-run ─────────────────────────────────────

@pytest.mark.parametrize("over, needle", [
    ({"qwen_tts_api_key": ""}, "YTFLOW_QWEN_TTS_API_KEY"),
    ({"qwen_tts_clone_voice_id": "  "}, "YTFLOW_QWEN_TTS_CLONE_VOICE_ID"),
])
def test_preflight_blocks_billed_calls_on_missing_credentials(harness, monkeypatch, tmp_path, over, needle):
    monkeypatch.setattr(ctp, "Settings", lambda: _settings(tmp_path, **over))
    monkeypatch.setattr(sys, "argv", ["x", "--text-file", str(harness.text_file)])
    import asyncio
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(ctp.main())
    assert needle in str(exc.value)
    assert harness.calls["synth"] == [], "preflight must run before any billed call"
    assert "sk-test" not in str(exc.value)


def test_failure_leaves_no_partial_package(harness, monkeypatch):
    async def boom(text, s, path):
        if harness.calls["synth"]:
            raise RuntimeError("second candidate failed")
        harness.calls["synth"].append(path)
        _write_wav(Path(path))

    monkeypatch.setattr(ctp.tts, "_synthesize", boom)
    monkeypatch.setattr(sys, "argv", ["x", "--text-file", str(harness.text_file), "--seed", "7"])
    import asyncio
    with pytest.raises(RuntimeError, match="second candidate failed"):
        asyncio.run(ctp.main())
    root = harness.tmp_path / "tts-provider-comparison"
    assert not root.exists() or not any(root.iterdir()), "a half-built package would read as a valid comparison"


def test_dry_run_makes_no_network_ffmpeg_or_file_writes(harness, monkeypatch, capsys):
    async def explode(*a, **k):
        raise AssertionError("dry-run must not call out")

    monkeypatch.setattr(ctp.tts, "_synthesize", explode)
    monkeypatch.setattr(ctp.tts, "_run_ffmpeg", explode)
    monkeypatch.setattr(sys, "argv", ["x", "--text-file", str(harness.text_file), "--dry-run"])
    import asyncio
    assert asyncio.run(ctp.main()) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["dry_run"] is True
    assert "sk-test" not in json.dumps(plan)
    assert not (harness.tmp_path / "tts-provider-comparison").exists()


def test_dry_run_needs_no_credentials(harness, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ctp, "Settings", lambda: _settings(tmp_path, qwen_tts_api_key="", qwen_tts_clone_voice_id=""))
    monkeypatch.setattr(sys, "argv", ["x", "--text-file", str(harness.text_file), "--dry-run"])
    import asyncio
    assert asyncio.run(ctp.main()) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True


# ── The frozen scene actually shipped in the repo ───────────────────────────

def test_frozen_scene_covers_the_required_normalization_cases():
    text = (Path(__file__).parent.parent / "data" / "tts-comparison" / "scene.txt").read_text(encoding="utf-8")
    assert "에스씨피-096" in text, "needs an SCP identifier"
    assert "이점삼팔 미터" in text, "needs a number + unit"
    assert text.count(",") >= 2, "needs comma/breath boundaries"
    assert not text.endswith("\n"), "must be byte-for-byte SceneState.narration, no trailing newline"


# ════════════════════════════════════════════════════════════════════════════
# E2E: the tests above stub `tts._synthesize`, so nothing there proves the
# script actually reaches DashScope correctly, or that its ffmpeg argument
# string is valid ffmpeg. These drive the real seams instead -- the HTTP
# transport below `_synthesize`, and the real ffmpeg binary -- while staying
# offline and unbilled.
# ════════════════════════════════════════════════════════════════════════════


class _FakeResponse:
    def __init__(self, data=None, content=b""):
        self._data = data or {}
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def _fake_httpx_client(requests, audio_bytes=b"RIFFfake"):
    """Record every outbound call the real `_synthesize` makes. Never touches a socket."""

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, headers, json):
            requests.append({"method": "POST", "url": url, "headers": headers, "json": json})
            return _FakeResponse({"output": {"audio": {"url": "https://audio.example/out.wav"}}})

        async def get(self, url):
            requests.append({"method": "GET", "url": url, "headers": {}, "json": None})
            return _FakeResponse(content=audio_bytes)

    return Client


@pytest.fixture
def transport(monkeypatch, tmp_path, text_file):
    """Same harness, but only ffmpeg is faked -- synthesis runs for real down to httpx."""
    requests = []
    ffmpeg = []

    async def fake_ffmpeg(*args):
        ffmpeg.append(list(args))
        _write_wav(Path(args[-1]))
        return 0, ""

    monkeypatch.setattr(ctp.tts.httpx, "AsyncClient", _fake_httpx_client(requests))
    monkeypatch.setattr(ctp.tts, "_run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(ctp, "Settings", lambda: _settings(tmp_path))
    return SimpleNamespace(requests=requests, ffmpeg=ffmpeg, tmp_path=tmp_path, text_file=text_file,
                           calls={"synth": [], "ffmpeg": ffmpeg})


def test_e2e_transport_posts_exact_dashscope_target_headers_and_bodies(transport, monkeypatch):
    """AC10 'exact provider target/headers/body' -- asserted through the script, not around it."""
    _run(transport, monkeypatch)
    posts = [r for r in transport.requests if r["method"] == "POST"]
    assert len(posts) == 2, "exactly one billed synthesis call per candidate"

    expected_url = "https://dashscope-intl.aliyuncs.com" + ctp.tts._GENERATION_PATH
    assert {p["url"] for p in posts} == {expected_url}
    assert {p["headers"]["Authorization"] for p in posts} == {"Bearer sk-test"}

    bodies = sorted((p["json"] for p in posts), key=lambda b: b["model"])
    assert bodies == [
        {"model": "qwen3-tts-flash", "input": {"text": TEXT, "voice": "Cherry"}},
        {"model": "qwen3-tts-vc-2026-01-22", "input": {"text": TEXT, "voice": "voice-sutak-secret-id"}},
    ], "stock must use the stock model/voice and clone the enrolled voice id, with identical text"


def test_e2e_transport_never_contacts_naver(transport, monkeypatch):
    """AC1 is `naver-ineligible`: this helper must not reach a Naver endpoint at all."""
    _run(transport, monkeypatch)
    hosts = " ".join(r["url"] for r in transport.requests)
    assert "ntruss" not in hosts and "naver" not in hosts, f"Naver was called despite AC1: {hosts}"


def test_e2e_transport_downloads_each_rendered_audio_once(transport, monkeypatch):
    run_dir = _run(transport, monkeypatch)
    assert len([r for r in transport.requests if r["method"] == "GET"]) == 2
    raw_dir = run_dir / "reveal" / "raw"
    raws = sorted(p.name for p in raw_dir.iterdir())
    assert raws == ["qwen-clone.wav", "qwen-stock.wav"], "raw originals stay provider-named, under reveal/"
    assert (raw_dir / "qwen-stock.wav").read_bytes() == b"RIFFfake", "downloaded body must be persisted"


def _write_tone(path: Path, *, framerate=16000, seconds=1.0):
    """A real, non-silent WAV: loudnorm on digital silence is not a meaningful exercise."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(framerate * seconds)
    frames = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / framerate))) for i in range(n))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(frames)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_e2e_real_ffmpeg_yields_identical_readable_pcm_and_applies_the_speed(harness, monkeypatch):
    """The mocked tests only compare the ffmpeg *argument string*; a typo in the filter
    chain would still ship. Run the real binary and read the result back."""
    async def synth_tone(text, s, path):
        # Deliberately unequal raw formats: post-processing must converge them.
        _write_tone(Path(path), framerate=16000 if s.qwen_tts_clone_enabled else 44100)

    monkeypatch.setattr(ctp.tts, "_synthesize", synth_tone)
    monkeypatch.setattr(ctp.tts, "_run_ffmpeg", _REAL_RUN_FFMPEG)  # harness faked it; put the binary back
    run_dir = _run(harness, monkeypatch)

    fmts = []
    for label in ("A", "B"):
        final = run_dir / "listen" / f"{label}.wav"
        with wave.open(str(final), "rb") as w:
            fmts.append((w.getframerate(), w.getnchannels(), w.getsampwidth()))
            assert w.getnframes() > 0, f"{label}.wav is empty"
        assert 0.75 < ctp.tts._wav_duration(final) < 0.92, "atempo=1.2 must shorten the 1.0s tone"
    assert fmts[0] == fmts[1] == (24000, 1, 2), "blinding requires one identical output format"


# ── Failure paths the stubbed suite never exercised ─────────────────────────

def test_ffmpeg_failure_aborts_with_no_partial_package(harness, monkeypatch):
    async def failing_ffmpeg(*args):
        return 1, "Error initializing filter 'atempo'"

    monkeypatch.setattr(ctp.tts, "_run_ffmpeg", failing_ffmpeg)
    monkeypatch.setattr(sys, "argv", ["x", "--text-file", str(harness.text_file), "--seed", "7"])
    with pytest.raises(RuntimeError, match="ffmpeg post-process failed"):
        asyncio.run(ctp.main())
    root = harness.tmp_path / "tts-provider-comparison"
    assert not root.exists() or not any(root.iterdir())


def test_unreadable_final_audio_fails_instead_of_shipping(harness, monkeypatch):
    """`.wav` is an extension, not a guarantee -- a package Jay cannot play must not exist."""
    async def bogus_ffmpeg(*args):
        Path(args[-1]).write_bytes(b"not a wav at all")
        return 0, ""

    monkeypatch.setattr(ctp.tts, "_run_ffmpeg", bogus_ffmpeg)
    monkeypatch.setattr(sys, "argv", ["x", "--text-file", str(harness.text_file), "--seed", "7"])
    # tts._wav_duration owns the "not a readable WAV" contract; a bare wave.Error here
    # would mean the helper validated the file behind that contract's back.
    with pytest.raises(ValueError, match="not a readable WAV"):
        asyncio.run(ctp.main())
    root = harness.tmp_path / "tts-provider-comparison"
    assert not root.exists() or not any(root.iterdir()), "no partial package after a bad render"


def test_preflight_failure_writes_nothing_at_all(harness, monkeypatch, tmp_path):
    monkeypatch.setattr(ctp, "Settings", lambda: _settings(tmp_path, qwen_tts_api_key=""))
    monkeypatch.setattr(sys, "argv", ["x", "--text-file", str(harness.text_file)])
    with pytest.raises(RuntimeError, match="preflight failed"):
        asyncio.run(ctp.main())
    assert not (tmp_path / "tts-provider-comparison").exists(), "credentials are checked before any mkdir"


# ── Package layout, reproducibility, text fidelity ──────────────────────────

def test_listening_dir_holds_only_neutral_files(harness, monkeypatch):
    run_dir = _run(harness, monkeypatch)
    assert sorted(p.name for p in (run_dir / "listen").iterdir()) == ["A.wav", "B.wav", "scorecard.md"]
    assert (run_dir / "reveal").is_dir(), "the reveal must be a sibling, not inside listen/"


def test_nothing_outside_reveal_can_identify_an_engine(harness, monkeypatch):
    """reveal/ is the one directory the listener is told not to open. Provider-named
    raw originals anywhere else are a second reveal -- playable, and their duration is
    just the blind file's x the speed factor."""
    run_dir = _run(harness, monkeypatch)
    outside = [p.relative_to(run_dir) for p in run_dir.rglob("*")
               if p.is_file() and p.relative_to(run_dir).parts[0] != "reveal"]
    assert sorted(map(str, outside)) == [
        "listen/A.wav", "listen/B.wav", "listen/scorecard.md", "manifest.json"]
    for rel in outside:
        assert "qwen" not in str(rel), f"{rel} names its engine outside reveal/"
    # manifest.json legitimately names both engines; a separate test proves it cannot
    # be joined back to a label. Playable audio has no such defence, so it must not
    # exist outside reveal/.
    assert not [rel for rel in outside if rel.suffix == ".wav" and rel.parts[0] != "listen"]


def test_manifest_never_pairs_a_label_with_a_candidate(harness, monkeypatch):
    """Label-keyed `outputs` and candidate-keyed `candidates` must not be joinable."""
    run_dir = _run(harness, monkeypatch)
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert sorted(m["outputs"]) == ["A", "B"]
    assert sorted(m["candidates"]) == ["qwen-clone", "qwen-stock"]
    assert "qwen" not in json.dumps(m["outputs"]), "output entries must not name their engine"
    for entry in m["candidates"].values():
        assert not ({"A", "B"} & set(json.dumps(entry))), "candidate entries must not carry a blind label"


def test_cli_seed_determines_the_mapping(harness, monkeypatch):
    """The seed is the reproduction handle for the whole experiment. Six seeds, because
    with two candidates a single ignored-seed run still matches by coin flip."""
    import random
    for seed in range(6):
        monkeypatch.setattr(sys, "argv", [
            "x", "--text-file", str(harness.text_file), "--seed", str(seed)])
        assert asyncio.run(ctp.main()) == 0
        root = harness.tmp_path / "tts-provider-comparison"
        actual = json.loads((next(root.iterdir()) / "reveal" / "mapping.json").read_text())
        shutil.rmtree(root)

        names = ["qwen-clone", "qwen-stock"]
        random.Random(seed).shuffle(names)
        assert actual == {"A": names[0], "B": names[1]}, f"seed {seed} did not drive the mapping"


def test_out_root_override_is_honored_and_leaves_story_5_21_evidence_alone(harness, monkeypatch, tmp_path):
    """AC4: the helper writes its own run dir and must not touch `workspace/voice-ab/`."""
    stale = tmp_path / "voice-ab"
    stale.mkdir()
    (stale / "clone.wav").write_bytes(b"story-5.21-evidence")
    elsewhere = tmp_path / "elsewhere"

    monkeypatch.setattr(sys, "argv", [
        "x", "--text-file", str(harness.text_file), "--seed", "7", "--out-root", str(elsewhere)])
    assert asyncio.run(ctp.main()) == 0
    assert (next(elsewhere.iterdir()) / "manifest.json").is_file()
    assert not (tmp_path / "tts-provider-comparison").exists(), "--out-root must replace the default root"
    assert (stale / "clone.wav").read_bytes() == b"story-5.21-evidence"


def test_source_text_reaches_the_provider_byte_for_byte(harness, monkeypatch):
    """No strip/normalize: whitespace and newlines are part of the frozen scene."""
    import hashlib
    quirky = "  들여쓰기가 있는 문장,\n두 번째 줄. 에스씨피-096.  "
    harness.text_file.write_text(quirky, encoding="utf-8")
    run_dir = _run(harness, monkeypatch)
    assert {c["text"] for c in harness.calls["synth"]} == {quirky}
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert m["text"] == quirky
    assert m["text_sha256"] == hashlib.sha256(quirky.encode("utf-8")).hexdigest()
    assert m["text_bytes"] == len(quirky.encode("utf-8"))
