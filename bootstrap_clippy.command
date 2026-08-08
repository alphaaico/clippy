#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Clippy needs Python 3 and Node.js/npm installed on this Mac."
  echo "Install them, then run this file again."
  exit 1
fi

if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
  # A copied macOS venv often points at the sender's Python binary. It cannot
  # be reused on another Mac, so replace only this generated environment.
  echo "Creating a Python environment for this Mac…"
  rm -rf "$ROOT_DIR/.venv"
  python3 -m venv .venv
fi

echo "Installing Python packages…"
.venv/bin/python -m pip install --upgrade pip
# MediaPipe's macOS wheel includes a malformed test fixture.  It is never
# imported by Clippy, but older Apple Python versions fail while compiling it.
.venv/bin/python -m pip install --no-compile --prefer-binary -r backend/requirements.txt

echo "Installing JavaScript packages…"
npm ci

if ! .venv/bin/python -c "import fastapi, faster_whisper, groq" >/dev/null 2>&1; then
  echo "Python packages could not be verified. Please retry with an internet connection."
  exit 1
fi

echo "Setup complete. Double-click run_clippy.command to start Clippy."
