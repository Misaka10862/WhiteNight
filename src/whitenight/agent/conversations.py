"""Conversation identity, serialization, cancellation and durable terminal events."""

import asyncio
import hashlib
import json
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from datetime import UTC, datetime

from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from whitenight.channels.types import ChannelContext, ChatEvent, ChatRequest
from whitenight.storage.application_models import ConversationRun


class ConversationCoordinator:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self._session_users: dict[str, int] = {}
        self._started: dict[str, asyncio.Event] = {}
        self._cancel_requested: set[str] = set()

    @staticmethod
    async def _drain(task: asyncio.Task[None]) -> None:
        """Do not forward repeated consumer cancellation into an active writer."""
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        if not task.cancelled():
            task.result()

    def recover(self) -> None:
        with Session(self.engine) as orm:
            orm.execute(
                update(ConversationRun)
                .where(ConversationRun.status.in_(["running", "cancelling"]))
                .values(status="awaiting_review", updated_at=datetime.now(UTC))
            )
            orm.commit()

    async def cancel(self, request_id: str) -> bool:
        task = self.tasks.get(request_id)
        if task is None or task.done():
            return False
        with Session(self.engine) as orm:
            row = orm.get(ConversationRun, request_id)
            if row is None or row.status not in {"running", "cancelling"}:
                return False
            orm.execute(
                update(ConversationRun)
                .where(
                    ConversationRun.request_id == request_id, ConversationRun.status == "running"
                )
                .values(status="cancelling", updated_at=datetime.now(UTC))
            )
            orm.commit()
        self._cancel_requested.add(request_id)
        started = self._started.get(request_id)
        if started is not None:
            await started.wait()
        if not task.cancelling():
            task.cancel()
        await self._drain(task)
        return True

    async def close(self) -> None:
        async def stop(request_id: str, task: asyncio.Task[None]) -> None:
            await self.cancel(request_id)
            if not task.done() and not task.cancelling():
                task.cancel()  # Close a terminal producer's remaining transport cleanup.
            await self._drain(task)

        await asyncio.gather(*(stop(key, task) for key, task in list(self.tasks.items())))

    def _save(self, request_id: str, event: ChatEvent) -> None:
        with Session(self.engine) as orm:
            orm.execute(
                update(ConversationRun)
                .where(
                    ConversationRun.request_id == request_id,
                    ConversationRun.status.in_({"running", "cancelling"}),
                    ConversationRun.terminal_event.is_(None),
                )
                .values(
                    status=event.status,
                    terminal_event=event.model_dump_json(),
                    updated_at=datetime.now(UTC),
                )
            )
            orm.commit()

    async def run(
        self,
        request: ChatRequest,
        channel: ChannelContext,
        generate: Callable[[], AsyncGenerator[ChatEvent, None]],
    ) -> AsyncGenerator[ChatEvent, None]:
        fingerprint = hashlib.sha256(
            json.dumps([request.model_dump(), channel.model_dump()], sort_keys=True).encode()
        ).hexdigest()
        with Session(self.engine) as orm:
            row = orm.get(ConversationRun, request.request_id)
            if row is not None:
                if row.fingerprint != fingerprint:
                    prior = ChatEvent(
                        type="error", message="请求编号已用于不同内容", status="failed"
                    )
                elif row.terminal_event:
                    prior = ChatEvent.model_validate_json(row.terminal_event)
                else:
                    prior = ChatEvent(
                        type="error",
                        message="请求已接收；请查看历史或任务状态，不会重复执行。",
                        status=row.status,
                    )
            else:
                prior = None
                orm.add(
                    ConversationRun(
                        request_id=request.request_id,
                        session_id=request.session_id,
                        fingerprint=fingerprint,
                        status="running",
                    )
                )
                orm.commit()
        if prior:
            yield prior.model_copy(
                update={"session_id": request.session_id, "request_id": request.request_id}
            )
            return

        queue: asyncio.Queue[ChatEvent | None] = asyncio.Queue()
        self._session_users[request.session_id] = self._session_users.get(request.session_id, 0) + 1
        started = self._started[request.request_id] = asyncio.Event()

        async def produce() -> None:
            terminal = False
            waiting_approval = False
            try:
                started.set()
                if request.request_id in self._cancel_requested:
                    raise asyncio.CancelledError
                async with (
                    self.locks.setdefault(request.session_id, asyncio.Lock()),
                    aclosing(generate()) as generated,
                ):
                    async for event in generated:
                        waiting_approval = waiting_approval or event.type == "approval"
                        delegated = (event.extra or {}).get("delegate_event", {})
                        event = event.model_copy(
                            update={
                                "session_id": request.session_id,
                                "request_id": request.request_id,
                                "channel": channel.channel,
                                "task_id": delegated.get("task_id")
                                if isinstance(delegated, dict)
                                else None,
                                "kind": {
                                    "start": "message",
                                    "chunk": "message",
                                    "done": "result",
                                    "task": "progress",
                                }.get(event.type, event.type),
                                "status": ("waiting_approval" if waiting_approval else "succeeded")
                                if event.type == "done"
                                else "failed"
                                if event.type == "error"
                                else "waiting_approval"
                                if event.type == "approval"
                                else "running",
                                "payload": event.model_dump(
                                    mode="json",
                                    include={"delta", "message_id", "text", "message", "extra"},
                                ),
                            }
                        )
                        if event.type in {"done", "error"}:
                            terminal = True
                            self._save(request.request_id, event)
                        queue.put_nowait(event)
                        if terminal:
                            break
            except asyncio.CancelledError:
                if terminal:
                    return
                event = ChatEvent(
                    type="error",
                    message="已停止本轮生成；已完成的操作可在任务和审计中查看。",
                    kind="aborted",
                    status="aborted",
                    request_id=request.request_id,
                    session_id=request.session_id,
                    channel=channel.channel,
                )
                self._save(request.request_id, event)
                queue.put_nowait(event)
                terminal = True
            except Exception as exc:
                if terminal:
                    return
                event = ChatEvent(
                    type="error",
                    message=f"请求处理失败（{type(exc).__name__}）",
                    status="failed",
                    request_id=request.request_id,
                    session_id=request.session_id,
                )
                self._save(request.request_id, event)
                queue.put_nowait(event)
                terminal = True
            finally:
                if not terminal:
                    event = ChatEvent(
                        type="error",
                        message="生成未正常完成",
                        status="failed",
                        request_id=request.request_id,
                        session_id=request.session_id,
                    )
                    self._save(request.request_id, event)
                    queue.put_nowait(event)
                queue.put_nowait(None)
                self._cancel_requested.discard(request.request_id)
                self._started.pop(request.request_id, None)
                users = self._session_users[request.session_id] - 1
                if users:
                    self._session_users[request.session_id] = users
                else:
                    self._session_users.pop(request.session_id, None)
                    self.locks.pop(request.session_id, None)

        task = asyncio.create_task(produce())
        self.tasks[request.request_id] = task
        try:
            while (event := await queue.get()) is not None:
                yield event
        finally:
            if not task.done():
                await self.cancel(request.request_id)
            if not task.done() and not task.cancelling():
                task.cancel()
            await self._drain(task)
            self.tasks.pop(request.request_id, None)
