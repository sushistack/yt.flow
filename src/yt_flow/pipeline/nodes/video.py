"""video_node — FFmpeg composition stage (Story 1.9 + 1.9b).

Story 1.9: per-scene segment render + concat → video.mp4
Story 1.9b: Ken Burns zoompan per shot
Story 1.13: LLM-based character angle pre-selection before FFmpeg composition
Story 5.16: dip-to-black fade + concat scene boundaries (retires xfade/acrossfade)

Layer rule: domain and config only; no db/, api/, services/. [AD-1]
"""

import asyncio
import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yt_flow.observability import get_client, observe

from yt_flow.config import Settings
from yt_flow.domain.state import PipelineState, SceneState, ShotData
from yt_flow.pipeline.nodes.color_grade import build_post_filter
from yt_flow.pipeline.nodes.sound_design import (
    AMBIENT_VOLUME,
    MOOD_ASSET_PATHS,
    STINGER_VOLUME,
    build_sound_design_args,
    build_sound_design_filter,
    resolve_mood,
    validate_mood_assets,
)

logger = logging.getLogger(__name__)

# ── Angle selection injection (Story 1.13) ────────────────────────────────────
# Injected by the service layer to avoid AD-1 violation. video_node calls this
# to pre-select character angles via LLM before FFmpeg composition runs.
_angle_selector: Any = None


def inject_angle_selector(fn: Any) -> None:
    """Inject the angle selection service callable.

    ``fn`` signature: ``async fn(scp_id: str, scenes: list) -> dict | None``
    Returns ``{shot_key: {"angle": name, "path": file_path}}`` or ``None``.
    """
    global _angle_selector
    _angle_selector = fn

# ── Ken Burns constants ───────────────────────────────────────────────────────

FPS = 25
COMP_W = 1920
COMP_H = 1080
ZOOM_IN_MAX = 1.15   # Story 5.3: raised from 1.08 — review found it read as still-image drift
ZOOM_SAFE_MARGIN = 0.10  # 10% inset before crop so zoom/pan never clips subject

# Direction pool: round-robin by scene_index to avoid identical consecutive directions.
# Story 5.3 added the diagonal directions for more visible fallback variety.
_DIRECTION_POOL = [
    "in-center", "pan-right", "pan-left", "out-center", "pan-up", "pan-down",
    "pan-up-right", "pan-up-left", "pan-down-right", "pan-down-left",
]

# Boundary grammar (Story 5.16): dip-to-black fade + concat replaces xfade —
# narration is never trimmed/overlapped, and the dip marks the act break (the
# chapter card where one exists, otherwise a plain black hold). 7.4's
# mood-driven xfade *type* variety is retired outright (Jay-aligned direction,
# 2026-07-06): wipe/white transitions blend two scene images, exactly the
# artifact this grammar removes.
FADE_DURATION = 0.5  # seconds — in-place fade-out/fade-in at each segment's own edges
BLACK_HOLD_DURATION = 0.3  # seconds — dip-to-black hold at card-less act breaks

# ── Chapter-card constants (Story 5.1, content Story 5.17) ─────────────────────
MIN_CARD_DURATION = 1.5
MAX_CARD_DURATION = 2.5  # Story 5.17: raised 2.0->2.5 — cards now carry title+kicker text
CARD_FADE_DURATION = 0.25  # seconds, in/out fade inside the card itself
CARD_FONT_SIZE = 72
CARD_KICKER_FONT_SIZE = 40
CARD_FONT_PATH = Path("data/fonts/Pretendard-Bold.otf")

# Bundled font directory for the subtitle `.ass` burn-in (Story 5.18 AC:6) — passed
# as the ffmpeg `subtitles=` filter's `fontsdir` so libass resolves Fontname from
# this dir first, never depending on system-installed fonts.
SUBTITLE_FONT_DIR = Path("data/fonts")

# ── CC BY-SA attribution constants (Story 5.20) ───────────────────────────────
WIKI_BASE_URL = "https://scp-wiki.wikidot.com"
CC_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/3.0/"
SCP_DATA_PATH = Path("data/scps.json")

# ── Character idle-motion constants (Story 1.9c) ──────────────────────────────
# Sway = larger/slower horizontal drift; bob = subtle/faster vertical breathing.
# Tremble (tense scenes) is out of scope until a scene ever requests it.
# ponytail: fixed tasteful defaults, not per-scene config; add a knob when a shot
# actually needs different motion.
SWAY_AMPLITUDE = 12   # px, x-axis idle drift
SWAY_FREQ = 0.8       # rad/s
BOB_AMPLITUDE = 8     # px, y-axis breathing/bob
BOB_FREQ = 1.2        # rad/s

# ── Parallax constants (Story 7.3) ────────────────────────────────────────────
# Character (near plane) zoom/pan is derived from the background (far plane)
# EffectSpec, amplified so it reads as depth rather than two unrelated animations.
# ponytail: fixed module constants tuned via live-render QA (same iteration style
# as ZOOM_IN_MAX's 1.08→1.15 history), not per-scene config.
CHAR_DEPTH_FACTOR = 1.3        # zoom-delta amplification for the near plane
CHAR_PAN_AMPLITUDE_PX = 12     # ponytail: eyeball-tuned; per-direction sign live-verified (AC:7/Task 8)

# Peak character zoom = the amplified in-center push-in. The motion-safe box below
# must reserve room for THIS before sway/bob, or the character grows ~19.5% past
# frame edges at the in-center peak (Story 7.3 AC:4).
CHAR_MAX_ZOOM = 1.0 + (ZOOM_IN_MAX - 1.0) * CHAR_DEPTH_FACTOR

# Motion-safe character box: shrink an oversized character to leave room for the
# peak parallax zoom *and* the full sway/bob excursion *and* the macro pan drift,
# so no combination of depth-zoom + idle motion + parallax pan can push it
# off-frame and a mis-sized ComfyUI asset (character bytes are written raw, never
# scaled upstream) can't overflow. Dividing by CHAR_MAX_ZOOM means a character
# capped here then zoomed to its peak lands back inside the frame; reserving
# SWAY/BOB *and* CHAR_PAN_AMPLITUDE_PX per side means the worst-case corner
# (peak zoom + sway peak + full pan ramp, e.g. pan-* directions) still stays on
# screen by construction — not by eyeball (Story 7.3 AC:4/AC:8 regression invariant).
CHAR_MAX_W = (COMP_W - 2 * (SWAY_AMPLITUDE + CHAR_PAN_AMPLITUDE_PX)) / CHAR_MAX_ZOOM
CHAR_MAX_H = (COMP_H - 2 * (BOB_AMPLITUDE + CHAR_PAN_AMPLITUDE_PX)) / CHAR_MAX_ZOOM


