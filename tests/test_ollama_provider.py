"""Ollama Provider 契约测试（本地集成）。

默认跳过；在本机 Ollama 可用时运行：
    WHITENIGHT_TEST_OLLAMA=1 uv run pytest tests/test_ollama_provider.py -q
"""

from __future__ import annotations

import asyncio
import os

import pytest

from whitenight.models.base import ProviderMessage
from whitenight.models.ollama import OllamaProvider

pytestmark = pytest.mark.skipif(
    os.environ.get("WHITENIGHT_TEST_OLLAMA") != "1",
    reason="需要本机 Ollama；设置 WHITENIGHT_TEST_OLLAMA=1 启用",
)

PROVIDER = OllamaProvider(base_url="http://127.0.0.1:11434", model="qwen3:8b")


def test_health_reports_model() -> None:
    health = asyncio.run(PROVIDER.health())
    assert health["provider"] == "ollama"
    assert health["model_available"] is True


def test_stream_chat_yields_content() -> None:
    async def run() -> str:
        parts: list[str] = []
        async for chunk in PROVIDER.stream_chat(
            [ProviderMessage(role="user", content="只回复两个字：好的")]
        ):
            if chunk.delta:
                parts.append(chunk.delta)
            if chunk.done:
                break
        return "".join(parts)

    text = asyncio.run(run())
    assert "好的" in text
