"""Regression evidence for deterministic retrieval and maintenance gaps."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine

from whitenight.channels.types import MessageRecord
from whitenight.memory.embeddings import NullEmbeddingProvider
from whitenight.memory.extraction import NullMemoryExtractor, OllamaMemoryExtractor
from whitenight.memory.retrieval import HybridMemoryRetriever
from whitenight.memory.service import MemoryMaintenanceError, MemoryService
from whitenight.memory.store import MemoryStore
from whitenight.memory.types import ExtractionResult, FactCandidate, FactUpsert
from whitenight.models.base import ModelChunk


class RecordingEmbedding:
    model = "synthetic-v1"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.extend(texts)
        return [[1.0, 0.0] for _ in texts]


def _message(sequence: int, content: str = "ordinary") -> MessageRecord:
    return MessageRecord(
        id=f"m{sequence}",
        session_id="s1",
        sequence=sequence,
        role="user",
        content=content,
        created_at=datetime.now(UTC),
    )


def test_semantic_candidates_do_not_require_lexical_overlap(engine: Engine) -> None:
    store = MemoryStore(engine)
    wanted = store.upsert_fact(FactUpsert(key="喜好", value="抹茶冰淇淋", character_id="a"))
    store.upsert_fact(FactUpsert(key="喜好", value="secret-other-character", character_id="b"))
    hits = HybridMemoryRetriever(store, RecordingEmbedding()).retrieve(
        "我最爱的甜品是什么", character_id="a"
    )
    assert [hit.item_id for hit in hits] == [wanted.id]
    assert hits[0].lexical_score == 0


def test_document_vectors_survive_retriever_restart_and_invalidate(engine: Engine) -> None:
    store = MemoryStore(engine)
    fact = store.upsert_fact(FactUpsert(key="dessert", value="matcha"))
    embeddings = RecordingEmbedding()
    HybridMemoryRetriever(store, embeddings).retrieve("dessert")
    HybridMemoryRetriever(MemoryStore(engine), embeddings).retrieve("dessert")
    assert embeddings.calls.count("dessert：matcha") == 1
    store.update_fact(fact.id, "chocolate", None)
    HybridMemoryRetriever(store, embeddings).retrieve("dessert")
    assert embeddings.calls.count("dessert：chocolate") == 1
    embeddings.model = "synthetic-v2"
    HybridMemoryRetriever(store, embeddings).retrieve("dessert")
    assert embeddings.calls.count("dessert：chocolate") == 2


def test_summary_merges_prior_summary_and_all_new_messages(engine: Engine) -> None:
    store = MemoryStore(engine)
    store.set_session_summary("s1", "EARLY_PROMISE", 1, 10)
    requests: list[str] = []

    class Provider:
        async def stream_chat(self, messages, tools=None):
            requests.append("\n".join(message.content for message in messages))
            yield ModelChunk(delta="EARLY_PROMISE retained", done=True)

    service = MemoryService(store, NullMemoryExtractor(), NullEmbeddingProvider())
    history = [_message(i, f"NEW_{i}") for i in range(1, 61)]
    asyncio.run(service.summarize_session(history, "s1", Provider()))
    assert "EARLY_PROMISE" in requests[0]
    assert "NEW_11" in requests[0]
    assert any("NEW_60" in request for request in requests)
    assert not any("NEW_1\n" in request for request in requests)
    before = len(requests)
    asyncio.run(service.summarize_session(history, "s1", Provider()))
    assert len(requests) == before


def test_async_retrieval_does_not_block_event_loop(engine: Engine) -> None:
    entered, release = threading.Event(), threading.Event()

    class SlowEmbedding(RecordingEmbedding):
        def embed(self, texts):
            entered.set()
            assert release.wait(2)
            return super().embed(texts)

    service = MemoryService(MemoryStore(engine), NullMemoryExtractor(), SlowEmbedding())

    async def run() -> None:
        pending = asyncio.create_task(service.aretrieve("synthetic"))
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        assert not pending.done()
        release.set()
        await pending

    asyncio.run(run())


def test_extraction_processes_every_uncovered_batch_and_retries_failure(engine: Engine) -> None:
    batches: list[list[int]] = []

    class Extractor:
        fail_second = True

        async def extract(self, messages):
            batches.append([message.sequence for message in messages])
            if messages[0].sequence == 21 and self.fail_second:
                self.fail_second = False
                return ExtractionResult(succeeded=False)
            return ExtractionResult()

    store = MemoryStore(engine)
    service = MemoryService(store, Extractor(), NullEmbeddingProvider())
    messages = [_message(i) for i in range(1, 46)]
    with pytest.raises(MemoryMaintenanceError):
        asyncio.run(service.extract_and_store(messages, "s1"))
    assert store.get_extraction_checkpoint("s1") == 20
    asyncio.run(service.extract_and_store(messages, "s1"))
    assert batches == [
        list(range(1, 21)),
        list(range(21, 41)),
        list(range(21, 41)),
        list(range(41, 46)),
    ]
    assert store.get_extraction_checkpoint("s1") == 45


def test_extraction_rejects_fabricated_sources_without_checkpoint(engine: Engine) -> None:
    class Extractor:
        async def extract(self, messages):
            return ExtractionResult(
                facts=[
                    FactCandidate(
                        key="invented", value="never stored", source_message_ids=["not-in-batch"]
                    )
                ]
            )

    store = MemoryStore(engine)
    service = MemoryService(store, Extractor(), NullEmbeddingProvider())
    with pytest.raises(MemoryMaintenanceError):
        asyncio.run(service.extract_and_store([_message(1)], "s1"))
    assert store.list_facts() == []
    assert store.get_extraction_checkpoint("s1") == 0


def test_incomplete_extraction_and_summary_keep_retryable_state(engine: Engine) -> None:
    class IncompleteProvider:
        async def stream_chat(self, messages, tools=None):
            yield ModelChunk(delta='{"facts":[],"episodes":[]}')

    store = MemoryStore(engine)
    store.set_session_summary("s1", "preserved", 1, 1)
    provider = IncompleteProvider()
    service = MemoryService(store, OllamaMemoryExtractor(provider), NullEmbeddingProvider())
    with pytest.raises(MemoryMaintenanceError):
        asyncio.run(service.extract_and_store([_message(2)], "s1"))
    with pytest.raises(MemoryMaintenanceError):
        asyncio.run(service.summarize_session([_message(2)], "s1", provider))
    assert store.get_extraction_checkpoint("s1") == 0
    assert store.summary_checkpoint("s1") == 1
    assert store.get_session_summary("s1") == "preserved"


def test_compiler_preview_never_invokes_embedding_provider(engine: Engine) -> None:
    from whitenight.personality.compiler import PromptCompiler
    from whitenight.personality.store import PersonalityStore
    from whitenight.personality.token_counter import UnavailableTokenCounter
    from whitenight.storage.sessions import SessionStore

    personalities = PersonalityStore(engine)
    session = SessionStore(engine).create_session()
    store = MemoryStore(engine)
    store.upsert_fact(FactUpsert(key="dessert", value="matcha", character_id=session.character_id))
    embeddings = RecordingEmbedding()
    compiler = PromptCompiler(
        personalities,
        MemoryService(store, NullMemoryExtractor(), embeddings),
        UnavailableTokenCounter(),
        32768,
        2048,
    )
    compiler.compile(session.id, [], "dessert", persist_trace=False)
    assert embeddings.calls == []
    messages, _, _ = asyncio.run(
        compiler.compile_async(session.id, [], "我最爱的甜品是什么", persist_trace=False)
    )
    assert embeddings.calls
    assert any("matcha" in message.content for message in messages)


def test_resolving_fact_conflict_cannot_supersede_other_character(engine: Engine) -> None:
    store = MemoryStore(engine)
    winner = store.upsert_fact(FactUpsert(key="dessert", value="matcha", character_id="a"))
    other = store.upsert_fact(FactUpsert(key="dessert", value="cake", character_id="b"))
    store.resolve_fact_conflict(winner.id, keep=True)
    assert store.get_fact(other.id).status == "active"


def test_maintenance_completion_does_not_erase_newer_work(engine: Engine) -> None:
    store = MemoryStore(engine)
    store.queue_maintenance("s1", 20)
    store.queue_maintenance("s1", 40)
    store.complete_maintenance("s1", 20)
    assert store.pending_maintenance() == [("s1", 40)]
    store.defer_maintenance("s1")
    assert store.pending_maintenance() == []
    assert store.pending_maintenance(due_only=False) == [("s1", 40)]
    # A lower sequence request cannot roll back pending coverage.
    store.queue_maintenance("s1", 10)
    assert store.pending_maintenance() == [("s1", 40)]
    store.complete_maintenance("s1", 40)
    assert store.pending_maintenance(due_only=False) == []


def test_deleted_memory_does_not_leave_cached_vectors(engine: Engine) -> None:
    from sqlalchemy import select

    from whitenight.memory.models import MemoryVector

    store = MemoryStore(engine)
    fact = store.upsert_fact(FactUpsert(key="dessert", value="matcha"))
    retriever = HybridMemoryRetriever(store, RecordingEmbedding())
    assert retriever.retrieve("dessert")
    with engine.connect() as connection:
        assert connection.execute(select(MemoryVector.cache_key)).all()
    store.delete_fact(fact.id)
    assert retriever.retrieve("dessert") == []
    with engine.connect() as connection:
        assert connection.execute(select(MemoryVector.cache_key)).all() == []
