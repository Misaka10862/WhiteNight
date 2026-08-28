"""Alembic 迁移入口：供应用启动时自动升级到 head。

命令行仍可用 ``uv run alembic upgrade head``；应用启动走同一 env.py。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from whitenight.config import Settings
from whitenight.storage.engine import backend_of

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_DIR = Path(__file__).resolve().parent / "migrations"


def upgrade_to_head(settings: Settings) -> None:
    """把数据库升级到最新迁移版本；幂等，可重复执行。"""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATION_DIR))
    config.attributes["whitenight_settings"] = settings
    _backup_sqlite_before_upgrade(settings, config)
    command.upgrade(config, "head")


def _backup_sqlite_before_upgrade(settings: Settings, config: Config) -> Path | None:
    """Create and integrity-check a recoverable copy only when an existing DB needs upgrade."""
    if backend_of(str(settings.database_url)) != "sqlite":
        return None
    url = make_url(str(settings.database_url))
    if not url.database or url.database == ":memory:":
        return None
    database = Path(url.database).expanduser().resolve()
    if not database.exists() or database.stat().st_size == 0:
        return None
    source = sqlite3.connect(str(database))
    try:
        has_version = source.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        if not has_version:
            return None
        current = source.execute("SELECT version_num FROM alembic_version").fetchone()
        target = ScriptDirectory.from_config(config).get_current_head()
        if not current or current[0] == target:
            return None
        backup_dir = settings.data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = (
            backup_dir
            / f"pre-migrate-{current[0]}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.db"
        )
        target_db = sqlite3.connect(str(backup))
        try:
            source.backup(target_db)
            integrity = target_db.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise RuntimeError("迁移前安全副本完整性检查失败")
        finally:
            target_db.close()
        return backup
    finally:
        source.close()
