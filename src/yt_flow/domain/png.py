"""Small stdlib-only PNG helpers."""

import struct
import zlib

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def dimensions(png_bytes: bytes) -> tuple[int, int] | None:
    """(width, height) from a PNG IHDR, or ``None`` if it isn't a readable PNG.

    Stdlib-only, same posture as :func:`has_alpha`. Callers use this to size a
    generation canvas to the sprite it must come back matching.
    """
    if len(png_bytes) < 24 or png_bytes[:8] != _PNG_SIGNATURE or png_bytes[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", png_bytes[16:24])
    return (width, height) if width and height else None


def has_alpha(png_bytes: bytes) -> bool:
    """Check a valid PNG IHDR color type for an alpha channel.

    Color type 4=grayscale+alpha, 6=RGBA. No Pillow needed. [ponytail: stdlib-only]
    """
    if len(png_bytes) < 33 or png_bytes[:8] != _PNG_SIGNATURE:
        return False
    length = struct.unpack(">I", png_bytes[8:12])[0]
    chunk_type = png_bytes[12:16]
    if chunk_type != b"IHDR" or length != 13:
        return False
    chunk_data = png_bytes[16:29]
    expected_crc = struct.unpack(">I", png_bytes[29:33])[0]
    actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
    if expected_crc != actual_crc:
        return False
    if chunk_data[9] not in (4, 6):
        return False

    offset = 33
    saw_idat = False
    while offset + 12 <= len(png_bytes):
        chunk_len = struct.unpack(">I", png_bytes[offset:offset + 4])[0]
        chunk_end = offset + 12 + chunk_len
        if chunk_end > len(png_bytes):
            return False
        current_type = png_bytes[offset + 4:offset + 8]
        current_data = png_bytes[offset + 8:offset + 8 + chunk_len]
        current_crc = struct.unpack(">I", png_bytes[offset + 8 + chunk_len:chunk_end])[0]
        if zlib.crc32(current_type + current_data) & 0xFFFFFFFF != current_crc:
            return False
        if current_type == b"IDAT":
            saw_idat = True
        if current_type == b"IEND":
            return saw_idat
        offset = chunk_end
    return False
