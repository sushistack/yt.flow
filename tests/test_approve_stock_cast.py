"""Tests for scripts/approve_stock_cast.py (Story 8.15, widened by Story 14.6).

This script is the only thing in the repo that can destroy live card assets: it
repoints ``Character.angle_*_path`` — a bare column read at runtime — and bumps the
global ``style_epoch``, which is what decides where the *next* ``--stage`` run writes.
So every refusal path is asserted to leave live state untouched, not merely to exit
non-zero. Uses a tmp DB + tmp assets root via env overrides; never the repo's own.

Story 14.6 added the three regressions at the bottom of this file. Each one was
REPRODUCED by a reviewer against the design this script used to have (per-pose orphan
checks, ``bump_style_epoch()`` only on ``standing``), and each one destroyed live
approved state. They pin the atomic-epoch contract, not an implementation detail.
"""

import asyncio
import importlib.util
import struct
import zlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.domain.state import STOCK_CAST_KEYS
from yt_flow.services.character_service import CANONICAL_ANGLES, CharacterService
from tests.stubs.fakes import SPRITE_PNG, sprite_png


def _load_script():
    spec = importlib.util.spec_from_file_location("approve_stock_cast", "scripts/approve_stock_cast.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _rgb_png() -> bytes:
    """A valid 1x1 PNG with color_type=2 — no alpha channel, so it must be refused."""
    def chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00"))
        + chunk(b"IEND", b"")
    )


def _live_path(key: str, angle: str) -> str:
    return f"characters/{key}/epoch_1/{angle}_candidate_1.png"


def _staged_rel(key: str, angle: str, pose: str = "standing") -> str:
    name = f"{angle}_candidate_1.png" if pose == "standing" else f"{pose}_{angle}.png"
    return f"characters/{key}/epoch_2/{name}"


def _setup(tmp_path, monkeypatch, keys=STOCK_CAST_KEYS, descriptor="live descriptor"):
    """Point Settings at a tmp DB + tmp assets root and seed a complete live epoch_1."""
    assets = tmp_path / "assets"
    monkeypatch.setenv("YTFLOW_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("YTFLOW_ASSETS_PATH", str(assets))
    db.init(f"sqlite:///{tmp_path / 'test.db'}")
    settings = Settings(workspace_path=str(tmp_path / "workspace"), assets_path=str(assets))
    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        for key in keys:
            character = service.create_character(key, key)
            live = {f"angle_{angle}_path": _live_path(key, angle) for angle in CANONICAL_ANGLES}
            for rel in live.values():
                (assets / rel).parent.mkdir(parents=True, exist_ok=True)
                (assets / rel).write_bytes(SPRITE_PNG)
            service.update_character(
                character.id,
                visual_descriptor=descriptor,
                selected_image_path=_live_path(key, "front"),
                **live,
            )
    return assets


def _stage(assets, key, *, pose="standing", angles=CANONICAL_ANGLES, payload=SPRITE_PNG,
           prestage=None, poststage=None):
    """Write what ``seed_stock_cast.py --stage`` writes.

    ``poststage`` is the descriptor as that stage LEFT it. ``--reject`` restores the
    pre-stage sidecar only while the live column still holds this — otherwise the column
    has been edited since and the sidecar is not what "undo this stage" means.
    """
    directory = assets / "characters" / key / "epoch_2"
    directory.mkdir(parents=True, exist_ok=True)
    for angle in angles:
        name = f"{angle}_candidate_1.png" if pose == "standing" else f"{pose}_{angle}.png"
        (directory / name).write_bytes(payload)
    if prestage is not None:
        (directory / "_prestage_descriptor.txt").write_text(prestage, encoding="utf-8")
    if poststage is not None:
        (directory / "_poststage_descriptor.txt").write_text(poststage, encoding="utf-8")
    return directory


def _characters(assets, tmp_path):
    settings = Settings(workspace_path=str(tmp_path / "workspace"), assets_path=str(assets))
    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        return {key: service.check_existing_character(key) for key in STOCK_CAST_KEYS}


def _asset_service(assets, tmp_path):
    settings = Settings(workspace_path=str(tmp_path / "workspace"), assets_path=str(assets))
    with Session(db._engine) as session:
        return CharacterService(session, settings=settings)._asset_service


def _cards(assets, tmp_path, key, pose):
    settings = Settings(workspace_path=str(tmp_path / "workspace"), assets_path=str(assets))
    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        return {angle: service.get_card(key, pose, angle) for angle in CANONICAL_ANGLES}


def _assert_live_untouched(assets, tmp_path):
    for key, character in _characters(assets, tmp_path).items():
        for angle in CANONICAL_ANGLES:
            assert getattr(character, f"angle_{angle}_path") == _live_path(key, angle)
        assert character.selected_image_path == _live_path(key, "front")
    asset_service = _asset_service(assets, tmp_path)
    assert asset_service.style_epoch == 1
    assert asset_service.load_manifest()["assets"] == {}


def test_promote_repoints_every_angle_and_approves_the_manifest(tmp_path, monkeypatch):
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch)
    for key in STOCK_CAST_KEYS:
        _stage(assets, key, prestage="live descriptor")

    assert approve.run(list(STOCK_CAST_KEYS), reject=False) == 0

    for key, character in _characters(assets, tmp_path).items():
        for angle in CANONICAL_ANGLES:
            assert getattr(character, f"angle_{angle}_path") == _staged_rel(key, angle)
        assert character.selected_image_path == _staged_rel(key, "front")
    asset_service = _asset_service(assets, tmp_path)
    manifest = asset_service.load_manifest()["assets"]
    for key in STOCK_CAST_KEYS:
        for angle in CANONICAL_ANGLES:
            entry = manifest[f"{key}/standing_{angle}"]
            assert entry["status"] == "approved"
            assert entry["path"] == _staged_rel(key, angle)
    # The bump retires epoch_2 as a staging target so the next --stage cannot
    # regenerate over the files just promoted.
    assert asset_service.style_epoch == 2
    # The sidecar exists only to undo a rejection; promotion consumes it.
    assert not (assets / "characters" / STOCK_CAST_KEYS[0] / "epoch_2" / "_prestage_descriptor.txt").exists()


