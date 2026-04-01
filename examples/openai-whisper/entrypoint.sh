#!/bin/sh
set -e
MODEL="${WHISPER_MODEL:-tiny}"

if [ "$#" -gt 0 ]; then
  exec whisper "$@"
fi

if [ -f /data/audio.wav ]; then
  mkdir -p /data/out
  exec whisper /data/audio.wav --model "$MODEL" --output_dir /data/out
fi

echo "openai-whisper: /data/audio.wav fehlt (auf dem Host: ./audio/audio.wav)." >&2
echo "" >&2
echo "  mkdir -p audio out && cp deine-datei.wav audio/audio.wav && docker compose up --build" >&2
echo "  docker compose run --rm openai-whisper /data/me.mp3 --model tiny --output_dir /data/out" >&2
exit 1
