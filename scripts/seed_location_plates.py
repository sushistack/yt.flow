"""Seed the stock location plate library (Story 8.5).

One-time (per style_epoch) curation batch — not a pipeline node, see the
story's Dev Notes "Why the seed script is a script, not a pipeline node".
For each LocationKey x variant (a/b/c, 3 per key), submits the IPAdapter
style-anchor workflow to ComfyUI, saves the PNG under
assets/locations/{location_key}/{variant}.png, and upserts a draft
LocationPlate row via AssetService (manifest + DB in one call). Curation
(scripts/approve_location_plate.py) promotes drafts to approved; only
approved plates are used by image_node's STOCK fast path.

Workflow node map (data/workflows/comfyui_location_plate_api.json):
  6 = positive CLIPTextEncode, 7 = negative CLIPTextEncode, 3 = KSampler (seed),
  20 = IPAdapter anchor LoadImage, 23 = IPAdapterAdvanced (weight).
"""

import argparse
import asyncio
import copy
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import Session, select  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.db.models import LocationPlate  # noqa: E402
from yt_flow.domain.state import LOCATION_KEYS  # noqa: E402
from yt_flow.services import comfyui_client  # noqa: E402
from yt_flow.services.asset_service import AssetService  # noqa: E402

VARIANTS = ("a", "b", "c")
POSITIVE_NODE, NEGATIVE_NODE, SAMPLER_NODE = "6", "7", "3"
ANCHOR_NODE, IPADAPTER_NODE = "20", "23"
LOCATION_PLATE_WIDTH = 1920
LOCATION_PLATE_HEIGHT = 1080
MIN_VALID_PLATE_BYTES = 1024
PLATE_NEGATIVE_PROMPT = (
    "lowres, bad anatomy, worst quality, blurry, watermark, text, logo, "
    "person, people, human, character, creature, figure, silhouette"
)

# ponytail: one sentence per key, curated by Jay during lookdev; ships with
# sensible defaults so the library is generatable out of the box.
LOCATION_PROMPTS = {
    "containment-chamber": "A cold concrete containment cell, reinforced walls, dim emergency lighting, heavy blast door, surveillance camera mounted in corner, utilitarian SCP Foundation facility",
    "observation-room": "A scientific observation room overlooking a containment cell through reinforced wire-mesh glass, banks of monitors and clipboards on a steel desk, cold fluorescent lighting",
    "corridor": "A dim utilitarian facility corridor, exposed pipes and conduits along the ceiling, painted steel walls, hazard stripes on the floor, receding into the distance",
    "interview-room": "A bare interrogation room, a metal table bolted to the floor, two mismatched chairs, one-way mirror on the far wall, harsh overhead light",
    "autopsy-room": "A stainless steel autopsy suite, drain channels in the tiled floor, overhead surgical lamp, instrument trays, clinical cold lighting",
    "control-room": "A facility control room, banks of monitoring screens and blinking consoles, swivel chairs, dim blue ambient light",
    "facility-exterior": "The brutalist concrete exterior of an SCP Foundation site at night, chain-link fencing, floodlights, guard towers in the distance",
    "server-room": "A data center server room, rows of server racks with blinking status lights, raised floor tiles, climate-control ducting overhead",
    "storage-vault": "A high-security storage vault, rows of numbered lockers and reinforced cages, dim overhead lighting, concrete floor",
    "medical-bay": "A Foundation infirmary room, a hospital bed with restraints, IV stand, medical cabinets, pale clinical lighting",
    "cafeteria": "An empty Foundation cafeteria, rows of long metal tables and stacked trays, fluorescent lighting, unsettlingly ordinary",
    "office": "A researcher's cluttered office, a metal desk with stacked case files, a corkboard of notes, a single desk lamp",
    "maintenance-tunnel": "A below-grade maintenance tunnel, exposed pipes and steam vents, grated walkway, dim work lights",
    "entrance-checkpoint": "A facility security checkpoint, a metal detector archway, a reinforced turnstile, guard booth behind bulletproof glass",
}
assert set(LOCATION_PROMPTS) == set(LOCATION_KEYS), "LOCATION_PROMPTS must cover every LocationKey"


def _load_workflow(path: str) -> dict:
    workflow = json.loads(Path(path).read_text(encoding="utf-8"))
    for node_id in (POSITIVE_NODE, NEGATIVE_NODE, ANCHOR_NODE, IPADAPTER_NODE):
        if node_id not in workflow:
            raise ValueError(f"location plate workflow at {path!r} missing node {node_id!r}")
    return workflow


def _load_anchor_paths(anchor_dir: Path) -> list[Path]:
    anchors = sorted(p for ext in ("*.png", "*.jpg", "*.jpeg") for p in anchor_dir.glob(ext))
    if not anchors:
        sys.exit(
            f"No anchor images found in {anchor_dir} — run the lookdev gate first "
            f"(see {anchor_dir / 'LOOKDEV_DECISION.md'})"
        )
    return anchors


def _check_lookdev_decision(anchor_dir: Path) -> None:
    decision = anchor_dir / "LOOKDEV_DECISION.md"
    if not decision.is_file():
        sys.exit(
            f"Lookdev decision not recorded at {decision} — record the frontier-vs-local "
            "decision before bulk generation spends GPU hours (story 8.5 AC10)"
        )


