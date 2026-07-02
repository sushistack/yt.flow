"""Deterministic fakes for the four external seams (B-2).

- ``fake_run_ffmpeg``       — replaces ``video._run_ffmpeg`` (subprocess seam)
- ``fake_submit_and_fetch`` / ``fake_submit_and_fetch_outputs`` — ComfyUI HTTP seam
- ``fake_synthesize``       — replaces ``tts._synthesize`` (Qwen HTTP seam)
- ``deepseek_from_cassette``/``qwen_payload_from_cassette`` — recorded-shape playback

None of these touch the network or a subprocess. The ffmpeg / synth fakes write
tiny real files so downstream file-existence checks pass.
"""

import json
import wave
from pathlib import Path

CASSETTE_DIR = Path(__file__).parent.parent / "fixtures" / "cassettes"

# Smallest valid 1x1 transparent PNG (67 bytes) — enough for any "image bytes" seam.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000100" "05fe02fe" "dccc59e70000000049454e44ae426082"
)


def load_cassette(name: str) -> dict:
    """Load a recorded response-shape cassette by filename (e.g. 'deepseek_scenario.json')."""
    return json.loads((CASSETTE_DIR / name).read_text(encoding="utf-8"))


# ── video._run_ffmpeg ───────────────────────────────────────────────────────
async def fake_run_ffmpeg(*args: str) -> tuple[int, str]:
    """No-op ffmpeg: write a 1-byte file to the output path (always the last arg)."""
    Path(args[-1]).write_bytes(b"\x00")
    return 0, ""


# ── services.comfyui_client ─────────────────────────────────────────────────
async def fake_submit_and_fetch(base_url, workflow, **kwargs) -> bytes:
    return TINY_PNG


async def fake_submit_and_fetch_outputs(base_url, workflow, output_node_ids, **kwargs) -> dict:
    return {node_id: TINY_PNG for node_id in output_node_ids}


# ── tts._synthesize ─────────────────────────────────────────────────────────
async def fake_synthesize(text: str, s, path: Path) -> None:
    """Write a tiny valid mono WAV instead of calling Qwen + downloading audio."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)  # 1 second of silence


# ── scenario._call_deepseek (cassette playback) ─────────────────────────────
def deepseek_from_cassette(name: str = "deepseek_scenario.json"):
    """Return an async fake matching ``_call_deepseek(rendered, s) -> (content, usage, finish_reason)``."""
    data = load_cassette(name)
    choice = data["choices"][0]

    async def fake(rendered, s):
        return choice["message"]["content"], data.get("usage", {}), choice.get("finish_reason")

    return fake
