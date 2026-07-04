# Kinetic Subtitle Typography (Word-Level Karaoke Highlight) — Design

**Date**: 2026-07-04
**Status**: Approved for planning (not scheduled — drafted ahead of need)
**Scope**: 4th candidate of the "영상미 개선" initiative, split from
"트랜지션/자막 다양화" — sibling to
[2026-07-04-transition-variety-design.md](2026-07-04-transition-variety-design.md),
no shared code (different file, `subtitle.py` not `video.py`; different
failure modes). Does not depend on the mood taxonomy — this is orthogonal to
mood.

## Problem

`SceneState.word_timings` already carries per-word `start_sec`/`end_sec`
(populated by `tts_node`, consumed today only to *group* words into
≤40-char SRT cues via `_word_timings_to_segments`). The per-word timing
precision is thrown away at that point — the burned-in subtitle is a plain
static SRT cue, no different from subtitles generated with no word-level
data at all. Karaoke-style word highlighting (the currently-spoken word lights
up as it's said) is a real production-value upgrade that costs nothing extra
in data — the timing already exists, it's just unused downstream.

## Why ASS, not SRT

ffmpeg's `subtitles=` filter is backed by `libass` regardless of input
format — SRT gets parsed and rendered with default/minimal styling; `.ass`
(SubStation Alpha) is the same filter, same dependency, but exposes styling
and per-character timing tags SRT has no syntax for. Specifically the `\k`
karaoke tag: `{\k50}word ` means "transition this word from the style's
`SecondaryColour` to `PrimaryColour` over 50 centiseconds" — exactly the
per-word highlight-as-spoken effect, natively supported by the same libass
ffmpeg already links. **Zero new dependencies.**

## Design

New function in `subtitle.py`, sitting alongside the existing SRT path
(`format_srt`/`_word_timings_to_segments`), not replacing it:

```python
# ── ASS/karaoke utilities ───────────────────────────────────────────────
SUBTITLE_FONT_SIZE = 48
SUBTITLE_PRIMARY_COLOR = "&H00FFFFFF"     # ASS BGR+alpha hex: white, unsung
SUBTITLE_HIGHLIGHT_COLOR = "&H0000D7FF"   # amber/gold, currently-sung word
SUBTITLE_OUTLINE_WIDTH = 2                # legibility over grainy/graded footage (spec 2)


@functools.lru_cache(maxsize=1)
def _ass_font_family() -> str:
    """Same fc-match resolution _drawtext_font() already does in video.py,
    but returns the font *family name* (ASS styles reference fontconfig
    families, not file paths)."""
    # fc-match --format=%{family} "Noto Sans CJK KR" / "DejaVu Sans"


def _ass_header() -> str:
    """[Script Info] + [V4+ Styles] block, one Style using the two colors
    above, resolution locked to COMP_W x COMP_H so libass doesn't rescale."""


def build_ass_events(timings: list[WordTiming], max_chars: int = 40) -> str:
    """Group words into ≤max_chars cues (same grouping rule as
    _word_timings_to_segments, reused not reimplemented), emit one
    Dialogue line per cue with {\\k<centiseconds>}word  runs — one \\k tag
    per word, duration = round((end_sec - start_sec) * 100)."""


def format_ass(timings: list[WordTiming], max_chars: int = 40) -> str:
    return _ass_header() + build_ass_events(timings, max_chars)
```

Cue grouping logic is **reused, not duplicated** — `build_ass_events` calls
the existing `_word_timings_to_segments` grouping (or a shared helper
factored out of it) to decide cue boundaries, then re-renders each group's
words as `\k`-tagged runs instead of plain concatenated text. Same 40-char
readability rule, same cue boundaries as the SRT path — only the per-word
tagging inside each cue is new.

## Fallback when word-level timing is unavailable

`subtitle_node` already has two paths: word-level timings from `tts_node`
(the common case) or segment-level output from the `SubtitleAligner`
fallback (no per-word granularity — see the story-1.8 deferral on partial
alignment). Karaoke tagging requires real per-word timestamps; when only
segment-level data is available, `subtitle_node` writes plain `.srt` exactly
as it does today — **no fake/estimated per-word timing is invented**. This
is a graceful capability drop, not an error: some scenes get the kinetic
effect, some don't, depending on what alignment data was actually available.

## `video.py` integration

None needed beyond what already exists. `subtitles='{sub}'` in
`_zoompan_filter`'s caller already takes a path string; `subtitles=` filter
auto-detects `.srt` vs `.ass` by file extension. `_escape_subtitles_path`'s
character-escaping logic is format-agnostic (it escapes the *path*, not the
subtitle content) — unchanged.

## Settings

```python
# src/yt_flow/config.py
kinetic_subtitles_enabled: bool = True   # same pattern as the other 4 specs
```

`subtitle_node` picks `format_ass(...)` + `.ass` extension when true and
word-level timings are available; `format_srt(...)` + `.srt` otherwise
(both the flag-off case and the no-word-timing fallback case funnel to the
same existing SRT path — one fallback, not two).

## Testing

`build_ass_events`/`format_ass` are pure functions — unit test asserts:
per-word `\k` duration matches `round((end - start) * 100)` centiseconds,
cue grouping boundaries match `_word_timings_to_segments`'s existing
grouping for the same input, and the header declares `PlayResX`/`PlayResY`
matching `COMP_W`/`COMP_H`. `subtitle_node`'s existing tests extend to cover
the flag-off and no-word-timing-data cases both landing on `.srt` output.

## Error handling

No new failure modes for the golden path — this only changes subtitle file
*format*, not the validation `video_node._validate_scene_assets` already
does on `subtitle_path` (existence check is extension-agnostic). The one
real risk is a font family libass can't resolve on the render host; reusing
`_drawtext_font()`'s existing `fc-match` resolution + hard failure (rather
than silently falling back to an unstyled default) keeps that consistent
with how Story 5.1's chapter cards already handle font resolution.
