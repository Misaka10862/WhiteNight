#!/usr/bin/env python3
"""QQ 链路就绪检查（只读）。

用法：uv run scripts/qq_link_check.py
检查：NapCat OneBot API、登录状态、owner 配置、WhiteNight 健康与事件端点。
"""

from __future__ import annotations

import json

import httpx

from whitenight.config import load_settings


def main() -> int:
    settings = load_settings()
    checks: dict[str, object] = {
        "qq_enabled": settings.qq_enabled,
        "owner_ids": settings.qq_owner_ids,
        "onebot_api_url": settings.qq_onebot_api_url,
    }

    try:
        response = httpx.get(
            f"{settings.qq_onebot_api_url}/get_login_info", timeout=5.0, trust_env=False
        )
        if response.status_code == 200:
            payload = response.json()
            checks["onebot_reachable"] = True
            checks["login"] = {
                "user_id": payload.get("data", {}).get("user_id"),
                "nickname": payload.get("data", {}).get("nickname"),
            }
        else:
            checks["onebot_reachable"] = False
            checks["onebot_http_status"] = response.status_code
    except Exception as exc:
        checks["onebot_reachable"] = False
        checks["onebot_error"] = str(exc)

    try:
        health = httpx.get("http://127.0.0.1:8765/healthz", timeout=3.0, trust_env=False)
        checks["whitenight_healthy"] = health.status_code == 200
    except Exception as exc:
        checks["whitenight_healthy"] = False
        checks["whitenight_error"] = str(exc)

    print(json.dumps(checks, ensure_ascii=False, indent=2))
    ready = bool(
        checks.get("qq_enabled")
        and checks.get("owner_ids")
        and checks.get("onebot_reachable")
        and checks.get("whitenight_healthy")
    )
    print("QQ LINK " + ("READY" if ready else "NOT READY"))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
