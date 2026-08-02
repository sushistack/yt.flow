"""Seed the stock location plate library (Story 8.5).

One-time (per style_epoch) curation batch — not a pipeline node, see the
story's Dev Notes "Why the seed script is a script, not a pipeline node".
For each LocationKey x variant (a/b/c, 3 per key), submits the IPAdapter
style-anchor workflow to ComfyUI, saves the PNG under
assets/locations/{location_key}/{variant}.png, and upserts a draft
LocationPlate row via AssetService (manifest + DB in one call). Curation
(scripts/label_location_plates.py, then scripts/approve_location_plate.py)
promotes drafts to approved; only approved plates are used by image_node's
STOCK fast path.

Story 8.17 made the batch actually survivable: renders at an SDXL-native bucket
and upscales to the 1920x1080 on-disk contract, resumes at the first plate
without a file after a ComfyUI abort, re-rolls a rejected plate to a different
image with --reroll, and can render its own style-anchor candidates.

Workflow node map (data/workflows/comfyui_location_plate_api.json):
  6 = positive CLIPTextEncode, 7 = negative CLIPTextEncode, 3 = KSampler (seed),
  5 = EmptyLatentImage (render size), 11 = last LoraLoader (model chain),
  20 = IPAdapter anchor LoadImage, 23 = IPAdapterAdvanced (weight),
  30 = scribble ControlNetLoader, 31 = structure-hint LoadImage,
  33 = FakeScribblePreprocessor, 32 = ControlNetApplyAdvanced.
"""

import argparse
import asyncio
import copy
import hashlib
import json
import secrets
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))  # sibling scripts/ modules (room_blockout)

from sqlmodel import Session, select  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.db.models import LocationPlate  # noqa: E402
from yt_flow.domain.state import LOCATION_KEYS  # noqa: E402
from yt_flow.pipeline.nodes.image import _wait_for_comfyui_recovery  # noqa: E402
from yt_flow.services import comfyui_client  # noqa: E402
from yt_flow.services.asset_service import AssetService  # noqa: E402
from yt_flow.services.comfyui_client import ComfyUIError  # noqa: E402

VARIANTS = ("a", "b", "c")
POSITIVE_NODE, NEGATIVE_NODE, SAMPLER_NODE = "6", "7", "3"
ANCHOR_NODE, IPADAPTER_NODE = "20", "23"
BLOCKOUT_NODE = "31"
BLOCKOUT_STRENGTH = 0.5
SCRIBBLE_NODE, CONTROLNET_APPLY_NODE = "33", "32"
CONTROLNET_LOADER_NODE = "30"
LATENT_NODE, MODEL_NODE = "5", "11"
LOCATION_PLATE_WIDTH = 1920
LOCATION_PLATE_HEIGHT = 1080
# Render at an SDXL-native bucket, not at the on-disk contract: a 1920x1080 latent is
# ~2x SDXL's training area and the sampler answers with duplicated architecture
# (doubled doorways, mirrored corridors). 1344x768 is the bucket Story 11.1 settled on
# for shot backgrounds; the plate is Lanczos-upscaled to 1920x1080 before validation.
PLATE_RENDER_WIDTH = 1344
PLATE_RENDER_HEIGHT = 768
MIN_VALID_PLATE_BYTES = 1024
# Prompt for --anchor-candidates. Deliberately an existing LOCATION_PROMPTS entry
# rather than new prompt text (prompt content is out of scope for Story 8.17): a
# corridor is the most generic facility interior in the set. Override with --key.
ANCHOR_CANDIDATE_KEY = "corridor"
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
    "server-room": "A data center server room seen from a corner, server racks along two walls with blinking status lights, raised floor tiles, climate-control ducting overhead",
    "storage-vault": "A high-security storage vault, numbered lockers and reinforced cages along the back and side walls, dim overhead lighting, concrete floor, viewed from one corner of the room",
    "medical-bay": "A Foundation infirmary room, a hospital bed with restraints, IV stand, medical cabinets, pale clinical lighting",
    "cafeteria": "An empty Foundation cafeteria, rows of long metal tables and stacked trays, fluorescent lighting, unsettlingly ordinary",
    "office": "A researcher's cluttered office, a metal desk with stacked case files, a corkboard of notes, a single desk lamp",
    "maintenance-tunnel": "A below-grade maintenance tunnel, exposed pipes and steam vents, grated walkway, dim work lights",
    "entrance-checkpoint": "A facility security checkpoint, a metal detector archway, a reinforced turnstile, guard booth behind bulletproof glass",
}
assert set(LOCATION_PROMPTS) == set(LOCATION_KEYS), "LOCATION_PROMPTS must cover every LocationKey"

