"""Tests for stdlib-only PNG helpers."""

import struct
import zlib

from yt_flow.domain.png import has_alpha


def _png_chunk(name: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(name + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)


def _make_png(color_type: int) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, color_type, 0, 0, 0))
    idat = _png_chunk(b"IDAT", zlib.compress(b"\x00"))
    iend = _png_chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def test_has_alpha_detects_rgba():
    assert has_alpha(_make_png(6)) is True


def test_has_alpha_detects_grayscale_alpha():
    assert has_alpha(_make_png(4)) is True


def test_has_alpha_rejects_rgb():
    assert has_alpha(_make_png(2)) is False


def test_has_alpha_rejects_short_or_garbage_bytes():
    assert has_alpha(b"\x89PNG\r\n\x1a\n") is False
    assert has_alpha(b"not a png at all") is False


def test_has_alpha_rejects_header_only_color_type_spoof():
    spoof = b"\x89PNG\r\n\x1a\n" + (b"\x00" * 17) + b"\x06"
    assert has_alpha(spoof) is False


def test_has_alpha_rejects_bad_ihdr_crc():
    png = bytearray(_make_png(6))
    png[32] ^= 0xFF
    assert has_alpha(bytes(png)) is False


def test_has_alpha_rejects_png_without_image_data():
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    iend = _png_chunk(b"IEND", b"")
    assert has_alpha(sig + ihdr + iend) is False


def test_has_alpha_rejects_bad_later_chunk_crc():
    png = bytearray(_make_png(6))
    png[-1] ^= 0xFF
    assert has_alpha(bytes(png)) is False


# ── Story 14.6: the pixel-level sprite contract ──────────────────────────────
#
# `has_alpha` above is a container check and stays exactly as it was. These cover the
# decoded-pixel contract that stands BESIDE it at the approval gate, and the last test
# in this file is the one that says why there are two.

import io  # noqa: E402

from PIL import Image  # noqa: E402

from yt_flow.domain.png import _MIN_TRANSPARENT_FRACTION, alpha_profile, sprite_contract  # noqa: E402


def _sprite(width=832, height=1216, *, transparent_fraction=0.72, alpha=255) -> bytes:
    """A portrait RGBA card whose transparent share is the requested value."""
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    opaque_rows = round(height * (1.0 - transparent_fraction))
    top = (height - opaque_rows) // 2
    for y in range(top, top + opaque_rows):
        for x in range(width):
            image.putpixel((x, y), (180, 160, 140, alpha))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _rgb_card(width=832, height=1216) -> bytes:
    """A DECODABLE RGB PNG. `_make_png(2)` above is a header fixture whose one-byte IDAT
    is too short for a real 1x1 scanline, so Pillow cannot decode it and the contract
    correctly answers `unreadable` — a different verdict than the one under test here."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (90, 90, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_alpha_profile_reports_the_measured_geometry():
    profile = alpha_profile(_sprite())
    assert profile["has_alpha_channel"] is True
    # Parenthesised: `assert a, b == c` is `assert a, <message>` and pins nothing.
    assert (profile["canvas_w"], profile["canvas_h"]) == (832, 1216)
    assert abs(profile["canvas_aspect"] - 832 / 1216) < 1e-9
    assert abs(profile["transparent_fraction"] - 0.72) < 0.01
    assert abs(profile["transparent_fraction"] + profile["opaque_fraction"] - 1.0) < 1e-9
    left, top, right, bottom = profile["alpha_bbox"]
    assert (left, right) == (0, 832) and bottom > top


def test_alpha_profile_leaves_alpha_stats_unmeasured_on_an_rgb_png():
    """`None`, never `0.0` — "not measured" and "measured as zero" are different
    answers, and the second one reads as a fully opaque RGBA, a different defect."""
    profile = alpha_profile(_rgb_card())
    assert profile["has_alpha_channel"] is False
    assert profile["transparent_fraction"] is None
    assert profile["opaque_fraction"] is None
    assert profile["alpha_bbox"] is None
    assert profile["canvas_w"] == 832


def test_alpha_profile_returns_none_for_bytes_that_are_not_an_image():
    assert alpha_profile(b"not a png at all") is None
    assert alpha_profile(b"") is None


def test_contract_passes_the_whole_measured_band_of_the_live_library():
    """Positive control. The live population's transparent_fraction spans
    0.4377 … 0.8556 (44 cards, measured 2026-08-29 — see `_MIN_TRANSPARENT_FRACTION`).
    A floor fitted to the front-only 6-card band (0.7055 … 0.8421) that an earlier draft
    quoted would reject 18 of those 44, four of them `standing` cards. Six samples here,
    zero false positives; `scripts/report_card_coverage.py` re-derives both numbers.
    """
    for fraction in (0.4377, 0.50, 0.61, 0.72, 0.80, 0.8556):
        assert sprite_contract(_sprite(transparent_fraction=fraction)) == (True, "ok"), fraction


def test_contract_rejects_an_rgb_card():
    """SCP-1471 and SCP-682, all eight cards: `video.py:2537` raises on these."""
    assert sprite_contract(_rgb_card()) == (False, "no_alpha_channel")
    # The live eight are also landscape (1664x928); `no_alpha_channel` is decided first
    # because it is the one `video.py` raises on.
    assert sprite_contract(_rgb_card(1664, 928)) == (False, "no_alpha_channel")


def test_contract_rejects_a_fully_opaque_rgba_card():
    """`has_alpha`'s blind spot — color type 6 with no transparency at all."""
    assert sprite_contract(_sprite(transparent_fraction=0.0)) == (False, "opaque")


