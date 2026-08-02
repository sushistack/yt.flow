"""Auto-label draft location plates with Qwen-VL (Story 8.17).

One vision call per draft plate returning a structured verdict. An unambiguous pass
is approved outright; everything else — ambiguous, defective, unparsable reply, or a
failed HTTP call — stays draft, which is already the operator queue
(scripts/approve_location_plate.py with no arguments lists it).

The verdict is always written into the plate's manifest ``source``: ``LocationPlate``
has no label/score column and one advisory dict does not justify a migration.

Reuses Story 5.13's DashScope wiring (endpoint constant + ``character_vision_*``
settings) — same provider, same request shape, no new dependency.
"""

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx  # noqa: E402
from sqlmodel import Session  # noqa: E402

from seed_location_plates import LOCATION_PROMPTS  # noqa: E402
from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.domain.state import LOCATION_KEYS  # noqa: E402
from yt_flow.services.asset_service import AssetService  # noqa: E402
from yt_flow.services.character_service import _DASHSCOPE_VISION_ENDPOINT  # noqa: E402
from yt_flow.services.location_service import LocationService  # noqa: E402

# Closed decision rule. Auto-approval spends no human attention, so it only fires on a
# reply that is explicit about every one of these: a missing or non-boolean field is a
# fail, never a pass. D11-class defects (a figure in the plate) can therefore never be
# auto-approved even if the model is confident about everything else.
REQUIRED_BOOLS = {
    "matches_location": True,
    "has_person": False,
    "has_legible_text": False,
    "has_duplicated_architecture": False,
}
AUTO_APPROVE_QUALITY = ("good",)
MIN_CONFIDENCE = 0.8

# ponytail: a module constant, not a Langfuse prompt. This is an offline curation
# script, not a runtime pipeline prompt, and seeding + promoting a new Langfuse prompt
# needs the operator (the A/B gate is frozen and AI sessions are hard-blocked from it).
LABEL_PROMPT = """You are grading one background plate rendered for an SCP Foundation video.
The plate is supposed to read as: {description}

Reply with a single JSON object and nothing else:
{{"matches_location": true|false, "has_person": true|false, "has_legible_text": true|false,
 "has_duplicated_architecture": true|false, "quality": "good"|"acceptable"|"poor",
 "confidence": 0.0-1.0, "notes": "one short sentence"}}

Field rules:
- has_person: any human, humanoid, creature, figure or silhouette, however small or blurred.
- has_legible_text: any readable signage, label, caption or watermark.
- has_duplicated_architecture: the same doorway, window or corridor repeated or mirrored
  as a rendering artifact rather than as real architecture.
- quality: "good" only if you would ship this frame as a video background unedited.
- confidence: how sure you are of the judgements above."""


def _parse_verdict(text: str) -> dict:
    """Parse the model's reply into a verdict dict; raise on anything else.

    Qwen-VL wraps JSON in ``` fences or prefaces it with prose, so the outermost
    brace pair is sliced out rather than fences being special-cased. Deliberately
    strict: the caller turns every failure here into "stays draft", so a chatty or
    truncated reply can never be mistaken for a pass.
    """
    if "{" not in text or "}" not in text:
        raise ValueError(f"no JSON object in reply: {text[:120]!r}")
    verdict = json.loads(text[text.index("{"):text.rindex("}") + 1])
    if not isinstance(verdict, dict):
        raise ValueError(f"verdict is not an object: {verdict!r}")
    return verdict


def _reject_reason(verdict: dict) -> str | None:
    """``None`` if the verdict is an unambiguous pass, else why it is not."""
    for field, expected in REQUIRED_BOOLS.items():
        value = verdict.get(field)
        if not isinstance(value, bool):
            return f"{field}={value!r} not boolean"
        if value is not expected:
            return f"{field}={value}"
    if verdict.get("quality") not in AUTO_APPROVE_QUALITY:
        return f"quality={verdict.get('quality')!r}"
    confidence = verdict.get("confidence")
    # bool is an int subclass, so `true` would otherwise read as confidence 1.0.
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return f"confidence={confidence!r} not a number"
    if confidence < MIN_CONFIDENCE:
        return f"confidence={confidence}"
    return None


async def score_plate(settings: Settings, image_path: Path, description: str) -> dict:
    """One Qwen-VL call for one plate. Raises on HTTP, decode or parse failure."""
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    content = [
        {"type": "text", "text": LABEL_PROMPT.format(description=description)},
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
    return _parse_verdict(resp.json()["choices"][0]["message"]["content"])


def _record_verdict(asset_service: AssetService, plate, verdict: dict, decision: str) -> bool:
    """Merge the verdict into the plate's manifest entry. False if it has none.

    load/save around the one key rather than ``add_asset``: re-adding would reset
    ``status`` to draft and overwrite created_at/approved_at — exactly the wrong thing
    to do to a plate that is about to be approved.
    """
    key = f"{plate.location_key}/{plate.variant}"
    manifest = asset_service.load_manifest()
    entry = manifest["assets"].get(key)
    if entry is None:
        return False
    entry.setdefault("source", {})["label"] = {**verdict, "decision": decision}
    asset_service.save_manifest(manifest)
    return True


async def run(args) -> int:
    settings = Settings()
    if not settings.character_vision_api_key:
        sys.exit("YTFLOW_CHARACTER_VISION_API_KEY is not set — the labeler needs the Qwen-VL key")
    db.init(f"sqlite:///{settings.db_path}")

    approved = errors = 0
    queue: list[str] = []
    with Session(db._engine) as session:
        service = LocationService(session, settings=settings)
        asset_service = AssetService(settings.assets_path, session)
        plates = service.list_plates(location_key=args.key, status="draft")
        if not plates:
            print("no draft plates to label")
            return 0

        for plate in plates:
            label = f"{plate.location_key} {plate.variant}"
            try:
                verdict = await score_plate(
                    settings,
                    Path(settings.assets_path) / plate.image_path,
                    LOCATION_PROMPTS[plate.location_key],
                )
            except Exception as exc:  # noqa: BLE001 — a failed scorer must never approve
                print(f"draft (scorer failed: {exc}): {label}")
                queue.append(label)
                errors += 1
                continue

            reason = _reject_reason(verdict)
            if not _record_verdict(asset_service, plate, verdict, "draft" if reason else "approved"):
                # No manifest entry means approve_plate would raise anyway (it is
                # manifest-first); leave the plate alone and say so.
                print(f"draft (no manifest entry): {label}")
                queue.append(label)
                errors += 1
                continue
            if reason:
                print(f"draft ({reason}): {label}")
                queue.append(label)
                continue
            service.approve_plate(plate.id)
            approved += 1
            print(f"approved: {label} (confidence {verdict.get('confidence')})")

    print(f"done: {approved} approved, {len(queue)} left draft, {errors} scorer errors")
    for label in queue:
        print(f"operator queue: {label}")
    # Non-zero on a scoring failure only: plates left draft on a clear verdict are the
    # designed outcome, an unscored plate is unfinished work.
    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Auto-label draft location plates with Qwen-VL.")
    parser.add_argument("--key", choices=LOCATION_KEYS, help="Label one location key's drafts instead of all.")
    return parser


def main(argv=None) -> int:
    return asyncio.run(run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