# The three variants used to differ only by seed, which is not variety: the batch came
# back as fourteen versions of the same one-point-perspective corridor with the wall
# contents swapped. Same prompt, same composition. Each variant now states its own
# camera, so a location's three plates are three shots of one room rather than three
# rolls of one shot — and none of them defaults to staring down a vanishing point.
VARIANT_CAMERAS = {
    "a": "wide establishing shot from the doorway, eye level, the far wall visible",
    "b": "three-quarter view from a corner of the room, low angle looking slightly up",
    "c": "closer asymmetric framing of the room's main feature, camera off to one side",
}
assert set(VARIANT_CAMERAS) == set(VARIANTS), "VARIANT_CAMERAS must cover every variant"

# The wording above is not what actually decides the composition — a scribble ControlNet
# is. Words were tried first and lost: 95% of the library came back as one identical
# receding corridor, and camera and room-shape phrasing only moved that to 74%. The
# prompt keeps subject and style; geometry comes from the control image, which is the
# standard archviz split.
#
# The control image is a curated reference photograph when one exists
# (scripts/fetch_location_refs.py -> data/refs/locations/<key>/ref_<variant>.png), and
# the procedural blockout below otherwise. The blockout fixes the geometry but is a box:
# it cannot make an autopsy room read differently from a cafeteria, which is the other
# half of the problem. A photo of the real kind of room carries both.
VARIANT_SHOTS = {"a": "wide-room-from-doorway", "b": "corner-three-quarter", "c": "close-detail-offset"}
# How far the room runs back, in units of its width. Corridors are meant to recede.
LOCATION_DEPTH = {"corridor": 4.0, "maintenance-tunnel": 3.5, "cafeteria": 2.0,
                  "facility-exterior": 2.5, "server-room": 1.8, "storage-vault": 1.8}
DEFAULT_DEPTH = 1.3
CORRIDOR_SHOT = "corridor"


# None of the descriptions state the shape of the space, so the checkpoint fell back on
# its own prior, which for "facility" is overwhelmingly a receding corridor: 95% of the
# first batch, and still 81% after the anchor was limited to style transfer. Naming the
# geometry is the positive-prompt counter-pull. Corridor and tunnel are left out — they
# are supposed to recede.
ROOM_SHAPES = {
    "containment-chamber": "a square sealed cell, all four walls close",
    "observation-room": "a small rectangular room, the observation window filling one wall",
    "interview-room": "a small square room, four bare walls close around the table",
    "autopsy-room": "a compact square operating room, the table in the middle of the floor",
    "control-room": "a wide low-ceilinged room, consoles curving around one end",
    "facility-exterior": "an outdoor establishing view, open sky above the building",
    "server-room": "a square machine room, racks along two adjacent walls",
    "storage-vault": "a boxy vault chamber, the far wall close",
    "medical-bay": "a small square ward, the bed against one wall",
    "cafeteria": "a wide open hall, tables scattered across an open floor",
    "office": "a cramped square office, desk against the wall",
    "entrance-checkpoint": "a compact lobby, the checkpoint across the width of the room",
}


async def _upload_blockout(settings, location_key: str, variant: str) -> str:
    """Render this shot's room blockout and upload it as the ControlNet image."""
    from yt_flow.services import comfyui_client

    from room_blockout import render_blockout

    shot = CORRIDOR_SHOT if location_key in ("corridor", "maintenance-tunnel") else VARIANT_SHOTS[variant]
    png = render_blockout(
        shot,
        LOCATION_DEPTH.get(location_key, DEFAULT_DEPTH),
        PLATE_RENDER_WIDTH,
        PLATE_RENDER_HEIGHT,
    )
    return await comfyui_client.upload_image(settings.comfyui_url, png, f"blockout_{location_key}_{variant}.png")


