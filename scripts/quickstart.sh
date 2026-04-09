#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${HOME}/.mdcn"
VENV_DIR="${MDCN_VENV_DIR:-$STATE_DIR/.venv}"
CONFIG_FILE="$ROOT_DIR/config.toml"
STAMP_FILE="$VENV_DIR/.mdcn_bootstrap_stamp"

cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Please install Python 3.11+ first."
  exit 1
fi

echo "Preparing mdcn..."
mkdir -p "$(dirname "$VENV_DIR")"
echo "Python environment: $VENV_DIR"

create_venv() {
  echo "Creating Python virtual environment..."
  python3 -m venv "$VENV_DIR"
}

rotate_broken_venv() {
  broken_dir="${VENV_DIR}.broken.$(date +%Y%m%d%H%M%S)"
  mv "$VENV_DIR" "$broken_dir"
  rm -rf "$broken_dir" >/dev/null 2>&1 &
}

if [ ! -d "$VENV_DIR" ]; then
  create_venv
elif [ ! -x "$VENV_DIR/bin/python" ] || [ ! -f "$VENV_DIR/pyvenv.cfg" ] || [ ! -x "$VENV_DIR/bin/pip" ]; then
  echo "Repairing broken Python virtual environment..."
  rotate_broken_venv
  create_venv
fi

source "$VENV_DIR/bin/activate"

BOOTSTRAP_HASH="$(
  python3 - <<'PY'
from pathlib import Path
import hashlib

pyproject = Path("pyproject.toml")
print(hashlib.sha256(pyproject.read_bytes()).hexdigest())
PY
)"

needs_install=1
runtime_ready=0
if python -c "import mdcn, httpx, parsel" >/dev/null 2>&1; then
  runtime_ready=1
fi

if [ -f "$STAMP_FILE" ]; then
  current_stamp="$(cat "$STAMP_FILE")"
  if [ "$current_stamp" = "$BOOTSTRAP_HASH" ] && [ "$runtime_ready" -eq 1 ]; then
    needs_install=0
  fi
elif [ "$runtime_ready" -eq 1 ]; then
  printf "%s" "$BOOTSTRAP_HASH" > "$STAMP_FILE"
  needs_install=0
fi

if [ "$needs_install" -eq 1 ]; then
  echo "Installing or updating dependencies..."
  echo "This can take 1-3 minutes on first launch."
  python -m pip install --upgrade pip
  python -m pip install -e ".[dev]"
  printf "%s" "$BOOTSTRAP_HASH" > "$STAMP_FILE"
else
  echo "Python environment is already ready."
fi

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
echo "Launching local config UI at http://127.0.0.1:8765 ..."
echo "If the browser does not open automatically, copy this address into your browser."
echo

python -m mdcn.app.cli config-ui --config "$CONFIG_FILE"
