#!/usr/bin/env bash
# WhiteNight local checks; dependency installation is an explicit setup step.
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

if [ ! -x .venv/bin/python ]; then
  echo "Missing Python environment. Run: uv sync --locked --dev --extra sqlcipher" >&2
  exit 1
fi
if ! .venv/bin/python -c 'import ruff, mypy, pytest, whitenight' >/dev/null 2>&1; then
  echo "Missing Python check dependencies. Run: uv sync --locked --dev --extra sqlcipher" >&2
  exit 1
fi

echo "==> Run Ruff checks"
.venv/bin/python -m ruff check .

echo "==> Check Ruff formatting"
.venv/bin/python -m ruff format --check .

echo "==> Run strict Python type checks"
.venv/bin/python -m mypy src/whitenight

echo "==> Scan tracked files for credentials"
.venv/bin/python scripts/check_tracked_secrets.py

echo "==> Run Python tests"
.venv/bin/python -m pytest

if [ -d apps/web ]; then
  if ! command -v npm >/dev/null 2>&1 || [ ! -x apps/web/node_modules/.bin/vite ]; then
    echo "Missing web dependencies. Install Node/npm, then run: cd apps/web && npm install" >&2
    exit 1
  fi

  echo "==> Run web checks"
  (cd apps/web && npm run check)
fi

echo "==> Audit technical English"
.venv/bin/python scripts/check_technical_english.py

echo "ALL CHECKS PASSED"
