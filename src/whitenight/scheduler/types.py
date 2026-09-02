"""主动消息调度类型与配置。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ProactiveConfig(BaseModel):
    enabled: bool = False
    expected_per_day: float = Field(default=1.5, ge=0.1, le=6.0)
    quiet_start: str = Field(default="23:00", pattern=r"^\d{2}:\d{2}$")
    quiet_end: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    suppress_minutes: int = Field(default=60, ge=0, le=480)
    skip_grace_minutes: int = Field(default=45, ge=5, le=240)


class ProactiveDelivery(BaseModel):
    configured_sender: Literal["log", "none", "qq"]
    active_sender: Literal["log", "none", "qq", "unavailable"]
    target_user_id: int | None = None
    onebot_reachable: bool | None = None
    available: bool
    reason: str = ""


class ProactiveStatus(BaseModel):
    config: ProactiveConfig
    paused: bool = False
    paused_until: datetime | None = None
    last_activity_at: datetime | None = None
    last_sent_at: datetime | None = None
    next_candidate_at: datetime | None = None
    delivery: ProactiveDelivery | None = None


class PauseRequest(BaseModel):
    until: datetime | None = None


class SendOutcome(BaseModel):
    action: str  # sent | skipped_expired | skipped_paused | skipped_disabled | not_due
    reason: str = ""
    message: str | None = None