# A key whose own search keeps coming back empty borrows structure from a sibling room
# with a compatible layout. autopsy-room is the case that forced this: morgue photography
# is dominated by shots with people or watermarks, so every candidate was rejected, and
# the empty blockout rendered a bare white box with no table and no lamp. The lender only
# supplies geometry — the prompt still describes an autopsy suite.
REF_BORROW = {"autopsy-room": "observation-room"}


def _reference_path(settings, location_key: str, variant: str) -> Path | None:
    """The curated structure reference for this plate, if fetch_location_refs.py found one.

    Falls back to a sibling variant's reference for the same location before giving up.
    Curation rarely fills all three slots, and the empty procedural blockout is a much
    worse hint than another photo of the right room: the keys that got one reference
    rendered variant `a` with furniture and variants `b`/`c` as bare boxes. Sharing the
    hint costs some composition variety — the seed and the variant's camera wording still
    differ — and buys the room its contents, which is the defect that actually shows.
    """
    key_dir = Path(settings.location_refs_dir) / location_key
    exact = key_dir / f"ref_{variant}.png"
    if exact.is_file():
        return exact
    siblings = sorted(key_dir.glob("ref_*.png"))
    if not siblings and location_key in REF_BORROW:
        lender = Path(settings.location_refs_dir) / REF_BORROW[location_key]
        siblings = sorted(lender.glob("ref_*.png"))
    if not siblings:
        return None
    # Deterministic per variant, so a re-run picks the same sibling.
    return siblings[VARIANTS.index(variant) % len(siblings)]


def _bypass_scribble(workflow: dict) -> dict:
    """Feed the ControlNet straight from LoadImage, skipping the scribble preprocessor.

    The blockout is *already* white-on-black structural line art. Running scribble_hed
    over it would find the edges of the drawn lines and hand back each 5px stroke as a
    pair of thin parallel ones — a worse hint than the input. The preprocessor exists
    for the reference-photo path only, so the fallback path drops it.
    """
    workflow[CONTROLNET_APPLY_NODE]["inputs"]["image"] = [BLOCKOUT_NODE, 0]
    workflow.pop(SCRIBBLE_NODE, None)
    # Weaker than the reference path, and the difference is the point. A reference photo
    # carries the room's contents as well as its shape, so it can be followed hard. The
    # blockout is an empty box: at 0.9 the sampler obeyed it literally and returned empty
    # boxes — an autopsy room with no table, a medical bay with no bed, a cafeteria with
    # no tables. The geometry still lands at 0.5; the furniture comes from the prompt.
    workflow[CONTROLNET_APPLY_NODE]["inputs"]["strength"] = BLOCKOUT_STRENGTH
    return workflow


async def _upload_structure_hint(settings, workflow: dict, location_key: str, variant: str) -> str:
    """Wire this plate's ControlNet hint: the curated photo if there is one, else the blockout.

    COPYRIGHT: the reference is uploaded to node 31 and nowhere else, and node 31 feeds
    only the scribble preprocessor. It never reaches the IPAdapter (node 23, whose image
    input is the style-anchor batch) and never reaches the latent (node 5 is an
    EmptyLatentImage). What the sampler sees of somebody's photograph is a line drawing.
    """
    reference = _reference_path(settings, location_key, variant)
    if reference is None:
        _bypass_scribble(workflow)
        return await _upload_blockout(settings, location_key, variant)
    return await comfyui_client.upload_image(
        settings.comfyui_url, reference.read_bytes(), f"locref_{location_key}_{variant}.png"
    )


def _plate_prompt(location_key: str, variant: str) -> str:
    """Location description, its room geometry, and that variant's camera framing."""
    parts = [LOCATION_PROMPTS[location_key]]
    if location_key in ROOM_SHAPES:
        parts.append(ROOM_SHAPES[location_key])
    parts.append(VARIANT_CAMERAS[variant])
    return ", ".join(parts)


