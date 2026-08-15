#!/usr/bin/env bash
# WhiteNight 一键检查：后端 ruff + pytest，前端 lint + build。
# 任何一步失败立即非零退出；本脚本只读源码，不执行破坏性操作。
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

echo "==> uv sync --dev"
uv sync --dev

echo "==> ruff check"
uv run ruff check .

echo "==> ruff format --check"
uv run ruff format --check .

echo "==> pytest"
uv run pytest

if [ -d apps/web ]; then
  echo "==> web npm ci"
  (cd apps/web && npm ci)

  echo "==> web npm run check"
  (cd apps/web && npm run check)
fi

echo "ALL CHECKS PASSED"
