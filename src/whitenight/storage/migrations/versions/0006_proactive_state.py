"""proactive message scheduler state

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "proactive_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.Column("expected_per_day", sa.Float(), nullable=False),
        sa.Column("quiet_start", sa.String(length=5), nullable=False),
        sa.Column("quiet_end", sa.String(length=5), nullable=False),
        sa.Column("suppress_minutes", sa.Integer(), nullable=False),
        sa.Column("skip_grace_minutes", sa.Integer(), nullable=False),
        sa.Column("paused", sa.Integer(), nullable=False),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_candidate_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        """
        INSERT INTO proactive_state
        (id, enabled, expected_per_day, quiet_start, quiet_end,
         suppress_minutes, skip_grace_minutes, paused)
        VALUES (1, 0, 1.5, '23:00', '08:00', 60, 45, 0)
        """
    )


def downgrade() -> None:
    op.drop_table("proactive_state")
