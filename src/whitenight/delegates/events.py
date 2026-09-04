"""标准化委派事件：WhiteNight/Hermes/Codex 共用同一事件信封。

消费方只依赖本结构，不解析任何执行器终端文本。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from whitenight.events import EventEnvelope

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


class DelegateEvent(EventEnvelope):
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

    @model_validator(mode="after")
    def normalize_envelope(self) -> DelegateEvent:
        self.actor = self.executor
        self.kind = {
            "queued": "plan",
            "started": "progress",
            "approval_required": "approval",
            "artifact": "result",
        }.get(self.type, self.type)
        self.status = {
            "result": "succeeded",
            "error": "failed",
            "aborted": "aborted",
            "approval_required": "waiting_approval",
        }.get(self.type, "running")
        reported = self.payload.get("status")
        if reported in {"awaiting_review", "cancelling", "cancel_failed"}:
            self.status = str(reported)
        return self


class DelegationRequest(BaseModel):
    task_id: str
    prompt: str
    cwd: str | None = None
    thread_id: str | None = None
    sandbox: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
