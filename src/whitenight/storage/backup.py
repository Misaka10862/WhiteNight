"""WNBK1 authenticated backups and journalled, non-destructive generation restore.

SQLite snapshots are serialized in memory. SQLCipher snapshots remain encrypted,
using a key derived from the independent recovery passphrase. Managed resources
and old database generations are retained; this module never removes directories.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.fernet import Fernet

from whitenight.config import Settings
from whitenight.credentials.keychain import Keychain, get_keychain
from whitenight.storage.engine import backend_of, resolve_database_key
from whitenight.storage.maintenance import MaintenanceLock, database_file

BACKUP_MAGIC = b"WNBK1"
RESOURCE_ROOTS = ("attachments", "qq_files", "characters", "stickers")
MAX_BUNDLE_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEMBERS = 100_000


class BackupError(RuntimeError):
    """Backup validation or restore failure."""


def generate_recovery_key() -> str:
    return secrets.token_urlsafe(24)


def resolve_recovery_key(
    settings: Settings, *, create: bool = False, keychain: Keychain | None = None
) -> str:
    """Read the independent recovery key from Keychain, optionally initialize it."""
    keychain = keychain or get_keychain(settings.keychain_backend)
    account = "backup-recovery-key"
    key = keychain.get(settings.keychain_service, account)
    if not key and create:
        key = generate_recovery_key()
        keychain.set(settings.keychain_service, account, key)
    if not key:
        raise BackupError("Keychain 未配置备份恢复密钥，请先生成或导入恢复密钥")
    return key


def derive_key(passphrase: str, salt: bytes) -> bytes:
    digest = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 600_000)
    return base64.urlsafe_b64encode(digest)


def database_path(settings: Settings) -> Path:
    return database_file(settings)


def _database_key(settings: Settings) -> str | None:
    key = resolve_database_key(
        str(settings.database_url), settings.keychain_backend, settings.keychain_service
    )
    if backend_of(str(settings.database_url)) == "sqlcipher" and not key:
        raise BackupError("SQLCipher 数据库主密钥未配置")
    return key


def _connect(
    path: Path | str, *, cipher: bool = False, key: str | None = None, readonly: bool = False
) -> Any:
    module: Any = sqlite3
    if cipher:
        import sqlcipher3  # type: ignore[import-untyped]

        module = sqlcipher3
    if readonly and isinstance(path, Path):
        connection = module.connect(path.as_uri() + "?mode=ro", uri=True)
    else:
        connection = module.connect(str(path))
    if cipher and key:
        connection.execute("PRAGMA key = '" + key.replace("'", "''") + "'")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _integrity(connection: Any) -> None:
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        if not row or row[0] != "ok":
            raise BackupError("备份数据库完整性检查失败")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise BackupError("备份数据库外键检查失败")
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError("备份数据库无法读取或完整性检查失败") from exc


def _cipher_workfile() -> Path:
    # SQLCipher's DB-API lacks serialize/deserialize. Only encrypted snapshots are
    # placed here, with owner-only access; retain them rather than wiping folders.
    fd, filename = tempfile.mkstemp(prefix="whitenight-encrypted-snapshot-", suffix=".db")
    os.close(fd)
    return Path(filename)


def _snapshot(settings: Settings, snapshot_key: str) -> bytes:
    cipher = backend_of(str(settings.database_url)) == "sqlcipher"
    source = _connect(
        database_path(settings), cipher=cipher, key=_database_key(settings), readonly=True
    )
    target_path: Path | str = _cipher_workfile() if cipher else ":memory:"
    target = _connect(target_path, cipher=cipher, key=snapshot_key if cipher else None)
    try:
        source.backup(target)
        _integrity(target)
        if cipher:
            target.close()
            return Path(target_path).read_bytes()
        return bytes(target.serialize())
    finally:
        target.close()
        source.close()


def _add_bytes(tar: tarfile.TarFile, name: str, content: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(content)
    member.mode = 0o600
    tar.addfile(member, io.BytesIO(content))


def create_backup(settings: Settings, output_path: Path, passphrase: str) -> Path:
    """Create an authenticated full backup; shared lock permits online snapshots."""
    with MaintenanceLock(settings, exclusive=False):
        _require_clean_journal(settings)
        if not database_path(settings).is_file():
            raise BackupError("数据库不存在")
        output_path = output_path.expanduser().resolve()
        if output_path.exists():
            raise BackupError("备份目标已存在，请使用新的文件名")
        salt = secrets.token_bytes(16)
        key = derive_key(passphrase, salt)
        manifest = {
            "version": 2,
            "backend": backend_of(str(settings.database_url)),
            "resources": list(RESOURCE_ROOTS),
        }
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as tar:
            _add_bytes(tar, "manifest.json", json.dumps(manifest).encode())
            _add_bytes(tar, "whitenight.db", _snapshot(settings, key.decode()))
            for name in RESOURCE_ROOTS:
                folder = settings.data_dir / name
                if folder.is_symlink():
                    raise BackupError("资源目录不能是符号链接")
                if not folder.exists():
                    continue
                for path in sorted(folder.rglob("*")):
                    if path.is_symlink() or not (path.is_file() or path.is_dir()):
                        raise BackupError("备份不支持符号链接或特殊文件")
                    if path.is_file():
                        _add_bytes(
                            tar, f"{name}/{path.relative_to(folder).as_posix()}", path.read_bytes()
                        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        data = BACKUP_MAGIC + salt + Fernet(key).encrypt(stream.getvalue())
        with output_path.open("xb") as handle:
            os.chmod(output_path, 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return output_path


def _decrypt(backup_path: Path, passphrase: str) -> tuple[bytes, str]:
    path = backup_path.expanduser().resolve()
    if path.stat().st_size > MAX_BUNDLE_BYTES:
        raise BackupError("备份包超过大小限制")
    data = path.read_bytes()
    if len(data) < len(BACKUP_MAGIC) + 16 or not data.startswith(BACKUP_MAGIC):
        raise BackupError("不是有效的 WhiteNight 备份文件")
    salt = data[len(BACKUP_MAGIC) : len(BACKUP_MAGIC) + 16]
    key = derive_key(passphrase, salt)
    try:
        return Fernet(key).decrypt(data[len(BACKUP_MAGIC) + 16 :]), key.decode()
    except Exception as exc:
        raise BackupError("解密失败：恢复密钥错误或文件损坏") from exc


def decrypt_bundle(backup_path: Path, passphrase: str) -> bytes:
    return _decrypt(backup_path, passphrase)[0]


def _read_bundle(
    backup_path: Path, passphrase: str
) -> tuple[dict[str, bytes], str, str, list[str]]:
    raw, key = _decrypt(backup_path, passphrase)
    files: dict[str, bytes] = {}
    size = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            for index, member in enumerate(tar):
                path = PurePosixPath(member.name)
                if member.name.rstrip("/") != path.as_posix():
                    raise BackupError("备份包路径未规范化")
                if (
                    index >= MAX_MEMBERS
                    or path.is_absolute()
                    or ".." in path.parts
                    or "\\" in member.name
                ):
                    raise BackupError("备份包路径或文件数量无效")
                if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                    raise BackupError("备份包含链接或特殊文件")
                if member.name in ("whitenight.db", "manifest.json"):
                    if not member.isfile():
                        raise BackupError("备份包数据库或清单不是文件")
                elif not path.parts or path.parts[0] not in RESOURCE_ROOTS:
                    raise BackupError("备份包包含未知资源")
                elif member.isfile() and len(path.parts) < 2:
                    raise BackupError("资源根必须是目录")
                if member.isdir():
                    continue
                if member.name in files:
                    raise BackupError("备份包包含重复文件")
                size += member.size
                if member.size < 0 or size > MAX_BUNDLE_BYTES:
                    raise BackupError("备份包解压后超过大小限制")
                handle = tar.extractfile(member)
                if handle is None:
                    raise BackupError("备份成员无法读取")
                files[member.name] = handle.read()
        if "whitenight.db" not in files:
            raise BackupError("备份包中缺少数据库")
        backend = "sqlite"
        resources = ["attachments"]  # Legacy WNBK1 never managed the other roots.
        if "manifest.json" in files:
            manifest = json.loads(files["manifest.json"])
            if manifest.get("version") != 2 or manifest.get("backend") not in (
                "sqlite",
                "sqlcipher",
            ):
                raise BackupError("不支持的备份清单版本")
            if manifest.get("resources") != list(RESOURCE_ROOTS):
                raise BackupError("备份资源清单无效")
            backend = manifest["backend"]
            resources = list(RESOURCE_ROOTS)
        return files, key, backend, resources
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError("备份包损坏") from exc


@contextmanager
def _bundle_connection(content: bytes, key: str, backend: str) -> Iterator[Any]:
    if backend == "sqlcipher":
        path = _cipher_workfile()
        path.write_bytes(content)
        connection = _connect(path, cipher=True, key=key, readonly=True)
    else:
        connection = sqlite3.connect(":memory:")
        try:
            # Online backup contains every committed page, but can retain the
            # source WAL header. deserialize() has no filesystem for WAL files.
            if content.startswith(b"SQLite format 3\x00") and content[18:20] == b"\x02\x02":
                content = content[:18] + b"\x01\x01" + content[20:]
            connection.deserialize(content)
        except sqlite3.DatabaseError as exc:
            connection.close()
            raise BackupError("备份数据库无法读取") from exc
    try:
        _integrity(connection)
        yield connection
    finally:
        connection.close()


def _preview(connection: Any, files: dict[str, bytes], backend: str) -> dict[str, object]:
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    counts = {}
    for table in (
        "sessions",
        "messages",
        "profile_facts",
        "episodic_memories",
        "character_profiles",
        "lorebooks",
        "agent_tasks",
    ):
        if table in tables:
            counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    resources = {
        name: sum(path.startswith(name + "/") for path in files) for name in RESOURCE_ROOTS
    }
    return {
        "tables": sorted(tables),
        "counts": counts,
        "attachments": resources["attachments"],
        "resources": resources,
        "backend": backend,
    }


def verify_backup(backup_path: Path, passphrase: str) -> dict[str, object]:
    files, key, backend, _ = _read_bundle(backup_path, passphrase)
    with _bundle_connection(files["whitenight.db"], key, backend) as connection:
        return _preview(connection, files, backend)


def restore_preview(backup_path: Path, passphrase: str) -> dict[str, object]:
    return verify_backup(backup_path, passphrase)


def _journal_path(settings: Settings) -> Path:
    database = database_path(settings)
    return database.with_name(f".{database.name}.restore-journal.json")


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_journal(settings: Settings, journal: dict[str, Any]) -> None:
    path = _journal_path(settings)
    temporary = path.with_name(path.name + "." + secrets.token_hex(4))
    with temporary.open("x") as handle:
        os.chmod(temporary, 0o600)
        json.dump(journal, handle)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    _sync_directory(path.parent)


def _load_journal(settings: Settings) -> dict[str, Any] | None:
    path = _journal_path(settings)
    if not path.exists():
        return None
    try:
        journal = json.loads(path.read_text())
        if not isinstance(journal, dict) or not re.fullmatch(
            r"[a-f0-9]{16}", journal.get("generation", "")
        ):
            raise ValueError
        if journal.get("state") not in ("prepared", "committed", "rolled_back"):
            raise ValueError
        if not isinstance(journal.get("resources"), list) or any(
            name not in RESOURCE_ROOTS for name in journal["resources"]
        ):
            raise ValueError
        if not isinstance(journal.get("originals"), dict):
            raise ValueError
        expected = {"database", "database-wal", "database-shm", *journal["resources"]}
        if set(journal["originals"]) != expected or any(
            type(value) is not bool for value in journal["originals"].values()
        ):
            raise ValueError
        return journal
    except Exception as exc:
        raise BackupError("恢复日志损坏，需要人工检查，拒绝启动或覆盖") from exc


def _require_clean_journal(settings: Settings) -> None:
    journal = _load_journal(settings)
    if journal and journal["state"] == "prepared":
        raise BackupError("检测到未完成恢复，请先在独占维护锁内恢复日志")


def _entries(settings: Settings, journal: dict[str, Any]) -> list[tuple[str, Path, Path, Path]]:
    database = database_path(settings)
    db_generation = database.parent / f".{database.name}.restore" / journal["generation"]
    resource_generation = settings.data_dir.resolve() / ".restore" / journal["generation"]
    entries = []
    for suffix in ("", "-wal", "-shm"):
        name = "database" + suffix
        entries.append(
            (
                name,
                Path(str(database) + suffix),
                db_generation / "new" / name,
                db_generation / "old" / name,
            )
        )
    for name in journal["resources"]:
        entries.append(
            (
                name,
                settings.data_dir.resolve() / name,
                resource_generation / "new" / name,
                resource_generation / "old" / name,
            )
        )
    return entries


def _move(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise BackupError("恢复代际目标已存在，拒绝覆盖")
    source.rename(destination)
    _sync_directory(source.parent)
    _sync_directory(destination.parent)


def _rollback(settings: Settings, journal: dict[str, Any]) -> None:
    for name, live, staged, old in reversed(_entries(settings, journal)):
        if old.exists():
            if live.exists():
                _move(live, old.parent.parent / "failed" / name)
            _move(old, live)
        elif not journal["originals"].get(name, False) and live.exists() and not staged.exists():
            _move(live, old.parent.parent / "failed" / name)
    journal["state"] = "rolled_back"
    _write_journal(settings, journal)


def recover_interrupted_restore(
    settings: Settings, *, maintenance_lock: MaintenanceLock | None = None
) -> dict[str, object] | None:
    """Idempotently roll back an uncommitted generation before startup/migration."""
    if maintenance_lock is None:
        with MaintenanceLock(settings) as lock:
            return recover_interrupted_restore(settings, maintenance_lock=lock)
    maintenance_lock.validate(settings)
    journal = _load_journal(settings)
    if journal and journal["state"] == "prepared":
        _rollback(settings, journal)
        return {"generation": journal["generation"], "state": "rolled_back"}
    return None


def restore_apply(
    settings: Settings, backup_path: Path, passphrase: str, *, service_health_url: str | None = None
) -> dict[str, object]:
    """Restore under an exclusive lock; retain old generations and roll back errors.

    service_health_url is retained for caller compatibility. An HTTP probe is not
    an exclusion primitive; only the shared service/exclusive maintenance lock is.
    """
    del service_health_url
    with MaintenanceLock(settings) as lock:
        recover_interrupted_restore(settings, maintenance_lock=lock)
        files, key, backend, resources = _read_bundle(backup_path, passphrase)
        if backend != backend_of(str(settings.database_url)):
            raise BackupError("备份与目标数据库类型不一致；跨 SQLite/SQLCipher 转换需独立迁移")
        with _bundle_connection(files["whitenight.db"], key, backend) as source:
            preview = _preview(source, files, backend)
            journal: dict[str, Any] = {
                "generation": secrets.token_hex(8),
                "state": "prepared",
                "resources": resources,
                "originals": {},
            }
            entries = _entries(settings, journal)
            for name, live, staged, old in entries:
                if live.is_symlink():
                    raise BackupError("恢复目标不能是符号链接")
                staged.parent.mkdir(parents=True, exist_ok=True)
                old.parent.mkdir(parents=True, exist_ok=True)
                journal["originals"][name] = live.exists()
            staged_db = entries[0][2]
            target = _connect(staged_db, cipher=backend == "sqlcipher", key=_database_key(settings))
            try:
                source.backup(target)
                _integrity(target)
            finally:
                target.close()
            os.chmod(staged_db, 0o600)
            for name, _, staged, _ in entries[3:]:
                staged.mkdir()
                for filename, content in files.items():
                    if filename.startswith(name + "/"):
                        destination = staged / PurePosixPath(filename).relative_to(name)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(content)
                        os.chmod(destination, 0o600)
            for _, _, staged, _ in entries:
                paths = (
                    [staged]
                    if staged.is_file()
                    else list(staged.rglob("*"))
                    if staged.is_dir()
                    else []
                )
                for path in paths:
                    if path.is_file():
                        with path.open("rb") as handle:
                            os.fsync(handle.fileno())
                for directory in reversed([path for path in paths if path.is_dir()]):
                    _sync_directory(directory)
                if staged.is_dir():
                    _sync_directory(staged)
                _sync_directory(staged.parent)
                _sync_directory(staged.parent.parent)
            _write_journal(settings, journal)
            try:
                for _, live, staged, old in entries:
                    if live.exists():
                        _move(live, old)
                    if staged.exists():
                        _move(staged, live)
            except Exception:
                _rollback(settings, journal)
                raise
            # A journal write may replace the file successfully, then fail on
            # directory fsync. Do not start rollback after that uncertain commit:
            # disk may already say committed. Every live entry is now installed,
            # so recovery can safely choose the complete old or new generation
            # according to the journal that survived, without mixing generations.
            journal["state"] = "committed"
            _write_journal(settings, journal)
        return {
            "restored_database": str(database_path(settings)),
            "safety_backup": str(entries[0][3]) if journal["originals"]["database"] else None,
            "generation": journal["generation"],
            "preview": preview,
        }