def test_missing_staged_card_refuses_and_leaves_live_state_untouched(tmp_path, monkeypatch):
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch)
    for key in STOCK_CAST_KEYS:
        _stage(assets, key)
    (assets / "characters" / STOCK_CAST_KEYS[-1] / "epoch_2" / "back_candidate_1.png").unlink()

    assert approve.run(list(STOCK_CAST_KEYS), reject=False) == 1
    _assert_live_untouched(assets, tmp_path)


def test_alpha_less_staged_card_refuses(tmp_path, monkeypatch):
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch)
    for key in STOCK_CAST_KEYS:
        _stage(assets, key)
    _stage(assets, STOCK_CAST_KEYS[-1], angles=["side"], payload=_rgb_png())

    assert approve.run(list(STOCK_CAST_KEYS), reject=False) == 1
    _assert_live_untouched(assets, tmp_path)


def test_fully_opaque_rgba_staged_card_refuses(tmp_path, monkeypatch):
    """`has_alpha`'s blind spot: color type 6 with not one transparent pixel. This is
    the shape an empty-descriptor render came back as, and the pre-14.6 gate promoted it."""
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch)
    for key in STOCK_CAST_KEYS:
        _stage(assets, key)
    _stage(assets, STOCK_CAST_KEYS[0], angles=["front"], payload=sprite_png(opaque=True))

    assert approve.run(list(STOCK_CAST_KEYS), reject=False) == 1
    _assert_live_untouched(assets, tmp_path)


