"""Concatenate one arm's per-scene WAVs into a single mp3, plus the script as text.

Nothing here is a measurement — ``measure_script.py`` and ``count_devices.py`` own
every number in ``ablation.md``. This exists so a human can listen to an arm end to
end instead of opening eight WAVs, and read along with the 어절/seconds of each scene.
It is committed because the mp3 and txt are not: they are regenerable from
``<arm>_scenes.json`` + ``<arm>_durations.json`` + the gitignored WAVs by re-running
this, which is exactly the deal the directory's ``.gitignore`` header describes.

    uv run python _bmad-output/implementation-artifacts/12-6-live-validation/make_listening_copy.py \
        --scenes armA_scenes.json --durations armA_durations.json \
        --title "12.6 ablation arm A 나레이션" --out 12-6-armA-narration

Encoding matches the existing ``12-6-after-narration.mp3`` (mono 24 kHz, 160 kbps CBR)
so the three tracks are comparable by ear rather than by codec.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenes", required=True)
    parser.add_argument("--durations", required=True, help="run_after_tts.py's output — has audio_dir")
    parser.add_argument("--title", required=True)
    parser.add_argument("--out", required=True, help="path stem; .mp3 and .txt are written")
    args = parser.parse_args()

    here = Path(args.scenes).resolve().parent
    doc = json.loads(Path(args.scenes).read_text(encoding="utf-8"))
    measured = json.loads(Path(args.durations).read_text(encoding="utf-8"))
    seconds = {int(num): sec for num, sec in measured["audio_duration_sec"].items()}
    audio_dir = Path(measured["audio_dir"])
    stem = Path(args.out)
    if not stem.is_absolute():
        stem = here / stem

    wavs = [audio_dir / f"scene_{scene['scene_num']:03d}.wav" for scene in doc["scenes"]]
    missing = [str(wav) for wav in wavs if not wav.exists()]
    if missing:
        raise SystemExit(f"missing WAVs (re-run run_after_tts.py): {missing}")

    listing = stem.with_suffix(".concat.txt")
    listing.write_text("".join(f"file '{wav}'\n" for wav in wavs), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c:a", "libmp3lame", "-b:a", "160k", "-ar", "24000", "-ac", "1", str(stem.with_suffix(".mp3"))],
        check=True,
    )
    listing.unlink()

    total_words = sum(len((scene.get("narration") or "").split()) for scene in doc["scenes"])
    total_sec = sum(seconds.values())
    lines = [
        f"# {args.title} ({doc.get('scp_id')}, {total_words}어절 / "
        f"{round(total_sec) // 60}분{round(total_sec) % 60}초)",
        "",
    ]
    for scene in doc["scenes"]:
        num = scene["scene_num"]
        words = len((scene.get("narration") or "").split())
        lines += [f"## 씬 {num} — {words}어절 / {seconds.get(num, 0):.1f}s", "", scene["narration"], ""]
    stem.with_suffix(".txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {stem.with_suffix('.mp3')} ({total_sec:.1f}s) and {stem.with_suffix('.txt')}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
