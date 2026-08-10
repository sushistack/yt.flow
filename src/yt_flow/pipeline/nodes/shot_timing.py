"""shot_timing — per-shot clip windows for video_node's per-shot cut assembly.

Derives each rendered shot's (start, end) clip span from its
``sentence_indices`` and the scene's ``sentence_windows()`` (subtitle.py) — the
SAME window math the burned subtitles use, so cuts and cues can never drift
apart (Story 8.11 AC:1). Gaps between consecutive shots' windows (inter-
sentence silence, or a sentence unclaimed by any shot) attach to the
PRECEDING shot; the first/last clip stretch to cover the full scene
audio_duration (AC:2); a clip shorter than ``min_shot_clip_sec`` merges into
the previous clip, the first clip merging forward (AC:3).
"""

import logging
from collections import Counter
from dataclasses import dataclass

from yt_flow.domain.state import ShotData, WordTiming
from yt_flow.pipeline.nodes.subtitle import sentence_windows

logger = logging.getLogger(__name__)


@dataclass
class ShotClip:
    shot: ShotData
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def plan_shot_clips(
    shots: list[ShotData],
    timings: list[WordTiming],
    narration: str,
    audio_duration: float,
    *,
    min_shot_clip_sec: float = 2.0,
) -> list[ShotClip]:
    """Build the per-shot clip plan for one scene. [AC:1,2,3,7]

    ``shots`` is the scene's full shot list; only shots carrying an
    ``image_path`` get their own clip. Falls back to a single full-duration
    clip (today's pre-8.11 behavior) when no usable sentence windows can be
    derived — never fails the stage on timing math (AC:7).
    """
    rendered = [s for s in shots if s.get("image_path")]
    if not rendered:
        return []

    windows = sentence_windows(timings, narration) if timings and narration else []
    if not windows:
        logger.warning(
            "shot_timing: no usable sentence windows (empty word_timings or narration); "
            "falling back to a single full-duration shot clip"
        )
        return [ShotClip(rendered[0], 0.0, audio_duration)]

    n_sentences = len(windows)
    spans: list[tuple[ShotData, int, int]] = []
    for shot in rendered:
        idxs = [i for i in shot.get("sentence_indices", []) if 0 <= i < n_sentences]
        if not idxs:
            logger.warning(
                "shot_timing: shot %s has no sentence_indices within [0, %d); dropped from clip plan",
                shot.get("shot_id"), n_sentences,
            )
            continue
        spans.append((shot, min(idxs), max(idxs)))

    # Story 10.4's ordered cover lets SEVERAL shots start on the same sentence (a
    # split). They would otherwise get identical windows, and the "gaps attach to the
    # preceding shot" loop below would give every one but the last a duration of 0.
    # So the start — and only the start — divides its first sentence's window by the
    # shot's share position. ``share_n == 1`` is every pre-cover run and reproduces
    # ``windows[min(idxs)][0]`` exactly.
    share_n = Counter(first for _, first, _ in spans)
    share_idx: Counter = Counter()
    clips: list[ShotClip] = []
    for shot, first, last in spans:
        w0, w1 = windows[first]
        start = w0 + (w1 - w0) * share_idx[first] / share_n[first]
        share_idx[first] += 1
        clips.append(ShotClip(shot, start, windows[last][1]))

    if not clips:  # defensive — AD-5 promises sentence coverage; guard anyway (AC:2)
        return [ShotClip(rendered[0], 0.0, audio_duration)]

    clips.sort(key=lambda c: c.start)

    # Gaps between consecutive windows (incl. sentences unclaimed by any shot)
    # attach to the PRECEDING shot (AC:1,2).
    for i in range(len(clips) - 1):
        clips[i].end = clips[i + 1].start

    # Full-scene coverage (AC:2).
    clips[0].start = 0.0
    clips[-1].end = audio_duration

    return _merge_short_clips(clips, min_shot_clip_sec)


def _merge_short_clips(clips: list[ShotClip], min_shot_clip_sec: float) -> list[ShotClip]:
    """Merge a clip shorter than ``min_shot_clip_sec`` into the previous clip;
    the first clip (no previous) merges FORWARD into the second instead.
    ``0.0`` disables merging. [AC:3]"""
    if min_shot_clip_sec <= 0.0 or len(clips) <= 1:
        return clips

    merged: list[ShotClip] = [clips[0]]
    for clip in clips[1:]:
        if clip.duration < min_shot_clip_sec:
            merged[-1].end = clip.end  # drop this shot's clip; extend the previous
        else:
            merged.append(clip)

    if len(merged) > 1 and merged[0].duration < min_shot_clip_sec:
        merged[1].start = merged[0].start
        merged.pop(0)

    return merged