def test_corrupt_container_refuses_even_though_the_sprite_contract_passes(tmp_path, monkeypatch):
    """Both checks stand at the gate because neither subsumes the other.

    A flipped IEND CRC is invisible to Pillow, so `sprite_contract` returns
    ``(True, "ok")`` on these exact bytes — asserted here so the test fails loudly if
    someone "simplifies" the gate down to the contract alone. `has_alpha` walks the
    chunk CRCs and is what refuses it; `video.py:2537` runs the same check at render
    time and raises, killing the run.
    """
    from yt_flow.domain.png import has_alpha, sprite_contract

    corrupt = bytearray(SPRITE_PNG)
    corrupt[-1] ^= 0xFF
    assert sprite_contract(bytes(corrupt)) == (True, "ok")
    assert has_alpha(bytes(corrupt)) is False

    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch)
    for key in STOCK_CAST_KEYS:
        _stage(assets, key)
    _stage(assets, STOCK_CAST_KEYS[1], angles=["back"], payload=bytes(corrupt))

    assert approve.run(list(STOCK_CAST_KEYS), reject=False) == 1
    _assert_live_untouched(assets, tmp_path)


def test_reject_deletes_the_staged_dir_and_restores_the_descriptor(tmp_path, monkeypatch):
    """Staging overwrites visual_descriptor, which runtime reads — leaving the STOCK
    text behind would describe cards that no longer exist."""
    assets = _setup(tmp_path, monkeypatch, descriptor="staged STOCK descriptor")
    approve = _load_script()
    for key in STOCK_CAST_KEYS:
        _stage(assets, key, prestage="original poisoned descriptor",
               poststage="staged STOCK descriptor")

    assert approve.run(list(STOCK_CAST_KEYS), reject=True) == 0

    for key, character in _characters(assets, tmp_path).items():
        assert not (assets / "characters" / key / "epoch_2").exists()
        assert character.visual_descriptor == "original poisoned descriptor"
    _assert_live_untouched(assets, tmp_path)


def test_reject_without_a_sidecar_leaves_the_descriptor_alone(tmp_path, monkeypatch):
    """An absent sidecar does NOT mean "there was no descriptor before staging".

    Promotion consumes the sidecar, so "absent" is also the state right after a
    promotion. Writing `None` back on absence is how review loop 1 wiped a live
    descriptor and still exited 0. The descriptor is only ever restored from a value
    that was actually snapshotted.
    """
    assets = _setup(tmp_path, monkeypatch, descriptor="staged STOCK descriptor")
    approve = _load_script()
    _stage(assets, STOCK_CAST_KEYS[0])

    assert approve.run([STOCK_CAST_KEYS[0]], reject=True) == 0
    assert _characters(assets, tmp_path)[STOCK_CAST_KEYS[0]].visual_descriptor == "staged STOCK descriptor"


def test_reject_with_nothing_staged_exits_non_zero(tmp_path, monkeypatch):
    """After a promotion `epoch` points past the retired staging epoch, so a mistaken
    --reject finds nothing — exiting 0 would read as a successful undo."""
    approve = _load_script()
    _setup(tmp_path, monkeypatch)

    assert approve.run(list(STOCK_CAST_KEYS), reject=True) == 1


def test_a_key_without_a_character_row_blocks_the_whole_promotion(tmp_path, monkeypatch):
    """A staged directory whose key has no `characters` row cannot be promoted, and it
    cannot be silently skipped either: the closing bump would strand it in a live epoch."""
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch, keys=STOCK_CAST_KEYS[:-1])
    for key in STOCK_CAST_KEYS:
        _stage(assets, key)

    assert approve.run(list(STOCK_CAST_KEYS), reject=False) == 1

    asset_service = _asset_service(assets, tmp_path)
    assert asset_service.style_epoch == 1
    assert asset_service.load_manifest()["assets"] == {}
    for key, character in _characters(assets, tmp_path).items():
        if character is None:
            continue
        assert character.angle_front_path == _live_path(key, "front")


def test_single_key_promotion_refused_while_a_sibling_is_staged(tmp_path, monkeypatch):
    """The closing bump retires epoch_2, orphaning any sibling left staged in what is
    now a live epoch directory."""
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch)
    for key in STOCK_CAST_KEYS:
        _stage(assets, key)

    assert approve.run([STOCK_CAST_KEYS[0]], reject=False) == 1
    _assert_live_untouched(assets, tmp_path)


def test_single_key_promotion_allowed_when_no_sibling_is_staged(tmp_path, monkeypatch):
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch)
    _stage(assets, STOCK_CAST_KEYS[0])

    assert approve.run([STOCK_CAST_KEYS[0]], reject=False) == 0
    assert _characters(assets, tmp_path)[STOCK_CAST_KEYS[0]].angle_front_path == _staged_rel(
        STOCK_CAST_KEYS[0], "front"
    )


