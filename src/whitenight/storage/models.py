"""数据库模型。

阶段 0：应用元数据；阶段 2：会话与统一消息。
长期记忆（情景记忆/结构化档案）在阶段 4 追加，不混入原始会话表。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class AppMeta(Base):
    """应用级键值元数据：schema 标记、初始化时间等。"""

    __tablename__ = "whitenight_meta"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class Session(Base):
    """统一会话：所有渠道共享同一会话命名空间。"""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200), default="新会话", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.sequence"
    )


class Message(Base):
    """统一消息：渠道无关的原始会话内容，按会话内序号严格排序。"""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_session_seq", "session_id", "sequence", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped[Session] = relationship(back_populates="messages")


class Approval(Base):
    """一次性审批请求：短期、不可重放（构建计划第 9.2 节）。"""

    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_code", "code", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    risk: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), default="once", nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False
    )  # pending|approved|rejected|revoked
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    params_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionGrant(Base):
    """按会话授权的工具类别（低风险写入等）。"""

    __tablename__ = "session_grants"
    __table_args__ = (Index("ix_session_grants_session_tool", "session_id", "tool_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    """现实动作审计：执行者、参数摘要、审批记录、结果和时间。"""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_ts", "ts"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    params_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    result_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
