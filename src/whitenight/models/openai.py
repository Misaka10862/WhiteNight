"""OpenAI-compatible Chat Completions provider."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable

import httpx

from whitenight.models.base import (
    ModelChunk,
    ModelProviderError,
    ProviderMessage,
    ToolCall,
    ToolSpec,
)


class OpenAIProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout_s: float = 120.0,
        max_output_tokens: int = 2048,
        transport: httpx.AsyncBaseTransport | None = None,
        key_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self.base_url, self.model = base_url.rstrip("/"), model
        self.api_key, self.max_output_tokens = api_key, max_output_tokens
        self.timeout = httpx.Timeout(timeout_s, connect=10.0)
        self._transport, self._key_provider = transport, key_provider

    def _api_key(self) -> str | None:
        return self._key_provider() if self._key_provider else self.api_key

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout, trust_env=False, transport=self._transport
        )

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[ModelChunk]:
        key = self._api_key()
        if not key:
            raise ModelProviderError("OpenAI-compatible API Key 未配置，请先写入 Keychain")
        wire_messages: list[dict[str, object]] = []
        for message in messages:
            item: dict[str, object] = {"role": message.role, "content": message.content}
            if message.tool_call_id:
                item["tool_call_id"] = message.tool_call_id
            if message.name:
                item["name"] = message.name
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                    for call in message.tool_calls
                ]
            wire_messages.append(item)
        payload: dict[str, object] = {
            "model": self.model,
            "messages": wire_messages,
            "stream": True,
            "max_tokens": self.max_output_tokens,
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
            payload["parallel_tool_calls"] = True
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        async with (
            self._client() as client,
            client.stream("POST", "/chat/completions", headers=headers, json=payload) as response,
        ):
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise ModelProviderError(
                    f"OpenAI-compatible API 返回 {response.status_code}: {body[:500]}"
                )
            calls: dict[int, dict[str, str]] = {}
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    break
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                delta_payload = (data.get("choices") or [{}])[0].get("delta") or {}
                delta = delta_payload.get("content") or ""
                if delta:
                    yield ModelChunk(delta=delta)
                for raw_call in delta_payload.get("tool_calls") or []:
                    index = int(raw_call.get("index", 0))
                    state = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    state["id"] += str(raw_call.get("id") or "")
                    function = raw_call.get("function") or {}
                    state["name"] += str(function.get("name") or "")
                    state["arguments"] += str(function.get("arguments") or "")
            parsed_calls: list[ToolCall] = []
            for index, state in sorted(calls.items()):
                try:
                    arguments = json.loads(state["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                parsed_calls.append(
                    ToolCall(
                        id=state["id"] or f"openai-{index}",
                        name=state["name"],
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )
            yield ModelChunk(done=True, tool_calls=parsed_calls)

    async def health(self) -> dict[str, object]:
        return {
            "provider": "openai",
            "base_url": self.base_url,
            "model": self.model,
            "configured": bool(self._api_key()),
        }
