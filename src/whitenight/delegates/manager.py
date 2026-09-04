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
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as OrmSession

from whitenight.delegates.base import (
    DelegateCapabilities,
    DelegateError,
    DelegateProvider,
    DelegateUnavailableError,
)
from whitenight.delegates.events import DelegateEvent, DelegationRequest
from whitenight.policy.engine import PolicyEngine
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


TERMINAL_TASK_STATES = frozenset({"succeeded", "failed", "aborted", "awaiting_review"})


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
            if task.status in TERMINAL_TASK_STATES or (
                task.status == "cancelling" and status not in {"aborted", "cancel_failed"}
            ):
                return self._record(task)
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

    def activity_snapshot(self, limit: int = 1000) -> dict[str, object]:
        """Project active task metadata without loading private task prompts."""
        with OrmSession(self._engine) as orm:
            rows = orm.execute(
                select(AgentTask.id, AgentTask.status, AgentTask.updated_at)
                .where(
                    AgentTask.status.in_(
                        {"queued", "running", "cancelling", "cancel_failed", "awaiting_review"}
                    )
                )
                .order_by(AgentTask.updated_at)
                .limit(limit + 1)
            ).all()
            return {
                "tasks_complete": len(rows) <= limit,
                "tasks": [
                    {"id": row.id, "status": row.status, "updated_at": row.updated_at.isoformat()}
                    for row in rows[:limit]
                ],
            }

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
        self._policy = PolicyEngine()

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
        if record is not None and record.status != "queued":
            yield DelegateEvent(
                task_id=record.id,
                executor=record.executor,  # type: ignore[arg-type]
                type="error",
                step="manager",
                label="任务不能直接重试",
                detail="已有任务必须先核验执行结果；不会重新提交可能产生过副作用的任务",
            )
            return
        if record is None:
            record = self._store.create(
                executor=executor,
                category=category,
                risk=risk,
                prompt=prompt,
                session_id=session_id,
                cwd=cwd,
            )

        capabilities = getattr(provider, "capabilities", DelegateCapabilities())
        decision = self._policy.evaluate_delegate(
            risk,
            read_only=capabilities.read_only,
            action_policy=capabilities.action_policy,
        )
        if not decision.allowed:
            self._store.update(record.id, status="failed", error=decision.reason)
            yield DelegateEvent(
                task_id=record.id,
                executor=executor,  # type: ignore[arg-type]
                type="error",
                step="policy",
                label="委派权限不足",
                detail=decision.reason,
            )
            return

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
                received_result = False
                request = DelegationRequest(
                    task_id=record.id,
                    prompt=prompt,
                    cwd=cwd,
                    thread_id=thread_id,
                    sandbox="read-only" if risk == "read_only" else "workspace-write",
                    metadata={**(metadata or {}), "risk": risk},
                )
                async for event in provider.submit(request):
                    if self._store.get(record.id).status in {"cancelling", "aborted"}:
                        return
                    event_thread = event.payload.get("thread_id")
                    if isinstance(event_thread, str) and event_thread:
                        thread_id = event_thread
                        self._store.update(record.id, thread_id=thread_id)
                    if event.type == "result":
                        received_result = True
                        self._store.update(
                            record.id,
                            status="succeeded",
                            thread_id=event.payload.get("thread_id"),
                            artifacts=event.artifacts,
                        )
                    yield event
                if not received_result:
                    reason = "执行器结束但未返回可验证结果，需要核验；不会自动重试"
                    self._store.update(record.id, status="awaiting_review", error=reason)
                    yield DelegateEvent(
                        task_id=record.id,
                        executor=executor,  # type: ignore[arg-type]
                        type="error",
                        step="manager",
                        label="执行结果需要核验",
                        detail=reason,
                        payload={"status": "awaiting_review", "automatic_retry": False},
                    )
                return
            except asyncio.CancelledError:
                await self.abort(record.id)
                raise
            except DelegateUnavailableError as exc:
                if self._store.get(record.id).status in {"cancelling", "aborted"}:
                    return
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
            except Exception as exc:
                if self._store.get(record.id).status in {"cancelling", "aborted"}:
                    return
                last_error = str(exc)
                execution_state = (
                    exc.execution_state if isinstance(exc, DelegateError) else "unknown"
                )
                if execution_state == "not_started" and attempts <= self._max_retries:
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
                status = "failed" if execution_state == "not_started" else "awaiting_review"
                self._store.update(record.id, status=status, error=last_error)
                yield DelegateEvent(
                    task_id=record.id,
                    executor=executor,  # type: ignore[arg-type]
                    type="error",
                    step="manager",
                    label="任务失败" if status == "failed" else "执行结果需要核验",
                    detail=last_error,
                    payload={"status": status, "automatic_retry": False},
                )
                return

    async def abort(self, task_id: str) -> DelegateEvent:
        record = self._store.get(task_id)
        if record.status in TERMINAL_TASK_STATES:
            return DelegateEvent(
                task_id=task_id,
                executor=record.executor,  # type: ignore[arg-type]
                type="error",
                step="manager",
                label="任务已结束",
                detail=f"当前状态：{record.status}",
            )
        self._store.update(task_id, status="cancelling")
        provider = self._providers.get(record.executor)
        accepted = False
        try:
            if provider is not None:
                accepted = await asyncio.wait_for(
                    provider.abort(task_id, record.thread_id), timeout=15
                )
        except Exception:
            accepted = False
        status = "aborted" if accepted else "cancel_failed"
        self._store.update(record.id, status=status)
        return DelegateEvent(
            task_id=task_id,
            executor=record.executor,  # type: ignore[arg-type]
            type="aborted" if accepted else "error",
            step="manager",
            label="中止请求",
            detail="执行器已确认停止" if accepted else "尚未确认执行器停止，请核验任务状态",
            payload={"status": status},
        )
