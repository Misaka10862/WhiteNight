"""路由→委派→ChatService 集成：故障不破坏主会话。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import Engine

from whitenight.agent.service import ChatService, DummyProvider
from whitenight.channels.types import ChatEvent, ChatRequest
from whitenight.config import Settings
from whitenight.delegates.base import DelegateCapabilities, DelegateUnavailableError
from whitenight.delegates.events import DelegateEvent, DelegationRequest
from whitenight.delegates.manager import DelegateManager, TaskStore
from whitenight.routing.engine import RoutingEngine
from whitenight.routing.rules import RuleRouter
from whitenight.storage.sessions import SessionStore


class FakeCodex:
    name = "codex"
    capabilities = DelegateCapabilities(read_only=True, action_policy=True)

    def __init__(self) -> None:
        self.last_request: DelegationRequest | None = None

    async def health(self) -> dict[str, object]:
        return {"ok": True}

    async def submit(self, request: DelegationRequest) -> AsyncGenerator[DelegateEvent, None]:
        self.last_request = request
        yield DelegateEvent(task_id=request.task_id, executor="codex", type="started", label="开始")
        yield DelegateEvent(
            task_id=request.task_id,
            executor="codex",
            type="result",
            label="完成",
            detail="已修复测试",
            payload={"thread_id": "t1"},
        )

    async def abort(self, task_id: str, thread_id: str | None = None) -> bool:
        del task_id, thread_id
        return True


class UnavailableCodex(FakeCodex):
    async def submit(self, request: DelegationRequest) -> AsyncGenerator[DelegateEvent, None]:
        del request
        raise DelegateUnavailableError("codex 未登录")
        yield  # pragma: no cover


def _collect(generator) -> list[ChatEvent]:
    async def run() -> list[ChatEvent]:
        return [event async for event in generator]

    return asyncio.run(run())


def _service(engine: Engine, settings: Settings, provider) -> tuple[ChatService, SessionStore]:
    store = SessionStore(engine)
    manager = DelegateManager(TaskStore(engine), {"codex": provider})
    service = ChatService(
        store,
        DummyProvider("好的，主人"),
        settings,
        router=RoutingEngine(rule_router=RuleRouter(), allow_llm_fallback=False),
        delegate_manager=manager,
    )
    return service, store


def test_codex_delegation_streams_and_persists(engine: Engine, settings: Settings) -> None:
    provider = FakeCodex()
    service, store = _service(engine, settings, provider)
    session = store.create_session()
    events = _collect(
        service.stream_reply(ChatRequest(session_id=session.id, text="/codex 帮我修一下这个 bug"))
    )
    assert events[0].type == "start"
    assert any(event.type == "task" for event in events)
    assert events[-1].type == "done"
    assert "已委派 codex" in events[-1].text
    assert "已修复测试" in events[-1].text
    messages = store.list_messages(session.id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert TaskStore(engine).list()[0].status == "succeeded"
    assert provider.last_request is not None
    assert provider.last_request.cwd == str(Path.cwd().resolve())


def test_delegation_includes_recent_verified_qq_attachment(
    engine: Engine, settings: Settings
) -> None:
    provider = FakeCodex()
    service, store = _service(engine, settings, provider)
    session = store.create_session()
    attachment = settings.data_dir / "qq_files" / "received-report.docx"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"docx")
    store.record_attachment_message(session.id, "report.docx", channel="onebot", path=attachment)

    _collect(
        service.stream_reply(ChatRequest(session_id=session.id, text="/codex 处理我刚才发的文件"))
    )

    assert provider.last_request is not None
    assert f"最近收到的 QQ 附件绝对路径：{attachment.resolve()}" in provider.last_request.prompt


def test_delegate_failure_does_not_break_session(engine: Engine, settings: Settings) -> None:
    service, store = _service(engine, settings, UnavailableCodex())
    session = store.create_session()
    events = _collect(
        service.stream_reply(ChatRequest(session_id=session.id, text="/codex 帮我重构这段代码"))
    )
    assert events[-1].type == "done"
    assert "没有完成" in events[-1].text

    # 失败后，同会话的普通聊天仍走本地模型
    events = _collect(service.stream_reply(ChatRequest(session_id=session.id, text="你好")))
    chunks = [event.delta for event in events if event.type == "chunk"]
    assert "".join(chunks) == "好的，主人"
    assert events[-1].type == "done"


def test_code_request_without_codex_command_stays_local(engine: Engine, settings: Settings) -> None:
    provider = FakeCodex()
    service, store = _service(engine, settings, provider)
    session = store.create_session()
    events = _collect(
        service.stream_reply(ChatRequest(session_id=session.id, text="帮我重构这段代码"))
    )
    assert not any(event.type == "task" for event in events)
    assert provider.last_request is None


def test_codex_command_without_task_is_rejected(engine: Engine, settings: Settings) -> None:
    provider = FakeCodex()
    service, store = _service(engine, settings, provider)
    session = store.create_session()
    events = _collect(service.stream_reply(ChatRequest(session_id=session.id, text=" /codex ")))
    assert events[-1].type == "done"
    assert "具体任务" in events[-1].text
    assert provider.last_request is None