# ── EffectSpec dataclass ──────────────────────────────────────────────────────


@dataclass
class EffectSpec:
    direction: str   # one of _DIRECTION_POOL
    start_zoom: float
    end_zoom: float


# ── Effect dispatcher — pure, no I/O ────────────────────────────────────────


_HINT_MAP: dict[str, str] = {
    "zoom in": "in-center",
    "zoom_in": "in-center",
    "push in": "in-center",
    "push_in": "in-center",
    "zoom out": "out-center",
    "zoom_out": "out-center",
    "pull back": "out-center",
    "pull_back": "out-center",
    "pan left": "pan-left",
    "pan_left": "pan-left",
    "pan right": "pan-right",
    "pan_right": "pan-right",
    "pan up": "pan-up",
    "pan_up": "pan-up",
    "pan down": "pan-down",
    "pan_down": "pan-down",
    # "static" → near-zero drift; handled below
}


def select_effect(shot: ShotData, scene_index: int) -> EffectSpec:
    """Pure effect dispatcher. Returns EffectSpec for zoompan. [AC:1,3]

    - Recognizes free-text camera_movement hints.
    - Unknown/None → rotates through _DIRECTION_POOL by scene_index (anti-monotony).
    - 'static' → near-zero 1.0→1.005 drift reusing the zoompan path.
    """
    # normalize internal/tab whitespace too so "pan  right" / "pan\tright" still match
    hint = " ".join((shot.get("camera_movement") or "").split()).lower()

    if hint == "static":
        # ponytail: reuse zoompan path instead of a separate static branch
        return EffectSpec(direction="in-center", start_zoom=1.0, end_zoom=1.005)

    direction = _HINT_MAP.get(hint)
    if direction is None:
        # Rotate pool so consecutive scenes never share the same direction
        direction = _DIRECTION_POOL[scene_index % len(_DIRECTION_POOL)]

    # in-center and pan-* zoom in; out-center zooms out
    if direction == "out-center":
        return EffectSpec(direction=direction, start_zoom=ZOOM_IN_MAX, end_zoom=1.0)
    return EffectSpec(direction=direction, start_zoom=1.0, end_zoom=ZOOM_IN_MAX)


def _character_spec(bg_spec: EffectSpec) -> EffectSpec:
    """Derive the near-plane character spec from the far-plane background spec. [AC:1]

    Same ``direction`` (parallax needs both planes moving the *same* way, only at
    different magnitude); the zoom deviation from 1.0 is amplified by
    CHAR_DEPTH_FACTOR. Direction-agnostic and no special-casing — 'static'
    (1.0→1.005) stays tiny after amplification.
    """
    return EffectSpec(
        direction=bg_spec.direction,
        start_zoom=1.0 + (bg_spec.start_zoom - 1.0) * CHAR_DEPTH_FACTOR,
        end_zoom=1.0 + (bg_spec.end_zoom - 1.0) * CHAR_DEPTH_FACTOR,
    )


# ── Filtergraph builders ──────────────────────────────────────────────────────


def _zoompan_filter(spec: EffectSpec, duration: float) -> str:
    """Build a jitter-safe zoompan filter chain for one shot. [AC:1]

    Chain: scale→setsar→crop→scale=8000 (jitter fix)→zoompan
    The pre-upscale to 8000px wide is the community-standard pixel-rounding fix.
    """
    frames = max(1, round(duration * FPS))
    safe_w = round(COMP_W * (1 - ZOOM_SAFE_MARGIN))
    safe_h = round(COMP_H * (1 - ZOOM_SAFE_MARGIN))

    # Honor the EffectSpec zoom range so 'static' (1.0→1.005) drifts subtly instead
    # of getting a full push-in. start_zoom/end_zoom were previously ignored — the
    # filter always ran to ZOOM_IN_MAX regardless of spec. [review:G]
    lo, hi = spec.start_zoom, spec.end_zoom
    direction = spec.direction
    if direction == "out-center":
        # zoom-out is stateful: the conditional re-seeds zoom to `lo` on the first
        # frame, then decrements by `inc` toward `hi`.
        inc = (lo - hi) / frames
        z_expr = f"if(lte(zoom,{hi}),{lo},max({hi + 0.001:.6f},zoom-{inc:.6f}))"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    else:
        inc = (hi - lo) / frames
        z_expr = f"min(zoom+{inc:.6f},{hi})"
        if direction == "pan-right":
            x_expr = f"(iw-iw/zoom)*on/{frames}"
            y_expr = "ih/2-(ih/zoom/2)"
        elif direction == "pan-left":
            x_expr = f"(iw-iw/zoom)*(1-on/{frames})"
            y_expr = "ih/2-(ih/zoom/2)"
        elif direction == "pan-up":
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = f"(ih-ih/zoom)*on/{frames}"
        elif direction == "pan-down":
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = f"(ih-ih/zoom)*(1-on/{frames})"
        elif direction in {
            "pan-up-right", "pan-up-left", "pan-down-right", "pan-down-left",
        }:
            # Diagonal: combine the horizontal pan-left/right expr with the
            # vertical pan-up/down expr instead of centering the other axis.
            diagonal_exprs = {
                "pan-up-right": (
                    f"(iw-iw/zoom)*on/{frames}",
                    f"(ih-ih/zoom)*on/{frames}",
                ),
                "pan-up-left": (
                    f"(iw-iw/zoom)*(1-on/{frames})",
                    f"(ih-ih/zoom)*on/{frames}",
                ),
                "pan-down-right": (
                    f"(iw-iw/zoom)*on/{frames}",
                    f"(ih-ih/zoom)*(1-on/{frames})",
                ),
                "pan-down-left": (
                    f"(iw-iw/zoom)*(1-on/{frames})",
                    f"(ih-ih/zoom)*(1-on/{frames})",
                ),
            }
            x_expr, y_expr = diagonal_exprs[direction]
        else:  # in-center
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih/2-(ih/zoom/2)"

    zp = (
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
        f":d={frames}:s={COMP_W}x{COMP_H}:fps={FPS}"
    )

    return (
        f"scale={safe_w}:-2,setsar=1:1,crop={safe_w}:{safe_h},"
        f"scale=8000:-1,{zp}"
    )


# Direction → (x_sign, y_sign) for the character's macro pan, in *apparent
# on-screen* space: the character drifts WITH the background's visible motion,
# which is the OPPOSITE sign of the background's crop-window expression (see
# _zoompan_filter — a crop moving right makes content appear to move left).
# in-center/out-center/static contribute zero pan (default). Story 7.3 AC:3/AC:7 —
# ponytail: provisional signs, live-verified per direction in Task 8.
_PAN_SIGN: dict[str, tuple[int, int]] = {
    "pan-right": (-1, 0),
    "pan-left": (1, 0),
    "pan-up": (0, -1),
    "pan-down": (0, 1),
    "pan-up-right": (-1, -1),
    "pan-up-left": (1, -1),
    "pan-down-right": (-1, 1),
    "pan-down-left": (1, 1),
}


