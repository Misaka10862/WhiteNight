"""加密备份与恢复：SQLite online backup + 附件目录 + Fernet 加密。

格式：WNBK1 | salt(16B) | Fernet(token(tar.gz))
恢复密钥独立于数据库主密钥；生产 SQLCipher 文件先解密或经 SQLCipher 连接备份。
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

from whitenight.config import Settings
from whitenight.storage.engine import backend_of

BACKUP_MAGIC = b"WNBK1"


class BackupError(RuntimeError):
    """备份/恢复失败。"""


def generate_recovery_key() -> str:
    return secrets.token_urlsafe(24)


def derive_key(passphrase: str, salt: bytes) -> bytes:
    digest = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 600_000)
    return base64.urlsafe_b64encode(digest)


def database_path(settings: Settings) -> Path:
    if backend_of(str(settings.database_url)) != "sqlite":
        raise BackupError("生产 SQLCipher 数据库请先用 SQLCipher 连接解密后备份")
    from sqlalchemy.engine import make_url

    url = make_url(str(settings.database_url))
    if not url.database or url.database == ":memory:":
        raise BackupError("内存数据库不可备份")
    return Path(url.database).expanduser().resolve()


def create_backup(settings: Settings, output_path: Path, passphrase: str) -> Path:
    """全量备份：数据库（online backup）+ attachments，打包加密。"""
    db_path = database_path(settings)
    if not db_path.exists():
        raise BackupError(f"数据库不存在：{db_path}")
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        db_copy = tmp_dir / "whitenight.db"
        source = sqlite3.connect(str(db_path))
        try:
            target = sqlite3.connect(str(db_copy))
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()

        attachments = settings.data_dir / "attachments"
        if attachments.exists():
            import shutil

            shutil.copytree(attachments, tmp_dir / "attachments")

        archive = tmp_dir / "bundle.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(db_copy, arcname="whitenight.db")
            if (tmp_dir / "attachments").exists():
                tar.add(tmp_dir / "attachments", arcname="attachments")

        salt = secrets.token_bytes(16)
        fernet = Fernet(derive_key(passphrase, salt))
        token = fernet.encrypt(archive.read_bytes())
        output_path.write_bytes(BACKUP_MAGIC + salt + token)
    return output_path


def decrypt_bundle(backup_path: Path, passphrase: str) -> bytes:
    data = backup_path.expanduser().resolve().read_bytes()
    if len(data) < len(BACKUP_MAGIC) + 16:
        raise BackupError("备份文件损坏")
    if data[: len(BACKUP_MAGIC)] != BACKUP_MAGIC:
        raise BackupError("不是 WhiteNight 备份文件")
    salt = data[len(BACKUP_MAGIC) : len(BACKUP_MAGIC) + 16]
    token = data[len(BACKUP_MAGIC) + 16 :]
    fernet = Fernet(derive_key(passphrase, salt))
    try:
        return fernet.decrypt(token)
    except Exception as exc:
        raise BackupError("解密失败：恢复密钥错误或文件损坏") from exc


def verify_backup(backup_path: Path, passphrase: str) -> dict[str, object]:
    bundle = decrypt_bundle(backup_path, passphrase)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        archive = tmp_dir / "bundle.tar.gz"
        archive.write_bytes(bundle)
        try:
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(tmp_dir, filter="data")
        except tarfile.TarError as exc:
            raise BackupError(f"备份包损坏：{exc}") from exc
        db_copy = tmp_dir / "whitenight.db"
        if not db_copy.exists():
            raise BackupError("备份包中缺少数据库")
        connection = sqlite3.connect(str(db_copy))
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise BackupError(f"备份数据库完整性检查失败：{integrity}")
        finally:
            connection.close()
        return preview_directory(tmp_dir)


def restore_preview(backup_path: Path, passphrase: str) -> dict[str, object]:
    return verify_backup(backup_path, passphrase)


def preview_directory(tmp_dir: Path) -> dict[str, object]:
    db_copy = tmp_dir / "whitenight.db"
    connection = sqlite3.connect(str(db_copy))
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        counts: dict[str, object] = {}
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
                counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        attachments = tmp_dir / "attachments"
        attachment_files = (
            [str(path.name) for path in attachments.glob("*")] if attachments.exists() else []
        )
        return {"tables": sorted(tables), "counts": counts, "attachments": len(attachment_files)}
    finally:
        connection.close()


def restore_apply(
    settings: Settings,
    backup_path: Path,
    passphrase: str,
    *,
    service_health_url: str | None = None,
) -> dict[str, object]:
    """恢复：先做当前库安全备份，再替换；服务运行中默认拒绝。"""
    import httpx

    if service_health_url:
        try:
            response = httpx.get(f"{service_health_url}/healthz", timeout=2.0, trust_env=False)
            if response.status_code == 200:
                raise BackupError("服务正在运行：请先停止服务再恢复（避免覆盖活跃数据库）")
        except BackupError:
            raise
        except Exception:
            pass  # 无法连接视为已停止

    bundle = decrypt_bundle(backup_path, passphrase)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        archive = tmp_dir / "bundle.tar.gz"
        archive.write_bytes(bundle)
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(tmp_dir, filter="data")

        db_copy = tmp_dir / "whitenight.db"
        if not db_copy.exists():
            raise BackupError("备份包中缺少数据库")
        current_db = database_path(settings)
        current_db.parent.mkdir(parents=True, exist_ok=True)
        safety: Path | None = None
        if current_db.exists():
            safety = current_db.with_suffix(f".pre-restore-{secrets.token_hex(4)}.db")
            current_db.replace(safety)
        try:
            import shutil

            shutil.copy2(db_copy, current_db)
            attachments = settings.data_dir / "attachments"
            backup_attachments = tmp_dir / "attachments"
            if backup_attachments.exists():
                if attachments.exists():
                    shutil.rmtree(attachments)
                shutil.copytree(backup_attachments, attachments)
        except Exception:
            if safety is not None:
                current_db.replace(safety)  # 恢复失败回滚
            raise
        return {
            "restored_database": str(current_db),
            "safety_backup": str(safety) if safety else None,
            "preview": preview_directory(tmp_dir),
        }
