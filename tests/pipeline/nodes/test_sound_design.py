"""Tests for src/yt_flow/pipeline/nodes/sound_design.py (Story 7.1).

Pure functions only — no real ffmpeg, no real audio decoding.
"""

from pathlib import Path

import pytest

from yt_flow.pipeline.nodes.sound_design import (
    DEFAULT_MOOD,
    MOOD_VALUES,
    build_sound_design_args,
    build_sound_design_filter,
    resolve_mood,
    validate_mood_assets,
)


# ── resolve_mood ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("mood", MOOD_VALUES)
def test_resolve_mood_passes_through_valid_values(mood):
    assert resolve_mood(mood) == mood


@pytest.mark.parametrize("bad", [None, "", "unknown-mood", "DREAD"])
def test_resolve_mood_falls_back_to_default(bad):
    assert resolve_mood(bad) == DEFAULT_MOOD


# ── validate_mood_assets ─────────────────────────────────────────────────────


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00")


def test_validate_mood_assets_passes_with_all_files_present(tmp_path, monkeypatch):
    import yt_flow.pipeline.nodes.sound_design as sd
    paths = {
        "bgm": tmp_path / "bgm" / "dread.mp3",
        "ambient": tmp_path / "ambient" / "dread.mp3",
        "stinger": tmp_path / "sfx" / "dread_stinger.mp3",
    }
    for p in paths.values():
        _touch(p)
    monkeypatch.setitem(sd.MOOD_ASSET_PATHS, "dread", paths)

    validate_mood_assets("dread")  # must not raise


@pytest.mark.parametrize("missing_role", ["bgm", "ambient", "stinger"])
def test_validate_mood_assets_raises_on_missing_file(tmp_path, monkeypatch, missing_role):
    import yt_flow.pipeline.nodes.sound_design as sd
    paths = {
        "bgm": tmp_path / "bgm" / "clinical.mp3",
        "ambient": tmp_path / "ambient" / "clinical.mp3",
        "stinger": tmp_path / "sfx" / "clinical_stinger.mp3",
    }
    for role, p in paths.items():
        if role != missing_role:
            _touch(p)
    monkeypatch.setitem(sd.MOOD_ASSET_PATHS, "clinical", paths)

    with pytest.raises(FileNotFoundError, match=missing_role):
        validate_mood_assets("clinical")


def test_validate_mood_assets_resolves_unknown_mood_first(tmp_path, monkeypatch):
    """An unknown mood must be resolved to DEFAULT_MOOD before path lookup, not KeyError."""
    import yt_flow.pipeline.nodes.sound_design as sd
    paths = {
        "bgm": tmp_path / "bgm" / "dread.mp3",
        "ambient": tmp_path / "ambient" / "dread.mp3",
        "stinger": tmp_path / "sfx" / "dread_stinger.mp3",
    }
    monkeypatch.setitem(sd.MOOD_ASSET_PATHS, DEFAULT_MOOD, paths)

    with pytest.raises(FileNotFoundError, match="dread"):
        validate_mood_assets("totally-unknown")


# ── build_sound_design_args ──────────────────────────────────────────────────


def test_build_sound_design_args_order_and_loop_flags():
    args = build_sound_design_args("dread")
    # bgm and ambient are looped; stinger is a plain one-shot -i.
    assert args == [
        "-stream_loop", "-1", "-i", "data/audio/bgm/dread.mp3",
        "-stream_loop", "-1", "-i", "data/audio/ambient/dread.mp3",
        "-i", "data/audio/sfx/dread_stinger.mp3",
    ]


def test_build_sound_design_args_resolves_unknown_mood():
    assert build_sound_design_args("nope") == build_sound_design_args(DEFAULT_MOOD)


# ── build_sound_design_filter ────────────────────────────────────────────────


def test_build_sound_design_filter_returns_aout_label():
    _, label = build_sound_design_filter("dread", 5.0, "[2:a]", 3)
    assert label == "[aout]"


def test_build_sound_design_filter_pins_character_branch_offsets():
    """Character branch: bg=0, char=1, narration=2 -> sound inputs start at 3."""
    fragment, _ = build_sound_design_filter("dread", 5.0, "[2:a]", 3)
    assert "[3:a]" in fragment   # bgm
    assert "[4:a]" in fragment   # ambient
    assert "[5:a]" in fragment   # stinger
    assert "[2:a]" in fragment   # narration referenced twice (duck + final mix)


def test_build_sound_design_filter_pins_background_only_branch_offsets():
    """Background-only branch: bg=0, narration=1 -> sound inputs start at 2."""
    fragment, _ = build_sound_design_filter("dread", 5.0, "[1:a]", 2)
    assert "[2:a]" in fragment   # bgm
    assert "[3:a]" in fragment   # ambient
    assert "[4:a]" in fragment   # stinger
    assert "[1:a]" in fragment   # narration


def test_build_sound_design_filter_binds_duration_and_ducking():
    fragment, _ = build_sound_design_filter("dread", 7.5, "[1:a]", 2)
    assert "apad=whole_dur=7.5" in fragment
    assert "sidechaincompress=" in fragment
    assert "amix=inputs=3:duration=first" in fragment
    assert "amix=inputs=2:duration=first:normalize=0" in fragment


def test_no_db_api_service_imports():
    """AD-1: sound_design.py must not import db, api, or services layers."""
    source = Path("src/yt_flow/pipeline/nodes/sound_design.py").read_text()
    for forbidden in (
        "from yt_flow.db", "from yt_flow.api", "from yt_flow.services",
        "import yt_flow.db", "import yt_flow.api", "import yt_flow.services",
    ):
        assert forbidden not in source, f"sound_design.py must not import {forbidden}"
