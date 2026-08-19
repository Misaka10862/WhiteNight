"""OpenAI-compatible Chat Completions provider."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable

import httpx

from whitenight.models.base import ModelChunk, ModelProviderError, ProviderMessage


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

    async def stream_chat(self, messages: list[ProviderMessage]) -> AsyncIterator[ModelChunk]:
        key = self._api_key()
        if not key:
            raise ModelProviderError("OpenAI-compatible API Key 未配置，请先写入 Keychain")
        payload = {
            "model": self.model,
            "messages": [m.model_dump(exclude_defaults=True) for m in messages],
            "stream": True,
            "max_tokens": self.max_output_tokens,
        }
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
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    yield ModelChunk(done=True)
                    return
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                delta = ((data.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                if delta:
                    yield ModelChunk(delta=delta)
            yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {
            "provider": "openai",
            "base_url": self.base_url,
            "model": self.model,
            "configured": bool(self._api_key()),
        }
