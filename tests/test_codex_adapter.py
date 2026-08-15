"""Codex Adapter 测试：结果解析 + 真实 MCP 握手（可选集成）。"""

from __future__ import annotations

import asyncio
import os

import pytest

from whitenight.delegates.codex import CodexMcpClient, _extract_codex_result


def test_extract_codex_result() -> None:
    text, thread_id = _extract_codex_result(
        {
            "content": [
                {"type": "text", "text": "完成"},
                {"type": "text", "text": "第二段"},
            ],
            "threadId": "thread-123",
        }
    )
    assert text == "完成\n第二段"
    assert thread_id == "thread-123"


@pytest.mark.skipif(
    os.environ.get("WHITENIGHT_TEST_CODEX_MCP") != "1",
    reason="需要 Codex CLI；设置 WHITENIGHT_TEST_CODEX_MCP=1 启用",
)
def test_codex_mcp_handshake_live() -> None:
    async def run() -> None:
        client = CodexMcpClient()
        try:
            await client.start()
            tools = await client.list_tools()
            names = {tool.get("name") for tool in tools}
            assert {"codex", "codex-reply"} <= names
        finally:
            await client.close()

    asyncio.run(run())
