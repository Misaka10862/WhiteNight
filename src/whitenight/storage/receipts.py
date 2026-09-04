"""Trusted attachment receipts with content verification and atomic message binding."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from whitenight.channels.types import AttachmentRecord
from whitenight.storage.application_models import AttachmentReceipt
from whitenight.storage.models import Message
from whitenight.storage.models import Session as Conversation


class AttachmentSessionNotFound(ValueError):
    """The upload's owning conversation no longer exists."""


def attachment_name(value: str) -> str:
    name = Path(value).name.strip()
    if (
        not name
        or name in {".", ".."}
        or len(name) > 200
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or "\\" in name
    ):
        raise ValueError("附件文件名无效")
    return name


def attachment_snapshot(path: Path, data_dir: Path) -> tuple[Path, int, str]:
    """Hash a regular managed file and reject replacement during verification."""
    try:
        if path.is_symlink():
            raise ValueError("附件路径不能是符号链接")
        resolved = path.resolve(strict=True)
        root = data_dir.resolve()
        if not any(resolved.is_relative_to(root / name) for name in ("attachments", "qq_files")):
            raise ValueError("附件不在受管理的接收目录中")
        # Keep each directory open while traversing below the managed root. A
        # concurrent parent-directory replacement must not redirect the file read.
        relative = resolved.relative_to(root)
        parent_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in relative.parts[:-1]:
                child_fd = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
                )
                os.close(parent_fd)
                parent_fd = child_fd
            descriptor = os.open(
                relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd
            )
        finally:
            os.close(parent_fd)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("附件必须是普通文件")
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
            after = os.fstat(handle.fileno())
            current = path.stat(follow_symlinks=False)

            def identity(item: os.stat_result) -> tuple[int, int, int, int]:
                return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns

            if identity(before) != identity(after) or identity(after) != identity(current):
                raise ValueError("附件在完整性检查期间发生变化")
            return resolved, after.st_size, digest
    except OSError as exc:
        raise ValueError("附件已不可读取，请重新上传") from exc


def verify_attachment(receipt: AttachmentRecord, data_dir: Path) -> Path:
    if receipt.status != "ready" or not receipt.path or not receipt.sha256:
        raise ValueError(receipt.error or "附件未成功接收")
    path, size, digest = attachment_snapshot(Path(receipt.path), data_dir)
    if size != receipt.size or digest != receipt.sha256:
        raise ValueError("附件内容发生变化，完整性检查失败，请重新上传")
    return path


