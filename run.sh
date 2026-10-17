#!/usr/bin/env bash
# One-command launcher: creates a virtualenv, installs dependencies, starts the web UI.
# Usage: ./run.sh            (then open http://localhost:8080)
#        PORT=9000 ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8080}"
PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  echo "Python 3.10+ is required (found: $("$PYTHON" --version 2>&1)). Set PYTHON=/path/to/python3.11 and retry." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating virtual environment in .venv ..."
  "$PYTHON" -m venv .venv
fi

if [ ! -f .venv/.deps-installed ] || [ requirements.txt -nt .venv/.deps-installed ]; then
  echo "Installing dependencies (first run takes a few minutes) ..."
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  touch .venv/.deps-installed
fi

if [ ! -f logistics_agent/.env ]; then
  echo "Missing logistics_agent/.env. Copy logistics_agent/.env.example and add a Gemini API key." >&2
  exit 1
fi

echo
echo "  Logistics agent running at  http://localhost:${PORT}"
echo "  Press Ctrl+C to stop."
echo
exec .venv/bin/python -m uvicorn web.server:app --host 127.0.0.1 --port "$PORT"
