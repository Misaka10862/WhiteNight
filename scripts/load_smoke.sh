#!/usr/bin/env bash
# 负载冒烟（非破坏性）：创建/写入/读取/删除临时会话，验证服务在压力下稳定。
# 不调用真实模型；只打会话与状态 API。
set -euo pipefail
cd "$(dirname "$0")/.."
BASE="${WHITENIGHT_URL:-http://127.0.0.1:8765}"
ROUNDS="${ROUNDS:-30}"

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin"
curl -fsS --max-time 2 "$BASE/healthz" >/dev/null || { echo "服务未启动"; exit 1; }

uv run python - <<PY
import httpx, time
base = "$BASE"
with httpx.Client(base_url=base, timeout=10, trust_env=False) as client:
    start = time.perf_counter()
    created = []
    for _ in range($ROUNDS):
        session = client.post('/api/v1/sessions', json={'title':'smoke'}).json()
        created.append(session['id'])
        client.get('/api/v1/sessions').raise_for_status()
        client.get('/api/v1/status').raise_for_status()
    for session_id in created:
        client.delete(f'/api/v1/sessions/{session_id}')
    elapsed = time.perf_counter() - start
    print(f"SMOKE OK: { $ROUNDS } rounds in {elapsed:.2f}s")
PY
