"""混合召回：FTS5 词法 + 嵌入语义 + 时间衰减 + 访问加成。

阶段 4 检索顺序（与构建计划 10.3 一致）：
近期原文 → 滚动摘要 → 结构化档案 → 混合检索命中的情景记忆 → 任务历史。
本模块负责后两层候选；上下文组装在 agent/context 阶段 4 接入。
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from whitenight.memory.embeddings import EmbeddingProvider
from whitenight.memory.store import MemoryStore
from whitenight.memory.types import MemoryHit

_LEXICAL_WEIGHT = 0.6
_SEMANTIC_WEIGHT = 0.4
_DECAY_HALF_LIFE_DAYS = 30.0


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _time_decay(created_at: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    if created_at.tzinfo is None:
        now = now.replace(tzinfo=None)  # SQLite 返回 naive UTC
    else:
        now = now.astimezone(created_at.tzinfo)
    days = max(0.0, (now - created_at).total_seconds() / 86400.0)
    return float(0.5 ** (days / _DECAY_HALF_LIFE_DAYS))


class HybridMemoryRetriever:
    def __init__(
        self,
        store: MemoryStore,
        embedding_provider: EmbeddingProvider,
        lexical_weight: float = _LEXICAL_WEIGHT,
        semantic_weight: float = _SEMANTIC_WEIGHT,
    ) -> None:
        self._store = store
        self._embeddings = embedding_provider
        self._lexical_weight = lexical_weight
        self._semantic_weight = semantic_weight

    def retrieve(self, query: str, limit: int = 8) -> list[MemoryHit]:
        facts = self._store.search_facts(query, limit=limit)
        episodes = self._store.search_episodes(query, limit=limit)

        documents: list[tuple[str, str, str]] = [
            (fact.id, "fact", f"{fact.key}：{fact.value}") for fact in facts
        ] + [(episode.id, "episode", episode.content) for episode in episodes]

        query_vector = self._query_vector(query)
        hits: list[MemoryHit] = []
        for item_id, item_type, content in documents:
            semantic = None
            if query_vector:
                doc_vector = self._document_vector(content)
                if doc_vector:
                    semantic = _cosine(query_vector, doc_vector)
            lexical = 1.0
            score = self._lexical_weight * lexical
            if semantic is not None:
                score += self._semantic_weight * semantic
            if item_type == "episode":
                episode = next((item for item in episodes if item.id == item_id), None)
                if episode:
                    score *= _time_decay(episode.created_at)
                    score *= 1.0 + min(episode.access_count, 20) * 0.01
            hits.append(
                MemoryHit(
                    item_type=item_type,  # type: ignore[arg-type]
                    item_id=item_id,
                    content=content,
                    score=score,
                    lexical_score=lexical,
                    semantic_score=semantic,
                )
            )

        hits.sort(key=lambda hit: hit.score, reverse=True)
        result = hits[:limit]
        for hit in result:
            if hit.item_type == "episode":
                self._store.touch_episode(hit.item_id)
        return result

    def _query_vector(self, query: str) -> list[float] | None:
        vectors = self._embeddings.embed([query])
        return vectors[0] if vectors and vectors[0] else None

    def _document_vector(self, content: str) -> list[float] | None:
        vectors = self._embeddings.embed([content])
        return vectors[0] if vectors and vectors[0] else None
