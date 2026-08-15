"""委派 Provider 协议：Hermes 与 Codex 都必须实现本接口。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from typing import Protocol

from whitenight.delegates.events import DelegateEvent, DelegationRequest


class DelegateError(RuntimeError):
    """委派执行失败（可安全重试）。"""


class DelegateUnavailableError(DelegateError):
    """执行器不可用（未登录、未安装、服务未启动）。"""


class DelegateProvider(Protocol):
    name: str

    def health(self) -> Awaitable[dict[str, object]]: ...

    def submit(self, request: DelegationRequest) -> AsyncIterator[DelegateEvent]:
        """流式执行任务；进度/审批/产物/失败必须通过事件上报。"""

    def abort(self, task_id: str, thread_id: str | None = None) -> Awaitable[bool]:
        """请求中止；返回是否已受理。"""
