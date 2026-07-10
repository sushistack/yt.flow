import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_script():
    spec = importlib.util.spec_from_file_location("seed_voice_clone", "scripts/seed_voice_clone.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _settings(tmp_path):
    return SimpleNamespace(
        qwen_tts_api_key="sk-test",
        qwen_tts_endpoint="https://dashscope-intl.aliyuncs.com",
        qwen_tts_clone_model="qwen3-tts-vc-2026-01-22",
        qwen_tts_clone_voice_path=str(tmp_path / "sutak.mp3"),
    )


def test_dry_run_payload_does_not_read_audio(tmp_path):
    seed = _load_script()
    s = _settings(tmp_path)

    payload = seed._create_payload(s, include_audio=False)

    assert payload["input"]["audio"]["data"] == "<base64 audio elided>"


def test_find_existing_matches_preferred_name_field(tmp_path):
    seed = _load_script()
    voices = [
        {"voice": "provider-id-without-name", "target_model": "qwen3-tts-vc-2026-01-22",
         "preferred_name": "sutak"},
    ]

    assert seed._find_existing(voices, "qwen3-tts-vc-2026-01-22") == "provider-id-without-name"


def test_list_voices_continues_full_pages_without_total_count(tmp_path):
    seed = _load_script()
    s = _settings(tmp_path)

    class Response:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

    class Client:
        def __init__(self):
            self.calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return Response({"output": {"page_size": 1, "voice_list": [{"voice": "first"}]}})
            return Response({"output": {"page_size": 1, "voice_list": []}})

    client = Client()
    assert seed._list_voices(client, s) == [{"voice": "first"}]
    assert client.calls == 2


@pytest.mark.parametrize("path_kind", ["directory", "empty_file"])
def test_audio_data_uri_rejects_unusable_sample(tmp_path, path_kind):
    seed = _load_script()
    path = tmp_path / "sample.mp3"
    if path_kind == "directory":
        path.mkdir()
        message = "not a file"
    else:
        path.write_bytes(b"")
        message = "empty"

    with pytest.raises(ValueError, match=message):
        seed._audio_data_uri(path)


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def _fake_client_factory(voices, calls):
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, headers=None, json=None):
            calls.append(json)
            action = json["input"]["action"]
            if action == "list":
                return _FakeResponse({"output": {"voice_list": voices}})
            if action == "delete":
                return _FakeResponse({"output": {}})
            return _FakeResponse({"output": {"voice": "new-voice-id"}})

    return lambda *a, **kw: FakeClient()


def _actions(calls):
    return [c["input"]["action"] for c in calls]


def _wire_main(monkeypatch, seed, tmp_path, voices):
    s = _settings(tmp_path)
    Path(s.qwen_tts_clone_voice_path).write_bytes(b"fake-audio-bytes")
    monkeypatch.setattr(seed, "Settings", lambda: s)
    calls = []
    monkeypatch.setattr(seed.httpx, "Client", _fake_client_factory(voices, calls))
    return calls, s


def test_main_force_with_existing_deletes_then_creates(tmp_path, monkeypatch, capsys):
    seed = _load_script()
    voices = [{"voice": "old-id", "preferred_name": "sutak", "target_model": "qwen3-tts-vc-2026-01-22"}]
    calls, _ = _wire_main(monkeypatch, seed, tmp_path, voices)

    seed.main(["--force"])

    assert _actions(calls) == ["list", "delete", "create"]
    out = capsys.readouterr().out
    assert "deleted voice_id=old-id" in out
    assert "voice_id=new-voice-id" in out


def test_force_delete_payload_targets_exact_existing_voice(tmp_path, monkeypatch):
    seed = _load_script()
    voices = [{"voice": "old-id", "preferred_name": "sutak", "target_model": "qwen3-tts-vc-2026-01-22"}]
    calls, _ = _wire_main(monkeypatch, seed, tmp_path, voices)

    seed.main(["--force"])

    delete_call = calls[_actions(calls).index("delete")]
    assert delete_call == {"model": "qwen-voice-enrollment", "input": {"action": "delete", "voice": "old-id"}}


def test_main_force_without_existing_only_creates(tmp_path, monkeypatch):
    seed = _load_script()
    calls, _ = _wire_main(monkeypatch, seed, tmp_path, voices=[])

    seed.main(["--force"])

    assert _actions(calls) == ["list", "create"]


def test_main_plain_run_unchanged(tmp_path, monkeypatch, capsys):
    seed = _load_script()
    voices = [{"voice": "old-id", "preferred_name": "sutak", "target_model": "qwen3-tts-vc-2026-01-22"}]
    calls, _ = _wire_main(monkeypatch, seed, tmp_path, voices)

    seed.main([])

    assert _actions(calls) == ["list"]
    assert "voice_id=old-id" in capsys.readouterr().out


def test_force_create_failure_after_delete_warns_before_raising(tmp_path, monkeypatch, capsys):
    seed = _load_script()
    voices = [{"voice": "old-id", "preferred_name": "sutak", "target_model": "qwen3-tts-vc-2026-01-22"}]
    s = _settings(tmp_path)
    Path(s.qwen_tts_clone_voice_path).write_bytes(b"fake-audio-bytes")
    monkeypatch.setattr(seed, "Settings", lambda: s)

    class _Response:
        def __init__(self, data, fail=False):
            self._data = data
            self._fail = fail

        def raise_for_status(self):
            if self._fail:
                request = seed.httpx.Request("POST", "https://example.test")
                response = seed.httpx.Response(500, request=request)
                raise seed.httpx.HTTPStatusError("server error", request=request, response=response)

        def json(self):
            return self._data

    class FailingClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, headers=None, json=None):
            action = json["input"]["action"]
            if action == "list":
                return _Response({"output": {"voice_list": voices}})
            if action == "delete":
                return _Response({"output": {}})
            return _Response({}, fail=True)

    monkeypatch.setattr(seed.httpx, "Client", lambda *a, **kw: FailingClient())

    with pytest.raises(seed.httpx.HTTPStatusError):
        seed.main(["--force"])

    err = capsys.readouterr().err
    assert "deleted voice_id=old-id" in err
    assert "re-run --force to retry" in err


def test_dry_run_force_prints_delete_target_and_no_network(tmp_path, monkeypatch, capsys):
    seed = _load_script()
    s = _settings(tmp_path)
    monkeypatch.setattr(seed, "Settings", lambda: s)

    def _boom(*a, **kw):
        raise AssertionError("dry-run must not open a network client")

    monkeypatch.setattr(seed.httpx, "Client", _boom)

    seed.main(["--dry-run", "--force"])

    out = capsys.readouterr().out
    assert "would delete" in out
    assert "sutak" in out
    assert "<base64 audio elided>" in out
