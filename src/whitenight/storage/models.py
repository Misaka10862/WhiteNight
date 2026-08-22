"""数据库模型。

阶段 0：应用元数据；阶段 2：会话与统一消息。
长期记忆（情景记忆/结构化档案）在阶段 4 追加，不混入原始会话表。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
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


class PendingToolCall(Base):
    """Durable continuation for a tool call waiting on user approval."""

    __tablename__ = "pending_tool_calls"
    __table_args__ = (
        Index("ix_pending_tool_calls_approval", "approval_id", unique=True),
        Index("ix_pending_tool_calls_session", "session_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    approval_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    channel_target: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    params_json: Mapped[str] = mapped_column(Text, nullable=False)
    params_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    assistant_content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


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


class ProfileFact(Base):
    """结构化档案：称呼、偏好、作息、重要日期和稳定事实。"""

    __tablename__ = "profile_facts"
    __table_args__ = (Index("ix_profile_facts_key", "key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(default=0.5, nullable=False)
    source_message_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="active", nullable=False
    )  # active|superseded|deleted
    conflict_state: Mapped[str] = mapped_column(
        String(16), default="none", nullable=False
    )  # none|conflicted|resolved
    superseded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class EpisodicMemory(Base):
    """情景记忆：重要事件、承诺、共同经历、趣事和情绪变化。"""

    __tablename__ = "episodic_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    confidence: Mapped[float] = mapped_column(default=0.5, nullable=False)
    importance: Mapped[float] = mapped_column(default=0.5, nullable=False)
    access_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionSummaryRecord(Base):
    """滚动摘要：把旧上下文压缩成摘要，而不是无限堆入模型。"""

    __tablename__ = "session_summaries"
    __table_args__ = (Index("ix_session_summaries_session", "session_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    start_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    end_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AgentTask(Base):
    """委派任务：执行者、状态、进度、产物、错误与重试记录。"""

    __tablename__ = "agent_tasks"
    __table_args__ = (Index("ix_agent_tasks_session", "session_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    executor: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="chat", nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="queued", nullable=False
    )  # queued|running|succeeded|failed|aborted
    risk: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    cwd: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    artifacts: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class ProactiveState(Base):
    """主动消息调度单例状态：频率、静默时段、暂停与最近活动抑制。"""

    __tablename__ = "proactive_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expected_per_day: Mapped[float] = mapped_column(Float, default=1.5, nullable=False)
    quiet_start: Mapped[str] = mapped_column(String(5), default="23:00", nullable=False)
    quiet_end: Mapped[str] = mapped_column(String(5), default="08:00", nullable=False)
    suppress_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    skip_grace_minutes: Mapped[int] = mapped_column(Integer, default=45, nullable=False)
    paused: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_candidate_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class ChannelSession(Base):
    """渠道 → 统一会话映射：QQ 与 WebUI 共享同一会话/记忆/任务。"""

    __tablename__ = "channel_sessions"
    __table_args__ = (Index("ix_channel_sessions_lookup", "channel", "owner_key", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_key: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
