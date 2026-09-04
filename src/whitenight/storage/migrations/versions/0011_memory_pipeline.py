"""Persist versioned vectors and resumable incremental memory maintenance.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_vectors",
        sa.Column("cache_key", sa.String(64), primary_key=True),
        sa.Column("model_key", sa.String(256), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("vector_json", sa.Text(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "memory_jobs",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("target_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Old summaries did not cover the sequence range they claimed. A zero summary
    # checkpoint rebuilds coverage incrementally while preserving their existing text.
    op.execute(
        "INSERT INTO memory_jobs "
        "(session_id, target_sequence, completed_sequence, summary_sequence, attempts, updated_at) "
        "SELECT session_id, MAX(sequence), 0, 0, 0, CURRENT_TIMESTAMP "
        "FROM messages GROUP BY session_id"
    )


def downgrade() -> None:
    # Source messages, extracted facts/episodes and the latest summary remain intact.
    op.drop_table("memory_jobs")
    op.drop_table("memory_vectors")
