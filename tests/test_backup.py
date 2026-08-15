"""加密备份与恢复测试：备份、预览、错误密钥、实际恢复。"""

from __future__ import annotations

from pathlib import Path

import pytest

from whitenight.config import Settings
from whitenight.storage import SessionStore
from whitenight.storage.backup import (
    BackupError,
    create_backup,
    restore_apply,
    restore_preview,
    verify_backup,
)
from whitenight.storage.engine import build_engine
from whitenight.storage.migrate import upgrade_to_head


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'whitenight.db'}",
        auto_migrate=False,
    )


@pytest.fixture
def prepared(tmp_path: Path) -> tuple[Settings, Path]:
    settings = _settings(tmp_path)
    settings.ensure_dirs()
    upgrade_to_head(settings)
    engine = build_engine(str(settings.database_url))
    store = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    session = store.create_session("备份测试")
    store.add_message(session.id, "user", "重要内容")
    engine.dispose()
    return settings, tmp_path


def test_backup_verify_preview_and_wrong_key(prepared) -> None:
    settings, tmp_path = prepared
    backup_path = tmp_path / "backup.bak"
    create_backup(settings, backup_path, "正确恢复密钥")

    assert verify_backup(backup_path, "正确恢复密钥")["counts"]["sessions"] == 1
    preview = restore_preview(backup_path, "正确恢复密钥")
    assert preview["counts"]["messages"] == 1

    with pytest.raises(BackupError, match="解密失败"):
        verify_backup(backup_path, "错误密钥")


def test_restore_apply_replaces_database(prepared) -> None:
    settings, tmp_path = prepared
    backup_path = tmp_path / "backup.bak"
    create_backup(settings, backup_path, "恢复密钥")

    # 当前库加一条“将被丢弃”的新数据
    engine = build_engine(str(settings.database_url))
    store = SessionStore(engine)
    store.create_session("恢复前新增")
    engine.dispose()

    result = restore_apply(settings, backup_path, "恢复密钥", service_health_url=None)
    assert result["safety_backup"]

    engine = build_engine(str(settings.database_url))
    sessions = SessionStore(engine).list_sessions()
    engine.dispose()
    assert [session.title for session in sessions] == ["备份测试"]
