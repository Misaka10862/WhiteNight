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
  echo "uv was not found; install it with Homebrew or the official installer" >&2
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
    echo "Installed and loaded: $PLIST_TARGET"
    echo "Status: launchctl print gui/$(id -u)/$LABEL | head"
    ;;
  --uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST_TARGET"
    echo "Unloaded and removed: $PLIST_TARGET"
    ;;
  *)
    echo "==> Preview only; run $0 --install after review"
    generate
    ;;
esac
