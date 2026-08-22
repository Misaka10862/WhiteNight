#!/usr/bin/env bash
# Check that relative Markdown links from README and PROGRESS resolve.
set -euo pipefail
cd "$(dirname "$0")/.."
FAIL=0
for file in README.md docs/PROGRESS.md; do
  while IFS= read -r target; do
    [[ -e "$target" ]] || { echo "Missing link: $file -> $target"; FAIL=1; }
  done < <(grep -oE '\([^)]+\.md\)' "$file" | tr -d '()' | sed 's/#.*//')
done
if [[ "$FAIL" == "0" ]]; then echo "DOC LINKS OK"; else exit 1; fi
