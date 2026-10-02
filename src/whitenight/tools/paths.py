"""Filesystem identity and access errors, without assuming case-insensitive volumes."""

from pathlib import Path


def canonical_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if path == path.parent:
        return path
    parent = canonical_path(path.parent)
    candidate = parent / path.name
    # Only aliases that identify the same filesystem object may be folded.
    try:
        stat = candidate.stat()
        for entry in parent.iterdir():
            if (
                entry.name.casefold() == path.name.casefold()
                and entry.stat().st_ino == stat.st_ino
                and entry.stat().st_dev == stat.st_dev
            ):
                return entry
    except (FileNotFoundError, NotADirectoryError):
        pass
    return candidate


def path_error(error: OSError) -> str:
    if isinstance(error, PermissionError):
        return f"没有访问权限：{error.filename}；请检查 WhiteNight 完全磁盘访问权限"
    if isinstance(error, FileNotFoundError):
        return f"路径不存在：{error.filename}"
    return f"文件系统访问失败：{error}"
