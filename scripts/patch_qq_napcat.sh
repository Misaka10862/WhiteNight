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
  echo "未找到 NapCat 加载器：$LOADER" >&2
  echo "请先在 NapCat 安装器中完成下载/安装步骤。" >&2
  exit 1
fi

REL_MAIN="$(uv run python - "$APP" "$LOADER" <<'PY'
import os, sys
app, loader = sys.argv[1], sys.argv[2]
print(os.path.relpath(loader, app))
PY
)"
echo "当前 QQ package.json："
grep '"main"' "$PKG"
echo "需要改为：$REL_MAIN"

if [[ "${1:-}" == "--dry-run" ]]; then
  echo "DRY RUN：未修改系统文件。运行 ./scripts/patch_qq_napcat.sh 实际执行。"
  exit 0
fi

if [[ -f "$BAK" ]]; then
  echo "备份已存在，跳过备份：$BAK"
else
  if ! sudo cp "$PKG" "$BAK"; then
    echo "备份失败。如果提示 Operation not permitted："
    echo "请打开「系统设置 → 隐私与安全性 → App 管理」，添加并允许当前终端应用，"
    echo "然后重新运行本脚本。"
    exit 1
  fi
  echo "已备份：$BAK"
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

echo "已写入。当前入口："
grep '"main"' "$PKG"
echo "完成。请完全退出 QQ，然后在 NapCat 安装器选择 NapCat 入口启动（或安装器里点启动 NapCat）。"
