"""Bounded execution: read-only batches may overlap; side effects preserve order."""

import asyncio
import contextvars
from collections.abc import Callable

from whitenight.models.base import ToolCall
from whitenight.policy.engine import PolicyEngine
from whitenight.policy.risk import RiskLevel
from whitenight.tools.executor import ExecutionOutcome


class ToolBatchScheduler:
    def __init__(self, policy: PolicyEngine, concurrency: int = 4) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be greater than zero")
        self.policy = policy
        self.limit = asyncio.Semaphore(concurrency)

    async def run(
        self, calls: list[ToolCall], execute: Callable[[ToolCall], ExecutionOutcome]
    ) -> list[ExecutionOutcome]:
        async def invoke(call: ToolCall) -> ExecutionOutcome:
            async with self.limit:
                # An executor Future is not an asyncio Task: event-loop shutdown
                # cannot cancel its wrapper while the underlying OS thread keeps
                # executing a write. Preserve the caller's tracing context.
                worker = asyncio.get_running_loop().run_in_executor(
                    None, contextvars.copy_context().run, execute, call
                )
                cancelled = False
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        # Repeated cancellation must not interrupt the drain.
                        cancelled = True
                outcome = worker.result()
                if cancelled:
                    raise asyncio.CancelledError
                return outcome

        if all(self.policy.risk_of(call.name) is RiskLevel.READ_ONLY for call in calls):
            return list(await asyncio.gather(*(invoke(call) for call in calls)))
        outcomes = []
        blocked = False
        for call in calls:
            if blocked:
                outcomes.append(
                    ExecutionOutcome(
                        status="refused", message="前序调用未完成，请等待审批或纠正后再继续。"
                    )
                )
                continue
            outcome = await invoke(call)
            outcomes.append(outcome)
            blocked = outcome.status != "ok"
        return outcomes
