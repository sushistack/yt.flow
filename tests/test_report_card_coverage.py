"""Tests for scripts/report_card_coverage.py — Story 14.6's three added axes.

The reporter was EXTENDED rather than duplicated (two sweeps over one population
diverge — `Settings.style_epoch` vs the manifest's is the recorded precedent), so these
tests cover what the extension is for:

* the contract axis sweeps the WHOLE card population, tier A included;
* the reconciliation axis counts MANIFEST card entries, not `character_cards` rows —
  32 of 52 live entries are `standing` and have no row at all, and the most dangerous
  shape (manifest `retired` while `angle_*_path` still publishes the file) lives
  entirely in that blind spot;
* `--demand` judges `served` against the contract, keys warning correspondence on
  `(shot_id, card_key)` because a shot can place two cast members, and refuses rather
  than guesses on an unreadable checkpoint or an ambiguous run prefix.

Every fixture writes into tmp — `Settings.assets_path` defaults to `./assets`, which is
the developer's real card library, and `AssetService.__init__` mkdirs into whatever it
is given.
"""

import asyncio
import importlib.util
import io
import sqlite3

import pytest
from PIL import Image
from sqlmodel import Session

from yt_flow import db
from yt_flow.config import Settings
from yt_flow.services.character_service import CANONICAL_ANGLES, CharacterService
from tests.stubs.fakes import SPRITE_PNG


