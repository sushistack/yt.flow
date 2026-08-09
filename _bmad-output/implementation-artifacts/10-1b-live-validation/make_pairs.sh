#!/bin/bash
# Story 10.1b — adapted from 10-1-live-validation/make_pairs.sh.
# Extracts tier-3 frames at the SAME shot ids and timestamps as 10.1's off/ and
# tier1/ extractions, then hstacks two pair sets:
#   pairs/${shot}_pair.jpg      tier1 | tier3   (the primary judgment)
#   pairs_off/${shot}_pair.jpg  off   | tier3   (against 10.1's third reference point)
#
# Re-runnable: writes tier3/, pairs/ and pairs_off/ only. NEVER touches off/ or
# tier1/, both of which are irreplaceable — video.py:1885 unlinks every
# shots/scene_NNN_*.mp4 per scene before re-rendering it.
set -euo pipefail
cd "$(dirname "$0")"
W=../../../workspace/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d

# Parameterized (10.1 hardcoded `on/` and its label) so the same script can build
# either pair set. $1 = frame dir to extract into, $2 = its burn-in label.
DIR=${1:-tier3}
LABEL=${2:-'TIER 3  IC-Light relight'}

# `-nostdin`: without it ffmpeg eats the loop's stdin and every other iteration is skipped.
# `drawtext=font=sans` (fontconfig name), NOT `fontfile=$FONT` — under zsh the `:text=`
# that follows is parsed as the `:t` (basename) modifier and silently mangles the filter.
SLATE="scene_001_S00102:1.5 scene_001_S00101:1.5 scene_002_S00203:2.4 scene_002_S00202:3.1 scene_001_S00104:1.2 scene_004_S00403:1.2"

mkdir -p "$DIR" pairs pairs_off

pair() {  # <left png> <left label> <right png> <right label> <out jpg>
  ffmpeg -nostdin -v error -i "$1" -i "$3" -filter_complex \
    "[0:v]drawtext=font=sans:text='$2':x=24:y=24:fontsize=56:fontcolor=white:box=1:boxcolor=black@0.8:boxborderw=16[a];\
     [1:v]drawtext=font=sans:text='$4':x=24:y=24:fontsize=56:fontcolor=white:box=1:boxcolor=black@0.8:boxborderw=16[b];\
     [a][b]hstack=inputs=2" \
    -q:v 3 -update 1 -y "$5"
}

for st in $SLATE; do
  s=${st%:*}; t=${st#*:}
  ffmpeg -nostdin -v error -ss "$t" -i "$W/shots/$s.mp4" -frames:v 1 -update 1 -y "$DIR/${s}_t${t}.png"
  pair "tier1/${s}_t${t}.png" 'TIER 1  tint+shadow+wrap' "$DIR/${s}_t${t}.png" "$LABEL" "pairs/${s}_pair.jpg"
  pair "off/${s}_t${t}.png"   'OFF'                      "$DIR/${s}_t${t}.png" "$LABEL" "pairs_off/${s}_pair.jpg"
  echo "pair: pairs/${s}_pair.jpg  pairs_off/${s}_pair.jpg"
done

# Composites are committed as JPEG q3 because they are read, not re-processed;
# off/, tier1/ and tier3/ stay lossless PNG so any future measurement uses real pixels.
