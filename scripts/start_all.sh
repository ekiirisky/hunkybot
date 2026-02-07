#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

cleanup() {
  if [[ -n "${PY_PID:-}" ]]; then kill "$PY_PID" 2>/dev/null || true; fi
  if [[ -n "${WA_PID:-}" ]]; then kill "$WA_PID" 2>/dev/null || true; fi
}

trap cleanup EXIT INT TERM

python3 app.py &
PY_PID=$!

node wa-engine/index.js &
WA_PID=$!

wait "$PY_PID" "$WA_PID"
