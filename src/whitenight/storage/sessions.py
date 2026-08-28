"""会话与消息存储：所有渠道共享同一会话命名空间。"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session as OrmSession

from whitenight.channels.types import MessageKind, MessageRecord, MessageRole, SessionSummary
from whitenight.storage.models import AppMeta, CharacterProfile, Message, Session


class SessionNotFoundError(KeyError):
    """会话不存在。"""


class SessionStore:
    """原始会话的持久化仓储（阶段 2：SQLAlchemy；后续保持接口不变）。"""

    def __init__(self, engine: Engine, attachments_dir: Path | None = None) -> None:
        self._engine = engine
        self._attachments_dir = attachments_dir

    def _orm(self) -> OrmSession:
        return OrmSession(self._engine, expire_on_commit=False)

    def create_session(
        self,
        title: str | None = None,
        *,
        character_id: str | None = None,
        persona_id: str | None = None,
        greeting: str | None = None,
    ) -> SessionSummary:
        with self._orm() as orm:
            character_id = character_id or self._meta_value(orm, "default_character_id")
            persona_id = persona_id or self._meta_value(orm, "default_persona_id")
            session = Session(
                title=title or "新会话",
                character_id=character_id,
                persona_id=persona_id,
            )
            orm.add(session)
            orm.flush()
            if greeting:
                orm.add(
                    Message(
                        session_id=session.id,
                        sequence=1,
                        role="assistant",
                        kind="text",
                        content=greeting,
                    )
                )
            orm.commit()
            return self._summary(session, 1 if greeting else 0, orm)

    def list_sessions(self, limit: int = 50) -> list[SessionSummary]:
        with self._orm() as orm:
            rows = orm.execute(
                select(Session, func.count(Message.id))
                .outerjoin(Message)
                .group_by(Session.id)
                .order_by(Session.updated_at.desc())
                .limit(limit)
            ).all()
            return [self._summary(session, count, orm) for session, count in rows]

    def get_session(self, session_id: str) -> SessionSummary:
        with self._orm() as orm:
            session = orm.get(Session, session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            count = orm.scalar(
                select(func.count(Message.id)).where(Message.session_id == session_id)
            )
            return self._summary(session, count or 0, orm)

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
            had_user = bool(
                orm.scalar(
                    select(func.count(Message.id)).where(
                        Message.session_id == session_id,
                        Message.role == "user",
                    )
                )
            )
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
            # 角色开场可能占 sequence=1；标题仍取首条用户消息。
            if role == "user" and not had_user and session.title == "新会话":
                session.title = (content.strip() or "图片消息")[:24] or "新会话"
            session.updated_at = datetime.now(UTC)
            orm.commit()
            return self._record(message)

    def rename_session(self, session_id: str, title: str) -> SessionSummary:
        with self._orm() as orm:
            session = orm.get(Session, session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            session.title = title.strip()[:200] or "新会话"
            session.updated_at = datetime.now(UTC)
            orm.commit()
            count = orm.scalar(
                select(func.count(Message.id)).where(Message.session_id == session_id)
            )
            return self._summary(session, count or 0, orm)

    def delete_session(self, session_id: str) -> None:
        """删除会话：级联删除消息，立即从应用移除。正文不进入审计。"""
        with self._orm() as orm:
            session = orm.get(Session, session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            orm.delete(session)
            orm.commit()

    def export_session(self, session_id: str, fmt: str = "markdown") -> str:
        messages = self.list_messages(session_id)
        if fmt == "jsonl":
            import json

            lines = [
                json.dumps(
                    {
                        "id": message.id,
                        "role": message.role,
                        "kind": message.kind,
                        "content": message.content,
                        "image_data_url": message.image_data_url,
                        "created_at": message.created_at.isoformat(),
                    },
                    ensure_ascii=False,
                )
                for message in messages
            ]
            return "\n".join(lines) + ("\n" if lines else "")
        parts = [f"# 会话 {session_id}", ""]
        for message in messages:
            parts.append(f"## {message.role} ({message.created_at.isoformat()})")
            if message.image_data_url:
                parts.append(f"![image]({message.image_data_url})")
            if message.content:
                parts.append(message.content)
            parts.append("")
        return "\n".join(parts)

    def set_identity(self, session_id: str, character_id: str, persona_id: str) -> None:
        with self._orm() as orm:
            session = orm.get(Session, session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            session.character_id, session.persona_id = character_id, persona_id
            session.updated_at = datetime.now(UTC)
            orm.commit()

    @staticmethod
    def _meta_value(orm: OrmSession, key: str) -> str | None:
        row = orm.get(AppMeta, key)
        return row.value if row else None

    def _summary(
        self, session: Session, message_count: int, orm: OrmSession | None = None
    ) -> SessionSummary:
        character = (
            orm.get(CharacterProfile, session.character_id)
            if orm and session.character_id
            else None
        )
        return SessionSummary(
            id=session.id,
            title=session.title,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=message_count,
            character_id=session.character_id,
            persona_id=session.persona_id,
            character_name=character.name if character else None,
            character_avatar_path=character.avatar_path if character else None,
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
