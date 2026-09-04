"""Alembic upgrades with an exclusive lock and verified pre-upgrade snapshots."""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from whitenight.config import Settings
from whitenight.storage.backup import (
    _connect,
    _database_key,
    _integrity,
    recover_interrupted_restore,
)
from whitenight.storage.engine import backend_of
from whitenight.storage.maintenance import MaintenanceLock, database_file

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_DIR = Path(__file__).resolve().parent / "migrations"


def upgrade_to_head(settings: Settings, *, maintenance_lock: MaintenanceLock | None = None) -> None:
    """Upgrade idempotently; a service startup may pass its exclusive lifetime lock."""
    url = make_url(str(settings.database_url))
    if maintenance_lock is None and url.database and url.database != ":memory:":
        with MaintenanceLock(settings) as lock:
            upgrade_to_head(settings, maintenance_lock=lock)
        return
    if maintenance_lock is not None:
        maintenance_lock.validate(settings)
        recover_interrupted_restore(settings, maintenance_lock=maintenance_lock)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATION_DIR))
    config.attributes["whitenight_settings"] = settings
    _backup_before_upgrade(settings, config)
    config.attributes["whitenight_maintenance_ready"] = True
    command.upgrade(config, "head")


def _backup_before_upgrade(
    settings: Settings, config: Config, *, force: bool = False
) -> Path | None:
    """Back up existing SQLite/SQLCipher databases; encrypted inputs stay encrypted."""
    url = make_url(str(settings.database_url))
    if not url.database or url.database == ":memory:":
        return None
    database = database_file(settings)
    if not database.exists() or database.stat().st_size == 0:
        return None
    cipher = backend_of(str(settings.database_url)) == "sqlcipher"
    key = _database_key(settings)
    source = _connect(database, cipher=cipher, key=key, readonly=True)
    try:
        has_version = source.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        current = (
            source.execute("SELECT version_num FROM alembic_version").fetchone()
            if has_version
            else None
        )
        target = ScriptDirectory.from_config(config).get_current_head()
        if not force and current and current[0] == target:
            return None
        revision = str(current[0]) if current else "unversioned"
        # Revision names originate in database contents; never interpolate paths.
        revision = "".join(char for char in revision if char.isalnum() or char in "_-")[:80]
        backup_dir = settings.data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = (
            backup_dir
            / f"pre-migrate-{revision}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}.db"
        )
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        target_db = _connect(backup, cipher=cipher, key=key)
        try:
            source.backup(target_db)
            _integrity(target_db)
        finally:
            target_db.close()
        with backup.open("rb") as handle:
            os.fsync(handle.fileno())
        return backup
    finally:
        source.close()
