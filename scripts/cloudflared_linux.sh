#!/bin/bash
# Cloudflare quick tunnel — 8765 portini ochadi, havolani web_url.txt ga yozadi, tirik tutadi
set -u
DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$DIR/cloudflared.log"
URLFILE="$DIR/web_url.txt"
while true; do
  : > "$LOG"
  cloudflared tunnel --url http://localhost:8765 --no-autoupdate >>"$LOG" 2>&1 &
  CFPID=$!
  # trycloudflare havolasini kutamiz
  for i in $(seq 1 40); do
    sleep 2
    URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1)
    if [ -n "$URL" ]; then
      printf '%s' "$URL" > "$URLFILE"
      break
    fi
  done
  # cloudflared tirik ekan kutamiz; o'lsa tsikl qaytadan (yangi havola)
  wait $CFPID
  sleep 3
done
