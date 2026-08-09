#!/usr/bin/env bash
# Story 10.7 identification package: each escalation cue ALONE, at its real mix gain,
# so a listener can say which one is "the siren" instead of guessing from a mix.
#
#   bash _bmad-output/implementation-artifacts/10-7-live-validation/make_identify.sh
#
# This script REGENERATES THE WHOLE identify/ DIRECTORY deterministically: every .wav
# in it is deleted and rewritten from the five recipes below. It is the generator of
# that directory, not a patcher of it — there is no round-1 file left in there that
# only exists on disk. (It used to `rm -f` one clip by name while rewriting the rest,
# which destroyed the round-1 baseline it claimed to reproduce.)
#
# Writes into identify/ :
#   A_bgm.wav                  bgm/escalation.mp3        at BGM_VOLUME=0.25
#   B_ambient_new.wav          ambient/escalation.mp3    at AMBIENT_VOLUME=0.15  (round-1 swap)
#   C_stinger_new.wav          sfx/escalation_stinger.mp3 at STINGER_VOLUME=0.5  (round-2 swap)
#   Z_old_siren_removed.wav    the ambient that round 1 removed, same 0.15
#   Z2_old_klaxon_removed.wav  the stinger that round 2 removed, same 0.5
# Slot C always means "the stinger that currently ships"; Z/Z2 are what was removed.
#
# MONITORING BOOST — a caveat that must travel with any verdict taken from these clips.
# Every clip gets a flat +12 dB boost, because at the real gains these cues sit 15-25 dB
# under narration and are inaudible alone. The boost is common to all five, so their
# relative loudness is still the real mix balance. BUT at 0.5 gain +12 dB the two stinger
# clips (C and Z2) overshoot full scale by ~2.8 dB and HARD-CLIP — both report
# max_volume 0.0 dB below, and the script flags them. Clipping adds harmonic distortion,
# which is exactly the "does this read as an alarm?" attribute under judgement, so a
# verdict on C vs Z2 is a verdict on two equally-clipped clips, not on the shipped audio.
# The boost is kept anyway: dropping it makes the A/B inaudible, and both stingers
# overshoot within 0.2 dB of each other, so they distort alike. Anywhere the
# identification result is quoted, quote this caveat with it.
#
# Beds are cued 5 s into the file (SEEK below), not at t=0, so the listener judges
# steady-state material rather than the loop's in-fade. Beds run 8 s, the one-shot
# stingers 4 s (hit + tail).
set -euo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/identify"
mkdir -p "$OUT"
rm -f "$OUT"/*.wav
BOOST=12   # dB, monitoring only — see the caveat above
SEEK=5     # seconds into the bed, so the clip is steady-state material

cue() {  # cue <src> <mix_gain> <seek_s> <seconds> <dst>
  ffmpeg -y -v error -ss "$3" -i "$1" -af "volume=$2,volume=${BOOST}dB,apad" -t "$4" \
         -ar 44100 -ac 2 "$OUT/$5"
  levels="$(ffmpeg -hide_banner -i "$OUT/$5" -af volumedetect -f null - 2>&1 \
            | grep -E 'mean_volume|max_volume' | sed 's/.*] //' | tr '\n' ' ')"
  case "$levels" in *"max_volume: 0.0 dB"*) levels="$levels  << CLIPPED by the +${BOOST} dB boost";; esac
  printf '%-28s %s\n' "$5" "$levels"
}

cue data/audio/bgm/escalation.mp3            0.25 "$SEEK" 8 A_bgm.wav
cue data/audio/ambient/escalation.mp3        0.15 "$SEEK" 8 B_ambient_new.wav
cue data/audio/sfx/escalation_stinger.mp3    0.5  0       4 C_stinger_new.wav
cue "$HERE/old_escalation_siren.mp3"         0.15 "$SEEK" 8 Z_old_siren_removed.wav
cue "$HERE/old_escalation_klaxon.mp3"        0.5  0       4 Z2_old_klaxon_removed.wav