def _inject_anchors(workflow: dict, anchor_names: list[str]) -> dict:
    """Wire N uploaded anchor images into one batched IMAGE tensor for IPAdapter.

    ComfyUI's LoadImage loads one file each; multiple anchors are combined
    via chained ImageBatch nodes so IPAdapterAdvanced sees a single batched
    reference (Saved Question #3: caps at however many anchors are curated,
    typically 3-5).
    """
    workflow[ANCHOR_NODE]["inputs"]["image"] = anchor_names[0]
    batch_ref = [ANCHOR_NODE, 0]
    for i, name in enumerate(anchor_names[1:], start=1):
        load_id, batch_id = f"{ANCHOR_NODE}_extra_{i}", f"{ANCHOR_NODE}_batch_{i}"
        workflow[load_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
        workflow[batch_id] = {"class_type": "ImageBatch", "inputs": {"image1": batch_ref, "image2": [load_id, 0]}}
        batch_ref = [batch_id, 0]
    workflow[IPADAPTER_NODE]["inputs"]["image"] = batch_ref
    return workflow


def _inject(template: dict, prompt: str, seed: int, weight: float) -> dict:
    workflow = copy.deepcopy(template)
    workflow[POSITIVE_NODE]["inputs"]["text"] = prompt
    workflow[NEGATIVE_NODE]["inputs"]["text"] = PLATE_NEGATIVE_PROMPT
    workflow[IPADAPTER_NODE]["inputs"]["weight"] = weight
    workflow[SAMPLER_NODE]["inputs"]["seed"] = seed
    return workflow


def _valid_plate(path: Path, *, mock: bool) -> bool:
    """AC13: non-fatal per-plate validation — file exists, PNG signature, size + dimensions.

    Mock mode only checks existence + signature — the fixture is a tiny
    stand-in, not a rendered plate (mirrors image.py's mock path, which never
    size-validates fixture copies either).
    """
    if not path.is_file():
        return False
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    if mock:
        return True
    if path.stat().st_size <= MIN_VALID_PLATE_BYTES:
        return False
    width, height = struct.unpack(">II", data[16:24])
    return width == LOCATION_PLATE_WIDTH and height == LOCATION_PLATE_HEIGHT


def _mock_fixture() -> Path:
    fixtures = sorted(Path("tests/fixtures/images").glob("*.png"))
    if not fixtures:
        raise SystemExit("mock mode requires a fixture PNG under tests/fixtures/images/")
    return fixtures[0]


def _existing_row(session, location_key: str, variant: str) -> LocationPlate | None:
    return session.exec(
        select(LocationPlate).where(
            LocationPlate.location_key == location_key, LocationPlate.variant == variant,
        )
    ).first()


async def seed_plate(
    *,
    session,
    settings: Settings,
    asset_service: AssetService,
    template: dict | None,
    anchor_names: list[str],
    location_key: str,
    variant: str,
    force: bool,
) -> bool:
    """Generate (or mock-copy) and upsert one plate. Returns True on success."""
    existing = _existing_row(session, location_key, variant)
    if existing is not None:
        if existing.status == "approved" and not force:
            print(f"skipped (approved): {location_key} {variant}")
            return True
        session.delete(existing)
        session.commit()

    dest_dir = Path(settings.assets_path) / "locations" / location_key
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{variant}.png"
    seed = int.from_bytes(f"{location_key}:{variant}".encode(), "little") % (2**31)

    try:
        if settings.comfyui_mock:
            dest.write_bytes(_mock_fixture().read_bytes())
        else:
            if template is None:
                raise ValueError("workflow must be loaded in real mode")
            workflow = _inject_anchors(
                _inject(template, LOCATION_PROMPTS[location_key], seed, settings.location_ipadapter_weight),
                anchor_names,
            )
            image_bytes = await comfyui_client.submit_and_fetch(settings.comfyui_url, workflow)
            dest.write_bytes(image_bytes)

        if not _valid_plate(dest, mock=settings.comfyui_mock):
            print(f"failed (validation): {location_key} {variant}")
            return False

        rel_path = str(dest.relative_to(Path(settings.assets_path)))
        asset_service.add_location_plate(location_key, variant, rel_path)
        print(f"generated: {location_key} {variant} -> {rel_path}")
        return True
    except Exception as exc:  # noqa: BLE001 — one plate's failure must not stop the batch
        print(f"failed ({exc}): {location_key} {variant}")
        return False


async def run(args) -> int:
    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    anchor_dir = Path(settings.location_anchor_dir)

    template = None
    anchor_names: list[str] = []
    if not settings.comfyui_mock:
        _check_lookdev_decision(anchor_dir)
        anchor_paths = _load_anchor_paths(anchor_dir)
        template = _load_workflow(settings.location_plate_workflow_path)
        for p in anchor_paths:
            anchor_names.append(await comfyui_client.upload_image(settings.comfyui_url, p.read_bytes(), p.name))

    keys = [args.key] if args.key else list(LOCATION_KEYS)
    variants = [args.variant] if args.variant else list(VARIANTS)

    ok = failed = 0
    with Session(db._engine) as session:
        asset_service = AssetService(settings.assets_path, session)
        for location_key in keys:
            for variant in variants:
                success = await seed_plate(
                    session=session, settings=settings, asset_service=asset_service,
                    template=template, anchor_names=anchor_names,
                    location_key=location_key, variant=variant, force=args.force,
                )
                ok += success
                failed += not success

    print(f"done: {ok} ok, {failed} failed")
    return 0 if failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed the stock location plate library.")
    parser.add_argument("--key", choices=LOCATION_KEYS, help="Seed one location key instead of all 14.")
    parser.add_argument("--variant", choices=VARIANTS, help="Seed one variant instead of all 3.")
    parser.add_argument("--force", action="store_true", help="Regenerate even if a plate is already approved.")
    return parser


def main(argv=None) -> int:
    return asyncio.run(run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
