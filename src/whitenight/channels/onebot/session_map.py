"""渠道 → 统一会话映射：QQ 与 WebUI 共享同一会话。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as OrmSession

from whitenight.storage.models import ChannelSession
from whitenight.storage.sessions import SessionStore


class ChannelSessionStore:
    def __init__(self, engine: Engine, sessions: SessionStore) -> None:
        self._engine = engine
        self._sessions = sessions

    def get_or_create(self, channel: str, owner_key: str) -> str:
        """返回 owner 在该渠道的稳定会话 id；不存在则创建（标题带渠道前缀）。"""
        with OrmSession(self._engine, expire_on_commit=False) as orm:
            row = orm.scalar(
                select(ChannelSession).where(
                    ChannelSession.channel == channel,
                    ChannelSession.owner_key == owner_key,
                )
            )
            if row is not None:
                return row.session_id
        title = f"QQ·{owner_key}"
        session = self._sessions.create_session(title)
        with OrmSession(self._engine, expire_on_commit=False) as orm:
            orm.add(
                ChannelSession(
                    channel=channel,
                    owner_key=owner_key,
                    session_id=session.id,
                    updated_at=datetime.now(UTC),
                )
            )
            orm.commit()
        return session.id

    def reset(self, channel: str, owner_key: str) -> tuple[str | None, str]:
        """Rotate the channel mapping to a fresh session without deleting prior history."""
        new_session = self._sessions.create_session(f"QQ·{owner_key} · reset")
        with OrmSession(self._engine, expire_on_commit=False) as orm:
            row = orm.scalar(
                select(ChannelSession).where(
                    ChannelSession.channel == channel,
                    ChannelSession.owner_key == owner_key,
                )
            )
            previous_id = row.session_id if row is not None else None
            if row is None:
                orm.add(
                    ChannelSession(
                        channel=channel,
                        owner_key=owner_key,
                        session_id=new_session.id,
                        updated_at=datetime.now(UTC),
                    )
                )
            else:
                row.session_id = new_session.id
                row.updated_at = datetime.now(UTC)
            orm.commit()
        return previous_id, new_session.id
