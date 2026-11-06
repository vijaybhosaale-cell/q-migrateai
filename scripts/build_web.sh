#!/usr/bin/env bash
# Rebuild the web front end into web/dist. Only needed after editing web/src.
# Needs: TypeScript (tsc) and the Tailwind CSS standalone CLI (set TAILWIND=/path/to/tailwindcss).
set -euo pipefail
cd "$(dirname "$0")/.."
TAILWIND="${TAILWIND:-tailwindcss}"
rm -rf web/dist/js
tsc -p web/tsconfig.json
"$TAILWIND" -c web/tailwind.config.js -i web/src/styles.css -o web/dist/css/app.css --minify
cp web/static/index.html web/static/favicon.svg web/dist/
echo "Built web/dist"
