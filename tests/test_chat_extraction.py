"""记忆提取的并发策略测试：聊天优先于后台提取，且提取输出限长。"""

from __future__ import annotations

import asyncio

from sqlalchemy import Engine

from whitenight.agent.service import ChatService, DummyProvider
from whitenight.api.app import _build_memory_extractor
from whitenight.channels.types import ChatRequest
from whitenight.config import Settings
from whitenight.memory import OllamaMemoryExtractor
from whitenight.models.ollama import OllamaProvider
from whitenight.storage.sessions import SessionStore


class RecordingMemory:
    """记录 extract_and_store 是否被新消息取消。"""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def extract_and_store(self, messages: list[object], session_id: str) -> None:
        del messages, session_id
        self.started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


def test_memory_extractor_uses_small_output_cap(settings: Settings) -> None:
    provider = OllamaProvider(base_url="http://contract.test", model="qwen3:8b")
    extractor = _build_memory_extractor(
        settings.model_copy(update={"memory_extractor": "ollama", "memory_extract_max_tokens": 77}),
        provider,
    )
    assert isinstance(extractor, OllamaMemoryExtractor)
    assert isinstance(extractor._provider, OllamaProvider)
    assert extractor._provider.max_output_tokens == 77


def test_new_message_cancels_running_extraction(engine: Engine, settings: Settings) -> None:
    store = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    session = store.create_session(title="聊天优先")
    memory = RecordingMemory()
    service = ChatService(store, DummyProvider("在的"), settings, memory_service=memory)  # type: ignore[arg-type]
    service._extract_delay_s = 0.0

    async def collect(text: str) -> None:
        async for _ in service.stream_reply(ChatRequest(session_id=session.id, text=text)):
            pass

    async def run() -> None:
        await collect("第一条")
        await asyncio.wait_for(memory.started.wait(), timeout=1.0)
        await collect("第二条")
        await asyncio.wait_for(memory.cancelled.wait(), timeout=1.0)
        assert memory.cancelled.is_set()

    asyncio.run(run())
