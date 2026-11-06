#!/usr/bin/env bash
# Thesis evaluation: quantum deadlines and explanations vs the rule baseline.
# Run start_demo.sh once first, so the real websites have been measured.
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Run start_demo.sh first."; exit 1; }
.venv/bin/python -m qmigrate.research.evaluate "$@"
