"""Fetch and auto-curate one real structure reference per location plate (Story 8.17).

Why this exists: composition is not prompt-controllable. Three rounds of prompt-only
fixes (style-transfer IPAdapter, per-variant camera wording, per-location room-shape
wording) took "every plate is the same one-point-perspective corridor" from 95% down to
74% and stopped there. The procedural blockout (scripts/room_blockout.py) fixed the
geometry but is a box: it cannot make an autopsy room read differently from a cafeteria.
A real photograph of the actual kind of room carries both — a composition the checkpoint
would not have invented, and the furniture layout that identifies the place.

What this writes, per location key:

    data/refs/locations/<key>/ref_a.png   (one per variant, up to 3)
    data/refs/locations/<key>/refs.json   (source URL + vision verdict per kept ref)

COPYRIGHT: a downloaded photo is somebody's work. It only ever reaches the model as a
preprocessed line-structure map (FakeScribblePreprocessor -> scribble ControlNet, wired
in seed_location_plates.py) — never as an img2img latent, never as an IPAdapter image.
Structure is not expression; the pixels never leave this directory. ``refs.json`` keeps
the source URL so that claim stays auditable.

Curation is one Qwen-VL call per candidate, the same DashScope wiring and the same
"a missing or non-boolean field is a fail" decision rule as
scripts/label_location_plates.py.
"""

import argparse
import asyncio
import base64
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx  # noqa: E402

from label_location_plates import _parse_verdict  # noqa: E402
from seed_location_plates import (  # noqa: E402
    LOCATION_PROMPTS,
    PLATE_RENDER_HEIGHT,
    PLATE_RENDER_WIDTH,
    VARIANTS,
)
from yt_flow.config import Settings  # noqa: E402
from yt_flow.domain.state import LOCATION_KEYS  # noqa: E402
from yt_flow.services.character_service import (  # noqa: E402
    _DASHSCOPE_VISION_ENDPOINT,
    CharacterService,
)
from yt_flow.services.image_search import DuckDuckGoImageSearch  # noqa: E402

# Search phrasing, not prompt phrasing. Two rules learned the hard way and applied to
# every entry: (1) no "SCP" and no "SCP Foundation" — that token returns fan art, wiki
# logos and cosplay, and it is the same attractor that poisoned the character cards
# (gotcha: "SCP Foundation" in a prompt IS the mask attractor); (2) name a real building
# type that photographers actually shoot, because the point is to inherit a real camera
# position. (3) "abandoned ... urbex" where a room type is dominated by stock libraries:
# medical-bay lost 17 of 20 candidates to the stock-host blocklist and autopsy-room had
# 10 rejected as not-that-room. Urbex photography lives on blogs, flickr and reddit, and
# a decayed facility is closer to the channel's look than a catalogue interior anyway.
# position. "empty" / "no people" is in most queries because a figure is an automatic
# reject downstream and it is cheaper to bias the search than to burn vision calls.
REF_QUERIES = {
    "containment-chamber": "prison isolation cell interior heavy steel door bunk concrete walls",
    "observation-room": "hospital observation room interior window into adjacent room monitors",
    "corridor": "hospital basement service corridor interior pipes doors along walls",
    "interview-room": "police interrogation room interior table two chairs one-way mirror",
    "autopsy-room": "abandoned morgue autopsy room urbex stainless steel table overhead lamp",
    "control-room": "industrial plant control room interior consoles monitor wall empty",
    "facility-exterior": "brutalist concrete industrial facility exterior night floodlights fence",
    "server-room": "data centre server racks cabinets interior cabling raised floor",
    "storage-vault": "secure storage vault interior caged lockers shelving empty",
    "medical-bay": "abandoned hospital ward urbex bed iv stand bedside cabinet decay",
    "cafeteria": "school canteen dining hall long tables benches serving counter",
    "office": "small office desk chair paperwork filing cabinet desk lamp interior",
    "maintenance-tunnel": "underground utility maintenance tunnel interior pipes grated walkway",
    "entrance-checkpoint": "building security checkpoint lobby interior turnstile guard booth",
}
assert set(REF_QUERIES) == set(LOCATION_KEYS), "REF_QUERIES must cover every LocationKey"

# What the vision model is told the shot should be. Only one key is an outdoor view, and
# an exterior photo filed under an interior key would hand the ControlNet a skyline.
EXTERIOR_KEYS = {"facility-exterior"}
INTERIOR_SHOT = "an interior photograph taken inside the room"
EXTERIOR_SHOT = "an exterior photograph of a building seen from outside"

# Same closed decision rule as the plate labeler: every field must be present, boolean
# and correct. An unparsable or missing field rejects — a reference that slips through
# is a copyright-adjacent artefact sitting in the repo, so the bias is toward too few.
REQUIRED_BOOLS = {
    "matches_location": True,
    "has_person": False,
    "has_watermark_or_text": False,
    "matches_shot_type": True,
}
MIN_CONFIDENCE = 0.8

