#!/usr/bin/env bash
# Story 10.7 A/B: render the REAL escalation audio graphs, both paths, over real assets.
#
#   bash _bmad-output/implementation-artifacts/10-7-live-validation/make_ab.sh
#
# Writes, next to this script:
#   before.wav                 SCENE path, both OUTGOING assets (siren ambient + klaxon
#                              stinger), through build_sound_design_filter()
#   after.wav                  SCENE path, the assets as they ship now
#   control_narration_only.wav narration alone, no sound design (subtraction control)
#   card_before.wav            CARD path, both OUTGOING assets, through the
#                              _compose_chapter_card audio mix
#   card_after.wav             CARD path, the assets as they ship now
#
# READ THIS BEFORE QUOTING before.wav AS "THE SHIPPED MIX" — it is not.
# `before.wav` is the scene-path mix with include_stinger=True, but production does
# NOT render escalation scene 5 that way: video.py:2510 passes
# `include_stinger=not (chapter_cards_enabled and i > 0)` and chapter_cards defaults
# True, so scene 5 (i=4) shipped with NO stinger input at all. Measured on the run's
# own artifacts (first 2.0 s, 540-580 Hz share / dominant bin): seg_005.mp4 2.49% /
# 378 Hz and seg_007.mp4 2.65% / 767 Hz, against card_004.mp4 and card_006.mp4 at
# 45.32% / 556 Hz each. The klaxon lived on the CHAPTER-CARD path.
# `card_before.wav` / `card_after.wav` are the faithful reproduction of the cue Jay
# identified; before.wav/after.wav remain the honest way to see the *bed* under
# narration, because the card path has no narration and no sidechain duck.
#
# Narration: run 8a9a288b scene 5 (an `escalation` scene in the run Jay watched).
# The scene filter graph is NOT hand-copied — it comes from build_sound_design_filter(),
# so the evidence tracks the real code, including the bed amix at ffmpeg's default
# normalize=1. Only the asset *input paths* are substituted for the "before" renders,
# and the substitution is asserted to have fired (a silent no-op would make
# before == after with no error at all).
set -euo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
exec uv run python - "$(cd "$(dirname "$0")" && pwd)" <<'PY'
import subprocess, sys
from pathlib import Path

out = Path(sys.argv[1])
run = Path("workspace/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d")
narration = run / "audio/scene_005.wav"
# Round 1 swapped the ambient; round 2 swapped the stinger. "before" restores both.
OLD_FOR_NEW = {
    "data/audio/ambient/escalation.mp3": out / "old_escalation_siren.mp3",
    "data/audio/sfx/escalation_stinger.mp3": out / "old_escalation_klaxon.mp3",
}
for p in [narration, *OLD_FOR_NEW.values()]:
    if not Path(p).exists():
        raise SystemExit(f"make_ab.sh: missing input {p}")

sys.path.insert(0, "src")
from yt_flow.pipeline.nodes.sound_design import (
    AMBIENT_VOLUME, STINGER_VOLUME, MOOD_ASSET_PATHS,
    build_sound_design_args, build_sound_design_filter,
)
from yt_flow.pipeline.nodes.video import _chapter_card_duration


def probe(path):
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True).stdout)


def substitute(args):
    """Swap shipped asset paths for the retained outgoing ones, and prove it fired."""
    swapped = [str(OLD_FOR_NEW.get(a, a)) for a in args]
    hits = sum(1 for a in args if a in OLD_FOR_NEW)
    if hits != len(OLD_FOR_NEW):
        raise SystemExit(
            f"make_ab.sh: expected {len(OLD_FOR_NEW)} old-asset substitutions, fired {hits}.\n"
            f"  args: {args}\n  keys: {list(OLD_FOR_NEW)}\n"
            "A silent no-op here would render before.wav identical to after.wav.")
    return swapped


# ---- SCENE path: the audio half of _render_scene_fast (narration is input 0) --------
duration = probe(narration)
sound_args = build_sound_design_args("escalation")
fragment, aout = build_sound_design_filter("escalation", duration, "[0:a]", 1)
print(f"scene duration={duration:.3f}s\nscene filter={fragment}\n")


def render_scene(args, dst):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(narration), *args,
                    "-filter_complex", fragment, "-map", aout, "-t", f"{duration}",
                    str(dst)], check=True)
    print(f"wrote {dst}")


render_scene(sound_args, out / "after.wav")
# ponytail: swap the input paths instead of shuffling files on disk — the graph
# addresses inputs by index, so the "before" render is byte-identical apart from the assets.
render_scene(substitute(sound_args), out / "before.wav")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(narration), "-t", f"{duration}",
                str(out / "control_narration_only.wav")], check=True)
print(f"wrote {out / 'control_narration_only.wav'}")

# ---- CARD path: _compose_chapter_card's audio mix (video.py ~:2142-2168) -----------
# Duration comes from the real code: the run's own escalation card, clamped by
# video.py's own _chapter_card_duration (MIN 1.5 / MAX 2.5).
card_dur = _chapter_card_duration(probe(run / "card_004.mp4"))
# ponytail: _compose_chapter_card is an async whole-render, so its audio fragment cannot
# be imported the way build_sound_design_filter can. Keep the black-video input as index 0
# so the ambient/stinger indices and the fragment text stay character-identical to the
# source; the gains and the normalize=0 come from the real constants.
card_frag = (
    f"[1:a]volume={AMBIENT_VOLUME}[amb_v];"
    f"[2:a]volume={STINGER_VOLUME},apad=whole_dur={card_dur}[stg_v];"
    f"[amb_v][stg_v]amix=inputs=2:duration=first:normalize=0[aout]"
)
print(f"\ncard duration={card_dur:.3f}s (run card_004.mp4)\ncard filter={card_frag}\n")
paths = MOOD_ASSET_PATHS["escalation"]
new_pair = [str(paths["ambient"]), str(paths["stinger"])]
old_pair = substitute(new_pair)
for pair, dst in ((new_pair, out / "card_after.wav"), (old_pair, out / "card_before.wav")):
    subprocess.run(["ffmpeg", "-y", "-v", "error",
                    "-f", "lavfi", "-i", f"color=c=black:s=64x64:r=30:d={card_dur}",
                    "-stream_loop", "-1", "-i", pair[0],
                    "-i", pair[1],
                    "-filter_complex", card_frag, "-map", "[aout]",
                    "-t", f"{card_dur:.3f}", str(dst)], check=True)
    print(f"wrote {dst}")
PY
