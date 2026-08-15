"""long-term memory tables with FTS5

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profile_facts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_message_ids", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("conflict_state", sa.String(length=16), nullable=False),
        sa.Column("superseded_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_profile_facts_key", "profile_facts", ["key"])

    op.create_table(
        "episodic_memories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_message_ids", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("access_count", sa.Integer(), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "session_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("start_sequence", sa.Integer(), nullable=False),
        sa.Column("end_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_session_summaries_session", "session_summaries", ["session_id"])

    # SQLite FTS5 中文混合检索：unicode61 分词。触发器随 facts/情景记忆增删改同步。
    op.execute(
        "CREATE VIRTUAL TABLE profile_facts_fts USING fts5(key, value, id UNINDEXED, tokenize='unicode61')"
    )
    op.execute(
        """
        CREATE TRIGGER profile_facts_ai AFTER INSERT ON profile_facts BEGIN
          INSERT INTO profile_facts_fts(rowid, key, value, id)
          VALUES (new.rowid, new.key, new.value, new.id);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER profile_facts_ad AFTER DELETE ON profile_facts BEGIN
          DELETE FROM profile_facts_fts WHERE rowid = old.rowid;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER profile_facts_au AFTER UPDATE ON profile_facts BEGIN
          DELETE FROM profile_facts_fts WHERE rowid = old.rowid;
          INSERT INTO profile_facts_fts(rowid, key, value, id)
          VALUES (new.rowid, new.key, new.value, new.id);
        END
        """
    )
    op.execute(
        "CREATE VIRTUAL TABLE episodic_memories_fts USING fts5(content, id UNINDEXED, tokenize='unicode61')"
    )
    op.execute(
        """
        CREATE TRIGGER episodic_memories_ai AFTER INSERT ON episodic_memories BEGIN
          INSERT INTO episodic_memories_fts(rowid, content, id) VALUES (new.rowid, new.content, new.id);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER episodic_memories_ad AFTER DELETE ON episodic_memories BEGIN
          DELETE FROM episodic_memories_fts WHERE rowid = old.rowid;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER episodic_memories_au AFTER UPDATE ON episodic_memories BEGIN
          DELETE FROM episodic_memories_fts WHERE rowid = old.rowid;
          INSERT INTO episodic_memories_fts(rowid, content, id) VALUES (new.rowid, new.content, new.id);
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS episodic_memories_au")
    op.execute("DROP TRIGGER IF EXISTS episodic_memories_ad")
    op.execute("DROP TRIGGER IF EXISTS episodic_memories_ai")
    op.execute("DROP TABLE IF EXISTS episodic_memories_fts")
    op.execute("DROP TRIGGER IF EXISTS profile_facts_au")
    op.execute("DROP TRIGGER IF EXISTS profile_facts_ad")
    op.execute("DROP TRIGGER IF EXISTS profile_facts_ai")
    op.execute("DROP TABLE IF EXISTS profile_facts_fts")
    op.drop_index("ix_session_summaries_session", table_name="session_summaries")
    op.drop_table("session_summaries")
    op.drop_table("episodic_memories")
    op.drop_index("ix_profile_facts_key", table_name="profile_facts")
    op.drop_table("profile_facts")