def _load_workflow(path: str) -> dict:
    try:
        workflow = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # JSONDecodeError is a ValueError subclass
        sys.exit(f"cannot load ComfyUI workflow at {path!r}: {exc}")
    for node_id in (POSITIVE_NODE, NEGATIVE_NODE, SAMPLER_NODE, LATENT_NODE, ANCHOR_NODE, IPADAPTER_NODE,
                    BLOCKOUT_NODE, SCRIBBLE_NODE, CONTROLNET_APPLY_NODE):
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
    workflow[LATENT_NODE]["inputs"]["width"] = PLATE_RENDER_WIDTH
    workflow[LATENT_NODE]["inputs"]["height"] = PLATE_RENDER_HEIGHT
    return workflow


def _strip_ipadapter(workflow: dict) -> dict:
    """Drop the IPAdapter *and* ControlNet branches, leaving prompt + LoRA chain only.

    An anchor *candidate* is the image the style will later be anchored to, so it
    cannot itself be style-anchored — and when --anchor-candidates runs there is no
    anchor image to load. Removal is by class_type (mirrors
    character_image_provider._drop_reference_only_nodes) so the orphaned CLIPVision /
    IPAdapterModelLoader loaders go with it and ComfyUI sees no dangling inputs.

    The ControlNet branch goes too, and not only for symmetry: dropping every LoadImage
    took node 31 out while ControlNetApplyAdvanced still pointed at it, so the candidate
    prompt ComfyUI received had a dangling link and would have been rejected outright.
    A candidate is also supposed to show what the checkpoint does unconditioned.
    """
    workflow = copy.deepcopy(workflow)
    workflow[SAMPLER_NODE]["inputs"]["model"] = [MODEL_NODE, 0]
    workflow[SAMPLER_NODE]["inputs"]["positive"] = [POSITIVE_NODE, 0]
    workflow[SAMPLER_NODE]["inputs"]["negative"] = [NEGATIVE_NODE, 0]
    for node_id in (SCRIBBLE_NODE, CONTROLNET_APPLY_NODE, CONTROLNET_LOADER_NODE):
        workflow.pop(node_id, None)
    for node_id, node in list(workflow.items()):
        if node.get("class_type") in ("LoadImage", "CLIPVisionLoader", "IPAdapterModelLoader", "IPAdapterAdvanced"):
            workflow.pop(node_id)
    return workflow


def _plate_seed(location_key: str, variant: str, salt: str = "") -> int:
    """Deterministic per-plate KSampler seed; a non-empty ``salt`` re-rolls it.

    sha256, not the shipped ``int.from_bytes(..., "little") % 2**31``: little-endian
    truncation makes that value a function of the first four bytes only, so
    "containment-chamber" and "control-room" drew the *same* seed and a salt appended
    to the end was discarded outright. Same reasoning as image.py's
    _plate_variant_index, which uses sha256 for the same reason.
    """
    return int(hashlib.sha256(f"{location_key}:{variant}:{salt}".encode()).hexdigest(), 16) % (2**31)


def _upscale_to_contract(image_bytes: bytes) -> bytes:
    """Lanczos-resample a native-bucket render up to the 1920x1080 on-disk contract.

    ``_valid_plate`` requires exactly those dimensions and image_node copies the file
    verbatim, so the render is upscaled to meet the contract rather than the check
    being weakened. ``convert("RGB")`` also pins the RGB-no-alpha half of it.
    # ponytail: PIL imported lazily, like character_image_provider._clean_alpha_noise —
    # already installed transitively, and mock mode never pays for it. 1344x768 is
    # 1.75:1, so this stretches width ~1.6% relative to height; cropping to 16:9 first
    # would cost 12 rows of a room interior for no visible gain.
    """
    import io

    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as im:
        resized = im.convert("RGB").resize((LOCATION_PLATE_WIDTH, LOCATION_PLATE_HEIGHT), Image.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format="PNG")
    return buffer.getvalue()


class RecoveryExhausted(RuntimeError):
    """ComfyUI stayed down past the recovery window — abort the batch instead of
    failing every remaining plate against a dead server."""


