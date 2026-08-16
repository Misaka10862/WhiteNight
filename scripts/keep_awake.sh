#!/bin/bash
# WhiteNight 保活脚本：防止 macOS 睡眠导致 QQ 服务空窗。
#
# 用法：
#   scripts/keep_awake.sh start    # 接电源时启动 caffeinate，防止系统睡眠
#   scripts/keep_awake.sh start --force  # 电池供电也启动（会持续耗电）
#   scripts/keep_awake.sh stop     # 停止保活
#   scripts/keep_awake.sh status   # 查看状态
#
# 保活会阻止系统睡眠，请在使用后 stop；外出用电池时不建议长期保活。

set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIDFILE="$ROOT/data/logs/caffeinate.pid"
LOG="$ROOT/data/logs/caffeinate.log"
COMMAND="${1:-status}"

is_running() {
  [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

start_keepawake() {
  if is_running; then
    echo "保活已在运行（pid $(cat "$PIDFILE")）"
    return 0
  fi
  if [ "${2:-}" != "--force" ]; then
    if ! pmset -g batt 2>/dev/null | grep -q 'AC Power'; then
      echo "当前是电池供电；保活会持续耗电。接上电源后重试，或用 start --force 强制启动。" >&2
      exit 1
    fi
  fi
  mkdir -p "$ROOT/data/logs"
  nohup caffeinate -i -m -s >>"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  echo "保活已启动（pid $(cat "$PIDFILE")）：防止系统睡眠。"
}

stop_keepawake() {
  if is_running; then
    kill "$(cat "$PIDFILE")" 2>/dev/null
    rm -f "$PIDFILE"
    echo "保活已停止。"
  else
    echo "保活没有在运行。"
  fi
}

status_keepawake() {
  if is_running; then
    echo "保活运行中（pid $(cat "$PIDFILE")）；日志：$LOG"
  else
    echo "保活未运行；系统按正常策略休眠，睡眠期间 QQ 无法即时回复。"
  fi
}

case "$COMMAND" in
  start) start_keepawake "$@" ;;
  stop) stop_keepawake ;;
  status) status_keepawake ;;
  *)
    echo "用法：$0 {start|start --force|stop|status}" >&2
    exit 2
    ;;
esac
