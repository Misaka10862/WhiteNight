"""scheduler: 主动消息与后台任务调度。"""

from whitenight.scheduler.poisson import next_candidate
from whitenight.scheduler.service import LogSender, NullSender, ProactiveService
from whitenight.scheduler.store import ProactiveStore
from whitenight.scheduler.types import (
    ProactiveConfig,
    ProactiveDelivery,
    ProactiveStatus,
    SendOutcome,
)

__all__ = [
    "LogSender",
    "NullSender",
    "ProactiveConfig",
    "ProactiveDelivery",
    "ProactiveService",
    "ProactiveStatus",
    "ProactiveStore",
    "SendOutcome",
    "next_candidate",
]