def _character_zoom_filter(spec: EffectSpec, duration: float) -> str:
    """Time-varying scale for the character (near plane). [AC:2]

    ``scale`` (not ``zoompan``): the character is a transparent PNG composited via
    ``overlay`` and needs no crop, and zoompan's alpha handling is unreliable here.
    ``eval=frame`` so ``t`` advances per frame — the same requirement
    ``_overlay_filter`` documents for its sines. Zoom ramps linearly start→end.
    """
    lo, hi = spec.start_zoom, spec.end_zoom
    z = f"({lo}+({hi}-{lo})*t/{duration})"
    return f"scale=w='iw*{z}':h='ih*{z}':eval=frame"


def _overlay_filter(spec: EffectSpec | None = None, duration: float | None = None) -> str:
    """Character overlay, centered on the background, with idle motion. [AC:1,2,3]

    ``eval=frame`` is REQUIRED and set explicitly: under the ``eval=init`` default
    for *some* builds the ``t``/``n`` timeline vars collapse to NAN and the
    character freezes. Two sines (x sway, y bob) at different freq/amplitude give
    the subtle "alive" drift without rigging.

    When ``spec`` is given (parallax on, Story 7.3), a direction-derived macro pan
    term rides *on top of* the sway/bob sines — a slow shot-duration-scale depth
    drift, ramped linearly like the zoom. ``spec=None`` reverts to the exact
    fixed-size sway/bob-only string (parallax off). The centering base stays
    correct under ``eval=frame`` even as the character scales.
    """
    x = f"(main_w-overlay_w)/2 + sin(t*{SWAY_FREQ})*{SWAY_AMPLITUDE}"
    y = f"(main_h-overlay_h)/2 + sin(t*{BOB_FREQ})*{BOB_AMPLITUDE}"
    if spec is not None and duration:
        sx, sy = _PAN_SIGN.get(spec.direction, (0, 0))
        if sx:
            x += f" + ({sx * CHAR_PAN_AMPLITUDE_PX})*t/{duration}"
        if sy:
            y += f" + ({sy * CHAR_PAN_AMPLITUDE_PX})*t/{duration}"
    return f"overlay=x='{x}':y='{y}':eval=frame"


def _character_scale_filter() -> str:
    """Cap an oversized character to the motion-safe box before overlay. [review:1.9c]

    Downscale-only (``min(iw,…)`` guards against upscaling a small cutout) and
    aspect-preserving (``force_original_aspect_ratio=decrease``). The character is
    never resized upstream, so without this an asset larger than the frame clips or
    overflows; capping to COMP minus the sway/bob amplitude also keeps the centered
    overlay's full sine excursion on-frame.
    """
    return (
        rf"scale=w='min(iw\,{CHAR_MAX_W})':h='min(ih\,{CHAR_MAX_H})'"
        ":force_original_aspect_ratio=decrease"
    )


# ── helpers ───────────────────────────────────────────────────────────────────


def _escape_subtitles_path(path: Path) -> str:
    """Escape a path for the ffmpeg ``subtitles=`` filter option. [1.9b hardening]

    The value is wrapped in single quotes by the caller; here we escape the
    characters the filtergraph/option parser still treats as special inside
    quotes: ``\\``, ``'`` and ``:`` (drive colons, run_ids with ``:``).
    """
    return (
        str(path)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
    )


def _settings() -> Settings:
    # ponytail: seam so unit tests can inject fake settings without a real .env.
    return Settings()  # type: ignore[call-arg]


def _card_font() -> str:
    """Resolve the bundled Pretendard Bold card font. [Story 5.17 AC:5]

    A repo-relative committed file, not a fontconfig lookup — portable by
    construction, unlike the machine-specific system-font search it replaces.
    Fails fast if missing: that's repo corruption, not an environment condition.
    """
    if not CARD_FONT_PATH.exists():
        raise RuntimeError(f"bundled card font not found: {CARD_FONT_PATH}")
    return str(CARD_FONT_PATH)


def _subtitle_fontsdir() -> Path:
    """Resolve the bundled subtitle font directory. [Story 5.18 AC:6]

    Fails fast if missing: a silently-absent fontsdir doesn't error in ffmpeg,
    it just falls back to whatever system font libass finds — same repo-corruption
    guard as _card_font().
    """
    if not SUBTITLE_FONT_DIR.is_dir():
        raise RuntimeError(f"bundled subtitle font directory not found: {SUBTITLE_FONT_DIR}")
    return SUBTITLE_FONT_DIR


def _card_label(scene: SceneState) -> str:
    """Chapter-card title for the upcoming scene, falling back to "- N -"
    when the scenario stage hasn't produced one yet. [Story 5.1 AC:3] [Story 5.17 AC:8]"""
    title = str(scene.get("title") or "").strip()
    return title or f"- {scene['scene_num']} -"


def _chapter_card_duration(value: float) -> float:
    """Clamp chapter-card duration to the accepted Story 5.1 range."""
    return min(MAX_CARD_DURATION, max(MIN_CARD_DURATION, float(value)))


def _scp_wiki_slug(scp_id: str) -> str:
    """Wikidot slug: lowercase, hyphenated, no zero-padding. [Story 5.20]

    Deterministic from scp_id alone — confirmed live against the real wiki by
    Story 5.10's ScpWikiImageFetch. No HTTP call needed to know the page URL.
    """
    return scp_id.strip().lower()


_scp_nicknames: dict[str, str] | None = None  # ponytail: lazy-loaded cache; read-only reference data


def _scp_nickname(scp_id: str) -> str | None:
    """Best-effort nickname lookup from data/scps.json, cached after first call.

    Tolerant: a missing/corrupt file or unknown scp_id just means no nickname
    (AC:3) — never raises.
    """
    global _scp_nicknames
    if _scp_nicknames is None:
        try:
            entries = json.loads(SCP_DATA_PATH.read_text(encoding="utf-8"))
            # per-entry tolerant: one entry missing "id"/"nickname" must not
            # discard every other entry's lookup (AC:3).
            _scp_nicknames = {e["id"]: e["nickname"] for e in entries if "id" in e and "nickname" in e}
        except Exception as exc:  # noqa: BLE001 — tolerant lookup (AC:3)
            logger.warning("SCP nickname lookup unavailable: %s", exc)
            _scp_nicknames = {}
    return _scp_nicknames.get(scp_id)


