"""bind sessions and memories to characters and add world state

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("character_id", sa.String(36), nullable=True))
    op.add_column("sessions", sa.Column("persona_id", sa.String(36), nullable=True))
    op.add_column("profile_facts", sa.Column("character_id", sa.String(36), nullable=True))
    op.add_column(
        "profile_facts",
        sa.Column("owner_namespace", sa.String(64), nullable=False, server_default="local-user"),
    )
    op.create_index("ix_profile_facts_character_id", "profile_facts", ["character_id"])
    op.add_column("episodic_memories", sa.Column("character_id", sa.String(36), nullable=True))
    op.add_column(
        "episodic_memories",
        sa.Column("owner_namespace", sa.String(64), nullable=False, server_default="local-user"),
    )
    op.create_index("ix_episodic_memories_character_id", "episodic_memories", ["character_id"])

    connection = op.get_bind()
    character_id = connection.execute(
        sa.text("SELECT value FROM whitenight_meta WHERE key='default_character_id'")
    ).scalar_one()
    persona_id = connection.execute(
        sa.text("SELECT value FROM whitenight_meta WHERE key='default_persona_id'")
    ).scalar_one()
    connection.execute(
        sa.text("UPDATE sessions SET character_id=:character, persona_id=:persona"),
        {"character": character_id, "persona": persona_id},
    )
    connection.execute(
        sa.text("UPDATE profile_facts SET character_id=:character"),
        {"character": character_id},
    )
    connection.execute(
        sa.text("UPDATE episodic_memories SET character_id=:character"),
        {"character": character_id},
    )

    op.create_table(
        "world_effect_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("entry_key", sa.String(128), nullable=False),
        sa.Column("sticky_until", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cooldown_until", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delayed_until", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "entry_key", name="uq_world_effect"),
    )
    op.create_index("ix_world_effect_states_session_id", "world_effect_states", ["session_id"])
    op.create_table(
        "memory_extraction_checkpoints",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("memory_extraction_checkpoints")
    op.drop_index("ix_world_effect_states_session_id", table_name="world_effect_states")
    op.drop_table("world_effect_states")
    op.drop_index("ix_episodic_memories_character_id", table_name="episodic_memories")
    op.drop_column("episodic_memories", "owner_namespace")
    op.drop_column("episodic_memories", "character_id")
    op.drop_index("ix_profile_facts_character_id", table_name="profile_facts")
    op.drop_column("profile_facts", "owner_namespace")
    op.drop_column("profile_facts", "character_id")
    op.drop_column("sessions", "persona_id")
    op.drop_column("sessions", "character_id")
