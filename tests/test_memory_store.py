"""长期记忆仓储测试：去重、冲突、编辑失效、删除与 FTS 检索。"""

from __future__ import annotations

from sqlalchemy import Engine

from whitenight.memory.store import MemoryStore
from whitenight.memory.types import EpisodeCreate, FactUpsert


def test_fact_dedupe_same_value(engine: Engine) -> None:
    store = MemoryStore(engine)
    first = store.upsert_fact(FactUpsert(key="称呼", value="主人", confidence=0.5))
    second = store.upsert_fact(FactUpsert(key="称呼", value="主人", confidence=0.9))
    facts = store.list_facts()
    assert len(facts) == 1
    assert facts[0].id == first.id == second.id
    assert facts[0].confidence == 0.9


def test_fact_conflict_detection_and_repeat_resolution(engine: Engine) -> None:
    store = MemoryStore(engine)
    store.upsert_fact(FactUpsert(key="喜好", value="晴天", confidence=0.8))
    b = store.upsert_fact(FactUpsert(key="喜好", value="雨天", confidence=0.8))
    facts = store.list_facts()
    assert len(facts) == 2
    assert all(fact.conflict_state == "conflicted" for fact in facts)

    # 再次确认“雨天”应解决冲突，旧值失效
    winner = store.upsert_fact(FactUpsert(key="喜好", value="雨天", confidence=0.9))
    facts = store.list_facts()
    assert len(facts) == 1
    assert facts[0].id == winner.id
    assert facts[0].conflict_state == "none"
    assert b.id == winner.id or facts[0].value == "雨天"


def test_update_fact_old_value_never_used(engine: Engine) -> None:
    store = MemoryStore(engine)
    old = store.upsert_fact(FactUpsert(key="称呼", value="主人"))
    new = store.update_fact(old.id, "亲爱的")
    facts = store.list_facts()
    assert [fact.id for fact in facts] == [new.id]
    assert facts[0].value == "亲爱的"
    # 旧值已 superseded，不能通过 list_facts 被使用
    assert all(fact.value != "主人" for fact in facts)


def test_delete_fact_hides_it(engine: Engine) -> None:
    store = MemoryStore(engine)
    fact = store.upsert_fact(FactUpsert(key="生日", value="8月15日"))
    store.delete_fact(fact.id)
    assert store.list_facts() == []
    assert store.search_facts("8月15日") == []


def test_fts_search_returns_active_facts(engine: Engine) -> None:
    store = MemoryStore(engine)
    store.upsert_fact(FactUpsert(key="喜好", value="抹茶冰淇淋"))
    store.upsert_fact(FactUpsert(key="住处", value="杭州"))
    hits = store.search_facts("抹茶", limit=5)
    assert len(hits) == 1
    assert hits[0].value == "抹茶冰淇淋"


def test_episodes_and_summary(engine: Engine) -> None:
    store = MemoryStore(engine)
    episode = store.add_episode(
        EpisodeCreate(content="第一次一起看烟花", importance=0.9, source_message_ids=["m1"])
    )
    assert store.list_episodes()[0].id == episode.id
    assert store.search_episodes("烟花")[0].id == episode.id

    store.set_session_summary("s1", "主人提到喜欢雨天", 1, 6)
    assert store.get_session_summary("s1") == "主人提到喜欢雨天"

    store.delete_episode(episode.id)
    assert store.list_episodes() == []
    assert store.search_episodes("烟花") == []


def test_episode_dedup_in_service_uses_normalization(engine: Engine) -> None:
    store = MemoryStore(engine)
    store.add_episode(EpisodeCreate(content="一起看烟花"))
    store.add_episode(EpisodeCreate(content="  一起看烟花  "))
    assert len(store.list_episodes()) == 2  # 去重逻辑在 MemoryService 层
