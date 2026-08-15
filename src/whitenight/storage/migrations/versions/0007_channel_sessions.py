"""channel sessions mapping

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("owner_key", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_channel_sessions_lookup",
        "channel_sessions",
        ["channel", "owner_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_channel_sessions_lookup", table_name="channel_sessions")
    op.drop_table("channel_sessions")
