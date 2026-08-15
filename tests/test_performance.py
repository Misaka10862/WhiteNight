"""性能冒烟（确定性、宽松阈值，避免 CI 抖动）。"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from sqlalchemy import Engine

from whitenight.agent.context import build_provider_messages
from whitenight.channels.types import MessageRecord
from whitenight.memory.store import MemoryStore
from whitenight.memory.types import FactUpsert
from whitenight.routing.engine import RoutingEngine
from whitenight.routing.rules import RuleRouter
from whitenight.storage.sessions import SessionStore


def test_session_store_100_messages(engine: Engine) -> None:
    store = SessionStore(engine)
    session = store.create_session()
    started = time.perf_counter()
    for index in range(100):
        store.add_message(session.id, "user" if index % 2 == 0 else "assistant", f"消息 {index}")
    messages = store.list_messages(session.id)
    elapsed = time.perf_counter() - started
    assert len(messages) == 100
    assert elapsed < 2.0


def test_context_budget_200_messages() -> None:
    now = datetime.now(UTC)
    history = [
        MessageRecord(
            id=str(index),
            session_id="s",
            sequence=index,
            role="user" if index % 2 == 0 else "assistant",
            content=f"第 {index} 条历史消息，内容足够长但仍在预算内",
            created_at=now,
        )
        for index in range(200)
    ]
    started = time.perf_counter()
    messages = build_provider_messages(history, "人格", 12_000, now=now)
    elapsed = time.perf_counter() - started
    assert messages[0].role == "system"
    assert elapsed < 0.2


def test_fts_search_200_facts(engine: Engine) -> None:
    store = MemoryStore(engine)
    for index in range(200):
        store.upsert_fact(FactUpsert(key=f"键{index}", value=f"值{index}"))
    started = time.perf_counter()
    hits = store.search_facts("值199", limit=5)
    elapsed = time.perf_counter() - started
    assert hits and hits[0].value == "值199"
    assert elapsed < 1.0


def test_golden_routing_fast() -> None:
    router = RoutingEngine(rule_router=RuleRouter(), allow_llm_fallback=False)

    async def run() -> None:
        started = time.perf_counter()
        for text in ["帮我写个排序函数", "打开 Safari", "还记得我喜欢什么吗", "我爱你"] * 25:
            await router.route(text)
        elapsed = time.perf_counter() - started
        assert elapsed < 0.5

    asyncio.run(run())
