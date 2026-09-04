"""长期记忆持久化：结构化档案、情景记忆、滚动摘要与 FTS5 检索。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, text
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session as OrmSession

from whitenight.memory.models import MemoryJob, MemoryVector
from whitenight.memory.types import (
    EpisodeCreate,
    EpisodeRecord,
    FactCandidate,
    FactRecord,
    FactUpsert,
)
from whitenight.storage.models import (
    EpisodicMemory,
    MemoryExtractionCheckpoint,
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

    def list_facts(
        self, include_deleted: bool = False, character_id: str | None = None
    ) -> list[FactRecord]:
        with self._orm() as orm:
            query = orm.query(ProfileFact)
            if character_id is not None:
                query = query.filter(ProfileFact.character_id == character_id)
            rows = query.order_by(ProfileFact.updated_at.desc()).all()
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
                .filter(
                    ProfileFact.key == key,
                    ProfileFact.status == "active",
                    ProfileFact.character_id == candidate.character_id,
                    ProfileFact.owner_namespace == candidate.owner_namespace,
                )
                .all()
            )
            matching = [fact for fact in existing if _normalize(fact.value) == value]
            now = _now()

            if not existing:
                fact = ProfileFact(
                    character_id=candidate.character_id,
                    owner_namespace=candidate.owner_namespace,
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
                character_id=candidate.character_id,
                owner_namespace=candidate.owner_namespace,
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
                character_id=old.character_id,
                owner_namespace=old.owner_namespace,
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
            self._discard_vector(orm, f"{old.key}：{old.value}")
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
            self._discard_vector(orm, f"{fact.key}：{fact.value}")
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
                    ProfileFact.character_id == winner.character_id,
                    ProfileFact.owner_namespace == winner.owner_namespace,
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

    def search_facts(
        self, query: str, limit: int = 10, character_id: str | None = None
    ) -> list[FactRecord]:
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", query, re.UNICODE)
        if not tokens:
            return []
        fts_query = " OR ".join(f'"{token}"' for token in tokens)
        with self._orm() as orm:
            try:
                fact_ids = orm.scalars(
                    text(
                        "SELECT f.id FROM profile_facts_fts "
                        "JOIN profile_facts f ON f.id = profile_facts_fts.id "
                        "WHERE profile_facts_fts MATCH :q AND f.status = 'active' "
                        "AND f.conflict_state != 'conflicted' "
                        "AND (:character_id IS NULL OR f.character_id = :character_id) "
                        "ORDER BY rank LIMIT :limit"
                    ),
                    {"q": fts_query, "limit": limit, "character_id": character_id},
                ).all()
            except Exception:  # FTS 语法/环境异常回退 LIKE
                fact_ids = []
            facts: list[ProfileFact] = []
            for fact_id in fact_ids:
                fact = orm.get(ProfileFact, fact_id)
                if (
                    fact
                    and fact.status == "active"
                    and fact.conflict_state != "conflicted"
                    and (character_id is None or fact.character_id == character_id)
                ):
                    facts.append(fact)
            if len(facts) < limit:
                like = f"%{query}%"
                rows = (
                    orm.query(ProfileFact)
                    .filter(
                        ProfileFact.status == "active",
                        ProfileFact.conflict_state != "conflicted",
                        *(
                            (ProfileFact.character_id == character_id,)
                            if character_id is not None
                            else ()
                        ),
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
                character_id=candidate.character_id,
                owner_namespace=candidate.owner_namespace,
                content=_normalize(candidate.content),
                source_message_ids=_dump_ids(candidate.source_message_ids),
                confidence=candidate.confidence,
                importance=candidate.importance,
            )
            orm.add(episode)
            orm.commit()
            return self._episode_record(episode)

    def list_episodes(
        self, include_deleted: bool = False, character_id: str | None = None
    ) -> list[EpisodeRecord]:
        with self._orm() as orm:
            query = orm.query(EpisodicMemory)
            if character_id is not None:
                query = query.filter(EpisodicMemory.character_id == character_id)
            rows = query.order_by(EpisodicMemory.created_at.desc()).all()
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
            self._discard_vector(orm, episode.content)
            orm.commit()

    def touch_episode(self, episode_id: str) -> None:
        with self._orm() as orm:
            episode = orm.get(EpisodicMemory, episode_id)
            if episode is not None:
                episode.access_count += 1
                episode.last_accessed_at = _now()
                orm.commit()

    def search_episodes(
        self, query: str, limit: int = 10, character_id: str | None = None
    ) -> list[EpisodeRecord]:
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", query, re.UNICODE)
        if not tokens:
            return []
        fts_query = " OR ".join(f'"{token}"' for token in tokens)
        with self._orm() as orm:
            try:
                episode_ids = orm.scalars(
                    text(
                        "SELECT e.id FROM episodic_memories_fts "
                        "JOIN episodic_memories e ON e.id = episodic_memories_fts.id "
                        "WHERE episodic_memories_fts MATCH :q AND e.deleted_at IS NULL "
                        "AND (:character_id IS NULL OR e.character_id = :character_id) "
                        "ORDER BY rank LIMIT :limit"
                    ),
                    {"q": fts_query, "limit": limit, "character_id": character_id},
                ).all()
            except Exception:
                episode_ids = []
            episodes: list[EpisodicMemory] = []
            for episode_id in episode_ids:
                episode = orm.get(EpisodicMemory, episode_id)
                if (
                    episode
                    and episode.deleted_at is None
                    and (character_id is None or episode.character_id == character_id)
                ):
                    episodes.append(episode)
            if len(episodes) < limit:
                like = f"%{query}%"
                rows = (
                    orm.query(EpisodicMemory)
                    .filter(
                        EpisodicMemory.deleted_at.is_(None),
                        *(
                            (EpisodicMemory.character_id == character_id,)
                            if character_id is not None
                            else ()
                        ),
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
            job = orm.get(MemoryJob, session_id)
            if job is not None and job.summary_sequence > end_sequence:
                return
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
            if job is None:
                job = MemoryJob(session_id=session_id)
                orm.add(job)
            job.summary_sequence = end_sequence
            job.updated_at = _now()
            orm.commit()

    def summary_checkpoint(self, session_id: str) -> int:
        with self._orm() as orm:
            job = orm.get(MemoryJob, session_id)
            return job.summary_sequence if job else 0

    def queue_maintenance(self, session_id: str, sequence: int, delay_s: float = 0) -> None:
        """Coalesce work by session; cancellation never removes this durable request."""
        now = _now()
        statement = insert(MemoryJob).values(
            session_id=session_id,
            target_sequence=sequence,
            completed_sequence=0,
            summary_sequence=0,
            attempts=0,
            next_attempt_at=now + timedelta(seconds=delay_s),
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[MemoryJob.session_id],
            set_={
                "target_sequence": text(
                    "max(memory_jobs.target_sequence, excluded.target_sequence)"
                ),
                "next_attempt_at": statement.excluded.next_attempt_at,
                "updated_at": statement.excluded.updated_at,
            },
        )
        with self._orm() as orm:
            orm.execute(statement)
            orm.commit()

    def pending_maintenance(self, *, due_only: bool = True) -> list[tuple[str, int]]:
        with self._orm() as orm:
            query = orm.query(MemoryJob).filter(
                MemoryJob.target_sequence > MemoryJob.completed_sequence
            )
            if due_only:
                query = query.filter(
                    MemoryJob.next_attempt_at.is_(None) | (MemoryJob.next_attempt_at <= _now())
                )
            return [
                (job.session_id, job.target_sequence)
                for job in query.order_by(MemoryJob.updated_at).all()
            ]

    def complete_maintenance(self, session_id: str, sequence: int) -> None:
        with self._orm() as orm:
            job = orm.get(MemoryJob, session_id)
            if job is not None:
                job.completed_sequence = max(job.completed_sequence, sequence)
                job.attempts = 0
                job.next_attempt_at = None
                job.updated_at = _now()
                orm.commit()

    def defer_maintenance(self, session_id: str) -> None:
        """Record retry metadata only; never store a provider error or conversation body."""
        with self._orm() as orm:
            job = orm.get(MemoryJob, session_id)
            if job is not None:
                job.attempts += 1
                seconds = min(300, 2 ** min(job.attempts, 8))
                job.next_attempt_at = _now() + timedelta(seconds=seconds)
                job.updated_at = _now()
                orm.commit()

    def cached_vectors(self, keys: list[str]) -> dict[str, list[float]]:
        result: dict[str, list[float]] = {}
        with self._orm() as orm:
            for offset in range(0, len(keys), 300):
                rows = orm.query(MemoryVector).filter(
                    MemoryVector.cache_key.in_(keys[offset : offset + 300])
                )
                for row in rows:
                    try:
                        vector = json.loads(row.vector_json)
                        if (
                            isinstance(vector, list)
                            and len(vector) == row.dimensions
                            and vector
                            and all(
                                isinstance(x, (int, float)) and math.isfinite(x) for x in vector
                            )
                        ):
                            result[row.cache_key] = [float(x) for x in vector]
                    except (ValueError, TypeError):
                        continue
        return result

    def cache_vector(
        self, key: str, model_key: str, content_hash: str, vector: list[float]
    ) -> None:
        if not vector or not all(math.isfinite(value) for value in vector):
            return
        statement = insert(MemoryVector).values(
            cache_key=key,
            model_key=model_key,
            content_hash=content_hash,
            vector_json=json.dumps(vector),
            dimensions=len(vector),
            updated_at=_now(),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[MemoryVector.cache_key],
            set_={
                "vector_json": statement.excluded.vector_json,
                "dimensions": statement.excluded.dimensions,
                "updated_at": statement.excluded.updated_at,
            },
        )
        with self._orm() as orm:
            orm.execute(statement)
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

    def get_extraction_checkpoint(self, session_id: str) -> int:
        with self._orm() as orm:
            row = orm.get(MemoryExtractionCheckpoint, session_id)
            return row.last_sequence if row else 0

    def set_extraction_checkpoint(self, session_id: str, sequence: int) -> None:
        with self._orm() as orm:
            row = orm.get(MemoryExtractionCheckpoint, session_id)
            if row is None:
                row = MemoryExtractionCheckpoint(session_id=session_id, last_sequence=sequence)
                orm.add(row)
            else:
                row.last_sequence = max(row.last_sequence, sequence)
                row.updated_at = _now()
            orm.commit()

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _discard_vector(orm: OrmSession, content: str) -> None:
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        orm.query(MemoryVector).filter(MemoryVector.content_hash == content_hash).delete()

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
            character_id=fact.character_id,
            owner_namespace=fact.owner_namespace,
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
            character_id=episode.character_id,
            owner_namespace=episode.owner_namespace,
        )
