from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from whitenight.models.base import ModelProviderError, ProviderMessage, ToolSpec
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


def test_openai_streamed_tool_call_is_assembled() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        body = (
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"file.","arguments":"{\\"names\\":["}}]}}]}\n\n'
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"find","arguments":"\\"x\\"]}"}}]}}]}\n\n'
            b"data: [DONE]\n\n"
        )
        return httpx.Response(200, content=body)

    provider = OpenAIProvider(
        "https://api.test/v1", "gpt-test", "secret", transport=httpx.MockTransport(handler)
    )

    async def run():
        return [
            chunk
            async for chunk in provider.stream_chat(
                [ProviderMessage(role="user", content="find")],
                [ToolSpec(name="file.find", description="find", parameters={"type": "object"})],
            )
        ]

    chunks = asyncio.run(run())
    assert chunks[-1].tool_calls[0].name == "file.find"
    assert chunks[-1].tool_calls[0].arguments == {"names": ["x"]}
    assert captured["parallel_tool_calls"] is True
