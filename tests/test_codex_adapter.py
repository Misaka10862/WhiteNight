"""Codex Adapter 测试：结果解析 + 真实 MCP 握手（可选集成）。"""

from __future__ import annotations

import asyncio
import os

import pytest

from whitenight.delegates.base import DelegateUnavailableError
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


def test_extract_codex_structured_result() -> None:
    text, thread_id = _extract_codex_result(
        {"structuredContent": {"content": "已完成", "threadId": "thread-456"}}
    )
    assert text == "已完成"
    assert thread_id == "thread-456"


def test_extract_codex_json_text_result() -> None:
    text, thread_id = _extract_codex_result(
        {
            "content": [
                {
                    "type": "text",
                    "text": '{"content":"已完成","threadId":"thread-789"}',
                }
            ]
        }
    )
    assert text == "已完成"
    assert thread_id == "thread-789"


def test_codex_tool_call_uses_task_timeout(monkeypatch) -> None:
    client = CodexMcpClient(timeout_s=321)
    captured: dict[str, object] = {}

    async def fake_request(method, params, timeout_s=None):
        captured.update({"method": method, "params": params, "timeout_s": timeout_s})
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    asyncio.run(client.call_tool("codex", {"prompt": "hello"}))

    assert captured["method"] == "tools/call"
    assert captured["timeout_s"] == 321


def test_codex_tool_call_surfaces_permanent_provider_error(monkeypatch) -> None:
    client = CodexMcpClient()

    async def fake_request(method, params, timeout_s=None):
        del method, params, timeout_s
        return {
            "isError": True,
            "content": [{"type": "text", "text": "Access blocked by Cloudflare: 403 Forbidden"}],
        }

    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(DelegateUnavailableError, match="Cloudflare"):
        asyncio.run(client.call_tool("codex", {"prompt": "hello"}))


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
