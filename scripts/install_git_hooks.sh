#!/usr/bin/env bash
# Configure this clone to use the versioned Git hooks.
set -euo pipefail
cd "$(dirname "$0")/.."

chmod +x .githooks/commit-msg
git config core.hooksPath .githooks
echo "Installed versioned Git hooks from .githooks"