def test_a_sidecar_only_directory_blocks_the_promotion(tmp_path, monkeypatch):
    """A stage that died after writing its sidecar leaves a directory with no cards.

    Discovery that only looks for card files reports "nothing staged" for it, and the
    closing bump then makes that directory live with a stray sidecar in it.
    """
    approve = _load_script()
    assets = _setup(tmp_path, monkeypatch)
    _stage(assets, STOCK_CAST_KEYS[0])
    residue = assets / "characters" / STOCK_CAST_KEYS[1] / "epoch_2"
    residue.mkdir(parents=True, exist_ok=True)
    (residue / "_prestage_descriptor.txt").write_text("half a stage", encoding="utf-8")

    assert approve.run(reject=False) == 1
    _assert_live_untouched(assets, tmp_path)


# ── Story 14.6: the atomic-epoch contract ────────────────────────────────────


def test_standing_and_sitting_staged_together_are_promoted_together(tmp_path, monkeypatch):
    """Regression 1 — reproduced by review: the staged `sitting` set was stranded.

    The old design bumped globally on a `standing` promotion while checking orphans per
    pose, so the `sitting` cards were left in `epoch_2`, which the bump had just made
    live. Neither a later promotion nor `--reject` could reach them: both compute
    `epoch_3`.
    """
    approve = _load_script()
    key = STOCK_CAST_KEYS[0]
    assets = _setup(tmp_path, monkeypatch, keys=[key])
    _stage(assets, key, pose="standing")
    _stage(assets, key, pose="sitting")

    # Narrowing to one pose cannot promote half of the epoch.
    assert approve.run([key], ["standing"], reject=False) == 1
    assert _asset_service(assets, tmp_path).style_epoch == 1

    assert approve.run(reject=False) == 0

    manifest = _asset_service(assets, tmp_path).load_manifest()["assets"]
    for angle in CANONICAL_ANGLES:
        assert manifest[f"{key}/standing_{angle}"]["status"] == "approved"
        assert manifest[f"{key}/sitting_{angle}"]["status"] == "approved"
        assert manifest[f"{key}/sitting_{angle}"]["path"] == _staged_rel(key, angle, "sitting")
    character = _characters(assets, tmp_path)[key]
    for angle in CANONICAL_ANGLES:
        assert getattr(character, f"angle_{angle}_path") == _staged_rel(key, angle)


def test_non_standing_promotion_stamps_the_epoch_the_files_live_in(tmp_path, monkeypatch):
    """`save_card` stamps the CURRENT manifest epoch, and the bump comes last — so an
    unstamped row claims epoch_1 for a file in epoch_2 and reads as off-epoch."""
    approve = _load_script()
    key = STOCK_CAST_KEYS[0]
    assets = _setup(tmp_path, monkeypatch, keys=[key])
    _stage(assets, key, pose="sitting")

    assert approve.run(reject=False) == 0

    for angle, card in _cards(assets, tmp_path, key, "sitting").items():
        assert card is not None
        assert card.style_epoch == 2
        assert card.image_path == _staged_rel(key, angle, "sitting")
    # A non-standing promotion is not a standing publication.
    character = _characters(assets, tmp_path)[key]
    assert character.angle_front_path == _live_path(key, "front")


def test_reject_after_a_promotion_does_not_delete_the_live_cards(tmp_path, monkeypatch):
    """Regression 2 — reproduced by review: `--reject` deleted four LIVE approved cards.

    Without the closing bump, `epoch` after a promotion still resolved to the directory
    that had just been published, so `--reject` rmtree'd it, "restored" a `None`
    descriptor over the live one, and exited 0.
    """
    approve = _load_script()
    key = STOCK_CAST_KEYS[0]
    assets = _setup(tmp_path, monkeypatch, keys=[key])
    _stage(assets, key, pose="sitting", prestage="original descriptor")

    assert approve.run(reject=False) == 0
    promoted = assets / "characters" / key / "epoch_2"
    descriptor_after_promotion = _characters(assets, tmp_path)[key].visual_descriptor

    assert approve.run([key], ["sitting"], reject=True) == 1

    for angle in CANONICAL_ANGLES:
        assert (promoted / f"sitting_{angle}.png").is_file()
    assert _characters(assets, tmp_path)[key].visual_descriptor == descriptor_after_promotion
    asset_service = _asset_service(assets, tmp_path)
    for angle in CANONICAL_ANGLES:
        assert asset_service.verify_asset(f"{key}/sitting_{angle}")