def _load_script():
    spec = importlib.util.spec_from_file_location("report_card_coverage", "scripts/report_card_coverage.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _rgb_card() -> bytes:
    """The shape SCP-1471 and SCP-682 are in: decodable, portrait-agnostic, no alpha."""
    buffer = io.BytesIO()
    Image.new("RGB", (1664, 928), (90, 90, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def _library(tmp_path, monkeypatch):
    """A tiny two-key library: one good standing set, one alpha-less standing set."""
    assets = tmp_path / "assets"
    monkeypatch.setenv("YTFLOW_DB_PATH", str(tmp_path / "coverage.db"))
    monkeypatch.setenv("YTFLOW_ASSETS_PATH", str(assets))
    db.init(f"sqlite:///{tmp_path / 'coverage.db'}")
    settings = Settings(workspace_path=str(tmp_path / "ws"), assets_path=str(assets))
    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        asset_service = service._asset_service
        for key, payload in (("STOCK-good", SPRITE_PNG), ("SCP-broken", _rgb_card())):
            character = service.create_character(key, key)
            paths = {}
            for angle in CANONICAL_ANGLES:
                rel = f"characters/{key}/epoch_1/{angle}_candidate_1.png"
                (assets / rel).parent.mkdir(parents=True, exist_ok=True)
                (assets / rel).write_bytes(payload)
                paths[f"angle_{angle}_path"] = rel
                asset_service.add_asset(
                    f"{key}/standing_{angle}", rel, source={"type": "test"},
                    card_key=key, pose="standing", angle=angle,
                )
                asset_service.approve_asset(f"{key}/standing_{angle}")
            service.update_character(character.id, selected_image_path=paths["angle_front_path"], **paths)
    return assets, settings


def _run(module, argv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["report_card_coverage.py", *argv])
    asyncio.run(module.main())


def test_contract_axis_sweeps_tier_a_and_names_the_failures(tmp_path, monkeypatch, capsys):
    module = _load_script()
    _library(tmp_path, monkeypatch)

    _run(module, [], monkeypatch)
    out = capsys.readouterr().out

    assert "-- SPRITE CONTRACT over 8 distinct card file(s)" in out
    assert "PASS 4  FAIL 4" in out
    # Tier A is the only addressable home of a `standing` card, so the failures have to
    # be reachable from it — a `character_cards`-only sweep prints nothing here.
    for angle in CANONICAL_ANGLES:
        assert f"SCP-broken standing/{angle} [tier A]" in out
    assert "no_alpha_channel" in out
    assert "observed transparent_fraction band over the passing population" in out


def test_reconciliation_counts_manifest_entries_not_card_rows(tmp_path, monkeypatch, capsys):
    """The population is the 52-entry (here 8-entry) manifest, and the tier-A shape that
    a row-based sweep cannot see — retired in the manifest, still published — prints."""
    module = _load_script()
    assets, settings = _library(tmp_path, monkeypatch)
    with Session(db._engine) as session:
        CharacterService(session, settings=settings)._asset_service.retire_asset("STOCK-good/standing_front")

    _run(module, [], monkeypatch)
    out = capsys.readouterr().out

    assert "-- REGISTRY RECONCILIATION over 8 manifest card entries (8 standing / 0 `character_cards` rows)" in out
    assert "manifest retired / still published in angle_*_path: 1" in out
    assert "STOCK-good/standing_front — manifest retired, still in angle_front_path" in out
    assert "db approved / manifest retired (HALTs reconcile_manifest.py): 0" in out


def test_provenance_never_counts_the_seeding_day_as_regenerated(tmp_path, monkeypatch, capsys):
    module = _load_script()
    assets, settings = _library(tmp_path, monkeypatch)
    with Session(db._engine) as session:
        asset_service = CharacterService(session, settings=settings)._asset_service
        manifest = asset_service.load_manifest()
        for key, day in (
            ("STOCK-good/standing_front", "2026-08-10"),
            ("STOCK-good/standing_back", "2026-08-16"),
            ("STOCK-good/standing_side", "2026-08-20"),
        ):
            manifest["assets"][key]["created_at"] = f"{day}T00:00:00+00:00"
        asset_service.save_manifest(manifest)

    _run(module, [], monkeypatch)
    out = capsys.readouterr().out.split("-- PROMPT PROVENANCE")[1]

    assert "pre-v5       1" in out
    assert "same-day     1" in out
    # The remaining 6 entries were created by this test just now, so they are post-v5.
    assert "post-v5      6" in out
    assert "`same-day` is NOT counted as regenerated" in out


# ── --demand ─────────────────────────────────────────────────────────────────


def _write_checkpoint(db_path, thread_id, channel_values, *, blob=None):
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    typ, payload = JsonPlusSerializer().dumps_typed({"channel_values": channel_values})
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS checkpoints "
            "(thread_id TEXT, checkpoint_id TEXT, type TEXT, checkpoint BLOB)"
        )
        conn.execute(
            "INSERT INTO checkpoints (thread_id, checkpoint_id, type, checkpoint) VALUES (?, ?, ?, ?)",
            (thread_id, "cp-1", typ, blob if blob is not None else payload),
        )


def _scenes(cast):
    return [{"scene_num": 1, "narration": "", "shots": [
        {"shot_id": "S00101", "sentence_indices": [0], "image_prompt": "", "negative_prompt": "",
         "camera_angle": None, "camera_movement": None, "cast": cast},
    ]}]


def test_demand_refuses_to_count_a_contract_failing_card_as_served(tmp_path, monkeypatch, capsys):
    """The §7 inversion, as an executable check: `SCP-broken` has all four
    `angle_*_path` columns populated and every file on disk, so a column-emptiness test
    calls it served. It is RGB, which raises at `video.py:2537` and kills the run."""
    module = _load_script()
    _library(tmp_path, monkeypatch)
    _write_checkpoint(tmp_path / "coverage.db", "run-aaa", {"scenes": _scenes([
        {"card_key": "SCP-broken", "position": "center", "depth": "mid", "pose": "standing"},
        {"card_key": "STOCK-good", "position": "left", "depth": "mid", "pose": "standing"},
    ])})

    _run(module, ["--demand", "run-aaa"], monkeypatch)
    out = capsys.readouterr().out.split("-- OBSERVED DEMAND")[1]

    assert "2 placement(s) across 1 scene(s)" in out
    assert "UNMET 1 of 2 placement(s)" in out
    assert "no_alpha_channel" in out
    assert "NO matching warning" in out  # this checkpoint carries none


def test_demand_matches_warnings_per_card_not_per_shot(tmp_path, monkeypatch, capsys):
    """One shot, two cast members, two independent misses. Keying on `shot_id` alone
    lets the first row's warning stand in for the second and silently drops one — run
    4b35c0ed has 8 multi-cast shots, `S00504` among them."""
    module = _load_script()
    _library(tmp_path, monkeypatch)
    warnings = [
        {"code": "cast_card_fallback", "stage": "video", "message": "-",
         "context": {"shot_id": "S00101", "card_key": "SCP-broken", "fallback_reason": "asset"}},
        {"code": "cast_card_fallback", "stage": "video", "message": "-",
         "context": {"shot_id": "S00101", "card_key": "STOCK-good", "fallback_reason": "asset"}},
    ]
    _write_checkpoint(tmp_path / "coverage.db", "run-bbb", {
        "scenes": _scenes([
            {"card_key": "SCP-broken", "position": "center", "depth": "mid", "pose": "standing"},
            {"card_key": "STOCK-good", "position": "left", "depth": "mid", "pose": "sitting"},
        ]),
        "run_warnings": warnings,
    })

    _run(module, ["--demand", "run-bbb"], monkeypatch)
    out = capsys.readouterr().out.split("-- OBSERVED DEMAND")[1]

    assert "UNMET 2 of 2 placement(s), against 2 `cast_card_fallback` warning(s)" in out
    assert out.count("cast_card_fallback reason=asset") == 2
    assert "warnings with no unmet placement: 0" in out


def test_demand_reraises_on_an_undeserializable_checkpoint(tmp_path, monkeypatch):
    """The 14-0 precedent SKIPS a bad blob because it measures a distribution. This one
    sizes a regeneration batch, and a silently skipped checkpoint understates demand."""
    module = _load_script()
    _library(tmp_path, monkeypatch)
    _write_checkpoint(tmp_path / "coverage.db", "run-ccc", {"scenes": _scenes([])}, blob=b"not msgpack")

    monkeypatch.setattr("sys.argv", ["report_card_coverage.py", "--demand", "run-ccc"])
    with pytest.raises(SystemExit) as excinfo:
        asyncio.run(module.main())
    assert "did not deserialize" in str(excinfo.value)


def test_demand_refuses_an_ambiguous_run_prefix(tmp_path, monkeypatch):
    module = _load_script()
    _library(tmp_path, monkeypatch)
    scenes = _scenes([{"card_key": "STOCK-good", "position": "center", "depth": "mid", "pose": "standing"}])
    _write_checkpoint(tmp_path / "coverage.db", "run-dddaaa", {"scenes": scenes})
    _write_checkpoint(tmp_path / "coverage.db", "run-dddbbb", {"scenes": scenes})

    monkeypatch.setattr("sys.argv", ["report_card_coverage.py", "--demand", "run-ddd"])
    with pytest.raises(SystemExit) as excinfo:
        asyncio.run(module.main())
    assert "refusing to mix runs" in str(excinfo.value)


# ── Story 14.6 review round 2 ────────────────────────────────────────────────


def test_an_entry_with_no_created_at_is_its_own_bucket_and_is_printed(tmp_path, monkeypatch, capsys):
    """`"" < "2026-08-16"` is True, so a missing `created_at` silently landed in
    `pre-v5` — a bucket that is counted in the headline and never listed. It is not
    evidence of a pre-v5 render; it is evidence of nothing."""
    module = _load_script()
    assets, settings = _library(tmp_path, monkeypatch)
    with Session(db._engine) as session:
        asset_service = CharacterService(session, settings=settings)._asset_service
        manifest = asset_service.load_manifest()
        manifest["assets"]["STOCK-good/standing_front"].pop("created_at")
        asset_service.save_manifest(manifest)

    _run(module, [], monkeypatch)
    out = capsys.readouterr().out.split("-- PROMPT PROVENANCE")[1]

    assert "unknown      1" in out
    assert "unknown: STOCK-good/standing_front (no created_at)" in out


def test_a_status_pair_matching_no_named_direction_still_prints(tmp_path, monkeypatch, capsys):
    """Manifest `draft` against an `approved` row matched neither named direction, so it
    printed in no bucket at all — a card the runtime serves whose manifest entry was
    never approved. Two named directions are not a class sweep."""
    module = _load_script()
    assets, settings = _library(tmp_path, monkeypatch)
    with Session(db._engine) as session:
        service = CharacterService(session, settings=settings)
        rel = "characters/STOCK-good/epoch_1/sitting_front.png"
        (assets / rel).write_bytes(SPRITE_PNG)
        service._asset_service.add_asset(  # add_asset alone leaves it `draft`
            "STOCK-good/sitting_front", rel, source={"type": "test"},
            card_key="STOCK-good", pose="sitting", angle="front",
        )
        service.save_card("STOCK-good", "sitting", "front", rel)  # rows are auto-approved

    _run(module, [], monkeypatch)
    out = capsys.readouterr().out.split("-- REGISTRY RECONCILIATION")[1]

    assert "other manifest/db status mismatch (e.g. manifest draft / db approved): 1" in out
    assert "STOCK-good/sitting_front — manifest draft / db approved" in out


def test_demand_serves_an_off_vocabulary_pose_from_the_standing_set(tmp_path, monkeypatch, capsys):
    """`resolve_cast_cards` normalises every non-hint pose before it looks anything up,
    so a checkpoint carrying `kneeling` is served by the standing cards at runtime.
    Reading the raw value reported UNMET for a placement the library covers."""
    module = _load_script()
    _library(tmp_path, monkeypatch)
    _write_checkpoint(tmp_path / "coverage.db", "run-ccc", {"scenes": _scenes([
        {"card_key": "STOCK-good", "position": "center", "depth": "mid", "pose": "kneeling"},
    ])})

    _run(module, ["--demand", "run-ccc"], monkeypatch)
    out = capsys.readouterr().out.split("-- OBSERVED DEMAND")[1]

    assert "UNMET 0 of 1 placement(s)" in out


def test_demand_still_reports_against_an_empty_library(tmp_path, monkeypatch, capsys):
    """`--demand` reads a CHECKPOINT, not the library. Returning early on an empty
    `characters` table printed nothing and exited 0, which reads as "no unmet demand" —
    the opposite of the truth, where every placement is unmet."""
    module = _load_script()
    monkeypatch.setenv("YTFLOW_DB_PATH", str(tmp_path / "empty.db"))
    monkeypatch.setenv("YTFLOW_ASSETS_PATH", str(tmp_path / "assets"))
    db.init(f"sqlite:///{tmp_path / 'empty.db'}")
    _write_checkpoint(tmp_path / "empty.db", "run-ddd", {"scenes": _scenes([
        {"card_key": "STOCK-good", "position": "center", "depth": "mid", "pose": "standing"},
    ])})

    _run(module, ["--demand", "run-ddd"], monkeypatch)
    out = capsys.readouterr().out

    assert "No `characters` rows" in out
    assert "-- OBSERVED DEMAND, run run-ddd" in out
    assert "UNMET 1 of 1 placement(s)" in out
