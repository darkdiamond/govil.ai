#!/bin/bash
# contact sheet of stills (time-ordered): scripts/sheet.sh <scene> [cols]  -> out/stills/<scene>-sheet.png
cd "$(dirname "$0")/.." ; s=$1; cols=${2:-6}
for f in $PWD/out/stills/$s-[0-9]*.png; do echo "$(echo $f | sed 's/.*-\([0-9.]*\)\.png/\1/') $f"; done | sort -n | awk '{print "file \x27"$2"\x27"}' > /tmp/$s.list
n=$(wc -l < /tmp/$s.list); rows=$(( (n + cols - 1) / cols ))
ffmpeg -y -loglevel error -f concat -safe 0 -i /tmp/$s.list -vf "scale=320:-1,tile=${cols}x${rows}" -frames:v 1 out/stills/$s-sheet.png
