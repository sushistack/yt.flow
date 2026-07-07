import importlib.util
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
