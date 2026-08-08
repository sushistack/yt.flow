#!/bin/bash
# Story 10.1 — extract on-state frames at the SAME shot ids and timestamps as the
# off-state extraction, then hstack each off/on into a self-describing pair.
# Re-runnable: writes on/ and pairs/ only. Never touches off/, which is irreplaceable.
set -euo pipefail
cd "$(dirname "$0")"
W=../../../workspace/8a9a288b-800f-4c73-88a2-25ae6b5a4d7d

# `-nostdin`: without it ffmpeg eats the loop's stdin and every other iteration is skipped.
# `drawtext=font=sans` (fontconfig name), NOT `fontfile=$FONT` — under zsh the `:text=`
# that follows is parsed as the `:t` (basename) modifier and silently mangles the filter.
SLATE="scene_001_S00102:1.5 scene_001_S00101:1.5 scene_002_S00203:2.4 scene_002_S00202:3.1 scene_001_S00104:1.2 scene_004_S00403:1.2"

for st in $SLATE; do
  s=${st%:*}; t=${st#*:}
  ffmpeg -nostdin -v error -ss "$t" -i "$W/shots/$s.mp4" -frames:v 1 -update 1 -y "on/${s}_t${t}.png"
  ffmpeg -nostdin -v error -i "off/${s}_t${t}.png" -i "on/${s}_t${t}.png" -filter_complex \
    "[0:v]drawtext=font=sans:text='OFF':x=24:y=24:fontsize=56:fontcolor=white:box=1:boxcolor=black@0.8:boxborderw=16[a];\
     [1:v]drawtext=font=sans:text='ON  depth placement':x=24:y=24:fontsize=56:fontcolor=white:box=1:boxcolor=black@0.8:boxborderw=16[b];\
     [a][b]hstack=inputs=2" \
    -q:v 3 -update 1 -y "pairs/${s}_pair.jpg"
  echo "pair: pairs/${s}_pair.jpg"
done

# Composites are committed as JPEG q3 (~2.4 MB for all ten) because they are read, not
# re-processed; off/ and on/ stay lossless PNG so any future measurement uses real pixels.
