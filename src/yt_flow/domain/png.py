"""PNG helpers.

:func:`dimensions` and :func:`has_alpha` are **stdlib-only** by design — they are
container/header checks and must stay callable from anywhere, including the runtime
hard-fail in ``pipeline/nodes/video.py``.

:func:`alpha_profile` and :func:`sprite_contract` are NOT stdlib-only: they decode
pixels, so they lazily import **Pillow and numpy** (both already runtime deps, same
posture as ``character_image_provider._normalize_subject_scale``). The lazy import
keeps the stdlib-only pair importable in an environment without them. Naming only
one of the two dependencies here would mislead an auditor reading this docstring for
the module's dependency contract, so both are named.
"""

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


# Alpha at or below this counts as transparent. Not a fresh judgement: it is the
# threshold `character_image_provider._normalize_subject_scale` already uses to decide
# what the subject is (`alpha.max(...) > 10`). Sharing it is what makes `empty_alpha`
# below name exactly the input that makes that function raise
# ("generated character sprite has an empty alpha mask") instead of a near-miss of it.
_TRANSPARENT_AT_OR_BELOW = 10

# Measured 2026-08-29 over the FULL card population of assets/manifest.json — all 52
# entries carrying a `card_key`. The 44 that have an alpha channel band
# `transparent_fraction` 0.4377 (STOCK-d-class/hint:b0f00082b3_front) … 0.8556
# (STOCK-d-class/hint:475c8a9231_front); the other 8 (SCP-1471, SCP-682) are RGB and
# fail earlier on `no_alpha_channel`. Re-derive with
# `uv run python scripts/report_card_coverage.py`, which prints the observed band next
# to this constant's value.
#
# The floor sits FAR below that band on purpose. The defect it screens is "no
# transparency at all" — a fully opaque RGBA, which is `has_alpha`'s blind spot — and
# NOT "too little margin around the figure". An earlier draft of this story quoted the
# 6-card front-only band (0.7055…0.8421); a floor fitted to that would reject 18 of the
# 44 cards the library is actually shipping (0.4377 … 0.7051), and FOUR of the 18 are
# `standing` cards — `SCP-049/standing_three_quarter` 0.4810,
# `STOCK-researcher/standing_three_quarter` 0.7032, `STOCK-d-class/standing_side` 0.7039,
# `SCP-096/standing_back` 0.7050 — so it is not a sitting/hint-card effect either. The
# report command above prints that counterfactual list on every run.
_MIN_TRANSPARENT_FRACTION = 0.02


def alpha_profile(png_bytes: bytes) -> dict | None:
    """Decoded alpha statistics for a sprite PNG, or ``None`` if it cannot be decoded.

    Keys: ``has_alpha_channel``, ``transparent_fraction``, ``opaque_fraction``,
    ``canvas_w``, ``canvas_h``, ``canvas_aspect`` (w/h) and ``alpha_bbox``
    (``(left, top, right, bottom)`` of the opaque pixels, right/bottom exclusive).

    On a PNG with no alpha channel the three alpha-derived values are ``None``, never
    ``0.0`` — "not measured" and "measured as zero" are different answers and the
    second one would read as a fully opaque RGBA, which is a different defect.

    Never raises **within the decode it performs**: the whole decode — open, load,
    ``convert("RGBA")`` and the numpy array build — is inside one ``try``, because each
    of those four is a separate place a truncated or hostile file blows up, and an
    earlier draft covered only the first. A caller passing something other than
    ``bytes`` still gets the TypeError it earned.
    """
    try:
        import io

        import numpy as np
        from PIL import Image

        with Image.open(io.BytesIO(png_bytes)) as im:
            im.load()
            canvas_w, canvas_h = im.size
            has_alpha_channel = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
            alpha = np.array(im.convert("RGBA"))[:, :, 3] if has_alpha_channel else None
    except Exception:  # noqa: BLE001 - an unreadable file is a verdict, not an outage
        return None

    profile: dict = {
        "has_alpha_channel": has_alpha_channel,
        "transparent_fraction": None,
        "opaque_fraction": None,
        "canvas_w": canvas_w,
        "canvas_h": canvas_h,
        "canvas_aspect": (canvas_w / canvas_h) if canvas_h else None,
        "alpha_bbox": None,
    }
    if alpha is None:
        return profile

    opaque = alpha > _TRANSPARENT_AT_OR_BELOW
    total = alpha.size
    profile["opaque_fraction"] = float(opaque.sum()) / total
    profile["transparent_fraction"] = 1.0 - profile["opaque_fraction"]
    rows = np.flatnonzero(opaque.any(axis=1))
    cols = np.flatnonzero(opaque.any(axis=0))
    if rows.size and cols.size:
        profile["alpha_bbox"] = (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)
    return profile


def sprite_contract(png_bytes: bytes) -> tuple[bool, str]:
    """``(passes, reason)`` for a character-card sprite. Reason is ``"ok"`` on a pass.

    Five failure reasons, checked in this order:

    ``unreadable``        not decodable at all
    ``no_alpha_channel``  RGB — `has_alpha`'s True negative, and what kills a run at
                          ``video.py``'s runtime check
    ``empty_alpha``       an alpha channel that is transparent everywhere (a blank
                          card). Without this reason a blank card passes the gate and
                          ``_normalize_subject_scale`` raises on it later, at render
                          time, where the operator cannot act on it
    ``opaque``            transparent share below ``_MIN_TRANSPARENT_FRACTION`` (0.02),
                          i.e. effectively no cut-out at all — `has_alpha`'s blind spot,
                          and the shape the empty-descriptor cards came in as. Not
                          literally "zero transparent pixels": a one-pixel transparent
                          corner must not buy a pass
    ``landscape_canvas``  a card canvas is taller than it is wide; a wider-than-tall one
                          is a background that got filed as a sprite. Exactly square is
                          NOT a failure — ``YTFLOW_CHARACTER_IMAGE_WIDTH``/``HEIGHT``
                          can be set to it, and a square canvas is not a background

    This does NOT replace :func:`has_alpha`, and the approval gate runs both. Their
    blind spots are disjoint: this one decodes pixels but Pillow happily opens a
    truncated file or one with a corrupt IEND CRC, which `has_alpha` rejects on the
    chunk walk. Collapsing the two into this one is exactly the hole review loop 1 of
    Story 14.6 opened.

    Deliberately NOT in the contract: any bbox width/height ratio. That was measured
    and rejected — a two-figure sprite came in at 0.359 wide-to-tall against a
    known-good single figure's 0.358 (see ``_normalize_subject_scale``'s docstring), so
    the ratio does not separate the classes, while `sitting` and `pose_hint` cards are
    legitimately wide. Counting figures is a vision question.

    # ponytail: palette PNGs carrying a `tRNS` chunk are read through
    # `convert("RGBA")` like anything else and get a real measurement, but nothing in
    # this pipeline emits one (ComfyUI returns RGBA), so no reason code distinguishes
    # them. Ceiling: a hand-made palette sprite is judged on decoded alpha only.
    """
    profile = alpha_profile(png_bytes)
    if profile is None:
        return False, "unreadable"
    if not profile["has_alpha_channel"]:
        return False, "no_alpha_channel"
    if profile["alpha_bbox"] is None:
        return False, "empty_alpha"
    if profile["transparent_fraction"] < _MIN_TRANSPARENT_FRACTION:
        return False, "opaque"
    aspect = profile["canvas_aspect"]
    if aspect is None or aspect > 1.0:
        return False, "landscape_canvas"
    return True, "ok"
