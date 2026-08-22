"""Agent 循环：会话持久化 → 上下文装配 → 模型流式 → 落库 → 事件发布。

事实保真策略：模型输出原样透传，不做人设改写；人格由 SOUL.md 约束。
主回复完成后异步提取长期记忆（阶段 4）；Hermes/Codex 委派与路由在阶段 5 接入。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from collections.abc import AsyncGenerator

from whitenight.agent.context import build_provider_messages, load_soul
from whitenight.channels.types import (
    ChannelContext,
    ChatEvent,
    ChatRequest,
    MessageKind,
    MessageRecord,
)
from whitenight.config import Settings
from whitenight.delegates.manager import DelegateManager
from whitenight.memory.service import MemoryService
from whitenight.models.base import ModelChunk, ModelProvider, ProviderMessage, ToolCall, ToolSpec
from whitenight.policy.approvals import ApprovalService
from whitenight.policy.engine import ApprovalMode, PolicyEngine
from whitenight.routing.engine import RoutingEngine
from whitenight.routing.models import ExecutorChoice
from whitenight.scheduler.service import ProactiveService
from whitenight.storage.attachments import save_image_data_url
from whitenight.storage.sessions import SessionNotFoundError, SessionStore
from whitenight.tools.base import FileDeliveryProvider, ToolRegistry
from whitenight.tools.executor import ExecutionOutcome, ToolExecutor
from whitenight.tools.pending import PendingToolStore, params_digest

logger = logging.getLogger(__name__)

_FILE_SEND_INTENT_RE = re.compile(r"(?:发给我|发送给我|传给我|发过来|发送文件|上传文件)")
_FILE_CONTEXT_RE = re.compile(
    r"(?:文件|文档|附件|报告|表格|压缩包|数据集|[A-Za-z0-9_.()-]+\.[A-Za-z0-9]{1,10})",
    re.IGNORECASE,
)
_SHORT_FILE_SEND_RE = re.compile(
    r"^(?:好的?[，,\s]*)?(?:直接发|发吧|发|速发|快发|赶紧发)(?:给我)?[！!。.]?$"
)
_MAX_ORCHESTRATED_FILE_SENDS = 20


class ChatService:
    """统一 Agent 循环：路由 → 本体/委派执行 → 人格化交付 → 落库。"""

    def __init__(
        self,
        store: SessionStore,
        provider: ModelProvider,
        settings: Settings,
        memory_service: MemoryService | None = None,
        router: RoutingEngine | None = None,
        delegate_manager: DelegateManager | None = None,
        proactive_service: ProactiveService | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_executor: ToolExecutor | None = None,
        approvals: ApprovalService | None = None,
        pending_tools: PendingToolStore | None = None,
        policy: PolicyEngine | None = None,
        file_delivery: FileDeliveryProvider | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._settings = settings
        self._memory = memory_service
        self._router = router or RoutingEngine()
        self._delegates = delegate_manager
        self._proactive = proactive_service
        self._tools = tool_registry
        self._tool_executor = tool_executor
        self._approvals = approvals
        self._pending_tools = pending_tools
        self._policy = policy
        self._file_delivery = file_delivery
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._extract_delay_s = 15.0
        self._extract_task: asyncio.Task[None] | None = None

    @property
    def provider(self) -> ModelProvider:
        return self._provider

    async def stream_reply(
        self, request: ChatRequest, channel_context: ChannelContext | None = None
    ) -> AsyncGenerator[ChatEvent, None]:
        """处理一条用户消息并流式产生事件；完整回复才落库为 assistant 消息。"""
        session_id = request.session_id
        trusted_channel = channel_context or ChannelContext()
        try:
            self._store.get_session(session_id)
        except SessionNotFoundError:
            yield ChatEvent(type="error", message=f"会话不存在：{session_id}")
            return

        # 聊天优先：新消息到达时取消待执行/执行中的记忆提取，把唯一推理槽让给用户。
        self._cancel_pending_extraction()

        image_path: str | None = None
        image_mime: str | None = None
        try:
            if request.image_data_url:
                image_path, image_mime = save_image_data_url(
                    request.image_data_url,
                    self._settings.data_dir / "attachments",
                    self._settings.max_image_bytes,
                )
        except ValueError as exc:
            yield ChatEvent(type="error", message=f"图片无法使用：{exc}")
            return

        kind: MessageKind = "image" if image_path else "text"
        user_message = self._store.add_message(
            session_id=session_id,
            role="user",
            content=request.text,
            kind=kind,
            image_path=image_path,
            image_mime=image_mime,
        )
        if self._proactive is not None:
            self._proactive.mark_activity()
        yield ChatEvent(type="start", session_id=session_id)

        plan = await self._router.route(request.text, has_image=image_path is not None)
        if (
            plan.executor in {ExecutorChoice.HERMES, ExecutorChoice.CODEX}
            and self._delegates is not None
        ):
            async for event in self._delegate_reply(
                session_id,
                request.text,
                plan,
                trusted_channel,
                request.image_data_url,
            ):
                yield event
            return

        if image_path is not None and not self._settings.model_supports_vision:
            reply = (
                "主人，现在临时使用文本模型（qwen3:8b），暂时看不了图片。"
                "等正式 LoRA 视觉模型完成并切回来后，我马上就能看图啦。"
            )
            message = self._persist_assistant(session_id, reply)
            yield ChatEvent(
                type="done",
                session_id=session_id,
                message_id=message.id,
                text=reply,
                extra={"user_message_id": user_message.id},
            )
            return

        try:
            history = self._store.list_messages(session_id)
            file_delivery_required = self._requires_file_delivery(
                request.text, history, trusted_channel
            )
            messages = build_provider_messages(
                history,
                load_soul(self._settings.soul_file),
                self._settings.context_budget_chars,
            )
            text_parts: list[str] = []
            seen_calls: set[str] = set()
            discovered_paths: set[str] = set()
            sent_paths: set[str] = set()
            fallback_attempted = False
            supports_tools = "tools" in inspect.signature(self._provider.stream_chat).parameters
            tool_specs = (
                self._tools.specs(
                    None
                    if trusted_channel.channel == "onebot"
                    else set(self._tools.names()) - {"channel.file.send"}
                )
                if self._tools and self._tool_executor and supports_tools
                else None
            )
            for _round in range(8):
                turn_parts: list[str] = []
                calls = []
                stream = (
                    self._provider.stream_chat(messages, tool_specs)
                    if tool_specs is not None
                    else self._provider.stream_chat(messages)
                )
                async for chunk in stream:
                    if chunk.delta:
                        turn_parts.append(chunk.delta)
                        if not file_delivery_required or self._file_delivery_complete(
                            discovered_paths, sent_paths
                        ):
                            text_parts.append(chunk.delta)
                            yield ChatEvent(type="chunk", delta=chunk.delta)
                    if chunk.tool_calls:
                        calls.extend(chunk.tool_calls)
                    if chunk.done:
                        break

                if not calls:
                    if file_delivery_required and not self._file_delivery_complete(
                        discovered_paths, sent_paths
                    ):
                        if (
                            discovered_paths
                            and not fallback_attempted
                            and len(discovered_paths) <= _MAX_ORCHESTRATED_FILE_SENDS
                        ):
                            fallback_attempted = True
                            fallback_calls = [
                                ToolCall(
                                    id=f"orchestrator-send-{_round}-{index}",
                                    name="channel.file.send",
                                    arguments={"path": path},
                                )
                                for index, path in enumerate(sorted(discovered_paths))
                            ]
                            messages.append(
                                ProviderMessage(role="assistant", tool_calls=fallback_calls)
                            )
                            assert self._tool_executor is not None
                            fallback_outcomes = await asyncio.gather(
                                *(
                                    asyncio.to_thread(
                                        self._tool_executor.execute,
                                        call.name,
                                        call.arguments,
                                        session_id=session_id,
                                        channel=trusted_channel.channel,
                                        channel_target=trusted_channel.target,
                                        file_delivery=self._file_delivery,
                                        data_dir=str(self._settings.data_dir),
                                    )
                                    for call in fallback_calls
                                )
                            )
                            for call, outcome in zip(
                                fallback_calls, fallback_outcomes, strict=True
                            ):
                                yield ChatEvent(
                                    type="tool",
                                    session_id=session_id,
                                    extra={
                                        "tool_name": call.name,
                                        "status": outcome.status,
                                        "message": outcome.message,
                                        "orchestrated": True,
                                    },
                                )
                                self._record_file_goal_result(
                                    call, outcome, discovered_paths, sent_paths
                                )
                                messages.append(
                                    ProviderMessage(
                                        role="tool",
                                        name=call.name,
                                        tool_call_id=call.id,
                                        content=json.dumps(
                                            self._tool_result_payload(outcome),
                                            ensure_ascii=False,
                                        ),
                                    )
                                )
                            if self._file_delivery_complete(discovered_paths, sent_paths):
                                break
                            continue
                        messages.append(
                            ProviderMessage(
                                role="system",
                                content=(
                                    "本轮用户要求发送文件，但目标尚未完成。不要输出解释、承诺或"
                                    "完成声明；立即调用可用的文件查找/发送工具。只有 "
                                    "channel.file.send 返回成功才能结束。"
                                ),
                            )
                        )
                        continue
                    break
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
                    ProviderMessage(
                        role="assistant",
                        content="".join(turn_parts),
                        tool_calls=calls,
                    )
                )
                assert self._tool_executor is not None
                outcomes = await asyncio.gather(
                    *(
                        asyncio.to_thread(
                            self._tool_executor.execute,
                            call.name,
                            call.arguments,
                            session_id=session_id,
                            channel=trusted_channel.channel,
                            channel_target=trusted_channel.target,
                            file_delivery=self._file_delivery,
                            data_dir=str(self._settings.data_dir),
                        )
                        for call in calls
                    )
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
                        self._record_file_goal_result(call, outcome, discovered_paths, sent_paths)
                        messages.append(
                            ProviderMessage(
                                role="tool",
                                name=call.name,
                                tool_call_id=call.id,
                                content=json.dumps(
                                    self._tool_result_payload(outcome), ensure_ascii=False
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
                            channel=trusted_channel.channel,
                            channel_target=trusted_channel.target,
                            tool_call_id=call.id,
                            tool_name=call.name,
                            params=pending_params,
                            assistant_content="".join(turn_parts),
                        )
                        approval_lines.append(
                            f"操作 {call.name} 需要审批。审批编号：{outcome.approval_code}。"
                        )
                    approval_text = "\n".join(approval_lines)
                    reply = "".join(text_parts).strip()
                    reply = f"{reply}\n\n{approval_text}".strip()
                    assistant_message = self._persist_assistant(session_id, reply)
                    for call, outcome in waiting:
                        yield ChatEvent(
                            type="approval",
                            session_id=session_id,
                            message_id=assistant_message.id,
                            text=approval_text,
                            extra={
                                "approval_id": outcome.approval_id,
                                "approval_code": outcome.approval_code,
                                "tool_name": call.name,
                            },
                        )
                    yield ChatEvent(
                        type="done",
                        session_id=session_id,
                        message_id=assistant_message.id,
                        text=reply,
                        extra={"user_message_id": user_message.id},
                    )
                    return
                if file_delivery_required and self._file_delivery_complete(
                    discovered_paths, sent_paths
                ):
                    break
            else:
                raise RuntimeError("工具调用超过 8 轮，已安全终止")
        except Exception as exc:  # Provider/存储异常：不伪造回复，原样报告
            logger.exception("聊天流式生成失败 session=%s", session_id)
            yield ChatEvent(type="error", message=f"模型调用失败：{exc}")
            return

        reply = "".join(text_parts).strip()
        if file_delivery_required and not self._file_delivery_complete(
            discovered_paths, sent_paths
        ):
            yield ChatEvent(
                type="error",
                message="文件发送目标未完成：发送工具没有成功处理全部已找到文件",
            )
            return
        if file_delivery_required:
            reply = f"已发送 {len(sent_paths)} 个文件。"
        if not reply:
            yield ChatEvent(type="error", message="模型没有产生可见回复，请重试")
            return

        assistant_message = self._persist_assistant(session_id, reply)
        yield ChatEvent(
            type="done",
            session_id=session_id,
            message_id=assistant_message.id,
            text=reply,
            extra={"user_message_id": user_message.id},
        )

    async def resume_approval(self, code: str, channel_context: ChannelContext) -> list[ChatEvent]:
        """Approve, consume and continue a previously suspended tool call."""
        if not all((self._pending_tools, self._approvals, self._policy, self._tool_executor)):
            return [ChatEvent(type="error", message="审批恢复服务未配置")]
        assert self._pending_tools is not None
        assert self._approvals is not None
        assert self._policy is not None
        assert self._tool_executor is not None
        pending = self._pending_tools.get_by_code(code)
        if pending is None or pending.status != "pending":
            return [ChatEvent(type="error", message="审批编号无效、已处理或无法恢复")]
        if pending.channel != channel_context.channel or (
            pending.channel_target and pending.channel_target != channel_context.target
        ):
            return [ChatEvent(type="error", message="审批编号不属于当前渠道或接收人")]
        if params_digest(pending.params) != pending.params_digest:
            self._pending_tools.update(pending.id, "failed", error="参数摘要不匹配")
            return [ChatEvent(type="error", message="待执行参数校验失败")]

        decision = self._policy.evaluate(pending.tool_name)
        expected_scope = "session" if decision.mode is ApprovalMode.SESSION else "once"
        resolution = self._approvals.approve(
            code,
            session_id=pending.session_id,
            expected_scope=expected_scope,
        )
        if not resolution.ok:
            return [ChatEvent(type="error", message=resolution.reason)]
        outcome = await asyncio.to_thread(
            self._tool_executor.execute,
            pending.tool_name,
            pending.params,
            session_id=pending.session_id,
            channel=pending.channel,
            channel_target=pending.channel_target,
            file_delivery=self._file_delivery,
            approval_id=pending.approval_id,
            data_dir=str(self._settings.data_dir),
        )
        result_payload = self._tool_result_payload(outcome)
        self._pending_tools.update(
            pending.id,
            "succeeded" if outcome.status == "ok" else "failed",
            result=result_payload,
            error=None if outcome.status == "ok" else outcome.message,
        )

        history = self._store.list_messages(pending.session_id)
        messages = build_provider_messages(
            history,
            load_soul(self._settings.soul_file),
            self._settings.context_budget_chars,
        )
        from whitenight.models.base import ToolCall

        messages.extend(
            [
                ProviderMessage(
                    role="assistant",
                    content=pending.assistant_content,
                    tool_calls=[
                        ToolCall(
                            id=pending.tool_call_id,
                            name=pending.tool_name,
                            arguments=pending.params,
                        )
                    ],
                ),
                ProviderMessage(
                    role="tool",
                    name=pending.tool_name,
                    tool_call_id=pending.tool_call_id,
                    content=json.dumps(result_payload, ensure_ascii=False),
                ),
            ]
        )
        events = [
            ChatEvent(
                type="tool",
                session_id=pending.session_id,
                extra={
                    "tool_name": pending.tool_name,
                    "status": outcome.status,
                    "message": outcome.message,
                },
            )
        ]
        events.extend(
            [
                event
                async for event in self._continue_after_approval(
                    pending.session_id, messages, channel_context
                )
            ]
        )
        return events

    async def reject_approval(self, code: str, channel_context: ChannelContext) -> str:
        if self._pending_tools is None or self._approvals is None:
            return "审批恢复服务未配置"
        pending = self._pending_tools.get_by_code(code)
        if pending is None or pending.status != "pending":
            return "审批编号无效、已处理或无法恢复"
        if pending.channel != channel_context.channel or (
            pending.channel_target and pending.channel_target != channel_context.target
        ):
            return "审批编号不属于当前渠道或接收人"
        resolution = self._approvals.reject(code)
        if resolution.ok:
            self._pending_tools.update(pending.id, "rejected")
            self._persist_assistant(pending.session_id, f"已拒绝操作 {pending.tool_name}。")
        return resolution.reason

    async def _continue_after_approval(
        self,
        session_id: str,
        messages: list[ProviderMessage],
        channel_context: ChannelContext,
    ) -> AsyncGenerator[ChatEvent, None]:
        text_parts: list[str] = []
        seen_calls: set[str] = set()
        supports_tools = "tools" in inspect.signature(self._provider.stream_chat).parameters
        tool_specs = (
            self._tools.specs(
                None
                if channel_context.channel == "onebot"
                else set(self._tools.names()) - {"channel.file.send"}
            )
            if self._tools and supports_tools
            else None
        )
        try:
            for _round in range(8):
                turn_parts: list[str] = []
                calls = []
                stream = (
                    self._provider.stream_chat(messages, tool_specs)
                    if tool_specs is not None
                    else self._provider.stream_chat(messages)
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
                outcomes = await asyncio.gather(
                    *(
                        asyncio.to_thread(
                            self._tool_executor.execute,
                            call.name,
                            call.arguments,
                            session_id=session_id,
                            channel=channel_context.channel,
                            channel_target=channel_context.target,
                            file_delivery=self._file_delivery,
                            data_dir=str(self._settings.data_dir),
                        )
                        for call in calls
                    )
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
                                    self._tool_result_payload(outcome), ensure_ascii=False
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
                            f"操作 {call.name} 需要审批。审批编号：{outcome.approval_code}。"
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
            yield ChatEvent(type="error", message=f"审批后继续失败：{exc}")
            return
        reply = "".join(text_parts).strip() or "操作已完成。"
        message = self._persist_assistant(session_id, reply)
        yield ChatEvent(type="done", session_id=session_id, message_id=message.id, text=reply)

    @staticmethod
    def _tool_result_payload(outcome: ExecutionOutcome) -> dict[str, object]:
        return {
            "ok": outcome.status == "ok",
            "summary": outcome.message,
            "content": outcome.result.content if outcome.result else "",
            "sources": (
                [source.model_dump() for source in outcome.result.sources] if outcome.result else []
            ),
            "metadata": outcome.result.metadata if outcome.result else {},
        }

    @staticmethod
    def _record_file_goal_result(
        call: ToolCall,
        outcome: ExecutionOutcome,
        discovered_paths: set[str],
        sent_paths: set[str],
    ) -> None:
        if outcome.status != "ok" or outcome.result is None:
            return
        if call.name == "file.find":
            discovered_paths.update(
                source.uri
                for source in outcome.result.sources
                if source.kind == "file" and source.uri
            )
        elif call.name == "channel.file.send":
            path = outcome.result.metadata.get("path")
            if isinstance(path, str) and path:
                sent_paths.add(path)

    @staticmethod
    def _file_delivery_complete(discovered_paths: set[str], sent_paths: set[str]) -> bool:
        return bool(sent_paths) and (not discovered_paths or discovered_paths <= sent_paths)

    @staticmethod
    def _requires_file_delivery(
        request_text: str,
        history: list[MessageRecord],
        channel_context: ChannelContext,
    ) -> bool:
        if channel_context.channel != "onebot" or not channel_context.target:
            return False
        text = request_text.strip()
        if _FILE_SEND_INTENT_RE.search(text) and _FILE_CONTEXT_RE.search(text):
            return True
        if not _SHORT_FILE_SEND_RE.fullmatch(text):
            return False
        recent_user_text = [
            message.content
            for message in history[-16:]
            if message.role == "user" and message.content != request_text
        ]
        return any(
            _FILE_SEND_INTENT_RE.search(content) and _FILE_CONTEXT_RE.search(content)
            for content in recent_user_text
        )

    async def _delegate_reply(
        self,
        session_id: str,
        prompt: str,
        plan: object,
        channel_context: ChannelContext,
        image_data_url: str | None = None,
    ) -> AsyncGenerator[ChatEvent, None]:
        """把任务交给 Hermes/Codex，并把标准化事件透传给渠道。

        结果原文落库；失败也不破坏主会话，下一次消息仍可正常使用。
        """
        from whitenight.routing.models import RoutingPlan

        assert isinstance(plan, RoutingPlan)
        result_text: str | None = None
        last_error: str | None = None
        task_id: str | None = None
        try:
            assert self._delegates is not None
            async for event in self._delegates.run(
                executor=plan.executor.value,
                category=plan.category.value,
                risk=plan.risk.value,
                prompt=prompt,
                session_id=session_id,
                cwd=str(self._settings.data_dir.parent),
                metadata={
                    "risk": plan.risk.value,
                    "whitenight_session_id": session_id,
                    "channel": channel_context.channel,
                    "channel_target": channel_context.target,
                    "image_data_url": image_data_url,
                },
            ):
                task_id = event.task_id
                yield ChatEvent(
                    type="task",
                    session_id=session_id,
                    extra={"delegate_event": event.model_dump()},
                )
                if event.type == "result":
                    result_text = event.detail
                elif event.type == "error":
                    last_error = event.detail
        except Exception as exc:  # 委派层异常同样不破坏主会话
            logger.exception("委派执行异常 session=%s", session_id)
            last_error = f"{exc}"

        if result_text:
            reply = (
                f"已委派 {plan.executor.value} 完成，以下是执行结果（技术内容保持原样）：\n\n"
                f"{result_text}"
            )
        else:
            reply = (
                f"已尝试委派 {plan.executor.value}，但任务没有完成："
                f"{last_error or '未知错误'}。这次失败不会影响会话，可以稍后重试。"
            )
        message = self._persist_assistant(session_id, reply)
        yield ChatEvent(
            type="done",
            session_id=session_id,
            message_id=message.id,
            text=reply,
            extra={"task_id": task_id},
        )

    def _persist_assistant(self, session_id: str, reply: str) -> MessageRecord:
        message = self._store.add_message(
            session_id=session_id,
            role="assistant",
            content=reply,
            kind="text",
        )
        if self._memory is not None:
            task = asyncio.create_task(self._extract_later(session_id))
            self._extract_task = task
            self._background_tasks.add(task)
            task.add_done_callback(self._on_extract_done)
        return message

    def _cancel_pending_extraction(self) -> None:
        """取消延迟中或执行中的记忆提取；正在跑的 Provider 流会被一并中断。"""
        task = self._extract_task
        if task is not None and not task.done():
            task.cancel()
            logger.info("新消息到达，取消后台记忆提取，释放推理槽")

    def _on_extract_done(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.discard(task)
        if self._extract_task is task:
            self._extract_task = None

    async def _extract_later(self, session_id: str) -> None:
        """回复后延迟提取：给连续聊天留出窗口，期间新消息会取消本任务。"""
        try:
            await asyncio.sleep(self._extract_delay_s)
            await self._extract_memories(session_id)
        except asyncio.CancelledError:
            pass  # 正常取消路径：新消息优先使用推理槽

    async def _extract_memories(self, session_id: str) -> None:
        """主回复后的异步记忆提取；失败只记日志，不影响会话。"""
        assert self._memory is not None
        try:
            history = self._store.list_messages(session_id)
            await self._memory.extract_and_store(history, session_id)
        except Exception:
            logger.exception("异步记忆提取失败 session=%s", session_id)


class DummyProvider:
    """测试与离线开发用 Provider：绝不虚构内容，只回显固定文本。"""

    def __init__(self, reply: str = "收到，主人。") -> None:
        self.reply = reply

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        del messages, tools
        for char in self.reply:
            yield ModelChunk(delta=char)
        yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"provider": "dummy", "ok": True}


def create_chat_service(
    store: SessionStore,
    provider: ModelProvider | None,
    settings: Settings,
    memory_service: MemoryService | None = None,
    router: RoutingEngine | None = None,
    delegate_manager: DelegateManager | None = None,
    proactive_service: ProactiveService | None = None,
    tool_registry: ToolRegistry | None = None,
    tool_executor: ToolExecutor | None = None,
    approvals: ApprovalService | None = None,
    pending_tools: PendingToolStore | None = None,
    policy: PolicyEngine | None = None,
    file_delivery: FileDeliveryProvider | None = None,
) -> ChatService:
    """Provider 未配置或测试注入时降级为 DummyProvider（开发环境显式选择）。"""
    return ChatService(
        store,
        provider or DummyProvider(),
        settings,
        memory_service,
        router,
        delegate_manager,
        proactive_service,
        tool_registry,
        tool_executor,
        approvals,
        pending_tools,
        policy,
        file_delivery,
    )
