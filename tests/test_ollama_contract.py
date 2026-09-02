"""Ollama Provider 契约（不依赖本机 Ollama）。

重点锁死 num_predict 上限：缺少该参数时，退化的采样循环会无限生成，
占住唯一推理槽，表现为 QQ 长时间无回复（2026-08-15 生产事故）。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from whitenight.models.base import ProviderMessage, ToolSpec
from whitenight.models.ollama import OllamaProvider


def test_stream_chat_payload_caps_output_tokens() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        body = "\n".join(
            [
                json.dumps({"message": {"content": "好的", "thinking": ""}}),
                json.dumps({"message": {"content": ""}, "done": True}),
            ]
        ).encode()
        return httpx.Response(200, headers={"content-type": "application/x-ndjson"}, content=body)

    provider = OllamaProvider(
        base_url="http://contract.test",
        model="qwen3:8b",
        max_output_tokens=123,
        keep_alive="-1",
        transport=httpx.MockTransport(handler),
    )

    async def run() -> str:
        parts: list[str] = []
        async for chunk in provider.stream_chat(
            [ProviderMessage(role="user", content="只回复两个字：好的")]
        ):
            if chunk.delta:
                parts.append(chunk.delta)
            if chunk.done:
                break
        return "".join(parts)

    assert asyncio.run(run()) == "好的"
    assert captured["model"] == "qwen3:8b"
    assert captured["stream"] is True
    assert captured["keep_alive"] == -1
    assert captured["think"] is False
    assert captured["options"] == {"num_predict": 123}


def test_ollama_tool_call_contract() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        body = json.dumps(
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {"name": "file.find", "arguments": {"names": ["x"]}},
                        }
                    ],
                },
                "done": True,
            }
        ).encode()
        return httpx.Response(200, content=body)

    provider = OllamaProvider(
        "http://contract.test", "qwen3:8b", transport=httpx.MockTransport(handler)
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
    assert chunks[-1].tool_calls[0].arguments == {"names": ["x"]}
    assert captured["tools"]


def test_ollama_list_models_contract() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "qwen3:8b"},
                    {"name": "llama3.2:latest"},
                    {"name": "qwen3:8b"},
                    {"name": ""},
                ]
            },
        )

    provider = OllamaProvider(
        "http://contract.test", "qwen3:8b", transport=httpx.MockTransport(handler)
    )

    assert asyncio.run(provider.list_models()) == ["qwen3:8b", "llama3.2:latest"]
    assert captured["path"] == "/api/tags"
