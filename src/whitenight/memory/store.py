"""长期记忆持久化：结构化档案、情景记忆、滚动摘要与 FTS5 检索。"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session as OrmSession

from whitenight.memory.types import (
    EpisodeCreate,
    EpisodeRecord,
    FactCandidate,
    FactRecord,
    FactUpsert,
)
from whitenight.storage.models import (
    EpisodicMemory,
    ProfileFact,
    SessionSummaryRecord,
)


class MemoryNotFoundError(KeyError):
    """记忆条目不存在。"""


def _now() -> datetime:
    return datetime.now(UTC)


def _load_ids(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _dump_ids(ids: list[str]) -> str:
    return json.dumps(ids, ensure_ascii=False)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


class MemoryStore:
    """三层记忆的仓储；FTS 由迁移 0004 的触发器维护。"""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def _orm(self) -> OrmSession:
        return OrmSession(self._engine, expire_on_commit=False)

    # ---- 结构化档案 ----------------------------------------------------

    def list_facts(self, include_deleted: bool = False) -> list[FactRecord]:
        with self._orm() as orm:
            rows = orm.query(ProfileFact).order_by(ProfileFact.updated_at.desc()).all()
            records = [self._fact_record(row) for row in rows]
        if include_deleted:
            return records
        # 默认只返回 active：superseded/deleted 旧值绝不被检索或展示。
        return [record for record in records if record.status == "active"]

    def get_fact(self, fact_id: str) -> FactRecord:
        with self._orm() as orm:
            fact = orm.get(ProfileFact, fact_id)
            if fact is None:
                raise MemoryNotFoundError(fact_id)
            return self._fact_record(fact)

    def upsert_fact(self, candidate: FactUpsert | FactCandidate) -> FactRecord:
        key = _normalize(candidate.key)
        value = _normalize(candidate.value)
        with self._orm() as orm:
            existing = (
                orm.query(ProfileFact)
                .filter(ProfileFact.key == key, ProfileFact.status == "active")
                .all()
            )
            matching = [fact for fact in existing if _normalize(fact.value) == value]
            now = _now()

            if not existing:
                fact = ProfileFact(
                    key=key,
                    value=value,
                    confidence=candidate.confidence,
                    source_message_ids=_dump_ids(candidate.source_message_ids),
                    status="active",
                    conflict_state="none",
                )
                orm.add(fact)
                orm.commit()
                return self._fact_record(fact)

            if matching:
                winner = matching[0]
                winner.confidence = max(winner.confidence, candidate.confidence)
                winner.source_message_ids = _dump_ids(
                    sorted(set(_load_ids(winner.source_message_ids) + candidate.source_message_ids))
                )
                winner.conflict_state = "none"
                winner.updated_at = now
                for other in existing:
                    if other.id != winner.id:
                        other.status = "superseded"
                        other.superseded_by = winner.id
                        other.conflict_state = "resolved"
                orm.commit()
                return self._fact_record(winner)

            # 值不同：冲突。重复确认某个值会自动解决冲突（上方分支）。
            for fact in existing:
                fact.conflict_state = "conflicted"
                fact.updated_at = now
            fact = ProfileFact(
                key=key,
                value=value,
                confidence=candidate.confidence,
                source_message_ids=_dump_ids(candidate.source_message_ids),
                status="active",
                conflict_state="conflicted",
            )
            orm.add(fact)
            orm.commit()
            return self._fact_record(fact)

    def update_fact(self, fact_id: str, value: str, confidence: float | None = None) -> FactRecord:
        """编辑：旧值立即失效（superseded），新值成为唯一 active。"""
        value = _normalize(value)
        with self._orm() as orm:
            old = orm.get(ProfileFact, fact_id)
            if old is None or old.status == "deleted":
                raise MemoryNotFoundError(fact_id)
            new = ProfileFact(
                key=old.key,
                value=value,
                confidence=old.confidence if confidence is None else confidence,
                source_message_ids=old.source_message_ids,
                status="active",
                conflict_state="resolved",
            )
            orm.add(new)
            orm.flush()
            old.status = "superseded"
            old.superseded_by = new.id
            old.conflict_state = "resolved"
            orm.commit()
            return self._fact_record(new)

    def delete_fact(self, fact_id: str) -> None:
        with self._orm() as orm:
            fact = orm.get(ProfileFact, fact_id)
            if fact is None:
                raise MemoryNotFoundError(fact_id)
            fact.status = "deleted"
            fact.conflict_state = "resolved"
            fact.updated_at = _now()
            orm.commit()

    def resolve_fact_conflict(self, fact_id: str, keep: bool) -> FactRecord | None:
        """解决冲突：保留 winner，其余 active 同 key 条目全部失效。"""
        with self._orm() as orm:
            winner = orm.get(ProfileFact, fact_id)
            if winner is None:
                raise MemoryNotFoundError(fact_id)
            others = (
                orm.query(ProfileFact)
                .filter(
                    ProfileFact.key == winner.key,
                    ProfileFact.status == "active",
                    ProfileFact.id != winner.id,
                )
                .all()
            )
            if keep:
                winner.conflict_state = "resolved"
                winner.status = "active"
                for other in others:
                    other.status = "superseded"
                    other.superseded_by = winner.id
                    other.conflict_state = "resolved"
                orm.commit()
                return self._fact_record(winner)
            winner.status = "superseded"
            winner.conflict_state = "resolved"
            winner.superseded_by = None
            orm.commit()
            return None

    def search_facts(self, query: str, limit: int = 10) -> list[FactRecord]:
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", query, re.UNICODE)
        if not tokens:
            return []
        fts_query = " OR ".join(f'"{token}"' for token in tokens)
        with self._orm() as orm:
            try:
                fact_ids = orm.scalars(
                    text(
                        "SELECT id FROM profile_facts_fts "
                        "WHERE profile_facts_fts MATCH :q ORDER BY rank LIMIT :limit"
                    ),
                    {"q": fts_query, "limit": limit},
                ).all()
            except Exception:  # FTS 语法/环境异常回退 LIKE
                fact_ids = []
            facts: list[ProfileFact] = []
            for fact_id in fact_ids:
                fact = orm.get(ProfileFact, fact_id)
                if fact and fact.status == "active":
                    facts.append(fact)
            if len(facts) < limit:
                like = f"%{query}%"
                rows = (
                    orm.query(ProfileFact)
                    .filter(
                        ProfileFact.status == "active",
                        (ProfileFact.key.like(like)) | (ProfileFact.value.like(like)),
                    )
                    .limit(limit - len(facts))
                    .all()
                )
                seen = {fact.id for fact in facts}
                facts.extend(fact for fact in rows if fact.id not in seen)
            return [self._fact_record(fact) for fact in facts[:limit]]

    # ---- 情景记忆 ------------------------------------------------------

    def add_episode(self, candidate: EpisodeCreate) -> EpisodeRecord:
        with self._orm() as orm:
            episode = EpisodicMemory(
                content=_normalize(candidate.content),
                source_message_ids=_dump_ids(candidate.source_message_ids),
                confidence=candidate.confidence,
                importance=candidate.importance,
            )
            orm.add(episode)
            orm.commit()
            return self._episode_record(episode)

    def list_episodes(self, include_deleted: bool = False) -> list[EpisodeRecord]:
        with self._orm() as orm:
            rows = orm.query(EpisodicMemory).order_by(EpisodicMemory.created_at.desc()).all()
            records = [self._episode_record(row) for row in rows]
        if include_deleted:
            return records
        return [record for record in records if record.deleted_at is None]

    def get_episode(self, episode_id: str) -> EpisodeRecord:
        with self._orm() as orm:
            episode = orm.get(EpisodicMemory, episode_id)
            if episode is None or episode.deleted_at is not None:
                raise MemoryNotFoundError(episode_id)
            return self._episode_record(episode)

    def delete_episode(self, episode_id: str) -> None:
        with self._orm() as orm:
            episode = orm.get(EpisodicMemory, episode_id)
            if episode is None:
                raise MemoryNotFoundError(episode_id)
            episode.deleted_at = _now()
            episode.updated_at = _now()
            orm.commit()

    def touch_episode(self, episode_id: str) -> None:
        with self._orm() as orm:
            episode = orm.get(EpisodicMemory, episode_id)
            if episode is not None:
                episode.access_count += 1
                episode.last_accessed_at = _now()
                orm.commit()

    def search_episodes(self, query: str, limit: int = 10) -> list[EpisodeRecord]:
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", query, re.UNICODE)
        if not tokens:
            return []
        fts_query = " OR ".join(f'"{token}"' for token in tokens)
        with self._orm() as orm:
            try:
                episode_ids = orm.scalars(
                    text(
                        "SELECT id FROM episodic_memories_fts "
                        "WHERE episodic_memories_fts MATCH :q ORDER BY rank LIMIT :limit"
                    ),
                    {"q": fts_query, "limit": limit},
                ).all()
            except Exception:
                episode_ids = []
            episodes: list[EpisodicMemory] = []
            for episode_id in episode_ids:
                episode = orm.get(EpisodicMemory, episode_id)
                if episode and episode.deleted_at is None:
                    episodes.append(episode)
            if len(episodes) < limit:
                like = f"%{query}%"
                rows = (
                    orm.query(EpisodicMemory)
                    .filter(
                        EpisodicMemory.deleted_at.is_(None),
                        EpisodicMemory.content.like(like),
                    )
                    .limit(limit - len(episodes))
                    .all()
                )
                seen = {episode.id for episode in episodes}
                episodes.extend(episode for episode in rows if episode.id not in seen)
            return [self._episode_record(episode) for episode in episodes[:limit]]

    # ---- 滚动摘要 ------------------------------------------------------

    def set_session_summary(
        self, session_id: str, summary: str, start_sequence: int, end_sequence: int
    ) -> None:
        with self._orm() as orm:
            orm.query(SessionSummaryRecord).filter(
                SessionSummaryRecord.session_id == session_id
            ).delete()
            orm.add(
                SessionSummaryRecord(
                    session_id=session_id,
                    summary=summary,
                    start_sequence=start_sequence,
                    end_sequence=end_sequence,
                )
            )
            orm.commit()

    def get_session_summary(self, session_id: str) -> str | None:
        with self._orm() as orm:
            record = (
                orm.query(SessionSummaryRecord)
                .filter(SessionSummaryRecord.session_id == session_id)
                .order_by(SessionSummaryRecord.created_at.desc())
                .first()
            )
            return record.summary if record else None

    # ---- helpers -------------------------------------------------------

    def _fact_record(self, fact: ProfileFact) -> FactRecord:
        return FactRecord(
            id=fact.id,
            key=fact.key,
            value=fact.value,
            confidence=fact.confidence,
            source_message_ids=_load_ids(fact.source_message_ids),
            status=fact.status,  # type: ignore[arg-type]
            conflict_state=fact.conflict_state,  # type: ignore[arg-type]
            created_at=fact.created_at,
            updated_at=fact.updated_at,
        )

    def _episode_record(self, episode: EpisodicMemory) -> EpisodeRecord:
        return EpisodeRecord(
            id=episode.id,
            content=episode.content,
            confidence=episode.confidence,
            importance=episode.importance,
            source_message_ids=_load_ids(episode.source_message_ids),
            access_count=episode.access_count,
            created_at=episode.created_at,
            updated_at=episode.updated_at,
            deleted_at=episode.deleted_at,
        )
