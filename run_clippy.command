#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo "Missing .env. Add the Groq API key configuration before running Clippy."
  exit 1
fi

if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import fastapi, faster_whisper, groq" >/dev/null 2>&1 || [ ! -x node_modules/.bin/vite ]; then
  echo "Preparing Clippy for this Mac…"
  "./bootstrap_clippy.command"
fi

echo "Starting Clippy at http://localhost:5173"
sleep 1
open "http://localhost:5173" 2>/dev/null || true
exec npm run dev:all
