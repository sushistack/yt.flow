#!/usr/bin/env python
"""Story 14.6 §5: prove every command in the regeneration batch before writing it down.

Spec: `_bmad-output/implementation-artifacts/spec-14-6-dclass-object-asset-sets.md`

Review loop 1 handed over a batch that exits 1 — a single `--key` promotion against a
global orphan check — because nobody ran it. This runs the exact argv of every command
report.md §5 lists, in that order, against a TEMPORARY library, and reports each exit
code.

WHAT THIS PROVES: argv parsing, the staging gate's widened target validation, the
staging invariants (no manifest entry / no card row / no `angle_*_path` write), the
approver's discovery, its atomic-epoch refusals, and the ordering of the batch.

WHAT IT CANNOT PROVE: the pixels. There is no GPU in this session (see report.md §1),
so the ComfyUI provider and the vision read-back are stubbed with a synthetic sprite.
A real run has to render, and a human has to look, before `approve_stock_cast.py` runs.

WHAT THE TMP LIBRARY IS NOT: the live library's data. It reproduces the two properties
the batch's ORDERING depends on — `style_epoch` 2 and a complete staged set already
sitting in `epoch_3` — and nothing else. It builds clean `standing` sets for three fresh
keys, so two shapes the real step 3 will hit are absent here:

  * `add_asset` over an ALREADY-APPROVED manifest entry. `STOCK-d-class/sitting_*` are
    `approved` today, and `add_asset` rewrites the entry wholesale — back to
    `status: "draft"` with a fresh `created_at` and `approved_at: None` (the following
    `approve_asset` re-approves it, so the end state is right and the provenance dates
    are not), while the `epoch_2` file the old entry hashed is left unreferenced.
  * `save_card` reviving a `retired` row. The same four rows are `retired`; the promotion
    sets them back to `approved`.

Both are the intended behaviour of a promotion, and neither changes an exit code, which
is what this harness measures — but "mirrors the live one's shape" would be an
overstatement and an earlier draft of this docstring made it. Recorded in
`deferred-work.md` rather than reproduced here, because reproducing them means building a
second fixture of the live library's status matrix to assert nothing new.

    uv run python .../dryrun_batch.py --residue reject
    uv run python .../dryrun_batch.py --residue promote

`--residue` selects which of the two step-0 options for the 2026-08-16 staging leftover
is exercised. Both are listed in report.md §5, so both are proven; the rest of the batch
is identical either way (the epoch it stages into shifts by one).
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

_REPO_ROOT = Path(__file__).resolve().parents[3]
os.chdir(_REPO_ROOT)
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

# The live shape this harness reproduces, measured 2026-08-29 (report.md §2/§3):
#   - style_epoch 2, so the staging slot is epoch_3;
#   - a COMPLETE STOCK-d-class standing set already sitting in epoch_3 — the 2026-08-16
#     staging residue. Atomic promotion makes clearing it step 0 of any batch, which is
#     exactly the property this harness exists to check.
_RESIDUE_KEY = "STOCK-d-class"
_LIVE_EPOCH = 2
_BATCH_KEYS = ("STOCK-researcher", "SCP-049-2", "STOCK-d-class")


def _sprite() -> bytes:
    from PIL import Image

    image = Image.new("RGBA", (832, 1216), (0, 0, 0, 0))
    for x in range(200, 632):
        for y in range(100, 1150):
            image.putpixel((x, y), (200, 180, 160, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run Story 14.6's regeneration batch.")
    parser.add_argument("--residue", choices=("reject", "promote"), default="reject",
                        help="how step 0 clears the 2026-08-16 staging leftover")
    args = parser.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="ytflow-14-6-dryrun-"))
    assets = tmp / "assets"
    os.environ["YTFLOW_DB_PATH"] = str(tmp / "dryrun.db")
    os.environ["YTFLOW_ASSETS_PATH"] = str(assets)
    os.environ["YTFLOW_WORKSPACE_PATH"] = str(tmp / "workspace")

    from sqlmodel import Session

    from yt_flow import db
    from yt_flow.config import Settings
    from yt_flow.services.character_service import CANONICAL_ANGLES, CharacterService

    settings = Settings()
    db.init(f"sqlite:///{settings.db_path}")
    sprite = _sprite()

    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        asset_service = service._asset_service
        for key in _BATCH_KEYS:
            character = service.create_character(key, key)
            live = {}
            for angle in CANONICAL_ANGLES:
                rel = f"characters/{key}/epoch_{_LIVE_EPOCH}/{angle}_candidate_1.png"
                (assets / rel).parent.mkdir(parents=True, exist_ok=True)
                (assets / rel).write_bytes(sprite)
                live[f"angle_{angle}_path"] = rel
                asset_service.add_asset(
                    f"{key}/standing_{angle}", rel, source={"type": "dryrun"},
                    card_key=key, pose="standing", angle=angle,
                )
                asset_service.approve_asset(f"{key}/standing_{angle}")
            service.update_character(
                character.id, visual_descriptor=f"authored look for {key}",
                selected_image_path=live["angle_front_path"], **live,
            )
        manifest = asset_service.load_manifest()
        manifest["style_epoch"] = _LIVE_EPOCH
        asset_service.save_manifest(manifest)
        # The 2026-08-16 residue, reproduced: a complete staged standing set plus its
        # write-once sidecar, in what is also the next staging slot.
        residue = assets / "characters" / _RESIDUE_KEY / f"epoch_{_LIVE_EPOCH + 1}"
        residue.mkdir(parents=True, exist_ok=True)
        for angle in CANONICAL_ANGLES:
            (residue / f"{angle}_candidate_1.png").write_bytes(sprite)
        (residue / "_prestage_descriptor.txt").write_text("pre-stage text", encoding="utf-8")

    seed = _load("seed_stock_cast")
    approve = _load("approve_stock_cast")

    provider = SimpleNamespace(
        produces_alpha=True, supports_i2i=True, last_i2i_fallback=False,
        generate=AsyncMock(return_value=sprite),
    )
    CharacterService._get_image_provider = lambda self: provider

    async def _no_enrichment(self, scp_id, ref_image_paths):
        return None

    CharacterService.enrich_descriptor_from_references = _no_enrichment

    staging_epoch = _LIVE_EPOCH + (2 if args.residue == "promote" else 1)
    batch: list[tuple[str, object, list[str], int]] = [
        (f"clear the 2026-08-16 staging residue ({args.residue} leg)", approve,
         ["--reject"] if args.residue == "reject" else [], 0),
        *[
            (f"stage the sitting set for {key}", seed,
             ["--stage", "--key", key, "--pose", "sitting"], 0)
            for key in _BATCH_KEYS
        ],
        ("refuse a partial promotion of the staged epoch", approve, ["--key", _BATCH_KEYS[0]], 1),
        (f"promote epoch_{staging_epoch} whole", approve, [], 0),
        ("a second promotion finds nothing — the bump moved the staging slot", approve, [], 1),
    ]

    failures = 0
    print(f"dry-run library: {tmp}\n")
    for label, module, command_argv, expected in batch:
        script = "approve_stock_cast.py" if module is approve else "seed_stock_cast.py"
        print(f"$ uv run python scripts/{script} {' '.join(command_argv)}")
        print(f"  ({label}; expecting exit {expected})")
        code = module.main(command_argv)
        print(f"  -> exit {code}\n")
        if code != expected:
            failures += 1
            print(f"  !! MISMATCH: expected {expected}, got {code}\n")

    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        epoch = service._asset_service.style_epoch
        print(f"style_epoch after the batch: {epoch} (was {_LIVE_EPOCH}, staged into "
              f"epoch_{staging_epoch})")
        for key in _BATCH_KEYS:
            rows = [service.get_card(key, "sitting", angle) for angle in CANONICAL_ANGLES]
            stamped = sorted({row.style_epoch for row in rows if row})
            print(f"  {key:<18} sitting rows {sum(row is not None for row in rows)}/4  style_epoch {stamped}")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'BATCH OK — every command returned its expected exit code' if not failures else f'{failures} COMMAND(S) MISMATCHED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
