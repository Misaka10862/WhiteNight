"""主动消息状态存储：单例行，读写统一 naive-UTC。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession

from whitenight.scheduler.types import ProactiveConfig, ProactiveStatus
from whitenight.storage.models import ProactiveState


def now_naive_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _to_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


class ProactiveStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def _orm(self) -> OrmSession:
        return OrmSession(self._engine, expire_on_commit=False)

    def _row(self, orm: OrmSession) -> ProactiveState:
        row = orm.get(ProactiveState, 1)
        if row is None:
            row = ProactiveState(id=1)
            orm.add(row)
            orm.flush()
        return row

    def status(self) -> ProactiveStatus:
        with self._orm() as orm:
            row = self._row(orm)
            return ProactiveStatus(
                config=ProactiveConfig(
                    enabled=bool(row.enabled),
                    expected_per_day=row.expected_per_day,
                    quiet_start=row.quiet_start,
                    quiet_end=row.quiet_end,
                    suppress_minutes=row.suppress_minutes,
                    skip_grace_minutes=row.skip_grace_minutes,
                ),
                paused=bool(row.paused),
                paused_until=row.paused_until,
                last_activity_at=row.last_activity_at,
                last_sent_at=row.last_sent_at,
                next_candidate_at=row.next_candidate_at,
            )

    def update_config(self, config: ProactiveConfig) -> ProactiveStatus:
        with self._orm() as orm:
            row = self._row(orm)
            row.enabled = int(config.enabled)
            row.expected_per_day = config.expected_per_day
            row.quiet_start = config.quiet_start
            row.quiet_end = config.quiet_end
            row.suppress_minutes = config.suppress_minutes
            row.skip_grace_minutes = config.skip_grace_minutes
            row.updated_at = now_naive_utc()
            orm.commit()
        return self.status()

    def mark_activity(self, at: datetime | None = None) -> None:
        value = _to_naive(at or datetime.now(UTC))
        with self._orm() as orm:
            row = self._row(orm)
            row.last_activity_at = value
            row.updated_at = now_naive_utc()
            orm.commit()

    def mark_sent(self, at: datetime | None = None) -> None:
        value = _to_naive(at or datetime.now(UTC))
        with self._orm() as orm:
            row = self._row(orm)
            row.last_sent_at = value
            row.updated_at = now_naive_utc()
            orm.commit()

    def set_next_candidate(self, at: datetime | None) -> None:
        with self._orm() as orm:
            row = self._row(orm)
            row.next_candidate_at = _to_naive(at) if at else None
            row.updated_at = now_naive_utc()
            orm.commit()

    def pause(self, until: datetime | None) -> None:
        with self._orm() as orm:
            row = self._row(orm)
            row.paused = 1
            row.paused_until = _to_naive(until) if until else None
            row.updated_at = now_naive_utc()
            orm.commit()

    def resume(self) -> None:
        with self._orm() as orm:
            row = self._row(orm)
            row.paused = 0
            row.paused_until = None
            row.updated_at = now_naive_utc()
            orm.commit()
