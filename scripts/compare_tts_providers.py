"""Generate a blind TTS listening package for one frozen scene (Story 12.5).

Renders the SAME frozen narration through each configured candidate, applies the
SAME post-processing to all of them, and writes neutrally-named files plus a
hidden mapping so the listener cannot tell which engine made which file.

    uv run python scripts/compare_tts_providers.py --dry-run   # plan only, zero network
    uv run python scripts/compare_tts_providers.py             # live, billed DashScope calls

Candidates are Qwen **stock** and Qwen **clone** only. Naver CLOVA Voice was
evaluated and excluded on 2026-08-07: its usage policy forbids downloading,
saving, editing or reusing generated files ("파일 다운로드 | X"; "반드시 실시간
API 호출 방식으로 이용해야 합니다") and directs CLOVA Dubbing for saved/editable
content -- which is exactly what this pipeline does. See AC1 `naver-ineligible`
in the story. Do not add a Naver candidate here without a recorded eligibility
change.
"""

import argparse
import asyncio
import hashlib
import json
import random
import shutil
import sys
import wave
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from yt_flow.config import Settings  # noqa: E402
from yt_flow.pipeline.nodes import tts  # noqa: E402

_DEFAULT_TEXT = Path("data/tts-comparison/scene.txt")

# Output format pinned identically for every candidate so format/volume cannot
# reveal the provider. EBU R128 loudnorm one-pass: good enough to equalise
# perceived volume between two engines, and deterministic per input file.
# ponytail: one-pass loudnorm, upgrade to two-pass only if a candidate clips.
_LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
_SAMPLE_RATE = "24000"
_CHANNELS = "1"


def _candidates(s: Settings) -> dict[str, Settings]:
    """Force each voice mode explicitly rather than trusting ambient .env state."""
    return {
        "qwen-stock": s.model_copy(update={"qwen_tts_clone_enabled": False}),
        "qwen-clone": s.model_copy(update={"qwen_tts_clone_enabled": True}),
    }


def _preflight(candidates: dict[str, Settings]) -> None:
    """Fail before any billed call. Reports *which* setting is missing, never its value."""
    missing = []
    for name, cs in candidates.items():
        if not cs.qwen_tts_api_key:
            missing.append(f"{name}: YTFLOW_QWEN_TTS_API_KEY is empty")
        if cs.qwen_tts_clone_enabled and not cs.qwen_tts_clone_voice_id.strip():
            missing.append(f"{name}: YTFLOW_QWEN_TTS_CLONE_VOICE_ID is empty -- run scripts/seed_voice_clone.py")
    if missing:
        raise RuntimeError("preflight failed:\n  " + "\n  ".join(missing))


async def _post_process(src: Path, dest: Path, speed: float) -> None:
    returncode, stderr = await tts._run_ffmpeg(
        "-y", "-i", str(src),
        "-filter:a", f"atempo={speed:g},{_LOUDNORM}",
        "-ar", _SAMPLE_RATE, "-ac", _CHANNELS, "-c:a", "pcm_s16le",
        str(dest),
    )
    if returncode != 0:
        raise RuntimeError(f"ffmpeg post-process failed ({returncode}): {stderr[-500:]}")


def _wav_format(path: Path) -> dict[str, int]:
    with wave.open(str(path), "rb") as w:
        return {"framerate": w.getframerate(), "channels": w.getnchannels(), "sampwidth": w.getsampwidth()}


