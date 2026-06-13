#!/usr/bin/env bash
# Push a synthetic live broadcast into Volt (no OBS needed).
# RTMP publishing is now gated: you must pass a valid stream key.
#
# Usage:
#   ./stream.sh <username> --key <stream_key>            # test pattern + tone
#   ./stream.sh <username> --key <stream_key> -f clip.mp4 # loop a real file
#
# Get your key from the web UI → "Go Live", or use the seeded demo account:
#   ./stream.sh demo --key demokey
set -e

USER_NAME="${1:-demo}"; shift || true
KEY=""; FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --key) KEY="$2"; shift 2;;
    -f|--file) FILE="$2"; shift 2;;
    *) echo "unknown arg: $1"; exit 1;;
  esac
done
[ -z "$KEY" ] && { echo "error: --key <stream_key> is required (see the Go Live panel)"; exit 1; }

URL="rtmp://localhost:1935/${USER_NAME}?user=${USER_NAME}&pass=${KEY}"

if [ -n "$FILE" ]; then
  echo "Streaming $FILE as @${USER_NAME} (looping)…"
  exec ffmpeg -re -stream_loop -1 -i "$FILE" \
       -c:v libx264 -preset veryfast -tune zerolatency -g 60 -keyint_min 60 -sc_threshold 0 \
       -c:a aac -ar 44100 -b:a 128k -f flv "$URL"
else
  echo "Streaming test pattern + tone as @${USER_NAME}  (Ctrl-C to stop)…"
  exec ffmpeg -re \
    -f lavfi -i "testsrc2=size=1920x1080:rate=30" \
    -f lavfi -i "sine=frequency=440:sample_rate=44100" \
    -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p -g 60 -keyint_min 60 -sc_threshold 0 -b:v 5000k \
    -c:a aac -ar 44100 -b:a 128k \
    -f flv "$URL"
fi
