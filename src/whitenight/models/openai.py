"""OpenAI-compatible Chat Completions provider."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable

import httpx

from whitenight.models.base import (
    ModelCapabilities,
    ModelChunk,
    ModelProviderError,
    ProviderMessage,
    ToolCall,
    ToolSpec,
)

_TOOL_NAME_MAX_LENGTH = 64


def _image_data_url(image: str, mime: str | None = None) -> str:
    """Normalize the provider-neutral base64 image value for Chat Completions.

    The core stores provider images as base64 without a data-URL prefix because
    Ollama requires that form.  OpenAI-compatible APIs require an ``image_url``
    part, and accept a data URL for local images.  PNG is the legacy/default
    MIME used by the existing image envelope; an already-prefixed data URL is
    retained so future producers can preserve a more specific MIME type.
    """
    if image.startswith("data:image/"):
        return image
    return f"data:{mime or 'image/png'};base64,{image}"


def _tool_name_mapping(
    tools: list[ToolSpec] | None, messages: list[ProviderMessage]
) -> tuple[dict[str, str], dict[str, str]]:
    """Map internal tool names to the restricted OpenAI function-name grammar."""
    names: list[str] = [tool.name for tool in tools or []]
    for message in messages:
        if message.name:
            names.append(message.name)
        names.extend(call.name for call in message.tool_calls)

    internal_to_wire: dict[str, str] = {}
    wire_to_internal: dict[str, str] = {}
    for internal_name in names:
        if internal_name in internal_to_wire:
            continue
        base = re.sub(r"[^A-Za-z0-9_-]", "_", internal_name)[:_TOOL_NAME_MAX_LENGTH]
        base = base or "tool"
        candidate = base
        suffix = 1
        while candidate in wire_to_internal and wire_to_internal[candidate] != internal_name:
            suffix_text = f"_{suffix}"
            candidate = f"{base[: _TOOL_NAME_MAX_LENGTH - len(suffix_text)]}{suffix_text}"
            suffix += 1
        internal_to_wire[internal_name] = candidate
        wire_to_internal[candidate] = internal_name
    return internal_to_wire, wire_to_internal


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

    @property
    def supports_vision(self) -> bool | None:
        # OpenAI-compatible endpoints have no portable capability metadata.
        # Recognize common multimodal model IDs, leave unknown IDs to the
        # explicit ``model_supports_vision`` setting, and keep text models on
        # the deterministic fallback path.
        model = self.model.lower()
        if any(
            marker in model
            for marker in (
                "vision",
                "-vl",
                "gpt-4o",
                "gpt-4.1",
                "gpt-4.5",
                "gemini",
                "claude-3",
            )
        ):
            return True
        return None

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tools=True, vision=self.supports_vision)

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
        internal_to_wire, wire_to_internal = _tool_name_mapping(tools, messages)
        wire_messages: list[dict[str, object]] = []
        for message in messages:
            if message.images:
                content: list[dict[str, object]] = []
                if message.content:
                    content.append({"type": "text", "text": message.content})
                for index, image in enumerate(message.images):
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": _image_data_url(
                                    image,
                                    message.image_mimes[index]
                                    if index < len(message.image_mimes)
                                    else None,
                                )
                            },
                        }
                    )
                item: dict[str, object] = {"role": message.role, "content": content}
            else:
                item = {"role": message.role, "content": message.content}
            if message.tool_call_id:
                item["tool_call_id"] = message.tool_call_id
            if message.name:
                item["name"] = internal_to_wire.get(message.name, message.name)
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": internal_to_wire.get(call.name, call.name),
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
                        "name": internal_to_wire[tool.name],
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
                raise ModelProviderError.http_failure(response.status_code)
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
                        name=wire_to_internal.get(state["name"], state["name"]),
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

    async def list_models(self) -> list[str]:
        """Return model IDs advertised by an OpenAI-compatible ``/models`` endpoint."""
        key = self._api_key()
        if not key:
            raise ModelProviderError("OpenAI-compatible API Key 未配置，请先写入 Keychain")
        headers = {"Authorization": f"Bearer {key}"}
        try:
            async with self._client() as client:
                response = await client.get("/models", headers=headers)
        except httpx.HTTPError as exc:
            raise ModelProviderError(f"OpenAI-compatible 模型列表请求失败：{exc}") from exc
        if response.status_code >= 400:
            # 不回显远端响应体：异常服务可能把 Authorization 中的 Key 原样反射回来。
            raise ModelProviderError(f"OpenAI-compatible /models 返回 {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ModelProviderError("OpenAI-compatible /models 返回了无效 JSON") from exc
        raw_models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(raw_models, list):
            raise ModelProviderError("OpenAI-compatible /models 响应缺少 data 列表")
        names: list[str] = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id.strip() and model_id not in names:
                names.append(model_id)
        return names