def _scorecard(labels: list[str]) -> str:
    axes = [
        "Korean naturalness / 한국어 자연스러움",
        "Normalization-sensitive tokens (에스씨피-096, 이점삼팔 미터)",
        "Prosody & breathing / 억양·호흡",
        "Pace / 속도감",
        "Voice fit for SCP documentary-horror",
        "Artifacts & noise / 잡음·아티팩트",
    ]
    header = "| Axis (1-5) | " + " | ".join(labels) + " |"
    sep = "|---" * (len(labels) + 1) + "|"
    rows = "\n".join(f"| {a} | " + " | ".join("" for _ in labels) + " |" for a in axes)
    return f"""# TTS blind listening scorecard (Story 12.5)

Listen to every file in this directory before scoring. Do **not** open
`../reveal/mapping.json` until the table and the verdict below are filled in.

{header}
{sep}
{rows}

## Free-form notes

-

## Overall preference

Preferred file: `?.wav`

## Verdict

Exactly one of: `qwen-stock` | `qwen-clone` | `naver` | `inconclusive`
(`naver` is unavailable -- excluded by the AC1 `naver-ineligible` policy verdict.)
Do not force a winner on a tie or low confidence; `inconclusive` is a valid result.

- verdict:
- by:
- date:
- reason:
"""


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text-file", type=Path, default=_DEFAULT_TEXT, help="frozen narration (UTF-8, byte-for-byte)")
    ap.add_argument("--source", default="run 53bceeaf-eed5-443b-b185-34d8b8522055 (SCP-096) scene 4 narration",
                    help="provenance of the frozen text, recorded in the manifest")
    ap.add_argument("--out-root", type=Path, default=None, help="default: <workspace>/tts-provider-comparison")
    ap.add_argument("--seed", type=int, default=None, help="pin the blind label shuffle (tests/reproduction)")
    ap.add_argument("--dry-run", action="store_true", help="write the plan only; makes no network or ffmpeg calls")
    args = ap.parse_args()

    text = args.text_file.read_text(encoding="utf-8")
    settings = Settings()
    candidates = _candidates(settings)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_root = args.out_root or Path(settings.workspace_path) / "tts-provider-comparison"
    run_dir = out_root / stamp

    names = sorted(candidates)
    labels = [chr(ord("A") + i) for i in range(len(names))]
    shuffled = list(names)
    random.Random(args.seed).shuffle(shuffled)
    mapping = dict(zip(labels, shuffled, strict=True))  # label -> candidate

    manifest = {
        "story": "12.5",
        "generated_at": stamp,
        "source": args.source,
        "text": text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text_bytes": len(text.encode("utf-8")),
        "tts_normalize_provenance": (
            "prompts/scenario/tts_normalize.md -- normalization rules unchanged since bac6f2b "
            "(Story 5.4, 2026-07-04); 342d6af (2026-07-11) changed only the output format JSON->YAML"
        ),
        "speed_factor": settings.qwen_tts_speed,
        "post_process": f"ffmpeg -filter:a atempo={settings.qwen_tts_speed:g},{_LOUDNORM} "
                        f"-ar {_SAMPLE_RATE} -ac {_CHANNELS} -c:a pcm_s16le",
        "candidates": {
            name: {
                "provider": "qwen-dashscope",
                "model": cs.qwen_tts_clone_model if cs.qwen_tts_clone_enabled else cs.qwen_tts_model,
                "voice_mode": "clone" if cs.qwen_tts_clone_enabled else "stock",
                # Stock voice name is a public identifier; the clone voice id is account-scoped -> redacted.
                "voice": "<redacted:clone-voice-id>" if cs.qwen_tts_clone_enabled else cs.qwen_tts_voice,
                "endpoint": cs.qwen_tts_endpoint,
            }
            for name, cs in candidates.items()
        },
        "excluded": {
            "naver-clova-voice": "naver-ineligible (2026-08-07): usage policy forbids saving/editing/"
                                 "reusing generated files and requires real-time API use only"
        },
        "blind_labels": labels,  # mapping itself lives in reveal/mapping.json
    }

    if args.dry_run:
        print(json.dumps({**manifest, "dry_run": True}, ensure_ascii=False, indent=2))
        return 0

    _preflight(candidates)
    # Everything that can name an engine lives under reveal/. Provider-named raw
    # originals as a sibling of listen/ would be a second, unguarded reveal: they
    # are playable, and raw duration is just final x speed.
    (run_dir / "reveal" / "raw").mkdir(parents=True, exist_ok=True)
    (run_dir / "listen").mkdir(exist_ok=True)
    try:
        formats = {}
        for label, name in mapping.items():
            raw = run_dir / "reveal" / "raw" / f"{name}.wav"
            final = run_dir / "listen" / f"{label}.wav"
            await tts._synthesize(text, candidates[name], raw)
            await _post_process(raw, final, settings.qwen_tts_speed)
            # _wav_duration first: it turns a non-WAV render into a readable error
            # instead of a bare wave.Error. [tts.py contract]
            duration = round(tts._wav_duration(final), 3)
            formats[label] = {**_wav_format(final), "duration_sec": duration}
            # Never print the label->candidate pair: the operator generating the package is
            # usually also the listener, and a terminal scrollback is not a blind test.
            print(f"  {label}.wav  ready  ({formats[label]['duration_sec']}s)")

        distinct = {tuple(sorted((k, v) for k, v in f.items() if k != "duration_sec")) for f in formats.values()}
        if len(distinct) > 1:
            raise RuntimeError(f"candidates differ in output format, blinding is broken: {formats}")

        manifest["outputs"] = formats
        (run_dir / "reveal" / "mapping.json").write_text(
            json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
        (run_dir / "listen" / "scorecard.md").write_text(_scorecard(labels), encoding="utf-8")
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        # No misleading partial package: a half-generated comparison is worse than none.
        shutil.rmtree(run_dir, ignore_errors=True)
        raise

    print(f"\nListening package: {run_dir / 'listen'}\nManifest: {run_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
