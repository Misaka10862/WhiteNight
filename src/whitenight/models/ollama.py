"""Ollama Provider。

阶段 1 实测契约（勿改回错误用法）：
- 图片必须挂在 user message 的 ``images`` 字段（顶层会被 qwen3-vl 忽略）；
- qwen3-vl 当前忽略 ``think:false``，thinking 与 content 分开流式返回；
- 本机探测必须 trust_env=False，否则被系统代理劫持返回 502。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from whitenight.models.base import ModelChunk, ModelProviderError, ProviderMessage


class OllamaProvider:
    """Ollama 本地推理实现。"""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float = 600.0,
        max_output_tokens: int = 2048,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.timeout = httpx.Timeout(timeout_s, connect=10.0)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            trust_env=False,
            transport=self._transport,
        )

    async def stream_chat(self, messages: list[ProviderMessage]) -> AsyncIterator[ModelChunk]:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                    **({"images": message.images} if message.images else {}),
                }
                for message in messages
            ],
            "stream": True,
            # 文本模型可关闭思考；qwen3-vl 忽略该开关，thinking 单独流式返回。
            "think": False,
            # 上限必须存在：无 num_predict 时，退化的采样循环会一直生成下去，
            # 占住唯一推理槽，导致 QQ 长时间“无回复”（实测 n_decoded > 4000）。
            "options": {"num_predict": self.max_output_tokens},
        }
        async with (
            self._client() as client,
            client.stream("POST", "/api/chat", json=payload) as response,
        ):
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise ModelProviderError(
                    f"Ollama /api/chat 返回 {response.status_code}: {body[:500]}"
                )
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = data.get("message", {})
                delta = message.get("content") or ""
                thinking = message.get("thinking") or ""
                if delta or thinking:
                    yield ModelChunk(delta=delta, thinking=thinking)
                if data.get("done"):
                    yield ModelChunk(done=True)
                    break

    async def health(self) -> dict[str, object]:
        async with self._client() as client:
            version_response = await client.get("/api/version")
            version_response.raise_for_status()
            version = version_response.json().get("version", "unknown")

            tags_response = await client.get("/api/tags")
            tags_response.raise_for_status()
            models = [item.get("name") for item in tags_response.json().get("models", [])]
        return {
            "provider": "ollama",
            "base_url": self.base_url,
            "version": version,
            "model": self.model,
            "model_available": self.model in models,
            "models": models,
        }
