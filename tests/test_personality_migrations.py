"""Upgrade/downgrade preservation for personality migrations."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config

from whitenight.config import Settings
from whitenight.storage.migrate import MIGRATION_DIR, PROJECT_ROOT, upgrade_to_head


def _config(settings: Settings) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATION_DIR))
    config.attributes["whitenight_settings"] = settings
    return config


def test_upgrade_assigns_legacy_data_and_downgrade_preserves_content(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    database = data_dir / "legacy.db"
    settings = Settings(
        data_dir=data_dir,
        database_url=f"sqlite:///{database}",
        keychain_backend="memory",
        auto_migrate=False,
        soul_file=tmp_path / "SOUL.md",
    )
    data_dir.mkdir(parents=True)
    settings.soul_file.write_text("旧版小白人格", encoding="utf-8")
    config = _config(settings)
    command.upgrade(config, "0008")
    now = datetime.now(UTC).isoformat()
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO sessions (id,title,created_at,updated_at) VALUES ('s1','旧会话',?,?)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO messages (id,session_id,sequence,role,kind,content,created_at) "
            "VALUES ('m1','s1',1,'user','text','旧消息',?)",
            (now,),
        )
        connection.execute(
            "INSERT INTO profile_facts "
            "(id,key,value,confidence,source_message_ids,status,conflict_state,created_at,updated_at) "
            "VALUES ('f1','喜好','抹茶',0.9,'[]','active','none',?,?)",
            (now, now),
        )
        connection.commit()
    finally:
        connection.close()

    upgrade_to_head(settings)
    connection = sqlite3.connect(database)
    try:
        default_id = connection.execute(
            "SELECT value FROM whitenight_meta WHERE key='default_character_id'"
        ).fetchone()[0]
        assert (
            connection.execute("SELECT character_id FROM sessions WHERE id='s1'").fetchone()[0]
            == default_id
        )
        assert (
            connection.execute("SELECT character_id FROM profile_facts WHERE id='f1'").fetchone()[0]
            == default_id
        )
        assert (
            connection.execute("SELECT content FROM messages WHERE id='m1'").fetchone()[0]
            == "旧消息"
        )
    finally:
        connection.close()
    assert list((data_dir / "backups").glob("pre-migrate-0008-*.db"))

    command.downgrade(config, "0008")
    connection = sqlite3.connect(database)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
        assert "character_id" not in columns
        assert (
            connection.execute("SELECT content FROM messages WHERE id='m1'").fetchone()[0]
            == "旧消息"
        )
        assert (
            connection.execute("SELECT value FROM profile_facts WHERE id='f1'").fetchone()[0]
            == "抹茶"
        )
    finally:
        connection.close()