async def _submit_with_recovery(settings: Settings, workflow: dict, *, done: int, total: int) -> bytes:
    """Submit one plate, absorbing a mid-batch ComfyUI abort (Story 5.23's loop, reused).

    ``hipErrorIllegalAddress`` core dumps are routine on this host, so a 42-plate batch
    will meet one. On a submit failure, wait for the server to come back and retry once;
    the retry's own failure is a per-plate failure (the batch continues), but a recovery
    window that never closes is fatal to the batch.
    """
    try:
        return await comfyui_client.submit_and_fetch(settings.comfyui_url, workflow)
    except ComfyUIError as exc:
        try:
            # ponytail: image.py's helper verbatim — its log line says "shots", which for
            # this batch means plates. Not worth renaming a parameter in a shared node.
            await _wait_for_comfyui_recovery(
                settings.comfyui_url,
                poll_sec=settings.comfyui_crash_recovery_poll_sec,
                timeout_sec=settings.comfyui_crash_recovery_timeout_sec,
                shots_done=done, total_shots=total,
            )
        except ComfyUIError as still_down:
            raise RecoveryExhausted(f"ComfyUI did not recover: {still_down}") from exc
        return await comfyui_client.submit_and_fetch(settings.comfyui_url, workflow)


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
    salt: str = "",
    done: int = 0,
    total: int = 0,
) -> bool:
    """Generate (or mock-copy) and upsert one plate. Returns True on success."""
    dest_dir = Path(settings.assets_path) / "locations" / location_key
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{variant}.png"

    existing = _existing_row(session, location_key, variant)
    if existing is not None:
        if existing.status == "approved" and not force:
            print(f"skipped (approved): {location_key} {variant}")
            return True
        # Resume: an aborted batch must not re-render what it already produced, so a
        # draft whose file is still on disk and valid counts as finished work. --force
        # and --reroll are the two ways to ask for a new image for the same plate.
        if not force and not salt and _valid_plate(dest, mock=settings.comfyui_mock):
            print(f"skipped (already generated): {location_key} {variant}")
            return True
        session.delete(existing)
        session.commit()

    seed = _plate_seed(location_key, variant, salt)

    try:
        if settings.comfyui_mock:
            dest.write_bytes(_mock_fixture().read_bytes())
        else:
            if template is None:
                raise ValueError("workflow must be loaded in real mode")
            workflow = _inject_anchors(
                _inject(template, _plate_prompt(location_key, variant), seed, settings.location_ipadapter_weight),
                anchor_names,
            )
            workflow[BLOCKOUT_NODE]["inputs"]["image"] = await _upload_structure_hint(
                settings, workflow, location_key, variant
            )
            image_bytes = await _submit_with_recovery(settings, workflow, done=done, total=total)
            dest.write_bytes(_upscale_to_contract(image_bytes))

        if not _valid_plate(dest, mock=settings.comfyui_mock):
            print(f"failed (validation): {location_key} {variant}")
            return False

        rel_path = str(dest.relative_to(Path(settings.assets_path)))
        # Seed + salt in the manifest source: enough to re-render this exact plate, which
        # is the only way a re-rolled keeper can be reproduced.
        asset_service.add_location_plate(
            location_key, variant, rel_path,
            source={"seed": seed, "reroll_salt": salt, "render_size": f"{PLATE_RENDER_WIDTH}x{PLATE_RENDER_HEIGHT}"},
        )
        print(f"generated: {location_key} {variant} -> {rel_path} (seed {seed})")
        return True
    except RecoveryExhausted:
        raise  # fatal to the batch, not to one plate
    except Exception as exc:  # noqa: BLE001 — one plate's failure must not stop the batch
        print(f"failed ({exc}): {location_key} {variant}")
        return False


