#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
CONFIG_FILE="$ROOT_DIR/config.toml"

cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Please install Python 3.11+ first."
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip >/dev/null
python -m pip install -e ".[dev]"

created_config=0
if [ ! -f "$CONFIG_FILE" ]; then
  cp "$ROOT_DIR/config.example.toml" "$CONFIG_FILE"
  created_config=1
fi

echo
echo "mdcn quickstart is ready."
echo "Config file: $CONFIG_FILE"
if [ "$created_config" -eq 1 ]; then
  echo "A new config.toml was created from the example file."
fi
echo "First-time setup:"
echo "  1. Fill in your source folder"
echo "  2. Fill in your target folder"
echo "  3. Click '保存并开始刮削' in the browser page"
echo "Launching local config UI..."
echo

python -m mdcn.app.cli config-ui --config "$CONFIG_FILE"
