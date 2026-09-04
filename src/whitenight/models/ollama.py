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

from whitenight.models.base import (
    ModelCapabilities,
    ModelChunk,
    ModelProviderError,
    ProviderMessage,
    ToolCall,
    ToolSpec,
)


class OllamaProvider:
    """Ollama 本地推理实现。"""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float = 600.0,
        max_output_tokens: int = 2048,
        keep_alive: str = "-1",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.keep_alive = keep_alive
        self.timeout = httpx.Timeout(timeout_s, connect=10.0)
        self._transport = transport

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tools=True, vision=self.supports_vision)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            trust_env=False,
            transport=self._transport,
        )

    @property
    def supports_vision(self) -> bool:
        """Qwen-VL (and other ``*-vl`` Ollama models) accept images."""
        return "vl" in self.model.lower() or "vision" in self.model.lower()

    def _keep_alive_value(self) -> str | int:
        """Ollama 的 keep_alive 接受时长字符串（如 "5m"）或数字秒；-1 必须是数字。"""
        try:
            return int(self.keep_alive)
        except ValueError:
            return self.keep_alive

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[ModelChunk]:
        def message_payload(message: ProviderMessage) -> dict[str, object]:
            payload: dict[str, object] = {"role": message.role, "content": message.content}
            if message.images:
                payload["images"] = message.images
            if message.tool_call_id:
                payload["tool_call_id"] = message.tool_call_id
            if message.name:
                payload["name"] = message.name
            if message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in message.tool_calls
                ]
            return payload

        payload = {
            "model": self.model,
            "messages": [message_payload(message) for message in messages],
            "stream": True,
            # 常驻模型：默认 keep_alive=5m 会让闲置后的首条消息等模型重新加载（实测 ~17s），
            # -1 保持常驻以消除冷启动延迟。
            "keep_alive": self._keep_alive_value(),
            # 文本模型可关闭思考；qwen3-vl 忽略该开关，thinking 单独流式返回。
            "think": False,
            # 上限必须存在：无 num_predict 时，退化的采样循环会一直生成下去，
            # 占住唯一推理槽，导致 QQ 长时间“无回复”（实测 n_decoded > 4000）。
            "options": {"num_predict": self.max_output_tokens},
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]
        async with (
            self._client() as client,
            client.stream("POST", "/api/chat", json=payload) as response,
        ):
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise ModelProviderError(
                    f"Ollama /api/chat 返回 {response.status_code}: {body[:500]}"
                )
            pending_tool_calls: list[ToolCall] = []
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
                for raw_call in message.get("tool_calls") or []:
                    function = raw_call.get("function") or {}
                    arguments = function.get("arguments") or {}
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = {}
                    pending_tool_calls.append(
                        ToolCall(
                            id=str(raw_call.get("id") or f"ollama-{len(pending_tool_calls)}"),
                            name=str(function.get("name") or ""),
                            arguments=arguments if isinstance(arguments, dict) else {},
                        )
                    )
                if delta or thinking:
                    yield ModelChunk(delta=delta, thinking=thinking)
                if data.get("done"):
                    yield ModelChunk(done=True, tool_calls=pending_tool_calls)
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

    async def list_models(self) -> list[str]:
        """Return model names advertised by Ollama's tags endpoint."""
        try:
            async with self._client() as client:
                response = await client.get("/api/tags")
        except httpx.HTTPError as exc:
            raise ModelProviderError(f"Ollama 模型列表请求失败：{exc}") from exc
        if response.status_code != 200:
            body = (await response.aread()).decode("utf-8", errors="replace")
            raise ModelProviderError(f"Ollama /api/tags 返回 {response.status_code}: {body[:500]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ModelProviderError("Ollama /api/tags 返回了无效 JSON") from exc
        raw_models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(raw_models, list):
            raise ModelProviderError("Ollama /api/tags 响应缺少 models 列表")
        names: list[str] = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if isinstance(name, str) and name.strip() and name not in names:
                names.append(name)
        return names
