"""Model continuation after approval using the shared bounded tool scheduler."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from uuid import uuid4

from whitenight.agent.batches import ToolBatchScheduler
from whitenight.channels.types import (
    ChannelContext,
    ChatEvent,
    MessageRecord,
)
from whitenight.config import Settings
from whitenight.models.base import (
    ModelProvider,
    ProviderMessage,
    ToolCall,
    model_capabilities,
)
from whitenight.tools.base import FileDeliveryProvider, ToolRegistry
from whitenight.tools.executor import ExecutionOutcome, ToolExecutor
from whitenight.tools.pending import PendingToolStore

logger = logging.getLogger(__name__)


def tool_invoker(
    executor: ToolExecutor,
    session_id: str,
    channel: ChannelContext,
    delivery: FileDeliveryProvider | None,
    data_dir: Path,
) -> Callable[[ToolCall], ExecutionOutcome]:
    def invoke(call: ToolCall) -> ExecutionOutcome:
        return executor.execute(
            call.name,
            call.arguments,
            session_id=session_id,
            channel=channel.channel,
            channel_target=channel.target,
            file_delivery=delivery,
            data_dir=str(data_dir),
        )

    return invoke


class ToolLoopRunner:
    def __init__(
        self,
        get_provider: Callable[[], ModelProvider],
        settings: Settings,
        tools: ToolRegistry | None,
        executor: ToolExecutor | None,
        pending: PendingToolStore | None,
        delivery: FileDeliveryProvider | None,
        batch: ToolBatchScheduler,
        persist: Callable[[str, str], MessageRecord],
    ) -> None:
        self._get_provider = get_provider
        self._settings, self._tools, self._tool_executor = settings, tools, executor
        self._pending_tools, self._file_delivery = pending, delivery
        self._batch, self._persist_assistant = batch, persist

    async def continue_reply(
        self,
        session_id: str,
        messages: list[ProviderMessage],
        channel_context: ChannelContext,
    ) -> AsyncGenerator[ChatEvent, None]:
        provider = self._get_provider()
        text_parts: list[str] = []
        seen_calls: set[str] = set()
        supports_tools = model_capabilities(provider).tools
        tool_specs = (
            self._tools.specs(set(self._tools.names()) - {"channel.file.send"})
            if self._tools and supports_tools
            else None
        )
        if tool_specs is not None:
            tool_specs = [spec for spec in tool_specs if spec.name != "channel.sticker.send"]
        advertised_tool_names = {spec.name for spec in tool_specs or []}
        try:
            for _round in range(8):
                turn_parts: list[str] = []
                calls = []
                stream = (
                    provider.stream_chat(messages, tool_specs)
                    if tool_specs is not None
                    else provider.stream_chat(messages)
                )
                async for chunk in stream:
                    if chunk.delta:
                        turn_parts.append(chunk.delta)
                        text_parts.append(chunk.delta)
                        yield ChatEvent(type="chunk", delta=chunk.delta)
                    calls.extend(chunk.tool_calls)
                    if chunk.done:
                        break
                if not calls:
                    break
                unavailable_calls = [
                    call.name for call in calls if call.name not in advertised_tool_names
                ]
                if unavailable_calls:
                    raise RuntimeError(
                        "模型调用了当前请求未开放的工具：" + ", ".join(unavailable_calls)
                    )
                call_keys = [
                    json.dumps(
                        {"name": call.name, "arguments": call.arguments},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    for call in calls
                ]
                if len(call_keys) != len(set(call_keys)) or any(
                    key in seen_calls for key in call_keys
                ):
                    raise RuntimeError("模型重复调用同一工具和参数")
                seen_calls.update(call_keys)
                messages.append(
                    ProviderMessage(role="assistant", content="".join(turn_parts), tool_calls=calls)
                )
                assert self._tool_executor is not None
                executor = self._tool_executor
                outcomes = await self._batch.run(
                    calls,
                    tool_invoker(
                        executor,
                        session_id,
                        channel_context,
                        self._file_delivery,
                        self._settings.data_dir,
                    ),
                )
                waiting: list[tuple[ToolCall, ExecutionOutcome]] = []
                for call, outcome in zip(calls, outcomes, strict=True):
                    yield ChatEvent(
                        type="tool",
                        session_id=session_id,
                        extra={
                            "tool_name": call.name,
                            "status": outcome.status,
                            "message": outcome.message,
                        },
                    )
                    if outcome.status == "waiting_approval":
                        waiting.append((call, outcome))
                    else:
                        messages.append(
                            ProviderMessage(
                                role="tool",
                                name=call.name,
                                tool_call_id=call.id,
                                content=json.dumps(
                                    self.result_payload(outcome), ensure_ascii=False
                                ),
                            )
                        )
                if waiting:
                    approval_lines: list[str] = []
                    for call, outcome in waiting:
                        if outcome.approval_id is None or self._pending_tools is None:
                            raise RuntimeError("审批调用缺少可恢复状态存储")
                        prepared_params = outcome.metadata.get("prepared_params")
                        pending_params = (
                            prepared_params if isinstance(prepared_params, dict) else call.arguments
                        )
                        self._pending_tools.create(
                            approval_id=outcome.approval_id,
                            session_id=session_id,
                            channel=channel_context.channel,
                            channel_target=channel_context.target,
                            tool_call_id=call.id,
                            tool_name=call.name,
                            params=pending_params,
                            assistant_content="".join(turn_parts),
                        )
                        approval_lines.append(
                            f"操作 {call.name} 需要审批。请回复：同意 "
                            f"{outcome.approval_code}，或：拒绝 {outcome.approval_code}。"
                        )
                    reply = (
                        "".join(text_parts).strip() + "\n\n" + "\n".join(approval_lines)
                    ).strip()
                    message = self._persist_assistant(session_id, reply)
                    for call, outcome in waiting:
                        yield ChatEvent(
                            type="approval",
                            session_id=session_id,
                            message_id=message.id,
                            text=reply,
                            extra={
                                "approval_code": outcome.approval_code,
                                "tool_name": call.name,
                            },
                        )
                    yield ChatEvent(
                        type="done", session_id=session_id, message_id=message.id, text=reply
                    )
                    return
            else:
                raise RuntimeError("工具调用超过 8 轮，已安全终止")
        except Exception as exc:
            logger.exception("审批后模型继续失败 session=%s", session_id)
            yield ChatEvent(
                type="error",
                message=f"审批后继续失败（{type(exc).__name__}，编号 {uuid4().hex[:12]}）",
            )
            return
        reply = "".join(text_parts).strip() or "操作已完成。"
        message = self._persist_assistant(session_id, reply)
        yield ChatEvent(type="done", session_id=session_id, message_id=message.id, text=reply)

    @staticmethod
    def result_payload(outcome: ExecutionOutcome) -> dict[str, object]:
        return {
            "ok": outcome.status == "ok",
            "summary": outcome.message,
            "content": outcome.result.content if outcome.result else "",
            "sources": (
                [source.model_dump() for source in outcome.result.sources] if outcome.result else []
            ),
            "metadata": outcome.result.metadata if outcome.result else {},
        }
