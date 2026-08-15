"""记忆提取、混合召回与服务层测试。"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import Engine

from whitenight.channels.types import MessageRecord
from whitenight.memory.embeddings import EmbeddingProvider, NullEmbeddingProvider
from whitenight.memory.extraction import OllamaMemoryExtractor, RuleBasedMemoryExtractor
from whitenight.memory.retrieval import HybridMemoryRetriever
from whitenight.memory.service import MemoryService
from whitenight.memory.store import MemoryStore
from whitenight.memory.types import EpisodeCreate, FactUpsert
from whitenight.models.base import ModelChunk


def _message(content: str) -> MessageRecord:
    return MessageRecord(
        id=f"m-{content[:4]}",
        session_id="s1",
        sequence=1,
        role="user",
        content=content,
        created_at=datetime(2026, 8, 15, tzinfo=UTC),
    )


def test_rule_extractor() -> None:
    result = asyncio.run(
        RuleBasedMemoryExtractor().extract(
            [
                _message("我是小明"),
                _message("我喜欢抹茶冰淇淋"),
                _message("今天是我们第一次见面，纪念一下"),
            ]
        )
    )
    assert any(fact.key == "称呼" and fact.value == "小明" for fact in result.facts)
    assert any(fact.key == "喜好" for fact in result.facts)
    assert any("第一次" in episode.content for episode in result.episodes)


class FakeJsonProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    async def stream_chat(self, messages: list[object]):
        del messages
        yield ModelChunk(delta=json.dumps(self.payload, ensure_ascii=False))
        yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"ok": True}


def test_ollama_extractor_parses_json() -> None:
    extractor = OllamaMemoryExtractor(
        FakeJsonProvider(
            {
                "facts": [
                    {
                        "key": "称呼",
                        "value": "主人",
                        "confidence": 0.9,
                        "source_message_ids": ["m1"],
                    }
                ],
                "episodes": [],
            }
        )
    )
    result = asyncio.run(extractor.extract([_message("我是主人")]))
    assert result.facts[0].value == "主人"


class FakeEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0 if text == "抹茶" else 0.0, 1.0 if "抹茶" in text else 0.0] for text in texts]


def test_hybrid_retrieval_lexical_and_semantic(engine: Engine) -> None:
    store = MemoryStore(engine)
    store.upsert_fact(FactUpsert(key="喜好", value="抹茶冰淇淋"))
    store.add_episode(EpisodeCreate(content="第一次一起吃抹茶冰淇淋"))

    lexical_only = HybridMemoryRetriever(store, NullEmbeddingProvider()).retrieve("抹茶")
    assert lexical_only
    assert all(hit.lexical_score == 1.0 for hit in lexical_only)

    hybrid = HybridMemoryRetriever(store, FakeEmbeddingProvider()).retrieve("抹茶")
    assert hybrid
    assert any(hit.semantic_score is not None for hit in hybrid)


def test_service_extract_dedup_and_delete_audit(engine: Engine) -> None:
    store = MemoryStore(engine)
    service = MemoryService(store, RuleBasedMemoryExtractor(), NullEmbeddingProvider())
    result = asyncio.run(service.extract_and_store([_message("我喜欢抹茶冰淇淋")], "s1"))
    assert result["facts_added"] == 1
    again = asyncio.run(service.extract_and_store([_message("我喜欢抹茶冰淇淋")], "s1"))
    assert again["facts_added"] == 0

    fact = service.list_facts()[0]
    service.delete_fact(fact.id)
    assert service.list_facts() == []
    assert service.retrieve("抹茶") == []


def test_export_formats(engine: Engine) -> None:
    store = MemoryStore(engine)
    store.upsert_fact(FactUpsert(key="称呼", value="主人"))
    store.add_episode(EpisodeCreate(content="一起看烟花"))
    service = MemoryService(store, RuleBasedMemoryExtractor(), NullEmbeddingProvider())
    jsonl = service.export("jsonl")
    markdown = service.export("markdown")
    assert '"type": "fact"' in jsonl
    assert '"type": "episode"' in jsonl
    assert "## 结构化档案" in markdown
    assert "一起看烟花" in markdown


def test_embedding_provider_protocol_fake() -> None:
    provider: EmbeddingProvider = FakeEmbeddingProvider()
    assert provider.embed(["抹茶"])[0][0] == 1.0
