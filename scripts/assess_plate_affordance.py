"""Score every location plate for whether a character can plausibly stand in it.

Why this exists: the recompose pass (Epic 10 "확정 방향") hands placement to the image
model, and on 2026-08-09 one plate out of five broke it — `scene_001_S00104`, a head-on
close-up of a hatch with almost no floor. Asked to stand a figure there, the model has no
plausible spot, so it re-frames the whole room instead. The plate survives everywhere the
policy says it must not change.

This is a named problem, not a local quirk: **Object Placement Assessment** (OPA, BCMI).
The research standard evaluates *where an object can plausibly go* as a step BEFORE
insertion, rather than inserting and judging the result. FOPA does it discriminatively;
Text2Place and "Putting People in Their Place" (CVPR 2023) do the human-specific version.
We start with the VLM already wired for plate curation instead of adding a model: if its
verdicts separate the known-good plates from the known-bad one, no new dependency is needed.

Two pixel heuristics were tried first and BOTH failed, which is why this asks a VLM:

* `compositing_service.ground_plane()` — returns None when no floor is readable. Measured
  against the five recomposed shots it was **anti-correlated**: the best result (S00101)
  scored "no floor" and the only failure (S00104) scored a clean 0.970. It reads the depth
  map's brightness gradient, i.e. "is there a receding surface", not "can someone stand".
* edge-map drift between plate and recompose output — ranked the failure last on all three
  metrics but the margin to the worst success was 0.012 on structure retention. One failure
  case cannot support a threshold; that would be fitting the threshold to the sample.

Offline curation, same posture as `label_location_plates.py`: a module constant prompt, not
a Langfuse runtime prompt. Writes a JSON report; changes no asset state.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt_flow.config import Settings  # noqa: E402
from yt_flow.services.character_service import _DASHSCOPE_VISION_ENDPOINT  # noqa: E402
from yt_flow.domain.png import dimensions  # noqa: E402

# ponytail: module constant, not a Langfuse prompt — offline curation, not runtime.
PROMPT = """You are assessing whether a background plate can accept a standing human figure.

Answer ONLY about the room as photographed. Do not imagine changing the camera.

Reply with strict JSON, no prose:
{
  "standing_room": true/false,     // is there visible floor a full-body adult could stand on?
  "floor_fraction": 0.0-1.0,       // roughly how much of the frame is usable standing floor
  "camera_distance": "close-up" | "medium" | "wide",
  "best_spot": "left" | "center" | "right" | "none",
  "reason": "one short sentence"
}

standing_room is false when the frame is a close-up of an object or surface with no floor,
or when the only floor is too small/occluded for a whole person."""


async def assess(settings: Settings, image_path: Path, client: httpx.AsyncClient) -> dict:
    import base64

    b64 = base64.b64encode(image_path.read_bytes()).decode()
    resp = await client.post(
        _DASHSCOPE_VISION_ENDPOINT,
        headers={"Authorization": f"Bearer {settings.character_vision_api_key}"},
        json={
            "model": settings.character_vision_model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": PROMPT},
            ]}],
            "max_tokens": settings.character_vision_max_tokens,
        },
        timeout=120,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"no JSON in verdict: {text[:200]}")
    return json.loads(text[start:end + 1])


async def run(args) -> int:
    settings = Settings()
    if not settings.character_vision_api_key:
        print("YTFLOW_CHARACTER_VISION_API_KEY is not set", file=sys.stderr)
        return 2
    targets = sorted(Path(p) for p in args.images) if args.images else \
        sorted(Path(settings.assets_path).glob("locations/**/*.png"))
    if not targets:
        print("no plates found", file=sys.stderr)
        return 2

    out: list[dict] = []
    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient() as client:
        async def one(p: Path) -> None:
            async with sem:
                try:
                    v = await assess(settings, p, client)
                    v["path"] = str(p)
                    v["size"] = dimensions(p.read_bytes())
                except Exception as exc:  # noqa: BLE001 — one bad plate must not stop the sweep
                    v = {"path": str(p), "error": f"{type(exc).__name__}: {exc}"[:200]}
                out.append(v)
                mark = "?" if "error" in v else ("OK " if v.get("standing_room") else "NO ")
                print(f"  {mark} {p.name:<44} {v.get('reason', v.get('error', ''))[:70]}", flush=True)

        await asyncio.gather(*(one(p) for p in targets))

    ok = [v for v in out if v.get("standing_room") is True]
    no = [v for v in out if v.get("standing_room") is False]
    err = [v for v in out if "error" in v]
    print(f"\n총 {len(out)}장 — 배치가능 {len(ok)} / 불가 {len(no)} / 오류 {len(err)}")
    Path(args.report).write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"report: {args.report}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Assess plates for standing-figure affordance (OPA).")
    p.add_argument("--images", nargs="*", help="specific images; default = every approved location plate")
    p.add_argument("--report", default="plate_affordance.json")
    p.add_argument("--concurrency", type=int, default=4)
    return p


def main(argv=None) -> int:
    return asyncio.run(run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
