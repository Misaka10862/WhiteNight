"""委派任务管理器测试：状态、重试、不可用快速失败、中止。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from sqlalchemy import Engine

from whitenight.delegates.base import DelegateError, DelegateUnavailableError
from whitenight.delegates.events import DelegateEvent, DelegationRequest
from whitenight.delegates.manager import DelegateManager, TaskStore


class FakeCodex:
    name = "codex"

    async def health(self) -> dict[str, object]:
        return {"ok": True}

    async def submit(self, request: DelegationRequest) -> AsyncGenerator[DelegateEvent, None]:
        yield DelegateEvent(
            task_id=request.task_id, executor="codex", type="started", step="x", label="开始"
        )
        yield DelegateEvent(
            task_id=request.task_id,
            executor="codex",
            type="result",
            step="x",
            label="完成",
            detail="代码结果",
            payload={"thread_id": "thread-1"},
        )

    async def abort(self, task_id: str, thread_id: str | None = None) -> bool:
        del task_id, thread_id
        return True


class FlakyCodex(FakeCodex):
    def __init__(self) -> None:
        self.calls = 0

    async def submit(self, request: DelegationRequest) -> AsyncGenerator[DelegateEvent, None]:
        self.calls += 1
        if self.calls == 1:
            raise DelegateError("临时失败")
        async for event in FakeCodex.submit(self, request):
            yield event


class UnavailableCodex(FakeCodex):
    async def submit(self, request: DelegationRequest) -> AsyncGenerator[DelegateEvent, None]:
        del request
        raise DelegateUnavailableError("codex 未登录")
        yield  # pragma: no cover


def _collect(events: list[DelegateEvent]) -> dict[str, object]:
    types = [event.type for event in events]
    result = next((event for event in events if event.type == "result"), None)
    error = next((event for event in events if event.type == "error"), None)
    return {"types": types, "result": result, "error": error}


def test_success_persists_thread_id(engine: Engine) -> None:
    store = TaskStore(engine)
    manager = DelegateManager(store, {"codex": FakeCodex()})

    async def run() -> dict[str, object]:
        events = [
            event
            async for event in manager.run(
                executor="codex", category="code", risk="high", prompt="修 bug", session_id="s1"
            )
        ]
        return _collect(events)

    result = asyncio.run(run())
    assert result["types"] == ["started", "started", "result"]
    assert result["result"].payload["thread_id"] == "thread-1"
    task = store.list(session_id="s1")[0]
    assert task.status == "succeeded"
    assert task.thread_id == "thread-1"


def test_retry_once_then_success(engine: Engine) -> None:
    store = TaskStore(engine)
    provider = FlakyCodex()
    manager = DelegateManager(store, {"codex": provider}, max_retries=1, retry_delay_s=0)

    async def run() -> dict[str, object]:
        events = [
            event
            async for event in manager.run(
                executor="codex", category="code", risk="high", prompt="重试"
            )
        ]
        return _collect(events)

    result = asyncio.run(run())
    assert provider.calls == 2
    assert result["result"] is not None
    assert store.list()[0].attempts == 2


def test_unavailable_fails_fast_without_raise(engine: Engine) -> None:
    store = TaskStore(engine)
    manager = DelegateManager(store, {"codex": UnavailableCodex()})

    async def run() -> dict[str, object]:
        events = [
            event
            async for event in manager.run(
                executor="codex", category="code", risk="high", prompt="任务"
            )
        ]
        return _collect(events)

    result = asyncio.run(run())
    assert result["error"] is not None
    assert "未登录" in result["error"].detail
    assert store.list()[0].status == "failed"


def test_abort_task(engine: Engine) -> None:
    store = TaskStore(engine)
    record = store.create(executor="codex", category="code", risk="high", prompt="长任务")
    manager = DelegateManager(store, {"codex": FakeCodex()})
    event = asyncio.run(manager.abort(record.id))
    assert event.type == "aborted"
    assert store.get(record.id).status == "aborted"
