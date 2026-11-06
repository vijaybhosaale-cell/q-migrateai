#!/usr/bin/env bash
# Q-MigrateAI local demo for macOS / Linux: one command, SQLite, no Docker.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
"$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || { echo "Python 3.10+ is required."; exit 1; }
if [ ! -x .venv/bin/python ]; then
  echo "First start: creating .venv ..."
  "$PY" -m venv .venv
fi
if [ ! -f .venv/packages-installed-v4.txt ]; then
  echo "Installing packages once ..."
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  echo installed > .venv/packages-installed-v4.txt
fi
echo
echo "  Open http://localhost:8002   (demo password: ${DEMO_PASSWORD:-QuantumDemo!2026})"
echo "  Project data (view, correct, download): http://localhost:8002/project-data/"
echo "  The first start measures real public websites (needs internet) and trains the AI models. Ctrl+C stops."
echo
exec .venv/bin/python -m uvicorn qmigrate.server.app:app --host 127.0.0.1 --port 8002
