#!/usr/bin/env bash
# WhiteNight 健康检查：等待本机服务就绪，超时非零退出。
set -euo pipefail
URL="${WHITENIGHT_URL:-http://127.0.0.1:8765/healthz}"
ATTEMPTS="${ATTEMPTS:-10}"
INTERVAL="${INTERVAL:-1}"

for _ in $(seq 1 "$ATTEMPTS"); do
  if curl -fsS --max-time 2 "$URL" >/dev/null 2>&1; then
    echo "healthy: $URL"
    exit 0
  fi
  sleep "$INTERVAL"
done
echo "unhealthy: $URL" >&2
exit 1
