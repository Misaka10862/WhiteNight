"""Persistent vector cache and resumable memory-maintenance state."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from whitenight.storage.models import Base


class MemoryVector(Base):
    __tablename__ = "memory_vectors"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_key: Mapped[str] = mapped_column(String(256), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    vector_json: Mapped[str] = mapped_column(Text, nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class MemoryJob(Base):
    __tablename__ = "memory_jobs"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    target_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
