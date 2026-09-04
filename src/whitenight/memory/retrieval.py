"""混合召回：FTS5 词法 + 嵌入语义 + 时间衰减 + 访问加成。

阶段 4 检索顺序（与构建计划 10.3 一致）：
近期原文 → 滚动摘要 → 结构化档案 → 混合检索命中的情景记忆 → 任务历史。
本模块负责后两层候选；上下文组装在 agent/context 阶段 4 接入。
"""

from __future__ import annotations

import hashlib
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

    def retrieve(
        self,
        query: str,
        limit: int = 8,
        character_id: str | None = None,
        *,
        include_semantic: bool = True,
    ) -> list[MemoryHit]:
        if not query.strip() or limit <= 0:
            return []
        facts = self._store.search_facts(query, limit=limit, character_id=character_id)
        episodes = self._store.search_episodes(query, limit=limit, character_id=character_id)
        lexical_ids = {item.id for item in facts} | {item.id for item in episodes}
        # Semantic retrieval has its own candidate set. Scope and deletion/conflict
        # filtering happen before embedding, so a cache cannot resurrect hidden data.
        if include_semantic:
            facts = [
                fact
                for fact in self._store.list_facts(character_id=character_id)
                if fact.conflict_state != "conflicted"
            ]
            episodes = self._store.list_episodes(character_id=character_id)
        documents = [(fact.id, "fact", f"{fact.key}：{fact.value}") for fact in facts]
        documents.extend((episode.id, "episode", episode.content) for episode in episodes)
        semantic_scores = self._semantic_scores(query, documents) if include_semantic else {}
        episode_by_id = {episode.id: episode for episode in episodes}
        hits: list[MemoryHit] = []
        for item_id, item_type, content in documents:
            semantic = semantic_scores.get(item_id)
            lexical = 1.0 if item_id in lexical_ids else 0.0
            if not lexical and (semantic is None or semantic < 0.35):
                continue
            score = self._lexical_weight * lexical
            if semantic is not None:
                score += self._semantic_weight * semantic
            if item_type == "episode":
                episode = episode_by_id.get(item_id)
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

        hits.sort(key=lambda hit: (-hit.score, hit.item_id))
        result = hits[:limit]
        for hit in result:
            if hit.item_type == "episode":
                self._store.touch_episode(hit.item_id)
        return result

    def _semantic_scores(
        self, query: str, documents: list[tuple[str, str, str]]
    ) -> dict[str, float]:
        identity = getattr(self._embeddings, "cache_identity", None)
        try:
            model_identity = (
                str(identity())
                if callable(identity)
                else "|".join(
                    str(value)
                    for value in (
                        type(self._embeddings).__module__,
                        type(self._embeddings).__qualname__,
                        getattr(self._embeddings, "base_url", ""),
                        getattr(self._embeddings, "model", ""),
                        getattr(self._embeddings, "model_version", ""),
                    )
                )
            )
            model_key = hashlib.sha256(model_identity.encode()).hexdigest()
            hashes = [hashlib.sha256(content.encode()).hexdigest() for _, _, content in documents]
            keys = [hashlib.sha256(f"{model_key}:{value}".encode()).hexdigest() for value in hashes]
            cached = self._store.cached_vectors(keys)
            missing = [index for index, key in enumerate(keys) if key not in cached]
            # Query and missing documents are sent in bounded batches; document
            # vectors survive process restarts and are keyed by model/content versions.
            texts = [query] + [documents[index][2] for index in missing]
            vectors: list[list[float]] = []
            for offset in range(0, len(texts), 32):
                batch = self._embeddings.embed(texts[offset : offset + 32])
                if len(batch) != len(texts[offset : offset + 32]):
                    return {}
                vectors.extend(batch)
            if not vectors or not self._valid_vector(vectors[0]):
                return {}
            query_vector = vectors[0]
            for index, vector in zip(missing, vectors[1:], strict=True):
                if self._valid_vector(vector) and len(vector) == len(query_vector):
                    cached[keys[index]] = vector
                    self._store.cache_vector(keys[index], model_key, hashes[index], vector)
            return {
                document[0]: _cosine(query_vector, cached[key])
                for document, key in zip(documents, keys, strict=True)
                if key in cached and len(cached[key]) == len(query_vector)
            }
        except Exception:
            # An unavailable embedding provider never prevents lexical recall.
            return {}

    @staticmethod
    def _valid_vector(vector: list[float]) -> bool:
        return bool(vector) and all(
            isinstance(value, (int, float)) and math.isfinite(value) for value in vector
        )
