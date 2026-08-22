"""pending tool-call continuations

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "pending_tool_calls",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("approval_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("channel_target", sa.String(length=128), nullable=True),
        sa.Column("tool_call_id", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("params_digest", sa.String(length=64), nullable=False),
        sa.Column("assistant_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pending_tool_calls_approval", "pending_tool_calls", ["approval_id"], unique=True
    )
    op.create_index(
        "ix_pending_tool_calls_session", "pending_tool_calls", ["session_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_pending_tool_calls_session", table_name="pending_tool_calls")
    op.drop_index("ix_pending_tool_calls_approval", table_name="pending_tool_calls")
    op.drop_table("pending_tool_calls")
