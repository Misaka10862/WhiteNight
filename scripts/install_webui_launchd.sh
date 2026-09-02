#!/usr/bin/env bash
# WhiteNight WebUI launchd 服务安装器（默认 dry-run，不修改系统）。
#
# 用法：
#   ./scripts/install_webui_launchd.sh                 # 预览将生成的 plist
#   ./scripts/install_webui_launchd.sh --install       # 写入 ~/Library/LaunchAgents 并加载
#   ./scripts/install_webui_launchd.sh --status        # 查看服务状态
#
# 该服务只管理 apps/web 的 Vite 开发服务器；后端仍由
# com.whitenight.service 独立管理。
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT_DIR="$(pwd)"
WEB_DIR="$PROJECT_DIR/apps/web"
NPM_PATH="${NPM_PATH:-$(command -v npm || true)}"
NODE_DIR="$(dirname "${NPM_PATH:-/usr/bin}")"
LABEL="com.whitenight.web"
USER_HOME="${HOME:?HOME is not set}"
AGENTS_DIR="$USER_HOME/Library/LaunchAgents"
LOG_DIR="$USER_HOME/Library/Logs/WhiteNight"
PLIST_TEMPLATE="deploy/com.whitenight.web.plist.template"
PLIST_TARGET="$AGENTS_DIR/$LABEL.plist"

if [[ -z "${NPM_PATH:-}" ]]; then
  echo "npm was not found; install Node.js before starting the WebUI" >&2
  exit 1
fi

if [[ ! -d "$WEB_DIR" || ! -f "$WEB_DIR/package.json" ]]; then
  echo "WebUI directory is missing: $WEB_DIR" >&2
  exit 1
fi

generate() {
  mkdir -p "$AGENTS_DIR" "$LOG_DIR"
  sed \
    -e "s|{{NPM_PATH}}|$NPM_PATH|g" \
    -e "s|{{NODE_DIR}}|$NODE_DIR|g" \
    -e "s|{{WEB_DIR}}|$WEB_DIR|g" \
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
  --status)
    launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | sed -n '1,80p' || {
      echo "WebUI launchd service is not loaded: $LABEL" >&2
      exit 1
    }
    ;;
  *)
    echo "==> Preview only; run $0 --install after review"
    generate
    ;;
esac
