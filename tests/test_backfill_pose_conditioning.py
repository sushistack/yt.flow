"""Tests for the pose_conditioning column migration + curated backfill (Story 8.20, AC4)."""

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlmodel import Session, select

from yt_flow import db
from yt_flow.db.models import Character
from yt_flow.domain.pose import DEFAULT_POSE_CONDITIONING, POSE_CONDITIONING_PROFILES

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "backfill_pose_conditioning.py"


def _isolate_db(tmp_path, monkeypatch, name: str) -> str:
    """Point the script's Settings() at a throwaway DB.

    Must go through the env var, not setattr on the class: main() constructs a
    fresh Settings(), which re-reads the environment and would otherwise resolve
    the real ./yt_flow.db and rewrite the developer's live character rows.
    """
    monkeypatch.setenv("YTFLOW_DB_PATH", str(tmp_path / name))
    return f"sqlite:///{tmp_path / name}"


@pytest.fixture
def mod():
    spec = importlib.util.spec_from_file_location("backfill_pose_conditioning", _SCRIPT)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    sys.modules["backfill_pose_conditioning"] = m
    spec.loader.exec_module(m)
    return m


# ── Column default + migration ──────────────────────────────────────────────


def test_new_characters_default_to_the_safe_route():
    """AC4: every creation path sets edit_only, so an uncurated character can
    never have a human skeleton applied to a non-human body."""
    db.init("sqlite://")
    with Session(db._engine) as s:
        s.add(Character(scp_id="SCP-9999", canonical_name="Unknown"))
        s.commit()
        assert s.exec(select(Character)).one().pose_conditioning == DEFAULT_POSE_CONDITIONING


def test_migration_self_heals_a_pre_8_20_database(tmp_path):
    """The real regression this guards: create_all() never adds a column to an
    existing table, so without _ensure_character_columns a pre-8.20 DB raises
    "no such column: pose_conditioning" on the first character read.
    """
    db_file = tmp_path / "legacy.db"
    url = f"sqlite:///{db_file}"

    # Build a genuine pre-8.20 characters table: same shape, column absent.
    db.init(url)
    with db._engine.connect() as conn:
        conn.exec_driver_sql("DROP TABLE characters")
        conn.exec_driver_sql(
            "CREATE TABLE characters ("
            "id TEXT PRIMARY KEY, scp_id TEXT, canonical_name TEXT, aliases JSON, "
            "visual_descriptor TEXT, style_guide TEXT, image_prompt_base TEXT, "
            "selected_image_path TEXT, angle_front_path TEXT, angle_back_path TEXT, "
            "angle_side_path TEXT, angle_three_quarter_path TEXT, created_at TEXT, updated_at TEXT)",
        )
        conn.exec_driver_sql(
            "INSERT INTO characters (id, scp_id, canonical_name, created_at, updated_at) "
            "VALUES ('id-1', 'SCP-049', 'Plague Doctor', 'x', 'x')",
        )
        conn.commit()
    with db._engine.connect() as conn:
        assert "pose_conditioning" not in {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(characters)")
        }

    db.init(url)  # re-init must migrate in place

    with Session(db._engine) as s:
        row = s.exec(select(Character)).one()
    assert row.scp_id == "SCP-049"
    assert row.pose_conditioning == DEFAULT_POSE_CONDITIONING, (
        "the pre-existing row must be explicitly backfilled, not left NULL"
    )


def test_migration_is_idempotent(tmp_path):
    url = f"sqlite:///{tmp_path / 'x.db'}"
    db.init(url)
    with Session(db._engine) as s:
        s.add(Character(scp_id="SCP-049", canonical_name="Plague Doctor", pose_conditioning="openpose"))
        s.commit()
    db.init(url)
    db.init(url)
    with Session(db._engine) as s:
        assert s.exec(select(Character)).one().pose_conditioning == "openpose", (
            "re-running init() must not clobber a curated value"
        )


# ── Curated mapping ─────────────────────────────────────────────────────────


def test_curated_values_are_all_inside_the_closed_vocabulary(mod):
    for key, value in mod.CURATED.items():
        assert value in POSE_CONDITIONING_PROFILES, f"{key} -> {value}"


def test_curated_mapping_matches_the_story_seed(mod):
    """AC4 names this exact mapping; SCP-1471 stays edit_only until separately
    approved because its depictions are inconsistent between humanoid and quadruped."""
    assert mod.CURATED == {
        "STOCK-d-class": "openpose",
        "STOCK-researcher": "openpose",
        "STOCK-security": "openpose",
        "SCP-049": "openpose",
        "SCP-049-2": "openpose",
        "SCP-096": "openpose",
        "SCP-682": "scribble",
        "SCP-1471": "edit_only",
    }


def test_non_humanoid_characters_never_get_the_humanoid_profile(mod):
    """SCP-682 is the non-humanoid case the story is explicit about."""
    assert mod.CURATED["SCP-682"] != "openpose"


def test_backfill_applies_the_curated_mapping_and_is_idempotent(tmp_path, monkeypatch, mod, capsys):
    url = _isolate_db(tmp_path, monkeypatch, "b.db")
    db.init(url)
    with Session(db._engine) as s:
        for scp_id in ("SCP-049", "SCP-682", "SCP-1471", "SCP-NEW"):
            s.add(Character(scp_id=scp_id, canonical_name=scp_id))
        s.commit()

    monkeypatch.setattr(sys, "argv", ["backfill_pose_conditioning.py"])
    assert mod.main() == 0

    with Session(db._engine) as s:
        got = {c.scp_id: c.pose_conditioning for c in s.exec(select(Character)).all()}
    assert got == {
        "SCP-049": "openpose",
        "SCP-682": "scribble",
        "SCP-1471": "edit_only",
        "SCP-NEW": DEFAULT_POSE_CONDITIONING,  # uncurated stays safe
    }

    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "changed=0" in out


def test_backfill_dry_run_writes_nothing(tmp_path, monkeypatch, mod):
    url = _isolate_db(tmp_path, monkeypatch, "d.db")
    db.init(url)
    with Session(db._engine) as s:
        s.add(Character(scp_id="SCP-049", canonical_name="SCP-049"))
        s.commit()

    monkeypatch.setattr(sys, "argv", ["backfill_pose_conditioning.py", "--dry-run"])
    assert mod.main() == 0
    with Session(db._engine) as s:
        assert s.exec(select(Character)).one().pose_conditioning == DEFAULT_POSE_CONDITIONING


def test_backfill_refuses_a_mapping_outside_the_closed_vocabulary(tmp_path, monkeypatch, mod):
    """A typo'd profile would be written to the DB and then silently degrade to
    edit_only at routing time — fail loudly at the source instead."""
    _isolate_db(tmp_path, monkeypatch, "v.db")
    monkeypatch.setitem(mod.CURATED, "SCP-049", "openpse")
    monkeypatch.setattr(sys, "argv", ["backfill_pose_conditioning.py"])
    assert mod.main() == 1
