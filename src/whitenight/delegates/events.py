"""标准化委派事件：WhiteNight/Hermes/Codex 共用同一事件信封。

消费方只依赖本结构，不解析任何执行器终端文本。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DelegateEventType = Literal[
    "queued",
    "started",
    "progress",
    "approval_required",
    "artifact",
    "result",
    "error",
    "aborted",
]


class DelegateEvent(BaseModel):
    task_id: str
    executor: Literal["whitenight", "hermes", "codex"]
    type: DelegateEventType
    step: str = ""
    label: str = ""
    detail: str = ""
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    approval_id: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DelegationRequest(BaseModel):
    task_id: str
    prompt: str
    cwd: str | None = None
    thread_id: str | None = None
    sandbox: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
