#!/usr/bin/env bash
# 文档链接检查：README 与 PROGRESS 中引用的相对文件必须存在。
set -euo pipefail
cd "$(dirname "$0")/.."
FAIL=0
for file in README.md docs/PROGRESS.md; do
  while IFS= read -r target; do
    [[ -e "$target" ]] || { echo "缺失链接：$file -> $target"; FAIL=1; }
  done < <(grep -oE '\([^)]+\.md\)' "$file" | tr -d '()' | sed 's/#.*//')
done
if [[ "$FAIL" == "0" ]]; then echo "DOC LINKS OK"; else exit 1; fi