async def generate_anchor_candidates(settings: Settings, template: dict, *, count: int, location_key: str) -> int:
    """Render N unconditioned candidates into a review dir and stop — no DB, no manifest.

    Satisfies the anchor gate without hand-made art: the operator picks one, copies it
    into ``location_anchor_dir`` and records the choice in LOOKDEV_DECISION.md. Nothing
    here is a library asset, so it goes under workspace_path (same shape as
    seed_stock_cast.py's --anchor-search review directory).
    """
    review_dir = Path(settings.workspace_path) / "location-anchor-candidates"
    review_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for index in range(1, count + 1):
        dest = review_dir / f"candidate_{index}.png"
        workflow = _strip_ipadapter(
            _inject(template, LOCATION_PROMPTS[location_key], _plate_seed(location_key, f"anchor{index}"), 0.0)
        )
        try:
            dest.write_bytes(await comfyui_client.submit_and_fetch(settings.comfyui_url, workflow))
        except Exception as exc:  # noqa: BLE001 — one bad candidate must not lose the others
            print(f"failed ({exc}): candidate {index}")
            continue
        written += 1
        print(f"candidate: {dest}")
    print(
        f"Review {review_dir} ({written}/{count} rendered), copy the chosen candidate into "
        f"{settings.location_anchor_dir}/ and record the choice in "
        f"{Path(settings.location_anchor_dir) / 'LOOKDEV_DECISION.md'} before seeding plates."
    )
    return 0 if written else 1


async def run(args) -> int:
    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    anchor_dir = Path(settings.location_anchor_dir)

    if args.anchor_candidates and settings.comfyui_mock:
        sys.exit("--anchor-candidates renders real images; it does nothing in YTFLOW_COMFYUI_MOCK mode")

    template = None
    anchor_names: list[str] = []
    if not settings.comfyui_mock:
        template = _load_workflow(settings.location_plate_workflow_path)
        if args.anchor_candidates:
            # Before the gates on purpose: this mode exists to satisfy them.
            return await generate_anchor_candidates(
                settings, template,
                count=args.anchor_candidates, location_key=args.key or ANCHOR_CANDIDATE_KEY,
            )
        _check_lookdev_decision(anchor_dir)
        anchor_paths = _load_anchor_paths(anchor_dir)
        for p in anchor_paths:
            anchor_names.append(await comfyui_client.upload_image(settings.comfyui_url, p.read_bytes(), p.name))

    salt = args.reroll or ""
    if args.reroll == "":  # bare --reroll: a fresh salt, printed so a keeper is reproducible
        salt = secrets.token_hex(4)
        print(f"reroll salt: {salt} (re-run with --reroll {salt} to reproduce these plates)")

    keys = [args.key] if args.key else list(LOCATION_KEYS)
    variants = [args.variant] if args.variant else list(VARIANTS)
    plates = [(key, variant) for key in keys for variant in variants]

    ok = failed = 0
    with Session(db._engine) as session:
        asset_service = AssetService(settings.assets_path, session)
        for index, (location_key, variant) in enumerate(plates):
            try:
                success = await seed_plate(
                    session=session, settings=settings, asset_service=asset_service,
                    template=template, anchor_names=anchor_names,
                    location_key=location_key, variant=variant, force=args.force,
                    salt=salt, done=index, total=len(plates),
                )
            except RecoveryExhausted as exc:
                # Name what is left: a re-run resumes at the first plate without a file.
                remaining = ", ".join(f"{key} {var}" for key, var in plates[index:])
                print(f"aborted ({exc})")
                print(f"not generated: {remaining}")
                print(f"done: {ok} ok, {failed} failed, {len(plates) - index} not attempted")
                return 1
            ok += success
            failed += not success

    print(f"done: {ok} ok, {failed} failed")
    return 0 if failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed the stock location plate library.")
    parser.add_argument(
        "--key", choices=LOCATION_KEYS,
        help=f"Seed one location key instead of all 14 (also picks the --anchor-candidates prompt, default {ANCHOR_CANDIDATE_KEY}).",
    )
    parser.add_argument("--variant", choices=VARIANTS, help="Seed one variant instead of all 3.")
    parser.add_argument("--force", action="store_true", help="Regenerate even if a plate is already approved.")
    parser.add_argument(
        "--reroll", nargs="?", const="", metavar="SALT",
        help="Re-render targeted plates with a salted seed. Bare flag = a fresh random salt "
             "(printed, and recorded in the manifest source); pass a recorded salt to reproduce it.",
    )
    parser.add_argument(
        "--anchor-candidates", type=int, metavar="N",
        help="Render N unconditioned style-anchor candidates into workspace/ for review, then exit.",
    )
    return parser


def main(argv=None) -> int:
    return asyncio.run(run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
