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


def _stream_provider(body: str) -> OpenAIProvider:
    return OpenAIProvider(
        "https://api.test/v1",
        "contract-test",
        "synthetic",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body.encode())),
    )


@pytest.mark.parametrize(
    ("body", "category"),
    [
        ('data: {"choices":[{"delta":{"content":"partial"}}]}\n\n', "incomplete_stream"),
        ("", "incomplete_stream"),
        (
            'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\ndata: [DONE]\n\n',
            "output_truncated",
        ),
        (
            'data: {"choices":[{"delta":{},"finish_reason":"content_filter"}]}\n\ndata: [DONE]\n\n',
            "content_filtered",
        ),
        (
            'data: {"error":{"message":"PRIVATE_UPSTREAM_BODY"}}\n\ndata: [DONE]\n\n',
            "provider_error",
        ),
        ("data: {PRIVATE_INVALID_JSON\n\ndata: [DONE]\n\n", "protocol_error"),
        ("data: []\n\ndata: [DONE]\n\n", "protocol_error"),
    ],
)
def test_failed_stream_never_emits_success(body: str, category: str) -> None:
    chunks: list[ModelChunk] = []

    async def run() -> None:
        async for chunk in _stream_provider(body).stream_chat([]):
            chunks.append(chunk)

    with pytest.raises(ModelProviderError) as failure:
        asyncio.run(run())
    assert failure.value.category == category
    assert "PRIVATE_" not in str(failure.value)
    assert not any(chunk.done or chunk.tool_calls for chunk in chunks)


@pytest.mark.parametrize("finish_reason", ["stop", "tool_calls"])
@pytest.mark.parametrize("with_usage", [False, True])
def test_explicit_successful_finish_is_sufficient_without_done_sentinel(
    finish_reason: str, with_usage: bool
) -> None:
    body = (
        "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": finish_reason}]}) + "\n\n"
    )
    if with_usage:
        body += 'data: {"choices":[],"usage":{"total_tokens":12}}\n\n'

    async def run() -> list[ModelChunk]:
        return [chunk async for chunk in _stream_provider(body).stream_chat([])]

    assert asyncio.run(run())[-1].done


@pytest.mark.parametrize("arguments", ['{"path":', "[]", "null", '"PRIVATE_ARGUMENT"', ""])
def test_invalid_tool_arguments_are_not_replaced_with_empty_object(arguments: str) -> None:
    body = (
        "data: "
        + json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "function": {"name": "file_find", "arguments": arguments},
                                }
                            ]
                        }
                    }
                ]
            }
        )
        + "\n\ndata: [DONE]\n\n"
    )

    async def run() -> None:
        async for _ in _stream_provider(body).stream_chat([]):
            pass

    with pytest.raises(ModelProviderError) as failure:
        asyncio.run(run())
    assert failure.value.category == "invalid_tool_arguments"
    assert "PRIVATE_" not in str(failure.value)


def test_one_invalid_call_blocks_publication_of_the_whole_batch() -> None:
    calls = [
        {
            "index": 0,
            "id": "valid",
            "function": {"name": "file_find", "arguments": '{"names":["x"]}'},
        },
        {"index": 1, "id": "invalid", "function": {"name": "file_move", "arguments": '{"source":'}},
    ]
    body = (
        "data: "
        + json.dumps({"choices": [{"delta": {"tool_calls": calls}}]})
        + "\n\ndata: [DONE]\n\n"
    )
    published: list[ToolCall] = []

    async def run() -> None:
        async for chunk in _stream_provider(body).stream_chat([]):
            published.extend(chunk.tool_calls)

    with pytest.raises(ModelProviderError):
        asyncio.run(run())
    assert published == []