# ponytail: a module constant, not a Langfuse prompt — offline curation, same call as
# label_location_plates.LABEL_PROMPT, and AI sessions are hard-blocked from the Hub.
CURATE_PROMPT = """You are screening one candidate photograph for use as a composition
reference. It should be {shot_type} of: {description}

Reply with a single JSON object and nothing else:
{{"matches_location": true|false, "has_person": true|false, "has_watermark_or_text": true|false,
 "matches_shot_type": true|false, "confidence": 0.0-1.0, "notes": "one short sentence"}}

Field rules:
- matches_location: the room really is that kind of place, not a lookalike or a diagram.
- has_person: any human, humanoid, mannequin, figure or silhouette, however small or blurred.
- has_watermark_or_text: a watermark, stock-photo overlay, or a caption/logo laid ON TOP
  of the photo. Signage that is physically part of the room (exit signs, door numbers,
  wall labels) is NOT this — say false for those. Only the reference's geometry is ever
  used, so in-scene signage is harmless; an overlaid watermark is a rights claim and is
  not. Bundling the two rejected almost every usable photo of a real facility.
- matches_shot_type: it is {shot_type}, not a floor plan, render, close-up detail or collage.
- confidence: how sure you are of the judgements above."""

# ponytail: a mime map, not mimetypes.guess_type — the downloader already normalised the
# extension to exactly one of these three from the Content-Type header.
_MIME = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def _shot_type(location_key: str) -> str:
    return EXTERIOR_SHOT if location_key in EXTERIOR_KEYS else INTERIOR_SHOT


def _reject_reason(verdict: dict) -> str | None:
    """``None`` if the verdict is an unambiguous keep, else why it is not."""
    for field, expected in REQUIRED_BOOLS.items():
        value = verdict.get(field)
        if not isinstance(value, bool):
            return f"{field}={value!r} not boolean"
        if value is not expected:
            return f"{field}={value}"
    confidence = verdict.get("confidence")
    # bool is an int subclass, so `true` would otherwise read as confidence 1.0.
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return f"confidence={confidence!r} not a number"
    if confidence < MIN_CONFIDENCE:
        return f"confidence={confidence}"
    return None


