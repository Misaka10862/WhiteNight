"""End-to-end local model tool loop and approval continuation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from whitenight.agent.service import ChatService
from whitenight.channels.types import ChannelContext, ChatRequest
from whitenight.models.base import ModelChunk, ProviderMessage, ToolCall, ToolSpec
from whitenight.policy.approvals import ApprovalService
from whitenight.policy.audit import AuditService
from whitenight.policy.engine import PolicyEngine
from whitenight.storage.sessions import SessionStore
from whitenight.tools import FileFindTool, FileReadTool, FileWriteTool, ToolExecutor, ToolRegistry
from whitenight.tools.pending import PendingToolStore


class FindProvider:
    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        assert tools and any(tool.name == "file.find" for tool in tools)
        tool_message = next((message for message in messages if message.role == "tool"), None)
        if tool_message is None:
            yield ModelChunk(
                done=True,
                tool_calls=[
                    ToolCall(
                        id="find-1",
                        name="file.find",
                        arguments={"names": ["adult.jsonl"]},
                    )
                ],
            )
        else:
            assert "adult.jsonl" in tool_message.content
            yield ModelChunk(delta="找到了 adult.jsonl。")
            yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class WriteProvider:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        if not any(message.role == "tool" for message in messages):
            yield ModelChunk(
                done=True,
                tool_calls=[
                    ToolCall(
                        id="write-1",
                        name="file.write",
                        arguments={"path": str(self.path), "content": "new"},
                    )
                ],
            )
        else:
            yield ModelChunk(delta="文件已经修改。")
            yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class ParallelReadProvider:
    def __init__(self, first: Path, second: Path) -> None:
        self.first = first
        self.second = second

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        tool_messages = [message for message in messages if message.role == "tool"]
        if not tool_messages:
            yield ModelChunk(
                done=True,
                tool_calls=[
                    ToolCall(id="read-1", name="file.read", arguments={"path": str(self.first)}),
                    ToolCall(id="read-2", name="file.read", arguments={"path": str(self.second)}),
                ],
            )
        else:
            assert [message.tool_call_id for message in tool_messages] == ["read-1", "read-2"]
            assert "first" in tool_messages[0].content
            assert "second" in tool_messages[1].content
            yield ModelChunk(delta="两个文件都读取完成。")
            yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"ok": True}


def _service(engine, settings, provider, tools):
    store = SessionStore(engine)
    approvals = ApprovalService(engine)
    policy = PolicyEngine()
    registry = ToolRegistry(tools)
    executor = ToolExecutor(registry, policy, approvals, AuditService(engine))
    return (
        ChatService(
            store,
            provider,
            settings,
            tool_registry=registry,
            tool_executor=executor,
            approvals=approvals,
            pending_tools=PendingToolStore(engine),
            policy=policy,
        ),
        store,
        approvals,
    )


def test_chat_executes_find_and_returns_grounded_answer(engine, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "adult.jsonl").write_text("{}\n", encoding="utf-8")
    service, store, _ = _service(engine, settings, FindProvider(), [FileFindTool()])
    session = store.create_session()

    async def run():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(session_id=session.id, text="找一下 adult.jsonl")
            )
        ]

    events = asyncio.run(run())
    assert any(event.type == "tool" for event in events)
    assert events[-1].text == "找到了 adult.jsonl。"


def test_write_approval_resumes_original_call(engine, settings, tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("old", encoding="utf-8")
    service, store, approvals = _service(
        engine, settings, WriteProvider(path), [FileReadTool(), FileWriteTool()]
    )
    session = store.create_session()

    async def request():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(session_id=session.id, text="修改这个文件")
            )
        ]

    events = asyncio.run(request())
    assert events[-2].type == "approval"
    assert path.read_text(encoding="utf-8") == "old"
    code = approvals.list_pending()[0].code
    resumed = asyncio.run(service.resume_approval(code, ChannelContext(channel="web")))
    assert resumed[-1].type == "done"
    assert path.read_text(encoding="utf-8") == "new"


def test_chat_accepts_parallel_tool_calls_and_returns_each_result(engine, settings, tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    service, store, _ = _service(
        engine, settings, ParallelReadProvider(first, second), [FileReadTool()]
    )
    session = store.create_session()

    async def run():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(session_id=session.id, text="读取两个文件")
            )
        ]

    events = asyncio.run(run())
    tool_events = [event for event in events if event.type == "tool"]
    assert [event.extra["tool_name"] for event in tool_events] == ["file.read", "file.read"]
    assert all(event.extra["status"] == "ok" for event in tool_events)
    assert events[-1].text == "两个文件都读取完成。"
