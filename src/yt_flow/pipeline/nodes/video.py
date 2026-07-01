"""video_node — FFmpeg composition stage (Story 1.9 + 1.9b).

Story 1.9: per-scene segment render + concat → video.mp4
Story 1.9b: Ken Burns zoompan per shot + xfade/acrossfade scene transitions
Story 1.13: LLM-based character angle pre-selection before FFmpeg composition

Layer rule: domain and config only; no db/, api/, services/. [AD-1]
"""

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langfuse import get_client, observe

from yt_flow.config import Settings
from yt_flow.domain.state import PipelineState, SceneState, ShotData

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
ZOOM_IN_MAX = 1.08   # subtle push; SCP horror = slow + deliberate
ZOOM_SAFE_MARGIN = 0.10  # 10% inset before crop so zoom/pan never clips subject

# Direction pool: round-robin by scene_index to avoid identical consecutive directions
_DIRECTION_POOL = ["in-center", "pan-right", "pan-left", "out-center", "pan-up", "pan-down"]

# xfade defaults — single type until a second is actually wanted
# ponytail: single crossfade type, constants not per-scene config
XFADE_TRANSITION = "fade"
XFADE_DURATION = 0.5  # seconds

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


def _validate_scene_assets(scenes: list[SceneState]) -> None:
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
) -> tuple[Path, EffectSpec, bool]:
    """Render one scene segment: Ken Burns zoompan + burned SRT, optionally with a
    transparent character composited on top with idle motion. [AC:1,3]

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
        filter_complex = (
            f"[0:v]{zp_chain}[bg];"
            f"[1:v]{_character_scale_filter()}[char];"
            f"[bg][char]{_overlay_filter()}[ov];"
            f"[ov]subtitles='{sub}'[out]"
        )
        rc, stderr = await _run_ffmpeg(
            "-y",
            "-loop", "1", "-framerate", str(FPS), "-i", str(bg_path),
            "-loop", "1", "-framerate", str(FPS), "-i", str(character_path),
            "-i", audio_path,
            "-filter_complex", filter_complex,
            "-map", "[out]", "-map", "2:a",
            *_OUTPUT_ARGS,
            str(seg_path),
        )
    else:
        # Background-only (1.9b): zoompan already emits COMP_W x COMP_H, just burn SRT.
        vf = f"{zp_chain},subtitles='{sub}'"
        rc, stderr = await _run_ffmpeg(
            "-y",
            "-loop", "1", "-framerate", str(FPS), "-i", str(bg_path),
            "-i", audio_path,
            "-vf", vf,
            *_OUTPUT_ARGS,
            str(seg_path),
        )
    if rc != 0:
        raise RuntimeError(f"FFmpeg scene {n} failed (rc={rc}): {stderr[-500:]}")
    if not seg_path.exists():
        raise RuntimeError(f"FFmpeg scene {n}: output not created: {seg_path}")
    return seg_path, spec, bool(character_path)


async def _join_with_xfade(
    segments: list[tuple[Path, float]],
    output: Path,
) -> None:
    """Join scenes with xfade (video) + acrossfade (audio) transitions. [AC:2]

    segments: list of (path, duration_seconds).
    xfade offset is measured on the *combined* prior output, so it accumulates:
    the transition after segment i begins at Σ(dur_0..i) − (i+1)·XFADE_DURATION,
    which is XFADE_DURATION before the running combined length ends. This is the
    #1 source of xfade timing bugs; we track running_offset explicitly.
    """
    n = len(segments)
    assert n >= 2
    # ponytail: assumes each scene ≥ XFADE_DURATION (TTS narration is always multi-second).
    # Sub-0.5s scenes would make offset negative / acrossfade underflow — add a per-pair
    # min-duration clamp only if scenes that short ever become real.

    # Build video filter chain
    v_parts: list[str] = []
    a_parts: list[str] = []
    running_offset = 0.0
    v_prev = "[0:v]"
    a_prev = "[0:a]"

    for i, (_, dur) in enumerate(segments):
        if i < n - 1:
            running_offset += dur
            offset = running_offset - (i + 1) * XFADE_DURATION
            v_out = f"[vx{i}]" if i < n - 2 else "[vout]"
            a_out = f"[ax{i}]" if i < n - 2 else "[aout]"
            v_parts.append(
                f"{v_prev}[{i+1}:v]xfade=transition={XFADE_TRANSITION}"
                f":duration={XFADE_DURATION}:offset={offset:.4f}{v_out}"
            )
            a_parts.append(
                f"{a_prev}[{i+1}:a]acrossfade=d={XFADE_DURATION}{a_out}"
            )
            v_prev = v_out
            a_prev = a_out

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
        _validate_scene_assets(scenes)

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

        s = _settings()
        run_dir = Path(s.workspace_path) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        segs_with_specs: list[tuple[Path, float, EffectSpec, bool]] = []
        for i, scene in enumerate(scenes):
            seg_path, spec, has_char = await _compose_scene(scene, i, run_dir)
            duration: float = scene["audio_duration"]  # type: ignore[assignment]  # validated positive
            segs_with_specs.append((seg_path, duration, spec, has_char))

        output = run_dir / "video.mp4"
        segs = [p for p, _, _, _ in segs_with_specs]

        if len(segs) == 1:
            segs[0].replace(output)  # replace: atomic overwrite, cross-platform
        else:  # 2+ scenes: xfade join (label wiring handles n>=2 uniformly)
            await _join_with_xfade(
                [(p, d) for p, d, _, _ in segs_with_specs],
                output,
            )

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
        )
        return {"current_stage": "video", "video_path": str(output)}

    except Exception as exc:  # noqa: BLE001
        _record_trace(
            run_id=run_id, scene_count=len(state.get("scenes", [])),
            latency_ms=_ms(t0), error=exc,
        )
        return {"current_stage": "video", "error": f"stage=video run_id={run_id}: {exc}"}
