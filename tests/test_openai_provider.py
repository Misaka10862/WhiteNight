from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from whitenight.models.base import (
    ModelChunk,
    ModelProviderError,
    ProviderMessage,
    ToolCall,
    ToolSpec,
)
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


def test_openai_multimodal_message_uses_image_url_parts() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    provider = OpenAIProvider(
        "https://api.test/v1",
        "deepseek-v4-flash-vision-exp",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    async def run() -> None:
        async for _ in provider.stream_chat(
            [
                ProviderMessage(
                    role="user", content="看图", images=["QUJD"], image_mimes=["image/jpeg"]
                )
            ]
        ):
            pass

    asyncio.run(run())
    message = captured["messages"][0]
    assert message["content"] == [
        {"type": "text", "text": "看图"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,QUJD"},
        },
    ]


def test_openai_vision_capability_is_inferred_from_model_id() -> None:
    assert (
        OpenAIProvider(
            "https://api.test/v1", "deepseek-v4-flash-vision-exp", "secret"
        ).supports_vision
        is True
    )
    assert OpenAIProvider("https://api.test/v1", "gpt-3.5-turbo", "secret").supports_vision is None


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
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"file_","arguments":"{\\"names\\":["}}]}}]}\n\n'
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
    assert captured["tools"][0]["function"]["name"] == "file_find"
    assert captured["parallel_tool_calls"] is True


def test_openai_tool_names_are_mapped_in_follow_up_messages() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            content='data: {"choices":[{"delta":{"content":"完成"}}]}\n\ndata: [DONE]\n\n'.encode(),
        )

    provider = OpenAIProvider(
        "https://api.test/v1",
        "gpt-test",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    async def run() -> list[ModelChunk]:
        return [
            chunk
            async for chunk in provider.stream_chat(
                [
                    ProviderMessage(
                        role="assistant",
                        tool_calls=[
                            ToolCall(
                                id="call-1",
                                name="file.find",
                                arguments={"names": ["x"]},
                            )
                        ],
                    ),
                    ProviderMessage(
                        role="tool",
                        name="file.find",
                        tool_call_id="call-1",
                        content='{"ok":true}',
                    ),
                ],
                [ToolSpec(name="file.find", description="find", parameters={"type": "object"})],
            )
        ]

    asyncio.run(run())
    messages = captured["messages"]
    assert messages[0]["tool_calls"][0]["function"]["name"] == "file_find"
    assert messages[1]["name"] == "file_find"


def test_openai_list_models_contract() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={"data": [{"id": "gpt-4o-mini"}, {"id": "deepseek-chat"}, {"id": "gpt-4o-mini"}]},
        )

    provider = OpenAIProvider(
        "https://api.test/v1",
        "gpt-test",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    assert asyncio.run(provider.list_models()) == ["gpt-4o-mini", "deepseek-chat"]
    assert captured == {"path": "/v1/models", "authorization": "Bearer secret"}
