"""Agent 循环：会话持久化 → 上下文装配 → 模型流式 → 落库 → 事件发布。

事实保真策略：模型输出原样透传，不做人设改写；人格由 SOUL.md 约束。
主回复完成后异步提取长期记忆（阶段 4）；Hermes/Codex 委派与路由在阶段 5 接入。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from whitenight.agent.context import build_provider_messages, load_soul
from whitenight.channels.types import ChatEvent, ChatRequest, MessageKind
from whitenight.config import Settings
from whitenight.memory.service import MemoryService
from whitenight.models.base import ModelChunk, ModelProvider, ProviderMessage
from whitenight.storage.attachments import save_image_data_url
from whitenight.storage.sessions import SessionNotFoundError, SessionStore

logger = logging.getLogger(__name__)


class ChatService:
    """最小纵向链路：Web/未来渠道 → Agent → Ollama → 回复落库。"""

    def __init__(
        self,
        store: SessionStore,
        provider: ModelProvider,
        settings: Settings,
        memory_service: MemoryService | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._settings = settings
        self._memory = memory_service
        self._background_tasks: set[asyncio.Task[None]] = set()

    @property
    def provider(self) -> ModelProvider:
        return self._provider

    async def stream_reply(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
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
        yield ChatEvent(type="start", session_id=session_id)

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

        assistant_message = self._store.add_message(
            session_id=session_id,
            role="assistant",
            content=reply,
            kind="text",
        )
        if self._memory is not None:
            task = asyncio.create_task(self._extract_memories(session_id))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        yield ChatEvent(
            type="done",
            session_id=session_id,
            message_id=assistant_message.id,
            text=reply,
            extra={"user_message_id": user_message.id},
        )

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

    async def stream_chat(self, messages: list[ProviderMessage]) -> AsyncIterator[ModelChunk]:
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
) -> ChatService:
    """Provider 未配置或测试注入时降级为 DummyProvider（开发环境显式选择）。"""
    return ChatService(store, provider or DummyProvider(), settings, memory_service)
