"""Enroll the local Qwen TTS voice clone sample and print the .env line.

Usage:
    uv run python scripts/seed_voice_clone.py            # list first, create if missing
    uv run python scripts/seed_voice_clone.py --dry-run  # print create payload, no writes
"""

import argparse
import base64
import mimetypes
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from yt_flow.config import Settings  # noqa: E402

_CUSTOMIZATION_PATH = "/api/v1/services/audio/tts/customization"
_ENROLLMENT_MODEL = "qwen-voice-enrollment"
_PREFERRED_NAME = "sutak"
_MAX_SAMPLE_BYTES = 10 * 1024 * 1024


def _endpoint(s: Settings) -> str:
    return f"{s.qwen_tts_endpoint.rstrip('/')}{_CUSTOMIZATION_PATH}"


def _auth_headers(s: Settings) -> dict[str, str]:
    if not s.qwen_tts_api_key:
        raise RuntimeError("YTFLOW_QWEN_TTS_API_KEY is not configured")
    return {"Authorization": f"Bearer {s.qwen_tts_api_key}", "Content-Type": "application/json"}


def _voices_from_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    output = data.get("output", {})
    for key in ("voice_list", "voices", "data"):
        voices = output.get(key)
        if isinstance(voices, list):
            return [v for v in voices if isinstance(v, dict)]
    return []


def _voice_id(voice: dict[str, Any]) -> str:
    for key in ("voice", "voice_id", "id"):
        value = voice.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _target_model(voice: dict[str, Any]) -> str:
    value = voice.get("target_model") or voice.get("model")
    return value if isinstance(value, str) else ""


def _voice_name(voice: dict[str, Any]) -> str:
    for key in ("preferred_name", "name", "voice_name"):
        value = voice.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _find_existing(voices: list[dict[str, Any]], target_model: str) -> str:
    for voice in voices:
        voice_id = _voice_id(voice)
        name = _voice_name(voice).lower()
        is_sutak = _PREFERRED_NAME in voice_id.lower() or name == _PREFERRED_NAME
        if is_sutak and _target_model(voice) == target_model:
            return voice_id
    return ""


def _list_voices(client: httpx.Client, s: Settings) -> list[dict[str, Any]]:
    voices: list[dict[str, Any]] = []
    page_index = 0
    while True:
        payload = {
            "model": _ENROLLMENT_MODEL,
            "input": {
                "action": "list",
                "target_model": s.qwen_tts_clone_model,
                "page_index": page_index,
                "page_size": 100,
            },
        }
        resp = client.post(_endpoint(s), headers=_auth_headers(s), json=payload)
        resp.raise_for_status()
        data = resp.json()
        page = _voices_from_response(data)
        voices.extend(page)
        output = data.get("output", {})
        total_count = output.get("total_count")
        page_size = output.get("page_size")
        page_size = page_size if isinstance(page_size, int) and page_size > 0 else 100
        if not page or (isinstance(total_count, int) and len(voices) >= total_count):
            break
        if not isinstance(total_count, int) and len(page) < page_size:
            break
        page_index += 1
    return voices


def _audio_data_uri(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"voice sample not found: {path}")
    if not path.is_file():
        raise ValueError(f"voice sample is not a file: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"voice sample is empty: {path}")
    if size > _MAX_SAMPLE_BYTES:
        raise ValueError(f"voice sample exceeds 10 MB: {path} ({size} bytes)")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _create_payload(s: Settings, *, include_audio: bool = True) -> dict[str, Any]:
    path = Path(s.qwen_tts_clone_voice_path)
    audio_data = _audio_data_uri(path) if include_audio else "<base64 audio elided>"
    return {
        "model": _ENROLLMENT_MODEL,
        "input": {
            "action": "create",
            "target_model": s.qwen_tts_clone_model,
            "preferred_name": _PREFERRED_NAME,
            "audio": {"data": audio_data},
        },
    }


def _print_voice_id(voice_id: str) -> None:
    print(f"voice_id={voice_id}")
    print(f"YTFLOW_QWEN_TTS_CLONE_VOICE_ID={voice_id}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Enroll the sutak Qwen TTS clone voice.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    s = Settings()
    if args.dry_run:
        print(_create_payload(s, include_audio=False))
        return

    with httpx.Client(timeout=httpx.Timeout(120.0)) as client:
        voices = _list_voices(client, s)
        existing = _find_existing(voices, s.qwen_tts_clone_model)
        if existing:
            print("found existing voice; no create call made")
            _print_voice_id(existing)
            return

        resp = client.post(_endpoint(s), headers=_auth_headers(s), json=_create_payload(s))
        resp.raise_for_status()
        data = resp.json()
        voice_id = data.get("output", {}).get("voice")
        if not voice_id:
            raise RuntimeError(f"voice enrollment response missing output.voice: {data!r}")
        print("created voice")
        _print_voice_id(voice_id)


if __name__ == "__main__":
    main()
