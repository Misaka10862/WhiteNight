"""Durable attachment receipts and conversation request state."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from whitenight.storage.models import Base


class AttachmentReceipt(Base):
    __tablename__ = "attachment_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    source_message_id: Mapped[str | None] = mapped_column(String(36), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16))
    path: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(String(128))
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ConversationRun(Base):
    __tablename__ = "conversation_runs"
    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    terminal_event: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
