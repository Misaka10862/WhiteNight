"""记忆提取的并发策略测试：聊天优先于后台提取，且提取输出限长。"""

from __future__ import annotations

import asyncio

from sqlalchemy import Engine

from whitenight.agent.service import DummyProvider
from whitenight.api.app import _build_memory_extractor
from whitenight.config import Settings
from whitenight.memory import (
    MemoryService,
    MemoryStore,
    NullEmbeddingProvider,
    OllamaMemoryExtractor,
)
from whitenight.memory.extraction import RuleBasedMemoryExtractor
from whitenight.memory.maintenance import MemoryMaintenance
from whitenight.models.ollama import OllamaProvider
from whitenight.storage.sessions import SessionStore


class RecordingExtractor:
    """Record provider cancellation without replacing the durable memory service."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def extract(self, messages):
        del messages
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
    other = store.create_session(title="另一个会话")
    store.add_message(session.id, "user", "我喜欢抹茶")
    store.add_message(other.id, "user", "我住在杭州")
    extractor = RecordingExtractor()
    memory_store = MemoryStore(engine)
    memory = MemoryService(memory_store, extractor, NullEmbeddingProvider())
    maintenance = MemoryMaintenance(memory, store, DummyProvider(), delay_s=0)

    async def run() -> None:
        maintenance.enqueue(session.id)
        maintenance.enqueue(other.id)
        maintenance.start()
        await asyncio.wait_for(extractor.started.wait(), timeout=1.0)
        maintenance.begin_chat()
        await asyncio.wait_for(extractor.cancelled.wait(), timeout=1.0)
        assert len(memory_store.pending_maintenance(due_only=False)) == 2
        assert memory_store.get_extraction_checkpoint(session.id) == 0
        await maintenance.close()

        # A new service instance recovers both sessions without another user message.
        recovered = MemoryMaintenance(
            MemoryService(memory_store, RuleBasedMemoryExtractor(), NullEmbeddingProvider()),
            store,
            DummyProvider(),
            delay_s=0,
        )
        assert await recovered.run_once() == 1
        assert await recovered.run_once() == 1
        assert memory_store.pending_maintenance(due_only=False) == []
        assert memory_store.get_extraction_checkpoint(session.id) == 1
        assert memory_store.get_extraction_checkpoint(other.id) == 1
        assert {fact.value for fact in memory_store.list_facts()} == {"抹茶", "杭州"}
        await recovered.close()

    asyncio.run(run())
