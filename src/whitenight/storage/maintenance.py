"""Process locks shared by service lifetimes and exclusive storage maintenance."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from types import TracebackType

from sqlalchemy.engine import make_url

from whitenight.config import Settings


class MaintenanceError(RuntimeError):
    """Storage is busy or an interrupted restore needs recovery."""


def database_file(settings: Settings) -> Path:
    database = make_url(str(settings.database_url)).database
    if not database or database == ":memory:":
        raise MaintenanceError("维护操作要求文件数据库")
    return Path(database).expanduser().resolve()


class MaintenanceLock:
    """Nonblocking advisory lock; keep a shared lock for the entire service lifetime.

    Startup acquires an exclusive lock, recovers any journal, migrates, then calls
    downgrade() before serving. The file is never unlinked, so another process
    cannot acquire a different inode while an existing lock is held.
    """

    def __init__(self, settings: Settings, *, exclusive: bool = True) -> None:
        self.database = database_file(settings)
        self.path = self.database.with_name(f".{self.database.name}.maintenance.lock")
        self.exclusive = exclusive
        self._fd: int | None = None

    def __enter__(self) -> MaintenanceLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            mode = fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH
            fcntl.flock(fd, mode | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise MaintenanceError("服务或维护操作正在使用数据库；请先停止服务再恢复") from exc
        self._fd = fd
        return self

    def validate(self, settings: Settings, *, exclusive: bool = True) -> None:
        if self._fd is None or self.database != database_file(settings):
            raise MaintenanceError("维护锁未持有或不属于当前数据库")
        if exclusive and not self.exclusive:
            raise MaintenanceError("操作需要独占维护锁")

    def downgrade(self) -> None:
        if self._fd is None:
            raise MaintenanceError("维护锁未持有")
        fcntl.flock(self._fd, fcntl.LOCK_SH)
        self.exclusive = False

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
