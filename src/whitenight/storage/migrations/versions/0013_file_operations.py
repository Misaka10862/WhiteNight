"""Deduplicated approvals and durable presentation/claim state.

Revision ID: 0013
Revises: 0012
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("active_key", sa.String(64), nullable=True))
    op.add_column("approvals", sa.Column("presented_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_approvals_active_key", "approvals", ["active_key"], unique=True)
    # Legacy continuations cannot safely be bulk approved after their original expiry.
    op.execute(
        "UPDATE approvals SET status='revoked' WHERE status='pending' "
        "AND expires_at IS NOT NULL AND expires_at < CURRENT_TIMESTAMP"
    )
    op.execute(
        "UPDATE pending_tool_calls SET status='expired' WHERE status='pending' "
        "AND approval_id IN (SELECT id FROM approvals WHERE status='revoked')"
    )

    # Preserve evidence but invalidate older exact duplicates from the old request path.
    connection = op.get_bind()
    seen: set[tuple[object, ...]] = set()
    rows = (
        connection.execute(
            sa.text(
                "SELECT id, session_id, channel, tool_name, params_summary FROM approvals "
                "WHERE status='pending' ORDER BY created_at DESC, id DESC"
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        try:
            binding = json.loads(row["params_summary"])
        except (ValueError, TypeError):
            continue
        if not isinstance(binding, dict) or not binding.get("params_digest"):
            continue
        key = (
            row["session_id"],
            row["channel"],
            row["tool_name"],
            binding.get("channel_target"),
            binding["params_digest"],
        )
        if key in seen:
            connection.execute(
                sa.text("UPDATE approvals SET status='revoked' WHERE id=:id"), {"id": row["id"]}
            )
            connection.execute(
                sa.text(
                    "UPDATE pending_tool_calls SET status='superseded' WHERE approval_id=:id AND status='pending'"
                ),
                {"id": row["id"]},
            )
        seen.add(key)


def downgrade() -> None:
    op.drop_index("ix_approvals_active_key", table_name="approvals")
    op.drop_column("approvals", "presented_at")
    op.drop_column("approvals", "active_key")