def build_description_text(
    scp_id: str,
    *,
    scp_nickname: str | None = None,
    wiki_page_url: str | None = None,
) -> str:
    """Build the YouTube description.txt block. [Story 5.20 AC:3,4]

    The image-source line reuses the same deterministic wiki URL: whether the
    run's reference image actually came from the wiki or fell back to DDG, the
    article itself is CC BY-SA either way (per AC:4). Author-byline extraction
    is deliberately out of scope — it would require fetching the wiki page at
    video time, which the story's own guardrails rule out; the page link alone
    is the documented-sufficient fallback (AC:3).
    """
    url = wiki_page_url or f"{WIKI_BASE_URL}/{_scp_wiki_slug(scp_id)}"
    title = f"[{scp_id}] {scp_nickname} — SCP Foundation Wiki" if scp_nickname else f"[{scp_id}] — SCP Foundation Wiki"
    return (
        f"{title}\n"
        f"{url}\n"
        "\n"
        "Licensed under CC BY-SA 3.0\n"
        f"{CC_LICENSE_URL}\n"
        "\n"
        f'This video is a derivative work based on "{scp_id}" from the SCP Foundation Wiki.\n'
        "\n"
        "---\n"
        f"Image source: {url}\n"
    )


async def _write_description_artifact(run_dir: Path, scp_id: str) -> Path | None:
    """Write description.txt to the run directory. Non-fatal (AD-10, AC:5).

    Async for consistency with video_node's other await'd calls; the actual I/O
    (mkdir + write_text) is synchronous — same seam _card_font()/_settings() use.
    """
    try:
        text = build_description_text(scp_id, scp_nickname=_scp_nickname(scp_id))
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "description.txt"
        path.write_text(text, encoding="utf-8")
        return path
    except Exception as exc:  # noqa: BLE001 — AD-10: attribution never fails the run
        logger.warning("description.txt write failed: %s", exc)
        return None


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _record_trace(
    *,
    run_id: str,
    scene_count: int,
    latency_ms: int,
    output_path: str | None = None,
    returncode: int | None = None,
    effects: list | None = None,
    upscale_pass: bool = True,
    character_scenes: int = 0,
    angle_selection: dict | None = None,
    chapter_cards_enabled: bool = False,
    chapter_card_duration: float | None = None,
    chapter_card_count: int = 0,
    ending_credit: bool = False,
    ending_credit_error: str | None = None,
    error=None,
) -> None:
    """Best-effort Langfuse span enrichment. [AD-10 — tracing is non-fatal]"""
    try:
        metadata: dict = {
            "run_id": run_id,
            "scene_count": scene_count,
            "latency_ms": latency_ms,
            **({"output_path": output_path} if output_path else {}),
            **({"ffmpeg_returncode": returncode} if returncode is not None else {}),
            **({"effects": effects} if effects is not None else {}),
            "transition": "dip-to-black",
            "fade_duration": FADE_DURATION,
            "black_hold_sec": BLACK_HOLD_DURATION,
            "chapter_cards_enabled": chapter_cards_enabled,
            "chapter_card_count": chapter_card_count,
            **({"chapter_card_duration": chapter_card_duration} if chapter_card_duration is not None else {}),
            "upscale_pass": upscale_pass,
            # Character idle-motion params (Story 1.9c) — constant across scenes.
            "character_scenes": character_scenes,
            "character_motion": {
                "sway_px": SWAY_AMPLITUDE, "sway_freq": SWAY_FREQ,
                "bob_px": BOB_AMPLITUDE, "bob_freq": BOB_FREQ,
            },
            "ending_credit": ending_credit,
            "ending_credit_error": ending_credit_error,
            **({"error": repr(error)} if error is not None else {}),
        }
        # Story 1.13: angle selection tracing metadata
        if angle_selection:
            metadata["angle_selection"] = angle_selection
        get_client().update_current_span(metadata=metadata)
    except Exception:  # noqa: BLE001
        pass


def _validate_scene_assets(
    scenes: list[SceneState], *, sound_design_enabled: bool = False,
) -> None:
    """Raise before FFmpeg if required per-scene assets are missing. [AC:2]"""
    for scene in scenes:
        n = scene["scene_num"]
        # Validate only the shot _compose_scene will actually render (first with an
        # image) — don't abort a run over an unused later shot's missing image.
        shot = next((s for s in (scene.get("shots") or []) if s.get("image_path")), None)
        if shot is None:
            raise ValueError(f"scene {n}: no shot has a valid image_path")
        img = shot["image_path"]
        assert img is not None  # selected because image_path is truthy
        if not Path(img).exists():
            raise FileNotFoundError(f"scene {n}: image_path not found: {img!r}")
        audio = scene.get("audio_path")
        if not audio or not Path(audio).exists():
            raise FileNotFoundError(f"scene {n}: audio_path missing or not found: {audio!r}")
        subtitle = scene.get("subtitle_path")
        if not subtitle or not Path(subtitle).exists():
            raise FileNotFoundError(f"scene {n}: subtitle_path missing or not found: {subtitle!r}")
        # character_path is optional (None = background-only, AC:3). But if a shot
        # *claims* a character layer, a missing file is a real error — fail loudly
        # rather than silently dropping the character overlay. [AC:1]
        character = shot.get("character_path")
        if character and not Path(character).exists():
            raise FileNotFoundError(f"scene {n}: character_path set but not found: {character!r}")
        # audio_duration drives zoompan frame count + segment fade timing; a missing/≤0 value
        # would silently truncate the scene (via -shortest) or corrupt timing. Fail fast
        # instead of inventing a fallback duration. [review:D]
        dur = scene.get("audio_duration")
        if not isinstance(dur, (int, float)) or dur <= 0:
            raise ValueError(f"scene {n}: audio_duration must be a positive number, got {dur!r}")
        # Sound design (Story 7.1): fail fast if the resolved mood's assets are missing,
        # same up-front posture as the image/audio/subtitle checks above. [AC:5]
        if sound_design_enabled:
            validate_mood_assets(resolve_mood(scene.get("mood")))


