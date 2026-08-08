#!/bin/sh
set -eu

if [ ! -x .venv/bin/python ]; then
  echo "Backend environment is missing. Run: python3 -m venv .venv && .venv/bin/python -m pip install -r backend/requirements.txt"
  exit 1
fi

cleanup() {
  kill "$API_PID" "$WEB_PID" 2>/dev/null || true
  wait "$API_PID" "$WEB_PID" 2>/dev/null || true
}

mkdir -p /private/tmp/clippy-mpl
MPLCONFIGDIR=/private/tmp/clippy-mpl .venv/bin/python -m uvicorn backend.main:app --reload --port 8000 &
API_PID=$!
npm run dev -- --host 127.0.0.1 &
WEB_PID=$!
trap cleanup INT TERM EXIT

echo "\nClippy is running at http://localhost:5173"
wait "$API_PID" "$WEB_PID"
