from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from whitenight.models.base import ModelProviderError, ProviderMessage
from whitenight.models.openai import OpenAIProvider


def test_openai_sse_contract() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        body = ('data: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: [DONE]\n\n').encode()
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    provider = OpenAIProvider(
        "https://api.test/v1",
        "gpt-test",
        "secret",
        max_output_tokens=99,
        transport=httpx.MockTransport(handler),
    )

    async def run() -> list[str]:
        return [
            chunk.delta
            async for chunk in provider.stream_chat([ProviderMessage(role="user", content="hi")])
        ]

    assert asyncio.run(run()) == ["你好", ""]
    assert captured["stream"] is True
    assert captured["max_tokens"] == 99


def test_openai_requires_key() -> None:
    provider = OpenAIProvider("https://api.test/v1", "gpt-test", None)

    async def run() -> None:
        async for _ in provider.stream_chat([]):
            pass

    with pytest.raises(ModelProviderError, match="Key"):
        asyncio.run(run())
