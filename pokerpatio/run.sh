#!/usr/bin/env bash
# Poker Patio Bot Control — start the control room.
# Uses the project venv when present (it carries playwright for the live site).
set -e
cd "$(dirname "$0")"
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python

if [ ! -f data/preflop_equity.json ]; then
  echo "building preflop equity table (one-off, ~30s)…"
  "$PY" tools/build_preflop.py 1200
fi

# Chromium refuses to start when TMPDIR is a very long path
export TMPDIR="${TMPDIR_OVERRIDE:-/tmp}"

exec "$PY" -m uvicorn server.app:app --host 127.0.0.1 --port "${PORT:-8777}" --log-level warning