def _stub_generation(monkeypatch, payload=SPRITE_PNG):
    """Real generation wiring, fake pixels — no GPU, no vision call."""
    provider = SimpleNamespace(
        produces_alpha=True, supports_i2i=True, last_i2i_fallback=False,
        generate=AsyncMock(return_value=payload),
    )
    monkeypatch.setattr(CharacterService, "_get_image_provider", lambda self: provider)

    async def no_enrichment(self, scp_id, ref_image_paths):
        return None

    monkeypatch.setattr(CharacterService, "enrich_descriptor_from_references", no_enrichment)
    return provider


def test_restaging_a_promoted_pose_cannot_overwrite_the_approved_pixels(tmp_path, monkeypatch):
    """Regression 3 — reproduced by review: the next `--stage` wrote over live pixels.

    The staging directory is `epoch_{style_epoch + 1}`, so a promotion that does not
    bump leaves its own output as the next stage's target: the manifest keeps the sha256
    of bytes that are no longer on disk and `verify_asset` starts failing on approved
    assets.

    Driven through ``seed.run(--stage)`` with the real filename and epoch arithmetic,
    not by writing where a re-stage is *believed* to write — that earlier form restated
    ``N + 1 != N`` and would have kept passing through a change to either.
    """
    approve = _load_script()
    seed_spec = importlib.util.spec_from_file_location("seed_stock_cast", "scripts/seed_stock_cast.py")
    seed = importlib.util.module_from_spec(seed_spec)
    seed_spec.loader.exec_module(seed)

    key = STOCK_CAST_KEYS[0]
    assets = _setup(tmp_path, monkeypatch, keys=[key])
    monkeypatch.setenv("YTFLOW_WORKSPACE_PATH", str(tmp_path / "workspace"))
    _stage(assets, key, pose="standing")

    assert approve.run(reject=False) == 0
    promoted_dir = assets / "characters" / key / "epoch_2"
    promoted_bytes = {
        angle: (promoted_dir / f"{angle}_candidate_1.png").read_bytes() for angle in CANONICAL_ANGLES
    }

    _stub_generation(monkeypatch, payload=sprite_png(width=32, height=96))
    args = seed.build_parser().parse_args(["--stage", "--key", key, "--pose", "standing"])
    assert asyncio.run(seed.run(args)) == 0

    asset_service = _asset_service(assets, tmp_path)
    for angle in CANONICAL_ANGLES:
        assert asset_service.verify_asset(f"{key}/standing_{angle}")
        assert (promoted_dir / f"{angle}_candidate_1.png").read_bytes() == promoted_bytes[angle]
    # It landed one epoch on, which is the only reason the bytes above survived.
    assert (assets / "characters" / key / "epoch_3" / "front_candidate_1.png").is_file()


# ── Story 14.6 review round 2: a crashed stage must not wedge the epoch ──────


def test_a_blocked_epoch_can_still_be_rejected(tmp_path, monkeypatch):
    """`--reject` is the recovery FROM a blocker, so blockers must not gate it.

    `seed_stock_cast.py` snapshots the descriptor and lets generation replace the live
    one before it raises on an incomplete set, so a ComfyUI crash (Story 5.23) lands as
    exactly this: an incomplete directory beside a sidecar-only one, with the live
    descriptor already holding staging text. Refusing rejection here left `rm -rf`
    inside `assets/` as the only way out — which is what this gate exists to prevent.
    """
    approve = _load_script()
    incomplete, half_dead = STOCK_CAST_KEYS[0], STOCK_CAST_KEYS[1]
    assets = _setup(tmp_path, monkeypatch, descriptor="text the crashed stage installed")
    _stage(assets, incomplete, angles=["front", "back"],
           prestage="the descriptor before the stage", poststage="text the crashed stage installed")
    residue = assets / "characters" / half_dead / "epoch_2"
    residue.mkdir(parents=True, exist_ok=True)
    (residue / "_prestage_descriptor.txt").write_text("the descriptor before the stage", encoding="utf-8")

    # Promotion is (correctly) refused by the blockers.
    assert approve.run(reject=False) == 1
    # Rejection is not.
    assert approve.run(reject=True) == 0

    assert not (assets / "characters" / incomplete / "epoch_2").exists()
    assert not residue.exists()
    characters = _characters(assets, tmp_path)
    assert characters[incomplete].visual_descriptor == "the descriptor before the stage"
    _assert_live_untouched(assets, tmp_path)


