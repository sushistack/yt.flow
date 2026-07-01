"""Unit tests for Character + ReferenceImage TypedDict shapes and SQLModel table creation.
AC: 1, 6
"""

from typing import get_type_hints

import pytest

import yt_flow.domain.state as state
from yt_flow import db
from yt_flow.db.models import Character, ReferenceImage


class TestCharacterTypedDict:
    """AC1: TypedDict imports without error."""

    def test_character_typeddict_import(self):
        assert hasattr(state, "Character")
        assert hasattr(state, "ReferenceImage")
        assert hasattr(state, "SearchResult")
        assert hasattr(state, "AngleName")

    def test_character_fields_match_ac6(self):
        """AC6: Multi-angle readiness fields present with None defaults."""
        hints = get_type_hints(state.Character)
        required = {"id", "scp_id", "canonical_name", "aliases", "created_at", "updated_at"}
        optional = {
            "visual_descriptor", "style_guide", "image_prompt_base",
            "selected_image_path",
            "angle_front_path", "angle_back_path", "angle_side_path",
            "angle_three_quarter_path",
        }
        assert set(hints) == required | optional, f"Unexpected fields: {set(hints)}"

        # Optional fields have None in their type
        for f in optional:
            assert hints[f].__repr__().endswith("None") or "None" in str(hints[f]), \
                f"{f} should be optional (contain None)"


class TestSQLModelTables:
    """AC1: SQLModel tables created on db.init()."""

    def test_tables_created(self):
        db.init("sqlite://")
        from sqlalchemy import inspect
        from yt_flow.db import _engine
        inspector = inspect(_engine)
        tables = set(inspector.get_table_names())
        assert "characters" in tables
        assert "reference_images" in tables

    def test_character_creation_and_persistence(self):
        db.init("sqlite://")
        from sqlmodel import Session
        from yt_flow.db import _engine

        with Session(_engine) as s:
            c = Character(scp_id="SCP-096", canonical_name="Shy Guy", aliases=["The Shy Guy"])
            s.add(c)
            s.commit()
            s.refresh(c)

            assert c.id is not None
            assert len(c.id) == 36  # UUID v4
            assert c.scp_id == "SCP-096"
            assert c.canonical_name == "Shy Guy"
            assert c.aliases == ["The Shy Guy"]
            assert c.visual_descriptor is None
            assert c.angle_front_path is None

    def test_reference_image_creation(self):
        db.init("sqlite://")
        from sqlmodel import Session
        from yt_flow.db import _engine

        with Session(_engine) as s:
            c = Character(scp_id="SCP-173", canonical_name="The Sculpture", aliases=[])
            s.add(c)
            s.commit()
            s.refresh(c)

            ref = ReferenceImage(
                character_id=c.id,
                url="https://example.com/img.jpg",
                local_path="/tmp/ref_1.jpg",
                width=800,
                height=600,
            )
            s.add(ref)
            s.commit()
            s.refresh(ref)

            assert ref.id is not None
            assert ref.character_id == c.id
            assert ref.url == "https://example.com/img.jpg"
