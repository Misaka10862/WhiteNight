"""委派任务管理器：状态持久化、安全重试、中止与升级边界。

Hermes/Codex 故障不允许破坏主会话：本管理器只产出事件/结果，
由 ChatService 决定如何人格化交付与本地降级。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession

from whitenight.delegates.base import DelegateError, DelegateProvider, DelegateUnavailableError
from whitenight.delegates.events import DelegateEvent, DelegationRequest
from whitenight.storage.models import AgentTask


class TaskRecord(BaseModel):
    id: str
    session_id: str | None
    executor: str
    category: str
    status: str
    risk: str
    prompt: str
    cwd: str | None = None
    thread_id: str | None = None
    artifacts: list[dict[str, object]] = Field(default_factory=list)
    error: str | None = None
    attempts: int = 0
    created_at: datetime
    updated_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


class TaskStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(
        self,
        *,
        executor: str,
        category: str,
        risk: str,
        prompt: str,
        session_id: str | None = None,
        cwd: str | None = None,
    ) -> TaskRecord:
        with OrmSession(self._engine, expire_on_commit=False) as orm:
            task = AgentTask(
                session_id=session_id,
                executor=executor,
                category=category,
                status="queued",
                risk=risk,
                prompt=prompt,
                cwd=cwd,
            )
            orm.add(task)
            orm.commit()
            return self._record(task)

    def update(
        self,
        task_id: str,
        *,
        status: str | None = None,
        thread_id: str | None = None,
        artifacts: list[dict[str, object]] | None = None,
        error: str | None = None,
        attempts: int | None = None,
    ) -> TaskRecord:
        with OrmSession(self._engine, expire_on_commit=False) as orm:
            task = orm.get(AgentTask, task_id)
            if task is None:
                raise KeyError(task_id)
            if status is not None:
                task.status = status
            if thread_id is not None:
                task.thread_id = thread_id
            if artifacts is not None:
                task.artifacts = json.dumps(artifacts, ensure_ascii=False)
            if error is not None:
                task.error = error
            if attempts is not None:
                task.attempts = attempts
            task.updated_at = _now()
            orm.commit()
            return self._record(task)

    def get(self, task_id: str) -> TaskRecord:
        with OrmSession(self._engine, expire_on_commit=False) as orm:
            task = orm.get(AgentTask, task_id)
            if task is None:
                raise KeyError(task_id)
            return self._record(task)

    def list(self, session_id: str | None = None, limit: int = 50) -> list[TaskRecord]:
        with OrmSession(self._engine, expire_on_commit=False) as orm:
            query = orm.query(AgentTask)
            if session_id:
                query = query.filter(AgentTask.session_id == session_id)
            tasks = query.order_by(AgentTask.created_at.desc()).limit(limit).all()
            return [self._record(task) for task in tasks]

    def _record(self, task: AgentTask) -> TaskRecord:
        try:
            artifacts = json.loads(task.artifacts or "[]")
        except json.JSONDecodeError:
            artifacts = []
        return TaskRecord(
            id=task.id,
            session_id=task.session_id,
            executor=task.executor,
            category=task.category,
            status=task.status,
            risk=task.risk,
            prompt=task.prompt,
            cwd=task.cwd,
            thread_id=task.thread_id,
            artifacts=artifacts if isinstance(artifacts, list) else [],
            error=task.error,
            attempts=task.attempts,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class DelegateManager:
    """按执行器分发任务；失败有限重试；不可用时快速失败。"""

    def __init__(
        self,
        store: TaskStore,
        providers: dict[str, DelegateProvider],
        max_retries: int = 1,
        retry_delay_s: float = 1.0,
    ) -> None:
        self._store = store
        self._providers = providers
        self._max_retries = max(0, max_retries)
        self._retry_delay_s = retry_delay_s

    def providers(self) -> dict[str, DelegateProvider]:
        return dict(self._providers)

    async def run(
        self,
        *,
        executor: str,
        category: str,
        risk: str,
        prompt: str,
        session_id: str | None = None,
        cwd: str | None = None,
        task_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AsyncGenerator[DelegateEvent, None]:
        """创建/续接任务并流式返回事件；终态落在 TaskStore。"""
        provider = self._providers.get(executor)
        if provider is None:
            yield DelegateEvent(
                task_id=task_id or "",
                executor=executor,  # type: ignore[arg-type]
                type="error",
                step="manager",
                label="未知执行器",
                detail=f"{executor} 没有注册 Provider",
            )
            return

        record = self._store.get(task_id) if task_id else None
        if record is None:
            record = self._store.create(
                executor=executor,
                category=category,
                risk=risk,
                prompt=prompt,
                session_id=session_id,
                cwd=cwd,
            )

        attempts = 0
        last_error: str | None = None
        thread_id = record.thread_id
        while attempts <= self._max_retries:
            attempts += 1
            self._store.update(record.id, status="running", attempts=attempts)
            yield DelegateEvent(
                task_id=record.id,
                executor=executor,  # type: ignore[arg-type]
                type="started",
                step="manager",
                label=f"第 {attempts} 次尝试",
                detail=f"executor={executor}",
            )
            try:
                request = DelegationRequest(
                    task_id=record.id,
                    prompt=prompt,
                    cwd=cwd,
                    thread_id=thread_id,
                    sandbox="workspace-write" if executor == "codex" else None,
                    metadata=metadata or {},
                )
                async for event in provider.submit(request):
                    if event.type == "result":
                        self._store.update(
                            record.id,
                            status="succeeded",
                            thread_id=event.payload.get("thread_id"),
                            artifacts=event.artifacts,
                        )
                    yield event
                return
            except DelegateUnavailableError as exc:
                last_error = str(exc)
                self._store.update(record.id, status="failed", error=last_error)
                yield DelegateEvent(
                    task_id=record.id,
                    executor=executor,  # type: ignore[arg-type]
                    type="error",
                    step="manager",
                    label="执行器不可用",
                    detail=last_error,
                )
                return
            except DelegateError as exc:
                last_error = str(exc)
                if attempts <= self._max_retries:
                    yield DelegateEvent(
                        task_id=record.id,
                        executor=executor,  # type: ignore[arg-type]
                        type="progress",
                        step="manager",
                        label="失败，准备安全重试",
                        detail=f"{last_error}（{attempts}/{self._max_retries + 1}）",
                    )
                    await asyncio.sleep(self._retry_delay_s)
                    continue
                self._store.update(record.id, status="failed", error=last_error)
                yield DelegateEvent(
                    task_id=record.id,
                    executor=executor,  # type: ignore[arg-type]
                    type="error",
                    step="manager",
                    label="任务失败",
                    detail=last_error,
                )
                return

    async def abort(self, task_id: str) -> DelegateEvent:
        record = self._store.get(task_id)
        provider = self._providers.get(record.executor)
        accepted = False
        if provider is not None:
            accepted = await provider.abort(task_id, record.thread_id)
        self._store.update(record.id, status="aborted")
        return DelegateEvent(
            task_id=task_id,
            executor=record.executor,  # type: ignore[arg-type]
            type="aborted",
            step="manager",
            label="中止请求",
            detail="已受理" if accepted else "Provider 未受理（进程级中止）",
        )
