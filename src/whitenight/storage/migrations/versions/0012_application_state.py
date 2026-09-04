"""Structured attachment receipts and idempotent conversation requests.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachment_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_message_id", sa.String(36)),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("path", sa.Text()),
        sa.Column("mime", sa.String(128)),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64)),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_attachment_receipts_session_id", "attachment_receipts", ["session_id"])
    op.create_index(
        "ix_attachment_receipts_source_message_id", "attachment_receipts", ["source_message_id"]
    )
    op.create_table(
        "conversation_runs",
        sa.Column("request_id", sa.String(64), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("terminal_event", sa.Text()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_conversation_runs_session_id", "conversation_runs", ["session_id"])


def downgrade() -> None:
    op.drop_table("conversation_runs")
    op.drop_table("attachment_receipts")
