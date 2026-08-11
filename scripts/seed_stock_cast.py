"""Seed stock and derived character card sprites (Story 8.2)."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import Session  # noqa: E402

from yt_flow import db  # noqa: E402
from yt_flow.config import Settings  # noqa: E402
from yt_flow.domain.png import has_alpha  # noqa: E402
# BANNED_STOCK_TOKEN / STOCK_NEGATIVE live in domain/state.py beside STOCK_CAST_KEYS
# (Story 10.6) because run_service needs them too and src/ must never import scripts/.
# Re-exported here, so seed.STOCK_NEGATIVE and seed.BANNED_STOCK_TOKEN still resolve.
from yt_flow.domain.state import (  # noqa: E402
    BANNED_STOCK_TOKEN,
    DERIVED_DESCRIPTORS,
    STOCK_CAST_KEYS,
    STOCK_NEGATIVE,
)
from yt_flow.services.character_service import CharacterService, _sanitize_scp_id  # noqa: E402
from yt_flow.services.image_search import DuckDuckGoImageSearch  # noqa: E402


# The descriptor is the only face constraint that actually reaches ComfyUI, so the
# head/face state leads it — and it stays purely affirmative. Diffusion text encoders
# do not negate, so "no mask" in the positive prompt summons masks; every prohibition
# belongs in STOCK_NEGATIVE instead (Story 8.15).
# Leads with Danbooru tags because the checkpoint is AnimagineXL, which is trained on
# them: "solo, 1boy" is the idiomatic one-character control for this model family.
# Prose alone did not hold — a run without them came back as a four-up character sheet,
# and because the four figures touched each other they were a single alpha component,
# so the largest-component cut in _clean_alpha_noise could not rescue it either.
# Hair and eye colour are pinned concretely, not as "dark": the non-front angles are
# prompted from this text, and vague colour let the front's black hair come back brown
# on one angle and teal on another. The enrichment read-back cannot cover for it — its
# prompt has no hair/eye/face dimension at all, only silhouette, texture, outfit
# palette, anomalous traits, lighting and art style.
# "mature adult male" is stated three ways and the age is numeric, because one
# adjective did not hold: four re-rolls of STOCK-d-class returned a child, a chibi and
# a girl despite "1boy, adult, a gaunt man in his thirties" already being present. The
# orange-jumpsuit prompt pulls this anime checkpoint hard toward young characters, so
# the counter-pull has to be in the tags, not in one word (Story 8.15).
_BARE_FACE = (
    "solo, 1boy, mature adult man, 35 years old, adult male body proportions, "
    "ordinary human face, short straight black hair, brown eyes, visible nose and "
    "mouth, natural skin"
)
# One concrete, reproducible feature per key. "plain forgettable features" was actively
# fighting cross-angle identity: with nothing to hold onto the model drew a different
# person for every angle. The one key that held up on its own was security, whose front
# happened to grow a moustache and a peaked cap — strong tokens the other angles could
# reproduce. So each key now gets its own cheap hook, and hair *shape* is pinned too,
# because colour alone still drifted between curly, straight and cropped (Story 8.15).
_KEY_FEATURES = {
    # Not "buzz cut" — from behind it read as fully bald.
    "STOCK-d-class": "very short cropped black hair, light stubble, gaunt hollow cheeks",
    "STOCK-researcher": "thin wire-rimmed glasses, neatly combed hair",
    # Not "peaked cap" — with "dark uniform" it pulled the whole card into a military
    # dress uniform: epaulettes, gold braid and rank insignia on every angle but the front.
    "STOCK-security": "short moustache, plain black baseball cap",
}
# BANNED_STOCK_TOKEN is deliberately absent below: probing the live checkpoint showed
# that token alone is what collapsed these extras into a masked, hazmat-suited figure —
# with it the render is a skull mask or a visored helmet, without it an ordinary
# person, every other lever held constant. The wardrobe carries the setting instead.
STOCK_DESCRIPTORS = {
    "STOCK-d-class": (
        f"{_BARE_FACE}, {_KEY_FEATURES['STOCK-d-class']}, a gaunt man in his thirties, "
        "orange prison jumpsuit with a stenciled number, long sleeves and long trousers, "
        "worn work boots, anxious posture"
    ),
    "STOCK-researcher": (
        f"{_BARE_FACE}, {_KEY_FEATURES['STOCK-researcher']}, a laboratory researcher in "
        "his thirties, white lab coat over shirt and tie, long dark trousers, ID badge, "
        "practical shoes, clinical professional posture"
    ),
    # "dark uniform" kept pulling this into a military dress uniform — epaulettes, gold
    # braid, rank insignia. Naming the actual garments instead of "uniform" holds it to
    # a facility guard, and does so in the positive prompt rather than by growing the
    # negative, which is what wrecked two earlier rounds.
    "STOCK-security": (
        f"{_BARE_FACE}, {_KEY_FEATURES['STOCK-security']}, a facility security guard in "
        "his thirties, black tactical vest over a plain grey short-sleeve shirt, black "
        "cargo trousers, alert disciplined posture"
    ),
}
VALID_POSES = ("standing", "sitting")

# Sidecar written into the staged directory so approve_stock_cast.py --reject can put
# characters.visual_descriptor back: staging overwrites that column, and runtime reads
# it (_get_visual_descriptor, generate_special_pose_card), so a rejected stage would
# otherwise leave the live row describing a deleted image. Absent means "no descriptor
# before staging". Not a .png, and the promote path looks up "{angle}_candidate_1.png"
# by name only, so it can never be mistaken for a card.
PRESTAGE_DESCRIPTOR_FILE = "_prestage_descriptor.txt"


def staged_dir(assets_path: Path, key: str, epoch: int) -> Path:
    """Directory a ``--stage`` run writes into (also read by approve_stock_cast.py)."""
    return assets_path / "characters" / _sanitize_scp_id(key) / f"epoch_{epoch}"


def _snapshot_prestage_descriptor(service: CharacterService, key: str, epoch: int) -> None:
    """Write the live ``visual_descriptor`` next to the staged cards, once.

    Only on first stage: a re-stage must not snapshot its own replacement text over
    the original, which is what ``--reject`` restores.
    """
    sidecar = staged_dir(Path(service._settings.assets_path), key, epoch) / PRESTAGE_DESCRIPTOR_FILE
    if sidecar.exists():
        return
    character = service.check_existing_character(key)
    if character is None or not character.visual_descriptor:
        return
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(character.visual_descriptor, encoding="utf-8")


def _validate_stage_target(pose: str, keys: list[str]) -> None:
    """Refuse a ``--stage`` combination approve_stock_cast.py could not act on.

    It only ever looks for ``{angle}_candidate_1.png`` under a ``STOCK_CAST_KEYS``
    key, so a non-standing pose (files are named ``{pose}_{angle}.png``) or a derived
    key would stage cards that can be neither promoted nor rejected — stranded in a
    directory that the next epoch bump turns live.
    """
    if pose != "standing":
        raise SystemExit("--stage supports --pose standing only (approve_stock_cast.py promotes standing cards)")
    unsupported = [key for key in keys if key not in STOCK_DESCRIPTORS]
    if unsupported:
        raise SystemExit(
            f"--stage supports stock keys only ({', '.join(STOCK_DESCRIPTORS)}); got {', '.join(unsupported)}"
        )


def _is_alpha_png_file(path: str | Path | None) -> bool:
    if not path:
        return False
    try:
        return Path(path).is_file() and has_alpha(Path(path).read_bytes())
    except OSError:
        return False


def _all_standing_paths_ready(character, assets_path: Path) -> bool:
    paths = [getattr(character, f"angle_{angle}_path") for angle in ("front", "back", "side", "three_quarter")]
    return all(p and _is_alpha_png_file(assets_path / p) for p in paths)


def _pose_complete(service: CharacterService, key: str, pose: str) -> bool:
    assets_path = Path(service._settings.assets_path)
    if pose == "standing":
        character = service.check_existing_character(key)
        return character is not None and _all_standing_paths_ready(character, assets_path)
    return all(
        (card := service.get_card(key, pose, angle)) is not None and _is_alpha_png_file(assets_path / card.image_path)
        for angle in ("front", "back", "side", "three_quarter")
    )


async def _anchor_search(service: CharacterService, key: str, descriptor: str, settings: Settings) -> int:
    query = descriptor.split(",")[0]
    results = await DuckDuckGoImageSearch().search(query=query, max_results=5)
    review_dir = Path(settings.workspace_path) / "anchor-search" / _sanitize_scp_id(key)
    review_dir.mkdir(parents=True, exist_ok=True)
    for idx, result in enumerate(results, start=1):
        url = result.get("url")
        if not url:
            print(f"skipped: malformed search result #{idx}")
            continue
        try:
            ext = await service._download_reference_image(url, review_dir, idx)
            print(f"downloaded: {review_dir / f'ref_{idx}.{ext}'}")
        except Exception as exc:  # noqa: BLE001 - best-effort curation aid
            print(f"skipped: {url} ({exc})")
    print(f"Review {review_dir}, then rerun with --anchor <path>.")
    return 0


async def seed_key(
    service: CharacterService,
    key: str,
    descriptor: str,
    *,
    pose: str = "standing",
    force: bool = False,
    anchor: str | None = None,
    stage: bool = False,
) -> list[str]:
    if pose not in VALID_POSES:
        raise ValueError(f"pose must be one of {VALID_POSES}")
    if not force and not stage and _pose_complete(service, key, pose):
        print(f"skipped: {key} ({pose})")
        return []
    # Story 10.6: authored derived keys get the same treatment as stock keys, so this
    # manual path cannot contradict run_service's runtime rule. Before that they got
    # neither the suffix nor the ban here while run_service applied both — the same key
    # seeded by hand came out different from the same key seeded by the pipeline, and
    # the hand path was the one a human was most likely to use.
    is_maskless = key in STOCK_DESCRIPTORS or key in DERIVED_DESCRIPTORS
    if stage:
        _snapshot_prestage_descriptor(service, key, service._asset_service.style_epoch + 1)
    paths = await service.generate_cards_from_descriptor(
        key,
        descriptor=descriptor,
        pose=pose,
        anchor_path=anchor,
        negative_suffix=STOCK_NEGATIVE if is_maskless else None,
        # Vision enrichment describes the generated front back into visual_descriptor,
        # and its prompt says "an SCP Foundation character" — the one token these
        # descriptors were purged of, because it is what attracts the mask. Keep the
        # enrichment (it is what holds the four angles to one face) and strip the
        # token from its output. Authored derived looks are defined by the *absence* of
        # a mask, so 10.6 stopped exempting them from the ban.
        enrich_ban=BANNED_STOCK_TOKEN if is_maskless else None,
        stage=stage,
    )
    if len(paths) < 4:
        raise RuntimeError(f"generated incomplete card set for {key} ({pose}): {len(paths)}/4 cards")
    print(f"generated: {key} ({pose}) {len(paths)} cards")
    if stage:
        for path in paths:
            print(f"staged: {path}")
    return paths


async def run(args) -> int:
    if args.stage:
        _validate_stage_target(args.pose, [args.key] if args.key else list(STOCK_CAST_KEYS))
    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        if args.key:
            # DERIVED_DESCRIPTORS is consulted too (Story 10.6), so seeding an authored
            # derived key by hand reproduces the pipeline's look instead of needing the
            # operator to retype it — free-text was how the authored table got bypassed.
            descriptor = (
                args.descriptor
                or STOCK_DESCRIPTORS.get(args.key)
                or DERIVED_DESCRIPTORS.get(args.key)
            )
            if not descriptor:
                raise SystemExit("--descriptor is required with --key")
            targets = {args.key: descriptor}
        else:
            missing = [key for key in STOCK_CAST_KEYS if key not in STOCK_DESCRIPTORS]
            if missing:
                raise SystemExit(f"missing stock descriptors for: {', '.join(missing)}")
            targets = {key: STOCK_DESCRIPTORS[key] for key in STOCK_CAST_KEYS}
            if args.anchor:
                raise SystemExit("--anchor requires --key so one curated image is not reused for every stock cast member")

        if args.anchor_search:
            for key, descriptor in targets.items():
                await _anchor_search(service, key, descriptor, settings)
            return 0

        for key, descriptor in targets.items():
            await seed_key(
                service,
                key,
                descriptor,
                pose=args.pose,
                force=args.force,
                anchor=args.anchor,
                stage=args.stage,
            )
        if args.stage:
            print("staged only — nothing is live until scripts/approve_stock_cast.py runs")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed stock/derived character card sprites.")
    parser.add_argument("--key", help="Seed one derived or stock key instead of all stock keys.")
    parser.add_argument("--descriptor", help="Descriptor for --key derived card generation.")
    parser.add_argument("--pose", default="standing", choices=VALID_POSES, help="Pose key to generate (default: standing).")
    parser.add_argument("--force", action="store_true", help="Regenerate even if cards already exist.")
    parser.add_argument(
        "--stage",
        action="store_true",
        help="Generate into the next style epoch without touching live cards (approve separately).",
    )
    parser.add_argument("--anchor", help="Optional curated front-angle anchor image path.")
    parser.add_argument("--anchor-search", action="store_true", help="Download candidate anchors and stop.")
    return parser


def main(argv=None) -> int:
    return asyncio.run(run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
