"""Hermes Gateway Adapter。

阶段 1 已确认 Gateway 可启动并暴露 OpenAPI；任务级端点语义与认证仍在
契约验证中（需要用户先 `hermes model` 登录 Provider）。本适配器：
- 只通过 HTTP/JSON 与 Gateway 通信，不解析终端文本；
- 未登录时快速失败为 DelegateUnavailableError，主会话不受影响；
- 真正的 submit 契约待用户登录后用契约测试锁定。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from whitenight.delegates.base import DelegateCapabilities, DelegateError, DelegateUnavailableError
from whitenight.delegates.events import DelegateEvent, DelegationRequest


class HermesGatewayAdapter:
    name = "hermes"
    capabilities = DelegateCapabilities()

    def __init__(self, base_url: str = "http://127.0.0.1:9119", timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_s, connect=5.0)

    def _client(self) -> httpx.AsyncClient:
        # Hermes Gateway 只在本机回环地址，绕开系统代理。
        return httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, trust_env=False)

    async def health(self) -> dict[str, object]:
        async with self._client() as client:
            try:
                response = await client.get("/api/status")
                if response.status_code != 200:
                    return {
                        "provider": "hermes-gateway",
                        "available": False,
                        "http_status": response.status_code,
                    }
                payload = response.json()
                return {
                    "provider": "hermes-gateway",
                    "available": True,
                    "version": payload.get("version"),
                    "gateway_running": payload.get("gateway_running"),
                    "auth_required": payload.get("auth_required"),
                }
            except Exception as exc:
                return {"provider": "hermes-gateway", "available": False, "error": str(exc)}

    async def _ensure_authenticated(self) -> None:
        async with self._client() as client:
            response = await client.get("/api/auth/me")
            if response.status_code in {401, 403}:
                raise DelegateUnavailableError(
                    "Hermes Gateway 未登录模型 Provider：请运行 `hermes model` / "
                    "`hermes auth` 完成登录后重试"
                )
            if response.status_code >= 500:
                raise DelegateError(f"Hermes Gateway 异常：HTTP {response.status_code}")

    async def submit(self, request: DelegationRequest) -> AsyncIterator[DelegateEvent]:
        # 阶段 5 先锁定健康/认证契约；任务端点语义在用户登录后的契约测试中
        # 再固化，避免猜测协议导致副作用。
        await self._ensure_authenticated()
        yield DelegateEvent(
            task_id=request.task_id,
            executor="hermes",
            type="started",
            step="gateway",
            label="Hermes Gateway 已连接",
            detail="认证通过；任务端点契约待锁定",
        )
        raise DelegateError(
            "Hermes Gateway 任务提交契约待验证：认证已通过，但 submit 端点"
            "尚未在真实 Provider 上完成契约测试"
        )

    async def abort(self, task_id: str, thread_id: str | None = None) -> bool:
        del task_id, thread_id
        return False