def test_contract_rejects_a_blank_card():
    """Alpha present but zero everywhere. Without its own reason this passes the gate
    and `_normalize_subject_scale` raises on it later, at render time."""
    blank = Image.new("RGBA", (832, 1216), (0, 0, 0, 0))
    buffer = io.BytesIO()
    blank.save(buffer, format="PNG")
    assert sprite_contract(buffer.getvalue()) == (False, "empty_alpha")
    assert alpha_profile(buffer.getvalue())["alpha_bbox"] is None


def test_contract_rejects_a_landscape_canvas():
    """A card canvas is portrait; a landscape one is a background filed as a sprite."""
    assert sprite_contract(_sprite(width=1216, height=832)) == (False, "landscape_canvas")
    assert sprite_contract(_sprite(width=833, height=832)) == (False, "landscape_canvas")


def test_an_exactly_square_canvas_is_not_a_landscape_one():
    """`aspect >= 1.0` failed a square card. Square is reachable — the canvas comes from
    `YTFLOW_CHARACTER_IMAGE_WIDTH`/`HEIGHT` — and a square sprite is not a background."""
    assert sprite_contract(_sprite(width=1000, height=1000)) == (True, "ok")


def test_contract_reports_unreadable_rather_than_raising():
    assert sprite_contract(b"\x89PNG\r\n\x1a\n") == (False, "unreadable")
    assert sprite_contract(b"") == (False, "unreadable")


def test_the_floor_only_screens_total_opacity_not_thin_margins():
    """Pinned so nobody "tightens" the floor into the measured band by accident: every
    live card clears it by more than an order of magnitude."""
    assert _MIN_TRANSPARENT_FRACTION < 0.4377 / 10


def test_the_contract_is_strictly_weaker_than_has_alpha_on_a_broken_container():
    """The argument for running BOTH at the approval gate, as an executable claim.

    Pillow opens a truncated file and one with a corrupt IEND CRC without complaint, so
    the pixel contract passes them. `has_alpha` walks chunk CRCs and refuses. Review
    loop 1 of Story 14.6 replaced `has_alpha` with the contract at the gate, which would
    promote exactly these bytes into the library.
    """
    good = _sprite()
    crc_flipped = bytearray(good)
    crc_flipped[-1] ^= 0xFF
    truncated = good[:-12]
    for broken in (bytes(crc_flipped), truncated):
        assert sprite_contract(broken) == (True, "ok")
        assert has_alpha(broken) is False
