"""Score rendered composite frames with Qwen-VL (Story 8.16).

Replaces libcom's composite scorer, which is uninstallable here (``libcom`` →
``mmpose`` → ``xtcocotools``, whose sdist ships no Cython C and fails to build on
Python 3.12) and photoreal-trained besides — these cards are flat anime art, so a
photoreal score would not transfer. Same DashScope wiring as
``label_location_plates.py``: one vision call per frame, strict JSON, nothing new
installed.

Frames in, verdicts out. Point it at a rendered video (frames are sampled) or at
PNG frames directly::

    python scripts/score_composites.py workspace/<run>/video/scene_001.mp4
    python scripts/score_composites.py workspace/review/816_live/*.png --json out.json

Exit code is 1 if any frame fails, so it can gate a live-verification task.

Known ceiling, measured 2026-08-03: qwen-vl-plus scored `grounded: 5` on BOTH the
ground-tracked render and a static-anchor render whose feet were 57px off the floor by
the last frame. It catches gross placement failures (a character in mid-air, on a wall,
doll-sized), not tens of pixels of drift — the vision model sees a downscaled frame. Use
it as a regression net over many frames, and measure pixels when the question is
"how far off".
"""

import argparse
import asyncio
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx  # noqa: E402

from yt_flow.config import Settings  # noqa: E402
from yt_flow.services.character_service import _DASHSCOPE_VISION_ENDPOINT  # noqa: E402

# What "placed in the room" decomposes into. Kept as three independent judgements
# rather than one overall score: the whole point of 8.16 is that feet-grounding and
# lighting are separate failures with separate fixes, and an averaged score hides
# which one regressed.
SCORE_FIELDS = ("grounded", "scale_plausible", "lighting_consistent")
MIN_SCORE = 3  # of 5, per field — below this the frame is a fail
MIN_CONFIDENCE = 0.6

# ponytail: a module constant, not a Langfuse prompt — offline QA, not a runtime
# pipeline prompt (same reasoning as label_location_plates.LABEL_PROMPT).
SCORE_PROMPT = """You are grading one frame from an animated SCP Foundation video.
A character illustration has been composited over a rendered background room.

Judge only the compositing, not the art style. The character is deliberately drawn in
a flat anime style over a more rendered background — that difference is intended and
is NOT a defect.

Reply with a single JSON object and nothing else:
{"grounded": 1-5, "scale_plausible": 1-5, "lighting_consistent": 1-5,
 "feet_visible": true|false, "confidence": 0.0-1.0, "notes": "one short sentence"}

Field rules:
- grounded: 5 = the character's feet meet the floor at a believable spot and any
  shadow sits under them; 1 = the character floats, or its feet are on a wall,
  a desk top, or in mid-air.
- scale_plausible: 5 = the character's height is right for how far into the room they
  stand; 1 = giant or doll-sized relative to doorways, chairs and desks.
- lighting_consistent: 5 = the character's brightness and colour temperature match the
  room; 1 = a bright cutout on a dark plate or vice versa.
- feet_visible: false if the feet are cropped by the frame edge or hidden behind an
  object — say so rather than guessing at `grounded`.
- confidence: how sure you are of the judgements above."""


def _parse(text: str) -> dict:
    """Strict JSON slice, same posture as the plate labeller: a chatty or truncated
    reply is an error, never a pass."""
    if "{" not in text or "}" not in text:
        raise ValueError(f"no JSON object in reply: {text[:120]!r}")
    verdict = json.loads(text[text.index("{"):text.rindex("}") + 1])
    if not isinstance(verdict, dict):
        raise ValueError(f"verdict is not an object: {verdict!r}")
    return verdict


def fail_reason(verdict: dict) -> str | None:
    """``None`` if the frame passes, else the first reason it does not."""
    for field in SCORE_FIELDS:
        value = verdict.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{field}={value!r} not a number"
        if value < MIN_SCORE:
            return f"{field}={value}"
    confidence = verdict.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return f"confidence={confidence!r} not a number"
    if confidence < MIN_CONFIDENCE:
        return f"confidence={confidence}"
    return None


async def score_frame(settings: Settings, frame: Path) -> dict:
    """One Qwen-VL call for one frame. Raises on HTTP, decode or parse failure."""
    b64 = base64.b64encode(frame.read_bytes()).decode("ascii")
    content = [
        {"type": "text", "text": SCORE_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        resp = await client.post(
            _DASHSCOPE_VISION_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.character_vision_api_key}"},
            json={
                "model": settings.character_vision_model,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": settings.character_vision_max_tokens,
            },
        )
    resp.raise_for_status()
    return _parse(resp.json()["choices"][0]["message"]["content"])


def extract_frames(video: Path, count: int, out_dir: Path) -> list[Path]:
    """Sample ``count`` frames spread across the clip.

    Spread, not the first N: a static-anchor regression only shows up in the second
    half of a moving shot, which is exactly the defect the ground-tracking expression
    fixes — sampling the head of the clip would have scored it as a pass.
    """
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    duration = float(probe.stdout.strip())
    frames = []
    for i in range(count):
        # Inset from both ends: t=0 can land before the first keyframe and t=duration
        # past the last frame, both of which yield an empty PNG rather than an error.
        t = duration * (i + 0.5) / count
        out = out_dir / f"{video.stem}_t{t:05.2f}.png"
        subprocess.run(["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(video),
                        "-frames:v", "1", str(out)], capture_output=True, check=True)
        if out.exists() and out.stat().st_size:
            frames.append(out)
    return frames


async def run(args) -> int:
    settings = Settings()  # type: ignore[call-arg]
    if not settings.character_vision_api_key:
        sys.exit("YTFLOW_CHARACTER_VISION_API_KEY is not set — the scorer needs the Qwen-VL key")

    with tempfile.TemporaryDirectory() as tmp:
        frames: list[Path] = []
        for target in args.targets:
            path = Path(target)
            if not path.exists():
                print(f"  ✗ {path}: not found")
                return 1
            if path.suffix.lower() in (".mp4", ".mkv", ".mov", ".webm"):
                frames.extend(extract_frames(path, args.frames, Path(tmp)))
            else:
                frames.append(path)

        results, failures = [], 0
        for frame in frames:
            try:
                verdict = await score_frame(settings, frame)
            except Exception as exc:  # noqa: BLE001 — an unscored frame is a failure, not a crash
                print(f"  ✗ {frame.name}: {type(exc).__name__}: {exc}")
                results.append({"frame": str(frame), "error": str(exc)})
                failures += 1
                continue
            reason = fail_reason(verdict)
            scores = " ".join(f"{f}={verdict.get(f)}" for f in SCORE_FIELDS)
            mark = "✓" if reason is None else "✗"
            print(f"  {mark} {frame.name}: {scores} — {verdict.get('notes', '')}"
                  + ("" if reason is None else f"  [FAIL: {reason}]"))
            results.append({"frame": str(frame), "verdict": verdict, "fail_reason": reason})
            failures += reason is not None

    print(f"\n{len(results) - failures}/{len(results)} frames passed"
          f" (min {MIN_SCORE}/5 on {', '.join(SCORE_FIELDS)})")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"verdicts -> {args.json}")
    return 1 if failures else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("targets", nargs="+", help="rendered video(s) and/or PNG frame(s)")
    ap.add_argument("--frames", type=int, default=3, help="frames sampled per video (default 3)")
    ap.add_argument("--json", help="write every verdict to this file")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
