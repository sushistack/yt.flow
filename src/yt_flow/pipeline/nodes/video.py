"""video_node — FFmpeg composition stage (Story 1.9 + 1.9b).

Story 1.9: per-scene segment render + concat → video.mp4
Story 1.9b: Ken Burns zoompan per shot + xfade/acrossfade scene transitions

Layer rule: domain and config only; no db/, api/, services/. [AD-1]
"""

import asyncio
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from langfuse import get_client, observe

from yt_flow.config import Settings
from yt_flow.domain.state import PipelineState, SceneState, ShotData

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

    inc = (ZOOM_IN_MAX - 1.0) / frames

    direction = spec.direction
    if direction == "in-center":
        z_expr = f"min(zoom+{inc:.6f},{ZOOM_IN_MAX})"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif direction == "out-center":
        # zoom-out needs the conditional: zoompan clamps z≥1 and is stateful
        z_expr = f"if(lte(zoom,1.0),{ZOOM_IN_MAX},max(1.001,zoom-{inc:.6f}))"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif direction == "pan-right":
        z_expr = f"min(zoom+{inc:.6f},{ZOOM_IN_MAX})"
        x_expr = f"(iw-iw/zoom)*on/{frames}"
        y_expr = "ih/2-(ih/zoom/2)"
    elif direction == "pan-left":
        z_expr = f"min(zoom+{inc:.6f},{ZOOM_IN_MAX})"
        x_expr = f"(iw-iw/zoom)*(1-on/{frames})"
        y_expr = "ih/2-(ih/zoom/2)"
    elif direction == "pan-up":
        z_expr = f"min(zoom+{inc:.6f},{ZOOM_IN_MAX})"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"(ih-ih/zoom)*on/{frames}"
    else:  # pan-down
        z_expr = f"min(zoom+{inc:.6f},{ZOOM_IN_MAX})"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"(ih-ih/zoom)*(1-on/{frames})"

    zp = (
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
        f":d={frames}:s={COMP_W}x{COMP_H}:fps={FPS}"
    )

    return (
        f"scale={safe_w}:-2,setsar=1:1,crop={safe_w}:{safe_h},"
        f"scale=8000:-1,{zp}"
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
    error=None,
) -> None:
    """Best-effort Langfuse span enrichment. [AD-10 — tracing is non-fatal]"""
    try:
        get_client().update_current_span(
            metadata={
                "run_id": run_id,
                "scene_count": scene_count,
                "latency_ms": latency_ms,
                **({"output_path": output_path} if output_path else {}),
                **({"ffmpeg_returncode": returncode} if returncode is not None else {}),
                **({"effects": effects} if effects is not None else {}),
                "transition": XFADE_TRANSITION,
                "transition_duration": XFADE_DURATION,
                "upscale_pass": upscale_pass,
                **({"error": repr(error)} if error is not None else {}),
            }
        )
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


async def _compose_scene(
    scene: SceneState,
    scene_index: int,
    out_dir: Path,
) -> tuple[Path, EffectSpec]:
    """Render one scene to MP4 segment with Ken Burns zoompan + burned SRT. [AC:1]"""
    n = scene["scene_num"]
    shots = scene.get("shots") or []
    shot = next((s for s in shots if s.get("image_path")), None)
    if shot is None:  # defensive; _validate_scene_assets guarantees this upstream
        raise ValueError(f"scene {n}: no shot has a valid image_path")
    image_path = shot["image_path"]
    audio_path: str = scene["audio_path"]  # type: ignore[assignment]
    subtitle_path: str = scene["subtitle_path"]  # type: ignore[assignment]
    duration = scene.get("audio_duration") or 2.0
    seg_path = out_dir / f"seg_{n:03d}.mp4"

    spec = select_effect(shot, scene_index)
    zp_chain = _zoompan_filter(spec, duration)

    # zoompan already emits exactly COMP_W x COMP_H (s=), so no rescale/pad needed;
    # just burn subtitles (path escaped + single-quoted for the filtergraph).
    sub = _escape_subtitles_path(Path(subtitle_path).resolve())
    vf = f"{zp_chain},subtitles='{sub}'"

    rc, stderr = await _run_ffmpeg(
        "-y",
        "-loop", "1", "-framerate", str(FPS),
        "-i", str(image_path),
        "-i", audio_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(seg_path),
    )
    if rc != 0:
        raise RuntimeError(f"FFmpeg scene {n} failed (rc={rc}): {stderr[-500:]}")
    if not seg_path.exists():
        raise RuntimeError(f"FFmpeg scene {n}: output not created: {seg_path}")
    return seg_path, spec


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

        s = _settings()
        run_dir = Path(s.workspace_path) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        segs_with_specs: list[tuple[Path, float, EffectSpec]] = []
        for i, scene in enumerate(scenes):
            seg_path, spec = await _compose_scene(scene, i, run_dir)
            duration = scene.get("audio_duration") or 2.0
            segs_with_specs.append((seg_path, duration, spec))

        output = run_dir / "video.mp4"
        segs = [p for p, _, _ in segs_with_specs]

        if len(segs) == 1:
            segs[0].replace(output)  # replace: atomic overwrite, cross-platform
        else:  # 2+ scenes: xfade join (label wiring handles n>=2 uniformly)
            await _join_with_xfade(
                [(p, d) for p, d, _ in segs_with_specs],
                output,
            )

        effects_meta = [
            {
                "scene_num": scenes[i]["scene_num"],
                "direction": spec.direction,
                "start_zoom": spec.start_zoom,
                "end_zoom": spec.end_zoom,
            }
            for i, (_, _, spec) in enumerate(segs_with_specs)
        ]

        _record_trace(
            run_id=run_id, scene_count=len(scenes),
            latency_ms=_ms(t0), output_path=str(output),
            returncode=0, effects=effects_meta, upscale_pass=True,
        )
        return {"current_stage": "video", "video_path": str(output)}

    except Exception as exc:  # noqa: BLE001
        _record_trace(
            run_id=run_id, scene_count=len(state.get("scenes", [])),
            latency_ms=_ms(t0), error=exc,
        )
        return {"current_stage": "video", "error": f"stage=video run_id={run_id}: {exc}"}
