#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$ROOT_DIR" || exit 1

echo "mdcn one-click startup"
echo "Project: $ROOT_DIR"
echo

"$ROOT_DIR/scripts/quickstart.sh"
exit_code=$?

echo
if [ "$exit_code" -eq 0 ]; then
  echo "mdcn has stopped."
else
  echo "mdcn failed to start. Exit code: $exit_code"
fi
echo
read -r -p "Press Enter to close..."
exit "$exit_code"