class AttachmentStore:
    def __init__(self, engine: Engine, data_dir: Path | None = None) -> None:
        self.engine = engine
        database = engine.url.database
        self.data_dir = data_dir or (
            Path(database).resolve().parent if database and database != ":memory:" else None
        )

    def _root(self) -> Path:
        if self.data_dir is None:
            raise ValueError("附件接收目录未配置")
        return self.data_dir

    def receive_bytes(
        self, session_id: str, name: str, data: bytes, *, channel: str, mime: str | None = None
    ) -> AttachmentRecord:
        """Hold session ownership while creating a private file and its receipt."""
        name = attachment_name(name)
        with Session(self.engine, expire_on_commit=False) as orm:
            # This conditional write acquires SQLite's writer lock before touching
            # the filesystem, preventing concurrent session deletion from orphaning
            # an otherwise successful upload.
            owner = orm.execute(
                update(Conversation)
                .where(Conversation.id == session_id)
                .values(updated_at=Conversation.updated_at)
                .returning(Conversation.id)
            ).scalar_one_or_none()
            if owner is None:
                raise AttachmentSessionNotFound("会话不存在")
            directory = self._root().resolve() / "attachments"
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            folder_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            basename = f"{uuid4()}-{name}"
            try:
                descriptor = os.open(
                    basename,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=folder_fd,
                )
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                os.close(folder_fd)
            receipt = self.record(
                session_id,
                name,
                channel=channel,
                path=directory / basename,
                mime=mime,
                transaction=orm,
            )
            orm.commit()
            return receipt

    @staticmethod
    def _message_owner(orm: Session, session_id: str, message_id: str) -> None:
        message = orm.get(Message, message_id)
        if message is None or message.session_id != session_id or message.role != "user":
            raise ValueError("附件只能绑定到当前会话的用户消息")

    def record(
        self,
        session_id: str,
        name: str,
        *,
        channel: str,
        path: Path | None = None,
        source_message_id: str | None = None,
        error: str | None = None,
        mime: str | None = None,
        transaction: Session | None = None,
    ) -> AttachmentRecord:
        name = attachment_name(name)
        digest, size = None, 0
        if path is not None:
            if error:
                raise ValueError("附件接收状态冲突")
            path, size, digest = attachment_snapshot(path, self._root())
        else:
            error = error or "附件未成功接收"

        def insert(orm: Session) -> AttachmentRecord:
            if orm.get(Conversation, session_id) is None:
                raise AttachmentSessionNotFound("会话不存在")
            if source_message_id is not None:
                self._message_owner(orm, session_id, source_message_id)
            row = AttachmentReceipt(
                session_id=session_id,
                name=name,
                channel=channel,
                source_message_id=source_message_id,
                status="ready" if path else "failed",
                path=path.relative_to(self._root().resolve()).as_posix() if path else None,
                mime=mime,
                size=size,
                sha256=digest,
                error=error,
            )
            orm.add(row)
            orm.flush()
            return self._record(row)

        if transaction is not None:
            return insert(transaction)
        with Session(self.engine, expire_on_commit=False) as orm:
            result = insert(orm)
            orm.commit()
            return result

    def for_message(self, message_id: str, session_id: str | None = None) -> list[AttachmentRecord]:
        with Session(self.engine) as orm:
            query = select(AttachmentReceipt).where(
                AttachmentReceipt.source_message_id == message_id
            )
            if session_id is not None:
                query = query.where(AttachmentReceipt.session_id == session_id)
            return [
                self._record(row)
                for row in orm.scalars(
                    query.order_by(AttachmentReceipt.created_at, AttachmentReceipt.id)
                )
            ]

    def get(self, attachment_id: str, session_id: str) -> AttachmentRecord:
        with Session(self.engine) as orm:
            row = orm.get(AttachmentReceipt, attachment_id)
            if row is None or row.session_id != session_id:
                raise ValueError("附件不属于当前会话")
            record = self._record(row)
        if record.status == "ready":
            verify_attachment(record, self._root())
        return record

    def bind(
        self,
        ids: list[str],
        session_id: str,
        message_id: str,
        *,
        transaction: Session | None = None,
    ) -> None:
        if len(ids) != len(set(ids)):
            raise ValueError("同一附件不能重复绑定")

        def bind_rows(orm: Session) -> None:
            self._message_owner(orm, session_id, message_id)
            for item in ids:
                row = orm.get(AttachmentReceipt, item)
                if row is None or row.session_id != session_id or row.source_message_id is not None:
                    raise ValueError("附件不存在、已使用或不属于当前会话")
                verify_attachment(self._record(row), self._root())
                bound = orm.execute(
                    update(AttachmentReceipt)
                    .where(
                        AttachmentReceipt.id == item,
                        AttachmentReceipt.session_id == session_id,
                        AttachmentReceipt.source_message_id.is_(None),
                    )
                    .values(source_message_id=message_id)
                    .returning(AttachmentReceipt.id)
                ).scalar_one_or_none()
                if bound is None:
                    raise ValueError("附件已被其他消息使用")

        if transaction is not None:
            bind_rows(transaction)
        else:
            with Session(self.engine) as orm:
                bind_rows(orm)
                orm.commit()

    def _record(self, row: AttachmentReceipt) -> AttachmentRecord:
        path: str | None = None
        if row.path is not None:
            stored = Path(row.path)
            if stored.is_absolute():
                # Legacy absolute records remain tied to their actual location.
                # Never remap an arbitrary external path by its basename or suffix.
                path = str(stored)
            else:
                if (
                    not stored.parts
                    or stored.parts[0] not in {"attachments", "qq_files"}
                    or ".." in stored.parts
                ):
                    raise ValueError("附件存储路径无效")
                path = str(self._root().resolve() / stored)
        return AttachmentRecord(
            id=row.id,
            name=row.name,
            status=row.status,  # type: ignore[arg-type]
            source_message_id=row.source_message_id,
            path=path,
            mime=row.mime,
            size=row.size,
            sha256=row.sha256,
            error=row.error,
        )
