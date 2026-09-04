"""加密备份与恢复测试：备份、预览、错误密钥、实际恢复。"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from whitenight.config import Settings
from whitenight.storage import SessionStore
from whitenight.storage.backup import (
    BACKUP_MAGIC,
    BackupError,
    create_backup,
    derive_key,
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


def test_backup_covers_all_managed_resource_roots(prepared) -> None:
    settings, tmp_path = prepared
    for name in ("attachments", "qq_files", "characters", "stickers"):
        folder = settings.data_dir / name
        folder.mkdir(exist_ok=True)
        (folder / "original.bin").write_bytes(name.encode())
    archive = tmp_path / "resources.bak"
    create_backup(settings, archive, "recovery")
    import whitenight.storage.backup as backup_module

    with tarfile.open(
        fileobj=io.BytesIO(backup_module.decrypt_bundle(archive, "recovery")), mode="r:gz"
    ) as bundle:
        names = set(bundle.getnames())
    assert all(
        f"{name}/original.bin" in names
        for name in ("attachments", "qq_files", "characters", "stickers")
    )


def test_restore_rejects_invalid_database_before_replacing_current(prepared) -> None:
    settings, tmp_path = prepared
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        member = tarfile.TarInfo("whitenight.db")
        member.size = len(b"invalid database")
        tar.addfile(member, io.BytesIO(b"invalid database"))
    salt = b"x" * 16
    archive = tmp_path / "invalid.bak"
    archive.write_bytes(
        BACKUP_MAGIC + salt + Fernet(derive_key("recovery", salt)).encrypt(stream.getvalue())
    )
    with pytest.raises(BackupError):
        restore_apply(settings, archive, "recovery")
    engine = build_engine(str(settings.database_url))
    assert len(SessionStore(engine).list_sessions()) == 1
    engine.dispose()


def _titles(settings: Settings) -> list[str]:
    from whitenight.storage.engine import resolve_database_key

    engine = build_engine(
        str(settings.database_url), key=resolve_database_key(str(settings.database_url))
    )
    try:
        return [session.title for session in SessionStore(engine).list_sessions()]
    finally:
        engine.dispose()


def test_restore_rolls_back_database_and_resources_without_deletion(prepared, monkeypatch):
    import whitenight.storage.backup as module

    settings, tmp_path = prepared
    folder = settings.data_dir / "attachments"
    folder.mkdir(exist_ok=True)
    (folder / "old.txt").write_text("backup contents")
    archive = tmp_path / "rollback.bak"
    create_backup(settings, archive, "recovery")
    (folder / "old.txt").write_text("current contents")
    engine = build_engine(str(settings.database_url))
    SessionStore(engine).create_session("current session")
    engine.dispose()
    move = module._move
    failed = False

    def inject(source, destination):
        nonlocal failed
        if source.name == "attachments" and source.parent.name == "new" and not failed:
            failed = True
            raise OSError("injected installation failure")
        move(source, destination)

    monkeypatch.setattr(module, "_move", inject)
    with pytest.raises(OSError, match="injected"):
        restore_apply(settings, archive, "recovery")
    assert set(_titles(settings)) == {"备份测试", "current session"}
    assert (folder / "old.txt").read_text() == "current contents"
    assert module.recover_interrupted_restore(settings) is None
    assert list(settings.data_dir.glob(".whitenight.db.restore/*/failed/database"))


def test_interrupted_restore_recovers_idempotently(prepared, monkeypatch):
    import whitenight.storage.backup as module

    settings, tmp_path = prepared
    archive = tmp_path / "crash.bak"
    create_backup(settings, archive, "recovery")
    engine = build_engine(str(settings.database_url))
    SessionStore(engine).create_session("preserve after crash")
    engine.dispose()
    move = module._move

    def crash_after_database_install(source, destination):
        move(source, destination)
        if source.name == "database" and source.parent.name == "new":
            raise SystemExit("simulated process loss")

    monkeypatch.setattr(module, "_move", crash_after_database_install)
    with pytest.raises(SystemExit):
        restore_apply(settings, archive, "recovery")
    monkeypatch.setattr(module, "_move", move)
    with pytest.raises(BackupError, match="未完成"):
        create_backup(settings, tmp_path / "blocked.bak", "recovery")
    assert module.recover_interrupted_restore(settings)["state"] == "rolled_back"
    assert module.recover_interrupted_restore(settings) is None
    assert set(_titles(settings)) == {"备份测试", "preserve after crash"}


def test_shared_service_lock_blocks_restore_and_upgrade(prepared):
    from whitenight.storage.maintenance import MaintenanceError, MaintenanceLock

    settings, tmp_path = prepared
    archive = tmp_path / "lock.bak"
    with MaintenanceLock(settings) as lock:
        lock.downgrade()
        create_backup(settings, archive, "recovery")
        with pytest.raises(MaintenanceError):
            restore_apply(settings, archive, "recovery", service_health_url="http://127.0.0.1:1")
        with pytest.raises(MaintenanceError):
            upgrade_to_head(settings)
    restore_apply(settings, archive, "recovery")


def test_restore_retains_old_resource_generations(prepared):
    settings, tmp_path = prepared
    archive = tmp_path / "generations.bak"
    for name in ("attachments", "qq_files", "characters", "stickers"):
        folder = settings.data_dir / name
        folder.mkdir(exist_ok=True)
        (folder / "asset.txt").write_text("backed up")
    create_backup(settings, archive, "recovery")
    for name in ("attachments", "qq_files", "characters", "stickers"):
        (settings.data_dir / name / "asset.txt").write_text("preserved old generation")
    result = restore_apply(settings, archive, "recovery")
    for name in ("attachments", "qq_files", "characters", "stickers"):
        assert (settings.data_dir / name / "asset.txt").read_text() == "backed up"
        old = settings.data_dir / ".restore" / result["generation"] / "old" / name / "asset.txt"
        assert old.read_text() == "preserved old generation"


def test_legacy_wnbk1_archive_still_restores(prepared):
    import whitenight.storage.backup as module

    settings, tmp_path = prepared
    modern = tmp_path / "modern.bak"
    create_backup(settings, modern, "recovery")
    with tarfile.open(
        fileobj=io.BytesIO(module.decrypt_bundle(modern, "recovery")), mode="r:gz"
    ) as tar:
        database = tar.extractfile("whitenight.db").read()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        member = tarfile.TarInfo("whitenight.db")
        member.size = len(database)
        tar.addfile(member, io.BytesIO(database))
    salt = b"z" * 16
    legacy = tmp_path / "legacy.bak"
    legacy.write_bytes(
        BACKUP_MAGIC + salt + Fernet(derive_key("recovery", salt)).encrypt(stream.getvalue())
    )
    extra = settings.data_dir / "qq_files"
    extra.mkdir()
    (extra / "untouched.txt").write_text("legacy has no QQ file inventory")
    assert restore_apply(settings, legacy, "recovery")["preview"]["counts"]["sessions"] == 1
    assert (extra / "untouched.txt").exists()


def test_sqlcipher_backup_restore_uses_independent_recovery_key(tmp_path, monkeypatch):
    pytest.importorskip("sqlcipher3")
    settings = _settings(tmp_path).model_copy(
        update={"database_url": f"sqlcipher:///{tmp_path / 'data' / 'encrypted.db'}"}
    )
    monkeypatch.setenv("WHITENIGHT_DATABASE_KEY", "first-master-key")
    upgrade_to_head(settings)
    engine = build_engine(str(settings.database_url), key="first-master-key")
    SessionStore(engine).create_session("encrypted session")
    engine.dispose()
    archive = tmp_path / "cipher.bak"
    create_backup(settings, archive, "independent recovery")
    monkeypatch.setenv("WHITENIGHT_DATABASE_KEY", "replacement-master-key")
    assert verify_backup(archive, "independent recovery")["counts"]["sessions"] == 1
    restore_apply(settings, archive, "independent recovery")
    assert _titles(settings) == ["encrypted session"]
    assert not (settings.data_dir / "encrypted.db").read_bytes().startswith(b"SQLite format")


def test_sqlcipher_migration_verifies_encrypted_safety_copy(tmp_path, monkeypatch):
    pytest.importorskip("sqlcipher3")
    from whitenight.storage import migrate
    from whitenight.storage.backup import _connect

    settings = _settings(tmp_path).model_copy(
        update={"database_url": f"sqlcipher:///{tmp_path / 'data' / 'encrypted.db'}"}
    )
    monkeypatch.setenv("WHITENIGHT_DATABASE_KEY", "test-migration-key")
    upgrade_to_head(settings)
    connection = _connect(settings.data_dir / "encrypted.db", cipher=True, key="test-migration-key")
    connection.execute("UPDATE alembic_version SET version_num='0008'")
    connection.commit()
    connection.close()
    upgrades = []
    monkeypatch.setattr(migrate.command, "upgrade", lambda *_: upgrades.append(True))
    upgrade_to_head(settings)
    assert upgrades == [True]
    snapshots = list((settings.data_dir / "backups").glob("pre-migrate-0008-*.db"))
    assert len(snapshots) == 1
    assert not snapshots[0].read_bytes().startswith(b"SQLite format")
    connection = _connect(snapshots[0], cipher=True, key="test-migration-key", readonly=True)
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    connection.close()
    upgrades.clear()
    monkeypatch.setattr(
        migrate,
        "_integrity",
        lambda _: (_ for _ in ()).throw(BackupError("injected backup failure")),
    )
    with pytest.raises(BackupError, match="injected"):
        upgrade_to_head(settings)
    assert upgrades == []


def test_service_without_auto_migration_refuses_unfinished_restore(settings, engine):
    from fastapi.testclient import TestClient

    from whitenight.agent.service import DummyProvider
    from whitenight.api.app import create_app
    from whitenight.storage.backup import _write_journal

    del engine
    _write_journal(
        settings,
        {
            "generation": "0123456789abcdef",
            "state": "prepared",
            "resources": [],
            "originals": {"database": True, "database-wal": False, "database-shm": False},
        },
    )
    with (
        pytest.raises(BackupError, match="未完成"),
        TestClient(create_app(settings, model_provider=DummyProvider())),
    ):
        pass


def test_commit_journal_failure_cannot_leave_committed_mixed_generation(prepared, monkeypatch):
    import whitenight.storage.backup as module

    settings, tmp_path = prepared
    folder = settings.data_dir / "attachments"
    folder.mkdir(exist_ok=True)
    asset = folder / "asset.txt"
    asset.write_text("backup generation")
    archive = tmp_path / "commit-window.bak"
    create_backup(settings, archive, "recovery")
    asset.write_text("current generation")
    engine = build_engine(str(settings.database_url))
    SessionStore(engine).create_session("preserve current generation")
    engine.dispose()
    write_journal, move = module._write_journal, module._move

    def uncertain_commit(config, journal):
        write_journal(config, journal)
        if journal["state"] == "committed":
            raise OSError("commit directory fsync failed after journal replacement")

    def interrupted_rollback(source, destination):
        move(source, destination)
        if source == folder and destination.parent.name == "failed":
            raise SystemExit("process lost during rollback")

    monkeypatch.setattr(module, "_write_journal", uncertain_commit)
    monkeypatch.setattr(module, "_move", interrupted_rollback)
    with pytest.raises((OSError, SystemExit)):
        restore_apply(settings, archive, "recovery")
    monkeypatch.setattr(module, "_write_journal", write_journal)
    monkeypatch.setattr(module, "_move", move)
    module.recover_interrupted_restore(settings)
    observed = (set(_titles(settings)), asset.read_text() if asset.exists() else None)
    assert observed in [
        ({"备份测试"}, "backup generation"),
        ({"备份测试", "preserve current generation"}, "current generation"),
    ]
