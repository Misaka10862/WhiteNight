"""approvals, session grants and audit events

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("risk", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=True),
        sa.Column("params_summary", sa.Text(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approvals_code", "approvals", ["code"], unique=True)

    op.create_table(
        "session_grants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_session_grants_session_tool", "session_grants", ["session_id", "tool_name"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("risk", sa.String(length=32), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("params_summary", sa.Text(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=True),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_ts", "audit_events", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_ts", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_session_grants_session_tool", table_name="session_grants")
    op.drop_table("session_grants")
    op.drop_index("ix_approvals_code", table_name="approvals")
    op.drop_table("approvals")
