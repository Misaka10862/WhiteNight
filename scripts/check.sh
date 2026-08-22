#!/usr/bin/env bash
# WhiteNight local checks: backend lint/tests, technical English, and web lint/build.
# The script exits on the first failure and does not modify source files.
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

echo "==> Sync Python dependencies"
uv sync --dev --extra sqlcipher

echo "==> Run Ruff checks"
uv run ruff check .

echo "==> Check Ruff formatting"
uv run ruff format --check .

echo "==> Scan tracked files for credentials"
uv run scripts/check_tracked_secrets.py

echo "==> Run Python tests"
uv run pytest

if [ -d apps/web ]; then
  echo "==> Install web dependencies"
  (cd apps/web && npm ci)

  echo "==> Run web checks"
  (cd apps/web && npm run check)
fi

echo "==> Audit technical English"
uv run scripts/check_technical_english.py

echo "ALL CHECKS PASSED"