async def score_candidate(settings: Settings, image_path: Path, location_key: str, description: str) -> dict:
    """One Qwen-VL call for one candidate. Raises on HTTP, decode or parse failure."""
    ext = image_path.suffix.lstrip(".").lower()
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    content = [
        {"type": "text", "text": CURATE_PROMPT.format(shot_type=_shot_type(location_key), description=description)},
        {"type": "image_url", "image_url": {"url": f"data:{_MIME.get(ext, 'image/png')};base64,{b64}"}},
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


def _write_ref(src: Path, dest: Path) -> None:
    """Normalise a keeper to the exact frame the sampler will condition on.

    ComfyUI center-crops and rescales a ControlNet hint to the latent anyway, so doing
    it here costs nothing and makes the on-disk file an honest record of what the model
    saw. ``ImageOps.fit`` is center-crop-to-aspect plus resample in one call.
    """
    from PIL import Image, ImageOps

    with Image.open(src) as im:
        ImageOps.fit(
            im.convert("RGB"), (PLATE_RENDER_WIDTH, PLATE_RENDER_HEIGHT), Image.LANCZOS
        ).save(dest, format="PNG")


def _is_complete(key_dir: Path) -> bool:
    return all((key_dir / f"ref_{variant}.png").is_file() for variant in VARIANTS)


# Stock-photo hosts are excluded at the source rather than filtered out later by the
# watermark check. Two reasons, and they point the same way: their previews are
# watermarked, and a watermark is an explicit rights assertion — harvesting them for a
# monetised channel is not something to wave through on the grounds that only the
# geometry is used. They are also the hosts that actually failed, with 301 redirects
# (the downloader refuses to follow them, deliberately, as SSRF protection) and 403
# hotlink blocks, so excluding them costs nothing that was working.
BLOCKED_SOURCES = (
    "freepik.com", "shutterstock.com", "dreamstime.com", "stockcake.com",
    "gettyimages.com", "istockphoto.com", "alamy.com", "123rf.com",
    "depositphotos.com", "adobestock.com", "vecteezy.com", "etsystatic.com",
)


def _is_blocked_source(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in BLOCKED_SOURCES)


async def fetch_key(
    settings: Settings,
    search,
    location_key: str,
    description: str,
    *,
    max_candidates: int,
    force: bool,
) -> int:
    """Search, download, curate and write up to ``len(VARIANTS)`` refs. Returns the count kept."""
    key_dir = Path(settings.location_refs_dir) / location_key
    if not force and _is_complete(key_dir):
        print(f"skipped (already curated): {location_key}")
        return len(VARIANTS)

    query = REF_QUERIES[location_key]
    try:
        results = await search.search(query=query, max_results=max_candidates)
    except Exception as exc:  # noqa: BLE001 — one key's search failure must not stop the batch
        print(f"failed (search: {exc}): {location_key}")
        return 0

    key_dir.mkdir(parents=True, exist_ok=True)
    # A re-fetch that keeps fewer refs than the last one must not leave the surplus
    # behind: the file would still be picked up by the seed script while refs.json no
    # longer names its source, which is exactly the provenance hole this dir exists to close.
    kept: dict[str, dict] = {}
    rejected: list[dict] = []

    # Candidates land in a temp dir: only the keepers are ever written into the repo,
    # so a rejected photo is not left sitting on disk.
    with tempfile.TemporaryDirectory() as staging:
        for index, result in enumerate(results, start=1):
            if len(kept) == len(VARIANTS):
                break
            url = result.get("url")
            if url and _is_blocked_source(url):
                rejected.append({"url": url, "reason": "blocked source (stock-photo host)"})
                continue
            if not url:
                print(f"skipped (malformed result #{index}): {location_key}")
                continue
            try:
                ext = await CharacterService._download_reference_image(url, Path(staging), index)
            except Exception as exc:  # noqa: BLE001 — dead links and blocked hosts are routine
                print(f"rejected (download: {exc}): {location_key} <- {url}")
                rejected.append({"url": url, "reason": f"download: {exc}"})
                continue

            candidate = Path(staging) / f"ref_{index}.{ext}"
            try:
                verdict = await score_candidate(settings, candidate, location_key, description)
            except Exception as exc:  # noqa: BLE001 — a failed scorer must never keep
                print(f"rejected (scorer failed: {exc}): {location_key} <- {url}")
                rejected.append({"url": url, "reason": f"scorer failed: {exc}"})
                continue

            reason = _reject_reason(verdict)
            if reason:
                print(f"rejected ({reason}): {location_key} <- {url}")
                rejected.append({"url": url, "reason": reason, "verdict": verdict})
                continue

            variant = VARIANTS[len(kept)]
            _write_ref(candidate, key_dir / f"ref_{variant}.png")
            kept[variant] = {"url": url, "title": result.get("title", ""), "verdict": verdict}
            print(f"kept: {location_key} {variant} <- {url}")

    if not kept:
        # Keep whatever a previous run curated. Clearing the directory up front and then
        # searching cost two keys their only reference when the re-run found nothing:
        # a partially-curated key is not "complete", so it gets re-fetched, and a bad
        # search then left it with nothing at all.
        existing = sorted(key_dir.glob("ref_*.png"))
        if existing:
            print(f"kept {len(existing)} existing ref(s): {location_key} (this search found none)")
            return len(existing)
    else:
        for stale in key_dir.glob("ref_*.png"):
            if stale.name not in {f"ref_{v}.png" for v in kept}:
                stale.unlink()

    (key_dir / "refs.json").write_text(
        json.dumps(
            {"location_key": location_key, "query": query, "refs": kept, "rejected": rejected},
            indent=2, ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"done: {location_key} {len(kept)}/{len(VARIANTS)} refs")
    return len(kept)


async def run(args) -> int:
    settings = Settings()
    if not settings.character_vision_api_key:
        sys.exit("YTFLOW_CHARACTER_VISION_API_KEY is not set — curation needs the Qwen-VL key")

    # A candidate is screened against the same sentence the finished plate is graded on
    # (label_location_plates.py), so "matches the location" means one thing in both places.
    keys = [args.key] if args.key else list(LOCATION_KEYS)
    search = DuckDuckGoImageSearch()
    empty: list[str] = []
    for location_key in keys:
        kept = await fetch_key(
            settings, search, location_key, LOCATION_PROMPTS[location_key],
            max_candidates=args.max_candidates, force=args.force,
        )
        if not kept:
            empty.append(location_key)

    print(f"done: {len(keys) - len(empty)}/{len(keys)} keys have at least one reference")
    for location_key in empty:
        print(f"no reference: {location_key} (its plates fall back to the procedural blockout)")
    # Non-zero only when a key got nothing: a partial set is a designed outcome (the
    # missing variants fall back to the blockout), an empty key means the search or the
    # curation bar needs a look before that key's plates are re-rendered.
    return 1 if empty else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch and auto-curate location structure references.")
    parser.add_argument("--key", choices=LOCATION_KEYS, help="Fetch one location key instead of all 14.")
    parser.add_argument(
        "--max-candidates", type=int, default=6, metavar="N",
        help="Search results to download and screen per key (default 6).",
    )
    parser.add_argument("--force", action="store_true", help="Re-fetch even if all three refs already exist.")
    return parser


def main(argv=None) -> int:
    return asyncio.run(run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
