"""长期记忆服务：提取、去重、冲突、检索、摘要与导出。"""

from __future__ import annotations

import json
import re

from whitenight.channels.types import MessageRecord
from whitenight.memory.embeddings import EmbeddingProvider
from whitenight.memory.extraction import MemoryExtractor
from whitenight.memory.retrieval import HybridMemoryRetriever
from whitenight.memory.store import MemoryStore
from whitenight.memory.types import (
    EpisodeCreate,
    EpisodeRecord,
    FactRecord,
    FactUpdate,
    FactUpsert,
    MemoryHit,
)
from whitenight.models.base import ModelProvider, ProviderMessage
from whitenight.policy.audit import AuditService


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


class MemoryService:
    """三层记忆的统一服务入口。"""

    def __init__(
        self,
        store: MemoryStore,
        extractor: MemoryExtractor,
        embedding_provider: EmbeddingProvider,
        audit: AuditService | None = None,
    ) -> None:
        self._store = store
        self._extractor = extractor
        self._audit = audit
        self.retriever = HybridMemoryRetriever(store, embedding_provider)

    # ---- 结构化档案 ----------------------------------------------------

    def list_facts(self, character_id: str | None = None) -> list[FactRecord]:
        return self._store.list_facts(character_id=character_id)

    def upsert_fact(self, payload: FactUpsert) -> FactRecord:
        return self._store.upsert_fact(payload)

    def update_fact(self, fact_id: str, payload: FactUpdate) -> FactRecord:
        return self._store.update_fact(fact_id, payload.value, payload.confidence)

    def delete_fact(self, fact_id: str) -> None:
        self._store.delete_fact(fact_id)
        if self._audit:
            self._audit.record(
                actor="user",
                action="memory.fact.deleted",
                decision="approved",
                tool_name="memory",
                params_summary=f"fact_id={fact_id}",
                result_summary="已删除（不含正文）",
            )

    def resolve_conflict(self, fact_id: str, keep: bool) -> FactRecord | None:
        return self._store.resolve_fact_conflict(fact_id, keep)

    # ---- 情景记忆 ------------------------------------------------------

    def add_episode(self, payload: EpisodeCreate) -> EpisodeRecord:
        return self._store.add_episode(payload)

    def list_episodes(self, character_id: str | None = None) -> list[EpisodeRecord]:
        return self._store.list_episodes(character_id=character_id)

    def delete_episode(self, episode_id: str) -> None:
        self._store.delete_episode(episode_id)
        if self._audit:
            self._audit.record(
                actor="user",
                action="memory.episode.deleted",
                decision="approved",
                tool_name="memory",
                params_summary=f"episode_id={episode_id}",
                result_summary="已删除（不含正文）",
            )

    # ---- 提取与召回 ----------------------------------------------------

    async def extract_and_store(
        self, messages: list[MessageRecord], session_id: str, character_id: str | None = None
    ) -> dict[str, int]:
        """主回复后异步调用：候选去重、冲突检测后写入。"""
        latest_sequence = max((message.sequence for message in messages), default=0)
        if latest_sequence <= self._store.get_extraction_checkpoint(session_id):
            return {"facts_added": 0, "episodes_added": 0}
        result = await self._extractor.extract(messages)
        facts_added = 0
        for candidate in result.facts:
            candidate.character_id = character_id
            existing = self._find_active_fact(candidate.key, character_id)
            stored = self._store.upsert_fact(candidate)
            if existing is None or existing.id != stored.id:
                facts_added += 1
        episodes_added = 0
        existing_episodes = {
            _normalize(item.content)
            for item in self._store.list_episodes(character_id=character_id)
        }
        for episode_candidate in result.episodes:
            normalized = _normalize(episode_candidate.content)
            if normalized and normalized not in existing_episodes:
                self._store.add_episode(
                    EpisodeCreate(
                        content=episode_candidate.content,
                        confidence=episode_candidate.confidence,
                        importance=episode_candidate.importance,
                        source_message_ids=episode_candidate.source_message_ids,
                        character_id=character_id,
                    )
                )
                existing_episodes.add(normalized)
                episodes_added += 1
        self._store.set_extraction_checkpoint(session_id, latest_sequence)
        return {"facts_added": facts_added, "episodes_added": episodes_added}

    def _find_active_fact(self, key: str, character_id: str | None = None) -> FactRecord | None:
        normalized_key = _normalize(key)
        for fact in self._store.list_facts(character_id=character_id):
            if _normalize(fact.key) == normalized_key and fact.status == "active":
                return fact
        return None

    def retrieve(
        self, query: str, limit: int = 8, character_id: str | None = None
    ) -> list[MemoryHit]:
        return self.retriever.retrieve(query, limit=limit, character_id=character_id)

    # ---- 滚动摘要 ------------------------------------------------------

    async def summarize_session(
        self,
        messages: list[MessageRecord],
        session_id: str,
        provider: ModelProvider | None = None,
    ) -> str | None:
        """把会话内容压缩为滚动摘要；provider 缺失时返回 None 不覆盖旧摘要。"""
        if not provider or not messages:
            return None
        transcript = "\n".join(f"[{message.role}] {message.content}" for message in messages[-40:])
        prompt = (
            "把以下对话压缩成 200 字以内的中文摘要，只保留人物、承诺、"
            "重要事件与未完成事项；不要输出摘要以外内容。\n\n" + transcript
        )
        parts: list[str] = []
        chunks = provider.stream_chat([ProviderMessage(role="user", content=prompt)])
        async for chunk in chunks:
            if chunk.delta:
                parts.append(chunk.delta)
            if chunk.done:
                break
        summary = "".join(parts).strip()
        if not summary:
            return None
        self._store.set_session_summary(
            session_id,
            summary,
            start_sequence=min(message.sequence for message in messages),
            end_sequence=max(message.sequence for message in messages),
        )
        return summary

    def get_session_summary(self, session_id: str) -> str | None:
        return self._store.get_session_summary(session_id)

    # ---- 导出 ----------------------------------------------------------

    def export(self, fmt: str = "jsonl") -> str:
        facts = self._store.list_facts(include_deleted=False)
        episodes = self._store.list_episodes(include_deleted=False)
        if fmt == "jsonl":
            lines: list[str] = []
            for fact in facts:
                lines.append(
                    json.dumps(
                        {
                            "type": "fact",
                            "id": fact.id,
                            "key": fact.key,
                            "value": fact.value,
                            "confidence": fact.confidence,
                            "source_message_ids": fact.source_message_ids,
                            "created_at": fact.created_at.isoformat(),
                        },
                        ensure_ascii=False,
                    )
                )
            for episode in episodes:
                lines.append(
                    json.dumps(
                        {
                            "type": "episode",
                            "id": episode.id,
                            "content": episode.content,
                            "confidence": episode.confidence,
                            "importance": episode.importance,
                            "source_message_ids": episode.source_message_ids,
                            "created_at": episode.created_at.isoformat(),
                        },
                        ensure_ascii=False,
                    )
                )
            return "\n".join(lines) + ("\n" if lines else "")
        if fmt == "markdown":
            parts = ["# WhiteNight 长期记忆导出", "", "## 结构化档案"]
            parts.extend(f"- **{fact.key}**：{fact.value}" for fact in facts)
            parts.extend(["", "## 情景记忆"])
            parts.extend(f"- {episode.content}" for episode in episodes)
            return "\n".join(parts) + "\n"
        raise ValueError(f"不支持的导出格式：{fmt}（支持 jsonl/markdown）")