async def _run_ffmpeg(*args: str) -> tuple[int, str]:
    """Spawn ffmpeg with argument list; return (returncode, stderr text)."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr_bytes = await proc.communicate()
    rc = proc.returncode
    assert rc is not None  # always set after communicate()
    return rc, (stderr_bytes or b"").decode(errors="replace")


_OUTPUT_ARGS = (
    "-c:v", "libx264", "-preset", "fast",
    "-c:a", "aac", "-b:a", "128k",
    "-pix_fmt", "yuv420p",
    "-shortest",
)


async def _compose_scene(
    scene: SceneState,
    scene_index: int,
    out_dir: Path,
    *,
    sound_design_enabled: bool = False,
    post_fx_enabled: bool = False,
    parallax_enabled: bool = False,
    include_stinger: bool = True,
) -> tuple[Path, EffectSpec, bool]:
    """Render one scene segment: Ken Burns zoompan + burned SRT, optionally with a
    transparent character composited on top with idle motion, optionally with a
    mood-driven BGM/ambient/stinger mix ducked under the narration, optionally
    with a mood-driven color grade + constant vignette/grain applied before
    subtitle burn-in. [AC:1,3] [Story 7.1] [Story 7.2 AC:4,5,6,8,9]

    `include_stinger=False` (Story 5.17 AC:7) omits this scene's own baked
    scene-entry stinger — set by the caller for a scene immediately preceded
    by a chapter card, since the card now carries that boundary's stinger hit.

    Returns (segment_path, effect_spec, character_overlaid).
    """
    n = scene["scene_num"]
    shots = scene.get("shots") or []
    shot = next((s for s in shots if s.get("image_path")), None)
    if shot is None:  # defensive; _validate_scene_assets guarantees this upstream
        raise ValueError(f"scene {n}: no shot has a valid image_path")
    # Prefer the opaque background layer for Ken Burns; fall back to image_path so
    # 1.9/1.9b (non-layered) shots still render. [1.6b contract]
    bg_path = shot.get("background_path") or shot["image_path"]
    character_path = shot.get("character_path")  # None = background-only (AC:3)
    audio_path: str = scene["audio_path"]  # type: ignore[assignment]
    subtitle_path: str = scene["subtitle_path"]  # type: ignore[assignment]
    duration: float = scene["audio_duration"]  # type: ignore[assignment]  # validated positive upstream
    seg_path = out_dir / f"seg_{n:03d}.mp4"

    spec = select_effect(shot, scene_index)
    zp_chain = _zoompan_filter(spec, duration)
    sub = _escape_subtitles_path(Path(subtitle_path).resolve())
    fontsdir = _escape_subtitles_path(_subtitle_fontsdir().resolve())
    mood = scene.get("mood")
    # [Story 7.2 AC:4-9] Precomputed fragments, empty when post_fx_enabled=False
    # so every chain below degrades to today's byte-for-byte ungraded output.
    post_filter = build_post_filter(mood) if post_fx_enabled else ""
    post_frag = f",{post_filter}" if post_fx_enabled else ""
    post_label = f"{post_filter}[graded];[graded]" if post_fx_enabled else ""

    if character_path:
        # Layered: zoompan the background, overlay the moving character, then burn
        # subtitles on top. Two looped image inputs (0=bg, 1=char) + audio (2).
        inputs = [
            "-loop", "1", "-framerate", str(FPS), "-i", str(bg_path),
            "-loop", "1", "-framerate", str(FPS), "-i", str(character_path),
            "-i", audio_path,
        ]
        # Parallax (Story 7.3): couple the character's zoom/pan to the background's
        # spec, amplified. Off → today's fixed-size, sway/bob-only overlay.
        if parallax_enabled:
            char_spec = _character_spec(spec)
            char_chain = (
                f"{_character_scale_filter()},"
                f"{_character_zoom_filter(char_spec, duration)}"
            )
            overlay = _overlay_filter(char_spec, duration)
        else:
            char_chain = _character_scale_filter()
            overlay = _overlay_filter()
        video_chain = (
            f"[0:v]{zp_chain}[bg];"
            f"[1:v]{char_chain}[char];"
            f"[bg][char]{overlay}[ov];"
            f"[ov]{post_label}subtitles='{sub}':fontsdir='{fontsdir}'[out]"
        )
        video_map = "[out]"
        narration_label = "[2:a]"
        input_offset = 3
        narration_map = "2:a"
    else:
        # Background-only (1.9b): zoompan already emits COMP_W x COMP_H, just burn SRT.
        inputs = [
            "-loop", "1", "-framerate", str(FPS), "-i", str(bg_path),
            "-i", audio_path,
        ]
        video_chain = f"[0:v]{zp_chain}{post_frag},subtitles='{sub}':fontsdir='{fontsdir}'[vout]"
        video_map = "[vout]"
        narration_label = "[1:a]"
        input_offset = 2
        narration_map = "1:a"

    if sound_design_enabled:
        # Hazard 1: -vf and -filter_complex are mutually exclusive in ffmpeg, so the
        # background-only branch's video chain is folded into filter_complex here
        # (labeled [vout]) instead of staying a -vf string. Hazard 2: input_offset/
        # narration_label differ per branch — see class docstring in sound_design.py.
        resolved_mood = resolve_mood(scene.get("mood"))
        sound_args = build_sound_design_args(resolved_mood, include_stinger=include_stinger)
        sound_fragment, audio_out_label = build_sound_design_filter(
            resolved_mood, duration, narration_label, input_offset, include_stinger=include_stinger,
        )
        ffmpeg_args = [
            "-y", *inputs, *sound_args,
            "-filter_complex", f"{video_chain};{sound_fragment}",
            "-map", video_map, "-map", audio_out_label,
            # -shortest alone doesn't reliably bound the infinite `-loop 1` video
            # against a filter-graph-produced [aout] pad (verified against real
            # ffmpeg: without -t, encoding never reaches EOF on the looped bgm/
            # ambient beds). -t pins the segment to the scene's real duration.
            "-t", str(duration),
            *_OUTPUT_ARGS, str(seg_path),
        ]
    elif character_path:
        ffmpeg_args = [
            "-y", *inputs,
            "-filter_complex", video_chain,
            "-map", video_map, "-map", narration_map,
            *_OUTPUT_ARGS, str(seg_path),
        ]
    else:
        # Sound design disabled (AC:8): keep the pre-existing -vf path, still
        # carrying post_frag (empty string when post_fx_enabled=False too).
        vf = f"{zp_chain}{post_frag},subtitles='{sub}':fontsdir='{fontsdir}'"
        ffmpeg_args = [
            "-y", *inputs,
            "-vf", vf,
            *_OUTPUT_ARGS, str(seg_path),
        ]

    rc, stderr = await _run_ffmpeg(*ffmpeg_args)
    if rc != 0:
        raise RuntimeError(f"FFmpeg scene {n} failed (rc={rc}): {stderr[-500:]}")
    if not seg_path.exists():
        raise RuntimeError(f"FFmpeg scene {n}: output not created: {seg_path}")
    return seg_path, spec, bool(character_path)


def _card_hold_audio_input(mood: str | None, *, sound_design_enabled: bool) -> tuple[list[str], list[str]]:
    """Audio input args + optional volume filter for a card/hold segment. [Story 5.16 AC:3]

    Sound design on: the upcoming scene's mood ambient bed, looped, at
    AMBIENT_VOLUME — the boundary never drops to digital silence. Off: today's
    anullsrc silence, unchanged.
    """
    if not sound_design_enabled:
        return ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"], []
    ambient = MOOD_ASSET_PATHS[resolve_mood(mood)]["ambient"]
    return ["-stream_loop", "-1", "-i", str(ambient)], ["-af", f"volume={AMBIENT_VOLUME}"]


async def _compose_chapter_card(
    label: str,
    index: int,
    out_dir: Path,
    duration: float,
    *,
    kicker: str = "",
    mood: str | None = None,
    post_fx_enabled: bool = False,
    sound_design_enabled: bool = False,
) -> Path:
    """Render a black title-card segment: color bg + centered title/kicker
    drawtext + audio bed, fading in/out at its own edges.
    [Story 5.1 AC:2,5] [Story 5.16 AC:3,5] [Story 5.17 AC:4,5,7]

    `mood` grades the card to the *upcoming* scene's mood, applied before
    drawtext so the text isn't grained. [Story 7.2 AC:7,8] The same mood also
    picks the card's ambient audio bed, and — when sound design is on — its
    mood stinger: the card IS the boundary now (Story 5.16's dip-to-black,
    Story 5.17's stinger-on-entry), so it carries the boundary's full audio,
    not just the ambient bed.

    Matches _compose_scene's output contract (COMP_W x COMP_H, FPS, H.264/AAC,
    yuv420p, has an audio stream) so _join_with_fades can treat it as an
    ordinary segment — no join-engine changes needed.
    """
    card_path = out_dir / f"card_{index:03d}.mp4"
    label_file = out_dir / f"card_{index:03d}_label.txt"
    label_stripped = label.strip()
    label_clean = label_stripped.splitlines()[0].strip() if label_stripped else label_stripped
    label_file.write_text(label_clean, encoding="utf-8")
    font = _escape_subtitles_path(Path(_card_font()))
    title_textfile = _escape_subtitles_path(label_file)
    fade_out_start = max(0.0, duration - CARD_FADE_DURATION)
    post_frag = f"{build_post_filter(mood)}," if post_fx_enabled else ""

    kicker_frag = ""
    kicker_stripped = kicker.strip()
    kicker_clean = kicker_stripped.splitlines()[0].strip() if kicker_stripped else ""
    if kicker_clean:
        kicker_file = out_dir / f"card_{index:03d}_kicker.txt"
        kicker_file.write_text(kicker_clean, encoding="utf-8")
        kicker_textfile = _escape_subtitles_path(kicker_file)
        kicker_frag = (
            f",drawtext=fontfile='{font}':textfile='{kicker_textfile}':"
            f"fontcolor=white:fontsize={CARD_KICKER_FONT_SIZE}:x=(w-text_w)/2:y=(h-text_h)/2+60"
        )
    vf = (
        f"{post_frag}"
        f"drawtext=fontfile='{font}':textfile='{title_textfile}':"
        f"fontcolor=white:fontsize={CARD_FONT_SIZE}:x=(w-text_w)/2:y=(h-text_h)/2-40"
        f"{kicker_frag},"
        f"fade=t=in:st=0:d={CARD_FADE_DURATION},"
        f"fade=t=out:st={fade_out_start:.3f}:d={CARD_FADE_DURATION}"
    )

    if sound_design_enabled:
        # Ambient bed (5.16) + this boundary's mood stinger, one-shot from t=0
        # (Story 5.17 AC:7) — the following scene omits its own baked stinger
        # via include_stinger=False so the boundary gets exactly one hit.
        resolved_mood = resolve_mood(mood)
        ambient = MOOD_ASSET_PATHS[resolved_mood]["ambient"]
        stinger = MOOD_ASSET_PATHS[resolved_mood]["stinger"]
        # normalize=0 (matches sound_design.py's own final mix): amix's default
        # normalize=1 auto-attenuates by active-input count, which flattened the
        # stinger down to the ambient bed's level — no audible hit at all. Summing
        # at the configured volumes verbatim is what makes AC:7's "one hit at
        # card t=0" actually audible. [caught in Story 5.17 live validation]
        audio_fragment = (
            f"[1:a]volume={AMBIENT_VOLUME}[amb_v];"
            f"[2:a]volume={STINGER_VOLUME},apad=whole_dur={duration}[stg_v];"
            f"[amb_v][stg_v]amix=inputs=2:duration=first:normalize=0[aout]"
        )
        rc, stderr = await _run_ffmpeg(
            "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={COMP_W}x{COMP_H}:r={FPS}:d={duration}",
            "-stream_loop", "-1", "-i", str(ambient),
            "-i", str(stinger),
            "-filter_complex", f"[0:v]{vf}[vout];{audio_fragment}",
            "-map", "[vout]", "-map", "[aout]",
            "-t", f"{duration:.3f}",
            *_OUTPUT_ARGS,
            str(card_path),
        )
    else:
        audio_input, _ = _card_hold_audio_input(mood, sound_design_enabled=False)
        rc, stderr = await _run_ffmpeg(
            "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={COMP_W}x{COMP_H}:r={FPS}:d={duration}",
            *audio_input,
            "-vf", vf,
            # Explicit -map: without it, a real ambient .mp3 (unlike anullsrc) could
            # carry an embedded cover-art video stream that hijacks ffmpeg's default
            # video-stream auto-selection away from the color background.
            "-map", "0:v", "-map", "1:a",
            "-t", f"{duration:.3f}",
            *_OUTPUT_ARGS,
            str(card_path),
        )
    if rc != 0:
        raise RuntimeError(f"FFmpeg chapter card {index} failed (rc={rc}): {stderr[-500:]}")
    if not card_path.exists():
        raise RuntimeError(f"FFmpeg chapter card {index}: output not created: {card_path}")
    return card_path


async def _compose_ending_credit(
    scp_id: str,
    out_dir: Path,
    *,
    mood: str | None = None,
    post_fx_enabled: bool = False,
    sound_design_enabled: bool = False,
) -> Path:
    """Render the CC BY-SA attribution ending card. [Story 5.20 AC:2]

    Thin wrapper over _compose_chapter_card — same renderer, distinct output
    filename (credit_ending.mp4, never card_NNN.mp4) so it can never collide
    with a chapter card. Raises on failure, same as _compose_chapter_card;
    video_node's caller decides how to log/report it (AC:5 non-fatal handling
    needs the run_id, which this function has no reason to know).
    """
    slug = _scp_wiki_slug(scp_id)
    label = f"Based on '{scp_id}' from the SCP Foundation Wiki"
    kicker = f"CC BY-SA 3.0 — scp-wiki.wikidot.com/{slug}"
    card_path = await _compose_chapter_card(
        label, 0, out_dir, MAX_CARD_DURATION,
        kicker=kicker, mood=mood, post_fx_enabled=post_fx_enabled,
        sound_design_enabled=sound_design_enabled,
    )
    ending_path = out_dir / "credit_ending.mp4"
    card_path.replace(ending_path)
    return ending_path


async def _compose_black_hold(
    out_dir: Path,
    index: int,
    *,
    mood: str | None = None,
    sound_design_enabled: bool = False,
) -> Path:
    """Render a pure-black hold segment for a card-less scene boundary dip.
    [Story 5.16 AC:1,3,5]

    No drawtext, no self-fades — it sits between two segments that already
    fade to/from black at their own edges. Carries the incoming scene's mood
    ambient bed when sound design is on (same recipe as the card); anullsrc
    otherwise. Mood-independent (silent) holds share one file per run; mood-
    bearing holds render per boundary since adjacent boundaries may announce
    different moods.
    """
    hold_path = out_dir / (
        f"hold_{index:03d}.mp4" if sound_design_enabled else "hold_shared.mp4"
    )
    if hold_path.exists():
        return hold_path
    audio_input, audio_filter_args = _card_hold_audio_input(
        mood, sound_design_enabled=sound_design_enabled,
    )
    # Render to a tmp path and rename into place atomically: a crash mid-render
    # must never leave a truncated file at hold_path for the exists() cache
    # check above to pick up on a retried/resumed run.
    tmp_path = hold_path.with_suffix(".tmp.mp4")
    rc, stderr = await _run_ffmpeg(
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s={COMP_W}x{COMP_H}:r={FPS}:d={BLACK_HOLD_DURATION}",
        *audio_input,
        *audio_filter_args,
        "-map", "0:v", "-map", "1:a",
        "-t", f"{BLACK_HOLD_DURATION:.3f}",
        *_OUTPUT_ARGS,
        str(tmp_path),
    )
    if rc != 0:
        raise RuntimeError(f"FFmpeg black hold {index} failed (rc={rc}): {stderr[-500:]}")
    if not tmp_path.exists():
        raise RuntimeError(f"FFmpeg black hold {index}: output not created: {tmp_path}")
    tmp_path.replace(hold_path)
    return hold_path


async def _join_with_fades(
    segments: list[tuple[Path, float, float, float]],
    output: Path,
) -> None:
    """Join segments with in-place fades + concat — no overlap. [Story 5.16 AC:1,2,6]

    segments: list of (path, duration_seconds, fade_in_sec, fade_out_sec).
    Fades are computed by the caller (video_node): 0.0 for cards/holds (already
    black, or self-fading), 0.0 fade-in on the first segment and 0.0 fade-out
    on the last (no fade into/out of nothing).

    Each segment fades to/from black over its OWN first/last frames — no frame
    ever blends two segments' images, and no segment content is trimmed or
    consumed by a shared transition window (replaces xfade's offset
    accounting, the #1 source of its timing bugs). Audio passes through
    untouched via plain concat: no acrossfade, no adelay/amix, no gain
    manipulation anywhere — narration plays to its last sample before the
    boundary (Story 5.9's no-volume-dip guarantee now holds by construction,
    since there is no overlap window at all).
    """
    n = len(segments)
    assert n >= 2

    v_parts: list[str] = []
    concat_labels: list[str] = []
    for i, (_, dur, fade_in, fade_out) in enumerate(segments):
        # Clamp fade_out against the remaining duration after fade_in (not just
        # against dur) so a segment shorter than fade_in+fade_out can't get
        # overlapping fade-in/fade-out windows on its own frames.
        fade_in = min(fade_in, dur)
        fade_out = min(fade_out, dur - fade_in)
        fades = []
        if fade_in:
            fades.append(f"fade=t=in:st=0:d={fade_in:.3f}")
        if fade_out:
            fades.append(f"fade=t=out:st={dur - fade_out:.3f}:d={fade_out:.3f}")
        if fades:
            v_label = f"[v{i}]"
            v_parts.append(f"[{i}:v]{','.join(fades)}{v_label}")
            concat_labels.append(v_label)
        else:
            concat_labels.append(f"[{i}:v]")
        concat_labels.append(f"[{i}:a]")

    filter_complex = "; ".join(
        [*v_parts, "".join(concat_labels) + f"concat=n={n}:v=1:a=1[vout][aout]"]
    )

    input_args: list[str] = []
    for path, _, _, _ in segments:
        input_args += ["-i", str(path)]

    rc, stderr = await _run_ffmpeg(
        "-y",
        *input_args,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        str(output),
    )
    if rc != 0:
        raise RuntimeError(f"FFmpeg fade join failed (rc={rc}): {stderr[-500:]}")
    if not output.exists():
        raise RuntimeError(f"FFmpeg fade join: output not created: {output}")



# ── Node ──────────────────────────────────────────────────────────────────────


@observe(name="video")
async def video_node(state: PipelineState) -> dict:
    run_id = state.get("run_id", "?")
    t0 = time.perf_counter()
    try:
        if not shutil.which("ffmpeg"):
            raise EnvironmentError("ffmpeg not found in PATH; install ffmpeg to use video_node")

        scenes = sorted(state.get("scenes", []), key=lambda sc: sc["scene_num"])
        if not scenes:  # explicit guard — don't rely on the join assert (stripped under -O)
            raise ValueError("no scenes to render")
        s = _settings()
        scp_id = state.get("scp_id", "")
        _validate_scene_assets(scenes, sound_design_enabled=s.sound_design_enabled)

        # ── Story 1.13: LLM angle pre-selection ───────────────────────────
        angle_meta: dict = {}
        if _angle_selector is not None:
            t_angle = time.perf_counter()
            try:
                selections = await _angle_selector(scp_id, scenes)
                if selections:
                    angles_selected: list[str] = []
                    fallback_used = 0
                    for scene in scenes:
                        for shot in scene.get("shots", []):
                            key = f"{scene['scene_num']}:{shot['shot_id']}"
                            sel = selections.get(key)
                            if sel and sel.get("path"):
                                shot["character_path"] = sel["path"]
                                angles_selected.append(sel.get("angle", "?"))
                                if sel.get("fallback"):
                                    fallback_used += 1  # true fallback, not a legit "front" pick
                            # ponytail: if no selection for this shot, leave character_path unchanged
                    angle_meta = {
                        "scp_id": scp_id,
                        "shots_analyzed": len(angles_selected),
                        "angles_selected": angles_selected,
                        "fallback_used": fallback_used,
                        "latency_ms": int((time.perf_counter() - t_angle) * 1000),
                    }
                    logger.info(
                        "Angle selection: %d shots, %d angles in %dms",
                        len(angles_selected), len(set(angles_selected)), angle_meta["latency_ms"],
                    )
            except Exception as exc:  # noqa: BLE001 — AD-10: never fail the pipeline
                logger.warning("Angle selection failed, continuing with existing character_path: %s", exc)

        # ── Story 1.9/1.9b: FFmpeg composition ────────────────────────────

        run_dir = Path(s.workspace_path) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Chapter cards (Story 5.1): only meaningful with 2+ scenes to join. Computed
        # up front (Story 5.17 AC:7) so _compose_scene knows whether to suppress its
        # own scene-entry stinger for scenes immediately following a card.
        chapter_cards_enabled = bool(s.chapter_cards) and len(scenes) >= 2

        segs_with_specs: list[tuple[Path, float, EffectSpec, bool]] = []
        for i, scene in enumerate(scenes):
            seg_path, spec, has_char = await _compose_scene(
                scene, i, run_dir,
                sound_design_enabled=s.sound_design_enabled,
                post_fx_enabled=s.post_fx_enabled,
                parallax_enabled=s.parallax_enabled,
                include_stinger=not (chapter_cards_enabled and i > 0),
            )
            duration: float = scene["audio_duration"]  # type: ignore[assignment]  # validated positive
            segs_with_specs.append((seg_path, duration, spec, has_char))

        output = run_dir / "video.mp4"
        segs = [p for p, _, _, _ in segs_with_specs]

        card_duration = _chapter_card_duration(s.chapter_card_duration_sec)
        card_count = 0

        # CC BY-SA attribution (Story 5.20): compute up front so both the single-
        # and multi-scene join paths know whether to append it as the true last
        # segment. Composition failure is non-fatal (AC:5) — the run's own
        # try/except records the message, ending_credit_path stays None, and the
        # join proceeds without it.
        cc_attribution = s.cc_attribution
        ending_credit_path: Path | None = None
        ending_credit_error: str | None = None
        if cc_attribution:
            try:
                ending_credit_path = await _compose_ending_credit(
                    scp_id, run_dir, mood=scenes[-1].get("mood"),
                    post_fx_enabled=s.post_fx_enabled,
                    sound_design_enabled=s.sound_design_enabled,
                )
            except Exception as exc:  # noqa: BLE001 — AD-10: attribution never fails the run
                logger.warning("Ending credit card failed for run %s: %s", run_id, exc)
                ending_credit_error = str(exc)

        if len(segs) == 1:
            if ending_credit_path is not None:
                await _join_with_fades(
                    [
                        (segs[0], segs_with_specs[0][1], 0.0, FADE_DURATION),
                        (ending_credit_path, MAX_CARD_DURATION, 0.0, 0.0),
                    ],
                    output,
                )
            else:
                segs[0].replace(output)  # replace: atomic overwrite, cross-platform
        else:  # 2+ scenes: dip-to-black fade+concat join (Story 5.16)
            last_idx = len(segs_with_specs) - 1
            join_segments: list[tuple[Path, float, float, float]] = []
            for i, (seg_path, duration, _, _) in enumerate(segs_with_specs):
                fade_in = 0.0 if i == 0 else FADE_DURATION
                # The true final segment gets no fade-out (nothing follows it) —
                # UNLESS the ending credit card is appended after it, in which
                # case it must dip to black like any other internal boundary.
                is_true_end = i == last_idx and ending_credit_path is None
                fade_out = 0.0 if is_true_end else FADE_DURATION
                join_segments.append((seg_path, duration, fade_in, fade_out))
                if i == last_idx:
                    continue
                upcoming_mood = scenes[i + 1].get("mood")
                if chapter_cards_enabled:
                    # Card boundaries produce no double dip (AC:5) — the card
                    # IS the dip, self-fading internally; it gets 0.0 join-fades.
                    next_scene = scenes[i + 1]
                    label = _card_label(next_scene)
                    # AC:8 — the "- N -" fallback carries no kicker line, even if a
                    # kicker exists without a title (partial checkpoint/LLM omission).
                    has_title = bool(str(next_scene.get("title") or "").strip())
                    kicker = (next_scene.get("kicker") or "") if has_title else ""
                    card_path = await _compose_chapter_card(
                        label, i + 1, run_dir, card_duration,
                        kicker=kicker, mood=upcoming_mood, post_fx_enabled=s.post_fx_enabled,
                        sound_design_enabled=s.sound_design_enabled,
                    )
                    join_segments.append((card_path, card_duration, 0.0, 0.0))
                    card_count += 1
                else:
                    hold_path = await _compose_black_hold(
                        run_dir, i + 1, mood=upcoming_mood,
                        sound_design_enabled=s.sound_design_enabled,
                    )
                    join_segments.append((hold_path, BLACK_HOLD_DURATION, 0.0, 0.0))
            if ending_credit_path is not None:
                # Self-fading, same contract as a chapter card (AC:2). Its actual
                # rendered length is always MAX_CARD_DURATION (_compose_ending_credit
                # never uses the configured card_duration), so the join must declare
                # the same value it was rendered at.
                join_segments.append((ending_credit_path, MAX_CARD_DURATION, 0.0, 0.0))
            await _join_with_fades(join_segments, output)

        if cc_attribution:
            await _write_description_artifact(run_dir, scp_id)

        effects_meta = [
            {
                "scene_num": scenes[i]["scene_num"],
                "direction": spec.direction,
                "start_zoom": spec.start_zoom,
                "end_zoom": spec.end_zoom,
                "character_overlay": has_char,
            }
            for i, (_, _, spec, has_char) in enumerate(segs_with_specs)
        ]

        _record_trace(
            run_id=run_id, scene_count=len(scenes),
            latency_ms=_ms(t0), output_path=str(output),
            returncode=0, effects=effects_meta, upscale_pass=True,
            character_scenes=sum(1 for *_, hc in segs_with_specs if hc),
            angle_selection=angle_meta if angle_meta else None,
            chapter_cards_enabled=chapter_cards_enabled,
            chapter_card_duration=card_duration,
            chapter_card_count=card_count,
            ending_credit=ending_credit_path is not None,
            ending_credit_error=ending_credit_error,
        )
        result = {"current_stage": "video", "video_path": str(output), "error": None}
        if cc_attribution:
            result["ending_credit_error"] = ending_credit_error
        return result

    except Exception as exc:  # noqa: BLE001
        _record_trace(
            run_id=run_id, scene_count=len(state.get("scenes", [])),
            latency_ms=_ms(t0), error=exc,
        )
        return {"current_stage": "video", "error": f"stage=video run_id={run_id}: {exc}"}
