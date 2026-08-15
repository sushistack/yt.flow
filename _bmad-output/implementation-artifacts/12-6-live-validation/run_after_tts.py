"""Speak the after-run's narrations so AC8's WPM half is measured, not projected.

Story 12.6 Task 5, second half. ``run_after.py`` ran the scenario chain only, so
``after_scenes.json`` carries no ``audio_duration`` and ``measure_script.py``
correctly reported ``wpm: null``. AC8 demands a measured WPM, and WPM is a property
of the *voice* rather than of the script — so the cheapest honest way to close it is
to synthesize those eight narrations and nothing else. No image, no subtitle, no
video, no graph, no second scenario call.

The seam is ``tts_node`` itself, driven with a minimal state. It is already a pure
function of ``PipelineState`` (reads ``scenes`` + ``run_id``, returns changed
fields), and calling it instead of re-driving ``_synthesize`` / ``_apply_speed`` by
hand is what guarantees the duration comes out of the *shipping* path: the same
voice resolution, the same ``atempo`` speed, the same ``_wav_duration`` bounded-frame
fix. A hand-rolled copy would be a second implementation whose drift nobody notices.

Output is a small durations file rather than a second copy of the scenes — one
canonical dump (``after_scenes.json``) stays the only description of this run, and
``measure_script.py --durations-json`` merges the seconds in at read time.

    uv run python _bmad-output/implementation-artifacts/12-6-live-validation/run_after_tts.py \
        --scenes _bmad-output/implementation-artifacts/12-6-live-validation/after_scenes.json \
        --out _bmad-output/implementation-artifacts/12-6-live-validation/after_durations.json

Voice: whatever is configured, recorded into the output — the baseline's 148.2 WPM
came from the *clone* voice (run ``e5ed4b3a``'s WAVs measure ~110-126 Hz median F0
against ``sutak.mp3``'s 131 Hz and stock ``Cherry``'s 247 Hz), so a run of this
script against a stock-voice config would measure a different voice and void the
comparison. Check the printed line before trusting the number.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "src"))

# Set before any Settings() is constructed: a real env var beats the .env file in
# pydantic-settings, so this parks the WAVs beside this file (gitignored, see
# .gitignore) without editing .env. It is the only setting this script overrides,
# and it is not a TTS setting.
os.environ["YTFLOW_WORKSPACE_PATH"] = str(HERE / "tts_audio")

from yt_flow.config import Settings  # noqa: E402
from yt_flow.pipeline.nodes.tts import _voice_config, tts_node  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenes", required=True, help="run_after.py's dump")
    parser.add_argument("--out", required=True, help="per-scene spoken seconds + voice used")
    parser.add_argument("--run-id", default="12-6-after", help="audio subdirectory name")
    args = parser.parse_args()

    doc = json.loads(Path(args.scenes).read_text(encoding="utf-8"))
    settings = Settings()
    if settings.qwen_tts_mock:
        raise SystemExit("YTFLOW_QWEN_TTS_MOCK is on — mock audio is a fabricated duration")
    model, voice, mode = _voice_config(settings, require_voice_id=False)
    print(f"voice: mode={mode} model={model} voice={voice} speed={settings.qwen_tts_speed}",
          file=sys.stderr)

    out = await tts_node({"run_id": args.run_id, "scenes": doc["scenes"]})
    if out.get("error"):
        raise SystemExit(out["error"])

    seconds = {str(scene["scene_num"]): scene["audio_duration"] for scene in out["scenes"]}
    Path(args.out).write_text(
        json.dumps(
            {
                "run_id": args.run_id,
                "source_scenes": Path(args.scenes).name,
                "voice_mode": mode,
                "model": model,
                "voice": voice,
                "speed": settings.qwen_tts_speed,
                "audio_dir": str(Path(settings.workspace_path) / args.run_id / "audio"),
                "audio_duration_sec": seconds,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    total = sum(seconds.values())
    words = sum(len(scene["narration"].split()) for scene in doc["scenes"])
    print(
        f"wrote {args.out}: {len(seconds)} scenes, {total:.2f}s, {words} 어절 "
        f"→ {words / (total / 60):.1f} WPM (measure_script.py is the report)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    asyncio.run(main())
