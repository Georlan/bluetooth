#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Virtualenv not found at $PYTHON_BIN" >&2
  echo "Create it with: python3 -m venv .venv" >&2
  exit 1
fi

exec "$PYTHON_BIN" -m bluetooth_hud.main
