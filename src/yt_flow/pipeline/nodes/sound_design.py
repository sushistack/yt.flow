"""sound_design — mood-driven BGM/ambient/stinger mixing for video_node (Story 7.1).

Pure functions only: mood resolution, asset-path lookup, fail-fast asset
validation, and ffmpeg arg/filter-graph builders. No ffmpeg invocation here —
video.py calls `_run_ffmpeg` with the args/filter this module builds.

Layer rule: domain and config only; no db/, api/, services/. [AD-1]
"""

from pathlib import Path

MOOD_VALUES = ("dread", "clinical", "escalation", "revelation")
DEFAULT_MOOD = "dread"

_AUDIO_ROOT = Path("data/audio")

MOOD_ASSET_PATHS: dict[str, dict[str, Path]] = {
    mood: {
        "bgm": _AUDIO_ROOT / "bgm" / f"{mood}.mp3",
        "ambient": _AUDIO_ROOT / "ambient" / f"{mood}.mp3",
        "stinger": _AUDIO_ROOT / "sfx" / f"{mood}_stinger.mp3",
    }
    for mood in MOOD_VALUES
}

# ponytail: tuned-by-ear defaults, promote to Settings only if a real scene needs a different value
BGM_VOLUME = 0.25
AMBIENT_VOLUME = 0.15
STINGER_VOLUME = 0.5
SIDECHAIN_THRESHOLD = 0.05
SIDECHAIN_RATIO = 8
SIDECHAIN_ATTACK = 5
SIDECHAIN_RELEASE = 300


def resolve_mood(mood: str | None) -> str:
    """Unknown/missing/empty mood -> DEFAULT_MOOD. Mirrors video.select_effect's hint fallback."""
    return mood if mood in MOOD_VALUES else DEFAULT_MOOD


def validate_mood_assets(mood: str) -> None:
    """Raise before FFmpeg if any of the resolved mood's 3 asset files are missing."""
    resolved = resolve_mood(mood)
    for role, path in MOOD_ASSET_PATHS[resolved].items():
        if not path.exists():
            raise FileNotFoundError(f"sound design: mood {resolved!r} {role} file not found: {path}")


def build_sound_design_args(mood: str) -> list[str]:
    """Extra ffmpeg -i input args: bgm/ambient looped, stinger as a one-shot.

    Order (bgm, ambient, stinger) matches the index math build_sound_design_filter
    assumes via input_offset.
    """
    paths = MOOD_ASSET_PATHS[resolve_mood(mood)]
    return [
        "-stream_loop", "-1", "-i", str(paths["bgm"]),
        "-stream_loop", "-1", "-i", str(paths["ambient"]),
        "-i", str(paths["stinger"]),
    ]


def build_sound_design_filter(
    mood: str, duration: float, narration_label: str, input_offset: int,
) -> tuple[str, str]:
    """Build the amix+sidechaincompress fragment ducking bgm/ambient/stinger under narration.

    `input_offset` is the ffmpeg input index of the first sound-design input
    (bgm); ambient and stinger follow at +1/+2. Returns (filter_fragment, output_label).
    """
    bgm_idx, ambient_idx, stinger_idx = input_offset, input_offset + 1, input_offset + 2
    fragment = (
        f"[{bgm_idx}:a]volume={BGM_VOLUME}[bgm_v];"
        f"[{ambient_idx}:a]volume={AMBIENT_VOLUME}[amb_v];"
        f"[{stinger_idx}:a]volume={STINGER_VOLUME},apad=whole_dur={duration}[stg_v];"
        f"[bgm_v][amb_v][stg_v]amix=inputs=3:duration=first[bgmix];"
        f"[bgmix]{narration_label}sidechaincompress="
        f"threshold={SIDECHAIN_THRESHOLD}:ratio={SIDECHAIN_RATIO}:"
        f"attack={SIDECHAIN_ATTACK}:release={SIDECHAIN_RELEASE}[ducked];"
        f"[ducked]{narration_label}amix=inputs=2:duration=first:normalize=0[aout]"
    )
    return fragment, "[aout]"
