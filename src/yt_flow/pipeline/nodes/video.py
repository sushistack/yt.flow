"""video_node — FFmpeg composition stage (Story 1.9 + 1.9b).

Story 1.9: per-scene segment render + concat → video.mp4
Story 1.9b: Ken Burns zoompan per shot + xfade/acrossfade scene transitions
Story 1.13: LLM-based character angle pre-selection before FFmpeg composition

Layer rule: domain and config only; no db/, api/, services/. [AD-1]
"""

import asyncio
import functools
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yt_flow.observability import get_client, observe

from yt_flow.config import Settings
from yt_flow.domain.state import PipelineState, SceneState, ShotData
from yt_flow.pipeline.nodes.sound_design import (
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

# xfade defaults — single type until a second is actually wanted
# ponytail: single crossfade type, constants not per-scene config
# fadeblack (Story 5.1): scene boundaries cut to black, never blend two scene
# images together — plain "fade" showed both images overlapped mid-transition.
XFADE_TRANSITION = "fadeblack"
XFADE_DURATION = 0.5  # seconds

# ── Chapter-card constants (Story 5.1) ─────────────────────────────────────────
MIN_CARD_DURATION = 1.5
MAX_CARD_DURATION = 2.0
CARD_FADE_DURATION = 0.25  # seconds, in/out fade inside the card itself
CARD_FONT_SIZE = 72

# ── Character idle-motion constants (Story 1.9c) ──────────────────────────────
# Sway = larger/slower horizontal drift; bob = subtle/faster vertical breathing.
# Tremble (tense scenes) is out of scope until a scene ever requests it.
# ponytail: fixed tasteful defaults, not per-scene config; add a knob when a shot
# actually needs different motion.
SWAY_AMPLITUDE = 12   # px, x-axis idle drift
SWAY_FREQ = 0.8       # rad/s
BOB_AMPLITUDE = 8     # px, y-axis breathing/bob
BOB_FREQ = 1.2        # rad/s

# Motion-safe character box: shrink an oversized character to leave room for the
# full sway/bob excursion, so idle motion can never push it off-frame and a
# mis-sized ComfyUI asset (character bytes are written raw, never scaled upstream)
# can't overflow. Sized so the centered overlay + max sine offset stays on-frame.
CHAR_MAX_W = COMP_W - 2 * SWAY_AMPLITUDE
CHAR_MAX_H = COMP_H - 2 * BOB_AMPLITUDE


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


def _overlay_filter() -> str:
    """Character sway+bob idle-motion overlay, centered on the background. [AC:1,2]

    ``eval=frame`` is REQUIRED and set explicitly: under the ``eval=init`` default
    for *some* builds the ``t``/``n`` timeline vars collapse to NAN and the
    character freezes. Two sines (x sway, y bob) at different freq/amplitude give
    the subtle "alive" drift without rigging.
    """
    x = f"(main_w-overlay_w)/2 + sin(t*{SWAY_FREQ})*{SWAY_AMPLITUDE}"
    y = f"(main_h-overlay_h)/2 + sin(t*{BOB_FREQ})*{BOB_AMPLITUDE}"
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


@functools.lru_cache(maxsize=1)
def _drawtext_font() -> str:
    """Resolve a Korean-capable drawtext font via fontconfig. [Story 5.1 AC:2]

    Never hardcodes a machine-specific path: ``fc-match`` resolves whatever the
    OS actually has installed. Noto Sans CJK first (Korean labels), DejaVu Sans
    as the widely-packaged fallback.
    """
    for family in ("Noto Sans CJK KR", "DejaVu Sans"):
        try:
            result = subprocess.run(
                ["fc-match", "--format=%{file}", family],
                capture_output=True, text=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        path = result.stdout.strip()
        if path and Path(path).exists():
            return path
    for path in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(path).exists():
            return path
    raise RuntimeError("no drawtext font resolved via fc-match (Noto Sans CJK KR / DejaVu Sans)")


def _card_label(scene: SceneState) -> str:
    """Chapter-card label for the upcoming scene. [Story 5.1 AC:3]

    Uses a real title only if the state already carries one; SceneState has no
    ``title`` field today, so this always falls back to ``"- N -"`` until one
    is added upstream.
    """
    if "title" in SceneState.__annotations__:
        title = str(scene.get("title", "")).strip()  # type: ignore[typeddict-item]
        if title:
            return title
    return f"- {scene['scene_num']} -"


def _chapter_card_duration(value: float) -> float:
    """Clamp chapter-card duration to the accepted Story 5.1 range."""
    return min(MAX_CARD_DURATION, max(MIN_CARD_DURATION, float(value)))


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
            "transition": XFADE_TRANSITION,
            "transition_duration": XFADE_DURATION,
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
        # audio_duration drives zoompan frame count + xfade offset; a missing/≤0 value
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
) -> tuple[Path, EffectSpec, bool]:
    """Render one scene segment: Ken Burns zoompan + burned SRT, optionally with a
    transparent character composited on top with idle motion, optionally with a
    mood-driven BGM/ambient/stinger mix ducked under the narration. [AC:1,3] [Story 7.1]

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

    if character_path:
        # Layered: zoompan the background, overlay the moving character, then burn
        # subtitles on top. Two looped image inputs (0=bg, 1=char) + audio (2).
        inputs = [
            "-loop", "1", "-framerate", str(FPS), "-i", str(bg_path),
            "-loop", "1", "-framerate", str(FPS), "-i", str(character_path),
            "-i", audio_path,
        ]
        video_chain = (
            f"[0:v]{zp_chain}[bg];"
            f"[1:v]{_character_scale_filter()}[char];"
            f"[bg][char]{_overlay_filter()}[ov];"
            f"[ov]subtitles='{sub}'[out]"
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
        video_chain = f"[0:v]{zp_chain},subtitles='{sub}'[vout]"
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
        sound_args = build_sound_design_args(resolved_mood)
        sound_fragment, audio_out_label = build_sound_design_filter(
            resolved_mood, duration, narration_label, input_offset,
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
        # Disabled = unchanged (AC:8): keep the pre-existing -vf path byte-for-byte.
        vf = f"{zp_chain},subtitles='{sub}'"
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


async def _compose_chapter_card(
    label: str,
    index: int,
    out_dir: Path,
    duration: float,
) -> Path:
    """Render a black title-card segment: color bg + centered drawtext + silent
    audio, fading in/out at its own edges. [Story 5.1 AC:2,5]

    Matches _compose_scene's output contract (COMP_W x COMP_H, FPS, H.264/AAC,
    yuv420p, has an audio stream) so _join_with_xfade can treat it as an
    ordinary segment — no join-engine changes needed.
    """
    card_path = out_dir / f"card_{index:03d}.mp4"
    label_file = out_dir / f"card_{index:03d}_label.txt"
    label_file.write_text(label, encoding="utf-8")
    font = _escape_subtitles_path(Path(_drawtext_font()))
    textfile = _escape_subtitles_path(label_file)
    fade_out_start = max(0.0, duration - CARD_FADE_DURATION)
    vf = (
        f"drawtext=fontfile='{font}':textfile='{textfile}':"
        f"fontcolor=white:fontsize={CARD_FONT_SIZE}:x=(w-text_w)/2:y=(h-text_h)/2,"
        f"fade=t=in:st=0:d={CARD_FADE_DURATION},"
        f"fade=t=out:st={fade_out_start:.3f}:d={CARD_FADE_DURATION}"
    )
    rc, stderr = await _run_ffmpeg(
        "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={COMP_W}x{COMP_H}:r={FPS}:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", vf,
        "-t", f"{duration:.3f}",
        *_OUTPUT_ARGS,
        str(card_path),
    )
    if rc != 0:
        raise RuntimeError(f"FFmpeg chapter card {index} failed (rc={rc}): {stderr[-500:]}")
    if not card_path.exists():
        raise RuntimeError(f"FFmpeg chapter card {index}: output not created: {card_path}")
    return card_path


async def _join_with_xfade(
    segments: list[tuple[Path, float]],
    output: Path,
) -> None:
    """Join scenes with xfade (video) + delayed overlay-mix (audio). [AC:2] [Story 5.9 AC:1-3]

    segments: list of (path, duration_seconds).
    xfade offset is measured on the *combined* prior output, so it accumulates:
    the transition after segment i begins at Σ(dur_0..i) − (i+1)·XFADE_DURATION,
    which is XFADE_DURATION before the running combined length ends. This is the
    #1 source of xfade timing bugs; we track running_offset explicitly.

    Audio does NOT use `acrossfade` (Story 5.9): that filter fades each
    segment's volume down/up over the overlap window, which is audible as a
    volume dip at every scene cut in sync with the video's fade-to-black.
    Instead, each segment's audio is delayed (`adelay`) to start at the exact
    same offset the video xfade uses for that segment, then summed
    (`amix=normalize=0`, so ongoing solo playback is never scaled down) —
    narration plays at full, constant volume and only briefly overlaps with
    its neighbor during the black-frame transition window, landing on the
    same total duration as the video stream (proven: the last segment's
    delayed end time telescopes to exactly the video's combined length).
    """
    n = len(segments)
    assert n >= 2
    # ponytail: assumes each scene ≥ 2×XFADE_DURATION (TTS narration is always multi-second).
    # Below XFADE_DURATION, offset goes negative outright (guarded below). Between
    # XFADE_DURATION and 2×XFADE_DURATION, offset stays non-negative but the scene's
    # own overlap windows with both neighbors touch/collide, producing 3-way audio
    # overlap instead of the intended pairwise crossfade window — add a per-pair
    # min-duration clamp only if scenes that short ever become real.

    # Build video filter chain
    v_parts: list[str] = []
    a_parts: list[str] = []
    audio_labels: list[str] = ["[0:a]"]
    running_offset = 0.0
    v_prev = "[0:v]"

    for i, (_, dur) in enumerate(segments):
        if i < n - 1:
            running_offset += dur
            offset = running_offset - (i + 1) * XFADE_DURATION
            v_out = f"[vx{i}]" if i < n - 2 else "[vout]"
            v_parts.append(
                f"{v_prev}[{i+1}:v]xfade=transition={XFADE_TRANSITION}"
                f":duration={XFADE_DURATION}:offset={offset:.4f}{v_out}"
            )
            v_prev = v_out

            assert offset >= 0, (
                f"segment {i} duration {dur}s is too short for XFADE_DURATION="
                f"{XFADE_DURATION}s — offset went negative ({offset:.3f}s); a silent "
                "clamp here would desync audio from the video xfade's own offset"
            )
            delay_ms = round(offset * 1000)
            a_out = f"[ad{i+1}]"
            a_parts.append(f"[{i+1}:a]adelay={delay_ms}:all=1{a_out}")
            audio_labels.append(a_out)

    a_parts.append(
        "".join(audio_labels) + f"amix=inputs={n}:normalize=0:duration=longest[aout]"
    )

    filter_complex = "; ".join(v_parts + a_parts)

    # Build input args: one -i per segment
    input_args: list[str] = []
    for path, _ in segments:
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
        raise RuntimeError(f"FFmpeg xfade join failed (rc={rc}): {stderr[-500:]}")
    if not output.exists():
        raise RuntimeError(f"FFmpeg xfade: output not created: {output}")



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
        _validate_scene_assets(scenes, sound_design_enabled=s.sound_design_enabled)

        # ── Story 1.13: LLM angle pre-selection ───────────────────────────
        angle_meta: dict = {}
        if _angle_selector is not None:
            t_angle = time.perf_counter()
            try:
                scp_id = state.get("scp_id", "")
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

        segs_with_specs: list[tuple[Path, float, EffectSpec, bool]] = []
        for i, scene in enumerate(scenes):
            seg_path, spec, has_char = await _compose_scene(
                scene, i, run_dir, sound_design_enabled=s.sound_design_enabled,
            )
            duration: float = scene["audio_duration"]  # type: ignore[assignment]  # validated positive
            segs_with_specs.append((seg_path, duration, spec, has_char))

        output = run_dir / "video.mp4"
        segs = [p for p, _, _, _ in segs_with_specs]

        # Chapter cards (Story 5.1): only meaningful with 2+ scenes to join.
        chapter_cards_enabled = bool(s.chapter_cards) and len(segs_with_specs) >= 2
        card_duration = _chapter_card_duration(s.chapter_card_duration_sec)
        card_count = 0

        if len(segs) == 1:
            segs[0].replace(output)  # replace: atomic overwrite, cross-platform
        else:  # 2+ scenes: xfade join (label wiring handles n>=2 uniformly)
            join_segments: list[tuple[Path, float]] = []
            for i, (seg_path, duration, _, _) in enumerate(segs_with_specs):
                join_segments.append((seg_path, duration))
                if chapter_cards_enabled and i < len(segs_with_specs) - 1:
                    label = _card_label(scenes[i + 1])
                    card_path = await _compose_chapter_card(label, i + 1, run_dir, card_duration)
                    join_segments.append((card_path, card_duration))
                    card_count += 1
            await _join_with_xfade(join_segments, output)

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
        )
        return {"current_stage": "video", "video_path": str(output), "error": None}

    except Exception as exc:  # noqa: BLE001
        _record_trace(
            run_id=run_id, scene_count=len(state.get("scenes", [])),
            latency_ms=_ms(t0), error=exc,
        )
        return {"current_stage": "video", "error": f"stage=video run_id={run_id}: {exc}"}