def test_a_narrowed_reject_leaves_a_staged_sibling_alone(tmp_path, monkeypatch):
    """Rejecting one key must not force discarding a good sibling.

    The all-or-nothing rule is a PROMOTION rule — it exists because the closing bump
    would orphan whatever a narrowed promotion left behind. A rejection publishes
    nothing and bumps nothing, so the same refusal would only mean "delete the good set
    too, or re-render both".
    """
    approve = _load_script()
    bad, good = STOCK_CAST_KEYS[0], STOCK_CAST_KEYS[1]
    assets = _setup(tmp_path, monkeypatch)
    _stage(assets, bad, angles=["front"])
    _stage(assets, good)

    assert approve.run([bad], reject=True) == 0

    assert not (assets / "characters" / bad / "epoch_2").exists()
    assert (assets / "characters" / good / "epoch_2" / "front_candidate_1.png").is_file()
    # And the survivor is promotable on its own now that it is the only staged set.
    assert approve.run(reject=False) == 0
    assert _characters(assets, tmp_path)[good].angle_front_path == _staged_rel(good, "front")


def test_reject_refuses_to_restore_a_descriptor_edited_since_the_stage(tmp_path, monkeypatch):
    """The sidecar is only "the text to go back to" while nothing has edited the column.

    Live case that motivated it: `STOCK-d-class/epoch_3` carries a sidecar that diverges
    from the live descriptor from character 380 on. A directory staged before Story 14.6
    has no post-stage record to settle which of the two is that staging's own product,
    so the restore is refused and the staged files still go — an operator can paste the
    sidecar back, but nobody can recover a descriptor this script has overwritten.
    """
    approve = _load_script()
    key = STOCK_CAST_KEYS[0]
    assets = _setup(tmp_path, monkeypatch, keys=[key], descriptor="edited by hand after the stage")
    directory = _stage(assets, key, prestage="the descriptor before the stage",
                       poststage="text the stage installed")

    assert approve.run([key], reject=True) == 0

    assert not directory.exists()
    assert _characters(assets, tmp_path)[key].visual_descriptor == "edited by hand after the stage"


def test_a_failure_mid_promotion_still_bumps_the_epoch(tmp_path, monkeypatch):
    """A raise inside the promotion loop used to return short of `bump_style_epoch()`.

    The earlier keys are ALREADY live at that point, so without the bump the staging slot
    is still the directory they live in: the next `--stage` overwrites approved pixels
    and a `--reject` deletes them — this module's failure mode 3, reached by the failure
    path instead of by design.
    """
    approve = _load_script()
    keys = list(STOCK_CAST_KEYS[:2])
    assets = _setup(tmp_path, monkeypatch, keys=keys)
    for key in keys:
        _stage(assets, key)

    original = approve._retire_special_pose_cards

    def boom(session, service, key):
        if key == keys[1]:
            raise RuntimeError("the promotion died half-way")
        return original(session, service, key)

    monkeypatch.setattr(approve, "_retire_special_pose_cards", boom)

    with pytest.raises(RuntimeError, match="died half-way"):
        approve.run(reject=False)

    asset_service = _asset_service(assets, tmp_path)
    assert asset_service.style_epoch == 2
    # The key that did go live is published, and epoch_2 is no longer a staging target.
    assert _characters(assets, tmp_path)[keys[0]].angle_front_path == _staged_rel(keys[0], "front")
