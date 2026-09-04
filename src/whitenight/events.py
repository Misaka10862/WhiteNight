"""Versioned application event envelope; legacy transports add their own fields."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    envelope: str = "whitenight.event/1"
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    request_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    channel: str = "web"
    kind: str = "message"
    actor: str = "whitenight"
    status: str = "running"
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)
