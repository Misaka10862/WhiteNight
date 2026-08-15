"""会话与消息存储：所有渠道共享同一会话命名空间。"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session as OrmSession

from whitenight.channels.types import MessageKind, MessageRecord, MessageRole, SessionSummary
from whitenight.storage.models import Message, Session


class SessionNotFoundError(KeyError):
    """会话不存在。"""


class SessionStore:
    """原始会话的持久化仓储（阶段 2：SQLAlchemy；后续保持接口不变）。"""

    def __init__(self, engine: Engine, attachments_dir: Path | None = None) -> None:
        self._engine = engine
        self._attachments_dir = attachments_dir

    def _orm(self) -> OrmSession:
        return OrmSession(self._engine, expire_on_commit=False)

    def create_session(self, title: str | None = None) -> SessionSummary:
        with self._orm() as orm:
            session = Session(title=title or "新会话")
            orm.add(session)
            orm.commit()
            return self._summary(session, 0)

    def list_sessions(self, limit: int = 50) -> list[SessionSummary]:
        with self._orm() as orm:
            rows = orm.execute(
                select(Session, func.count(Message.id))
                .outerjoin(Message)
                .group_by(Session.id)
                .order_by(Session.updated_at.desc())
                .limit(limit)
            ).all()
            return [self._summary(session, count) for session, count in rows]

    def get_session(self, session_id: str) -> SessionSummary:
        with self._orm() as orm:
            session = orm.get(Session, session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            count = orm.scalar(
                select(func.count(Message.id)).where(Message.session_id == session_id)
            )
            return self._summary(session, count or 0)

    def list_messages(self, session_id: str) -> list[MessageRecord]:
        with self._orm() as orm:
            if orm.get(Session, session_id) is None:
                raise SessionNotFoundError(session_id)
            rows = orm.execute(
                select(Message).where(Message.session_id == session_id).order_by(Message.sequence)
            ).scalars()
            return [self._record(message) for message in rows]

    def add_message(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        kind: MessageKind = "text",
        image_path: str | None = None,
        image_mime: str | None = None,
    ) -> MessageRecord:
        with self._orm() as orm:
            session = orm.get(Session, session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            sequence = (
                orm.scalar(
                    select(func.max(Message.sequence)).where(Message.session_id == session_id)
                )
                or 0
            ) + 1
            message = Message(
                session_id=session_id,
                sequence=sequence,
                role=role,
                kind=kind,
                content=content,
                image_path=image_path,
                image_mime=image_mime,
            )
            orm.add(message)
            # 会话标题：未显式命名时，用首条用户消息的前 24 个字符。
            if role == "user" and sequence == 1 and session.title == "新会话":
                session.title = (content.strip() or "图片消息")[:24] or "新会话"
            session.updated_at = datetime.now(UTC)
            orm.commit()
            return self._record(message)

    def _summary(self, session: Session, message_count: int) -> SessionSummary:
        return SessionSummary(
            id=session.id,
            title=session.title,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=message_count,
        )

    def _record(self, message: Message) -> MessageRecord:
        image_data_url: str | None = None
        if message.image_path and self._attachments_dir is not None:
            path = self._attachments_dir / message.image_path
            if path.exists() and message.image_mime:
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                image_data_url = f"data:{message.image_mime};base64,{encoded}"
        return MessageRecord(
            id=message.id,
            session_id=message.session_id,
            sequence=message.sequence,
            role=message.role,  # type: ignore[arg-type]
            kind=message.kind,  # type: ignore[arg-type]
            content=message.content,
            image_data_url=image_data_url,
            created_at=message.created_at,
        )
