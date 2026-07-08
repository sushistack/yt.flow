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
