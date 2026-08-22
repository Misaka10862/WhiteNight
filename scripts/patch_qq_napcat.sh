#!/usr/bin/env bash
# 修复 NapCat 安装器“显示安装成功但仍未安装”：补做 QQ 入口注入。
#
# 原因：安装器已把 NapCat 文件放入 QQ 沙箱容器，但修改
# /Applications/QQ.app/Contents/Resources/app/package.json 需要管理员权限。
#
# 用法（在终端运行，会请求开机密码）：
#   ./scripts/patch_qq_napcat.sh
# 只预览不修改：
#   ./scripts/patch_qq_napcat.sh --dry-run
set -euo pipefail
cd "$(dirname "$0")/.."

APP="/Applications/QQ.app/Contents/Resources/app"
PKG="$APP/package.json"
BAK="$PKG.bak"
LOADER="$HOME/Library/Containers/com.tencent.qq/Data/Documents/napcat/loadNapCat.js"

if [[ ! -f "$LOADER" ]]; then
  echo "NapCat loader not found: $LOADER" >&2
  echo "Complete the download/install step in the NapCat installer first." >&2
  exit 1
fi

REL_MAIN="$(uv run python - "$APP" "$LOADER" <<'PY'
import os, sys
app, loader = sys.argv[1], sys.argv[2]
print(os.path.relpath(loader, app))
PY
)"
echo "Current QQ package.json:"
grep '"main"' "$PKG"
echo "Required entry point: $REL_MAIN"

if [[ "${1:-}" == "--dry-run" ]]; then
  echo "DRY RUN: no system files changed. Run ./scripts/patch_qq_napcat.sh to apply."
  exit 0
fi

if [[ -f "$BAK" ]]; then
  echo "Backup already exists; skipping: $BAK"
else
  if ! sudo cp "$PKG" "$BAK"; then
    echo "Backup failed. If macOS reports Operation not permitted:"
    echo "open System Settings > Privacy & Security > App Management, allow this terminal,"
    echo "then rerun this script."
    exit 1
  fi
  echo "Backup created: $BAK"
fi

TMP_JSON="$(mktemp -t napcat_package.json.XXXXXX)"
uv run python - "$PKG" "$REL_MAIN" "$TMP_JSON" <<'PY'
import json, sys
pkg, main, out = sys.argv[1], sys.argv[2], sys.argv[3]
with open(pkg, encoding="utf-8") as handle:
    data = json.load(handle)
data["main"] = main
with open(out, "w", encoding="utf-8") as handle:
    json.dump(data, handle, ensure_ascii=False, indent=2)
PY
sudo cp "$TMP_JSON" "$PKG"
rm -f "$TMP_JSON"

echo "Updated. Current entry point:"
grep '"main"' "$PKG"
echo "Done. Quit QQ fully, then launch it through the NapCat entry in the installer."
