"""character, persona, prompt, lorebook and generation trace domain

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-26
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic import context, op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> str:
    return str(uuid4())


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.create_table(
        "character_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("active_revision_id", sa.String(36), nullable=True),
        sa.Column("avatar_path", sa.String(512), nullable=True),
        sa.Column("is_default", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_character_profiles_name", "character_profiles", ["name"])
    op.create_table(
        "character_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("character_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("card_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("character_id", "revision", name="uq_character_rev"),
    )
    op.create_index("ix_character_revisions_character_id", "character_revisions", ["character_id"])
    op.create_table(
        "persona_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "prompt_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("character_id", sa.String(36), nullable=False, unique=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("blocks_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "persona_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("persona_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("persona_id", "revision", name="uq_persona_rev"),
    )
    op.create_index("ix_persona_revisions_persona_id", "persona_revisions", ["persona_id"])
    op.create_table(
        "prompt_profile_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("blocks_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("profile_id", "revision", name="uq_prompt_profile_rev"),
    )
    op.create_index(
        "ix_prompt_profile_revisions_profile_id", "prompt_profile_revisions", ["profile_id"]
    )
    op.create_table(
        "lorebooks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("book_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("globally_enabled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "character_lorebooks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("character_id", sa.String(36), nullable=False),
        sa.Column("lorebook_id", sa.String(36), nullable=False),
        sa.UniqueConstraint("character_id", "lorebook_id", name="uq_char_lore"),
    )
    op.create_table(
        "lorebook_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lorebook_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("book_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("lorebook_id", "revision", name="uq_lorebook_rev"),
    )
    op.create_index("ix_lorebook_revisions_lorebook_id", "lorebook_revisions", ["lorebook_id"])
    op.create_index("ix_character_lorebooks_character_id", "character_lorebooks", ["character_id"])
    op.create_table(
        "session_lorebooks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("lorebook_id", sa.String(36), nullable=False),
        sa.UniqueConstraint("session_id", "lorebook_id", name="uq_session_lore"),
    )
    op.create_index("ix_session_lorebooks_session_id", "session_lorebooks", ["session_id"])
    op.create_table(
        "generation_traces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("assistant_message_id", sa.String(36), nullable=True),
        sa.Column("character_revision_id", sa.String(36), nullable=False),
        sa.Column("prompt_profile_revision", sa.Integer(), nullable=False),
        sa.Column("seed", sa.String(64), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_generation_traces_session", "generation_traces", ["session_id", "created_at"]
    )

    settings = context.config.attributes.get("whitenight_settings")
    soul_path = Path(getattr(settings, "soul_file", "SOUL.md"))
    soul = (
        soul_path.read_text(encoding="utf-8")
        if soul_path.exists()
        else ("我是 WhiteNight（白夜），昵称小白。日常温柔、准确、可靠。")
    )
    now = datetime.now(UTC)
    character_id, revision_id, persona_id, prompt_id = _id(), _id(), _id(), _id()
    card = {
        "spec": "chara_card_v3",
        "spec_version": "3.0",
        "data": {
            "name": "小白",
            "description": "WhiteNight 默认角色",
            "personality": "",
            "scenario": "",
            "first_mes": "主人，我在。",
            "mes_example": "",
            "creator_notes": "由升级程序从 SOUL.md 导入",
            "system_prompt": soul,
            "post_history_instructions": "",
            "alternate_greetings": [],
            "tags": ["WhiteNight", "默认"],
            "creator": "WhiteNight",
            "character_version": "1",
            "extensions": {},
        },
    }
    card_json = json.dumps(card, ensure_ascii=False, sort_keys=True)
    blocks = json.dumps([], ensure_ascii=False)
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO character_profiles "
            "(id,name,active_revision_id,is_default,created_at,updated_at) "
            "VALUES (:id,'小白',:revision,1,:now,:now)"
        ),
        {"id": character_id, "revision": revision_id, "now": now},
    )
    connection.execute(
        sa.text(
            "INSERT INTO persona_revisions "
            "(id,persona_id,revision,name,description,content_hash,created_at) "
            "VALUES (:id,:persona,1,'主人','',:hash,:now)"
        ),
        {"id": _id(), "persona": persona_id, "hash": _hash("主人\n"), "now": now},
    )
    connection.execute(
        sa.text(
            "INSERT INTO character_revisions "
            "(id,character_id,revision,card_json,content_hash,created_at) "
            "VALUES (:id,:character,1,:card,:hash,:now)"
        ),
        {
            "id": revision_id,
            "character": character_id,
            "card": card_json,
            "hash": _hash(card_json),
            "now": now,
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO prompt_profile_revisions "
            "(id,profile_id,revision,blocks_json,content_hash,created_at) "
            "VALUES (:id,:profile,1,:blocks,:hash,:now)"
        ),
        {
            "id": _id(),
            "profile": prompt_id,
            "blocks": blocks,
            "hash": _hash(blocks),
            "now": now,
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO persona_profiles "
            "(id,name,description,content_hash,created_at,updated_at) "
            "VALUES (:id,'主人','',:hash,:now,:now)"
        ),
        {"id": persona_id, "hash": _hash("主人\n"), "now": now},
    )
    connection.execute(
        sa.text(
            "INSERT INTO prompt_profiles "
            "(id,character_id,revision,blocks_json,content_hash,created_at,updated_at) "
            "VALUES (:id,:character,1,:blocks,:hash,:now,:now)"
        ),
        {
            "id": prompt_id,
            "character": character_id,
            "blocks": blocks,
            "hash": _hash(blocks),
            "now": now,
        },
    )
    for key, value in (
        ("default_character_id", character_id),
        ("default_persona_id", persona_id),
    ):
        connection.execute(
            sa.text(
                "INSERT INTO whitenight_meta (key,value,updated_at) VALUES (:key,:value,:now) "
                "ON CONFLICT(key) DO UPDATE SET value=:value, updated_at=:now"
            ),
            {"key": key, "value": value, "now": now},
        )


def downgrade() -> None:
    op.drop_index("ix_generation_traces_session", table_name="generation_traces")
    op.drop_table("generation_traces")
    op.drop_index("ix_lorebook_revisions_lorebook_id", table_name="lorebook_revisions")
    op.drop_table("lorebook_revisions")
    op.drop_index("ix_session_lorebooks_session_id", table_name="session_lorebooks")
    op.drop_table("session_lorebooks")
    op.drop_index("ix_character_lorebooks_character_id", table_name="character_lorebooks")
    op.drop_table("character_lorebooks")
    op.drop_table("lorebooks")
    op.drop_index("ix_prompt_profile_revisions_profile_id", table_name="prompt_profile_revisions")
    op.drop_table("prompt_profile_revisions")
    op.drop_index("ix_persona_revisions_persona_id", table_name="persona_revisions")
    op.drop_table("persona_revisions")
    op.drop_table("prompt_profiles")
    op.drop_table("persona_profiles")
    op.drop_index("ix_character_revisions_character_id", table_name="character_revisions")
    op.drop_table("character_revisions")
    op.drop_index("ix_character_profiles_name", table_name="character_profiles")
    op.drop_table("character_profiles")
    op.execute(
        "DELETE FROM whitenight_meta WHERE key IN ('default_character_id','default_persona_id')"
    )
