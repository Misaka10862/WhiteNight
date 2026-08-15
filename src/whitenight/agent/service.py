"""Agent 循环：会话持久化 → 上下文装配 → 模型流式 → 落库 → 事件发布。

事实保真策略：模型输出原样透传，不做人设改写；人格由 SOUL.md 约束。
主回复完成后异步提取长期记忆（阶段 4）；Hermes/Codex 委派与路由在阶段 5 接入。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

from whitenight.agent.context import build_provider_messages, load_soul
from whitenight.channels.types import ChatEvent, ChatRequest, MessageKind, MessageRecord
from whitenight.config import Settings
from whitenight.delegates.manager import DelegateManager
from whitenight.memory.service import MemoryService
from whitenight.models.base import ModelChunk, ModelProvider, ProviderMessage
from whitenight.routing.engine import RoutingEngine
from whitenight.routing.models import ExecutorChoice
from whitenight.scheduler.service import ProactiveService
from whitenight.storage.attachments import save_image_data_url
from whitenight.storage.sessions import SessionNotFoundError, SessionStore

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._store = store
        self._provider = provider
        self._settings = settings
        self._memory = memory_service
        self._router = router or RoutingEngine()
        self._delegates = delegate_manager
        self._proactive = proactive_service
        self._background_tasks: set[asyncio.Task[None]] = set()

    @property
    def provider(self) -> ModelProvider:
        return self._provider

    async def stream_reply(self, request: ChatRequest) -> AsyncGenerator[ChatEvent, None]:
        """处理一条用户消息并流式产生事件；完整回复才落库为 assistant 消息。"""
        session_id = request.session_id
        try:
            self._store.get_session(session_id)
        except SessionNotFoundError:
            yield ChatEvent(type="error", message=f"会话不存在：{session_id}")
            return

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

        plan = await self._router.route(request.text, has_image=image_path is not None)
        if (
            plan.executor in {ExecutorChoice.HERMES, ExecutorChoice.CODEX}
            and self._delegates is not None
        ):
            async for event in self._delegate_reply(session_id, request.text, plan):
                yield event
            return

        try:
            history = self._store.list_messages(session_id)
            messages = build_provider_messages(
                history,
                load_soul(self._settings.soul_file),
                self._settings.context_budget_chars,
            )
            text_parts: list[str] = []
            async for chunk in self._provider.stream_chat(messages):
                if chunk.delta:
                    text_parts.append(chunk.delta)
                    yield ChatEvent(type="chunk", delta=chunk.delta)
                if chunk.done:
                    break
        except Exception as exc:  # Provider/存储异常：不伪造回复，原样报告
            logger.exception("聊天流式生成失败 session=%s", session_id)
            yield ChatEvent(type="error", message=f"模型调用失败：{exc}")
            return

        reply = "".join(text_parts).strip()
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

    async def _delegate_reply(
        self, session_id: str, prompt: str, plan: object
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
            task = asyncio.create_task(self._extract_memories(session_id))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        return message

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
        self, messages: list[ProviderMessage]
    ) -> AsyncGenerator[ModelChunk, None]:
        del messages
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
    )
