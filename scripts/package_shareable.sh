#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STAGE_DIR="$ROOT_DIR/dist/Clippy"
ARCHIVE="$ROOT_DIR/dist/Clippy-macOS.zip"

if [ ! -f "$ROOT_DIR/.env" ]; then
  echo "Missing .env — package cancelled so no configuration is omitted."
  exit 1
fi

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/data/uploads" "$STAGE_DIR/data/outputs"

rsync -a \
  --exclude '.DS_Store' \
  --exclude '.git/' \
  --exclude 'dist/' \
  --exclude 'data/uploads/' \
  --exclude 'data/outputs/' \
  --exclude '__pycache__/' \
  "$ROOT_DIR/" "$STAGE_DIR/"

chmod +x "$STAGE_DIR/run_clippy.command" "$STAGE_DIR/bootstrap_clippy.command" "$STAGE_DIR/scripts/dev.sh" "$STAGE_DIR/scripts/package_shareable.sh"
rm -f "$ARCHIVE"
ditto -c -k --sequesterRsrc --keepParent "$STAGE_DIR" "$ARCHIVE"

echo "Created $ARCHIVE"
echo "Includes .env, .venv and node_modules; excludes uploaded/generated media."
