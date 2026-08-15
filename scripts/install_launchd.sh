#!/usr/bin/env bash
# WhiteNight launchd 服务安装器（默认 dry-run，不修改系统）。
#
# 用法：
#   ./scripts/install_launchd.sh                 # 预览将生成的 plist
#   ./scripts/install_launchd.sh --install       # 写入 ~/Library/LaunchAgents 并加载
#   ./scripts/install_launchd.sh --uninstall     # 卸载并移除
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT_DIR="$(pwd)"
UV_PATH="${UV_PATH:-$(command -v uv)}"
UV_DIR="$(dirname "$UV_PATH")"
LABEL="com.whitenight.service"
AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/WhiteNight"
PLIST_TEMPLATE="deploy/com.whitenight.service.plist.template"
PLIST_TARGET="$AGENTS_DIR/$LABEL.plist"

if [[ -z "${UV_PATH:-}" ]]; then
  echo "找不到 uv；请先安装：brew install uv 或使用官方安装器" >&2
  exit 1
fi

generate() {
  mkdir -p "$AGENTS_DIR" "$LOG_DIR"
  sed -e "s|{{UV_PATH}}|$UV_PATH|g" \
      -e "s|{{UV_DIR}}|$UV_DIR|g" \
      -e "s|{{PROJECT_DIR}}|$PROJECT_DIR|g" \
      -e "s|{{LOG_DIR}}|$LOG_DIR|g" \
      "$PLIST_TEMPLATE"
}

case "${1:-}" in
  --install)
    generate > "$PLIST_TARGET"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST_TARGET"
    launchctl enable "gui/$(id -u)/$LABEL"
    echo "已安装并加载：$PLIST_TARGET"
    echo "状态：launchctl print gui/$(id -u)/$LABEL | head"
    ;;
  --uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST_TARGET"
    echo "已卸载并移除：$PLIST_TARGET"
    ;;
  *)
    echo "==> 预览（未写入系统）。确认后运行：$0 --install"
    generate
    ;;
esac
