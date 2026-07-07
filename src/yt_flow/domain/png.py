"""Small stdlib-only PNG helpers."""

import struct
import zlib

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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
    return chunk_data[9] in (4, 6)
