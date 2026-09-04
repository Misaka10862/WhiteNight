"""Managed upload and backup routes. Restoration remains an offline operation."""

import asyncio
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from whitenight.channels.types import AttachmentRecord
from whitenight.config import Settings
from whitenight.credentials.keychain import KeychainError
from whitenight.storage.backup import (
    BackupError,
    create_backup,
    resolve_recovery_key,
    verify_backup,
)
from whitenight.storage.maintenance import MaintenanceError
from whitenight.storage.receipts import AttachmentSessionNotFound, attachment_name
from whitenight.storage.sessions import SessionNotFoundError, SessionStore


def resource_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    workers = asyncio.Semaphore(2)
    backup_workers = asyncio.Semaphore(1)

    @router.post("/sessions/{session_id}/attachments", response_model=AttachmentRecord)
    async def upload(session_id: str, filename: str, request: Request) -> AttachmentRecord:
        store: SessionStore = request.app.state.store
        try:
            store.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(404, "会话不存在") from exc
        try:
            name = attachment_name(filename)
            if Path(filename).name != filename:
                raise ValueError("文件名不能包含路径")
        except ValueError as exc:
            raise HTTPException(400, "文件名无效") from exc
        async with workers:
            chunks: list[bytes] = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.max_file_bytes:
                    raise HTTPException(413, "文件超过接收大小限制")
                chunks.append(chunk)
            try:
                return await asyncio.to_thread(
                    store.attachments.receive_bytes,
                    session_id,
                    name,
                    b"".join(chunks),
                    channel="web",
                    mime=mimetypes.guess_type(name)[0] or "application/octet-stream",
                )
            except AttachmentSessionNotFound as exc:
                raise HTTPException(404, "会话不存在") from exc
            except (OSError, ValueError) as exc:
                raise HTTPException(409, "附件接收未完成，请检查存储目录后重试") from exc

    def backup_path(backup_id: str) -> Path:
        if Path(backup_id).name != backup_id or not backup_id.endswith(".bak"):
            raise HTTPException(400, "备份编号无效")
        path = settings.data_dir / "backups" / backup_id
        if path.is_symlink() or not path.is_file():
            raise HTTPException(404, "备份不存在")
        return path

    def metadata(path: Path) -> dict[str, object]:
        stat = path.stat()
        return {
            "id": path.name,
            "size": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        }

    @router.get("/backups")
    async def list_backups() -> list[dict[str, object]]:
        return [
            metadata(path)
            for path in sorted((settings.data_dir / "backups").glob("*.bak"), reverse=True)
            if path.is_file() and not path.is_symlink()
        ]

    @router.post("/backups")
    async def new_backup(request: Request) -> dict[str, object]:
        async with backup_workers:
            try:
                key = await asyncio.to_thread(
                    resolve_recovery_key,
                    settings,
                    create=True,
                    keychain=request.app.state.credentials,
                )
                path = (
                    settings.data_dir
                    / "backups"
                    / f"backup-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}.bak"
                )
                await asyncio.to_thread(create_backup, settings, path, key)
                return metadata(path)
            except (BackupError, MaintenanceError, KeychainError) as exc:
                raise HTTPException(409, f"备份未完成（{type(exc).__name__}）") from exc

    @router.post("/backups/{backup_id}/verify")
    @router.post("/backups/{backup_id}/preview")
    async def preview(backup_id: str, request: Request) -> dict[str, object]:
        path = backup_path(backup_id)
        async with backup_workers:
            try:
                key = await asyncio.to_thread(
                    resolve_recovery_key, settings, keychain=request.app.state.credentials
                )
                return await asyncio.to_thread(verify_backup, path, key)
            except (BackupError, KeychainError) as exc:
                raise HTTPException(400, "备份验证失败，请检查恢复密钥与备份完整性") from exc

    @router.get("/backups/{backup_id}/download")
    async def download(backup_id: str) -> FileResponse:
        return FileResponse(
            backup_path(backup_id), filename=backup_id, media_type="application/octet-stream"
        )

    return router
