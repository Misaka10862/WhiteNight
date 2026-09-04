"""委派 Provider 协议：Hermes 与 Codex 都必须实现本接口。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from typing import Literal, Protocol

from whitenight.delegates.events import DelegateEvent, DelegationRequest


class DelegateError(RuntimeError):
    """Failure whose default outcome is unknown, so repeating it is unsafe."""

    def __init__(
        self, message: str, *, execution_state: Literal["not_started", "unknown"] = "unknown"
    ) -> None:
        super().__init__(message)
        self.execution_state = execution_state


class DelegateUnavailableError(DelegateError):
    """执行器不可用（未登录、未安装、服务未启动）。"""


@dataclass(frozen=True)
class DelegateCapabilities:
    """Trusted adapter guarantees, never inferred from model output.

    action_policy requires a tested per-action WhiteNight approval/denial bridge,
    including an unconditional batch-delete prohibition. Native agent prompts or
    sandbox escalation prompts alone do not establish that guarantee.
    """

    read_only: bool = False
    action_policy: bool = False


class DelegateProvider(Protocol):
    name: str
    capabilities: DelegateCapabilities

    def health(self) -> Awaitable[dict[str, object]]: ...

    def submit(self, request: DelegationRequest) -> AsyncIterator[DelegateEvent]:
        """流式执行任务；进度/审批/产物/失败必须通过事件上报。"""

    def abort(self, task_id: str, thread_id: str | None = None) -> Awaitable[bool]:
        """Return True only after the running execution has verifiably stopped."""
