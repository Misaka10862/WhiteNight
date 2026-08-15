"""压缩包只列内容，不自动解压（构建计划第 11 节）。"""

from __future__ import annotations

import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

_MAX_ENTRIES = 10_000


class ArchiveError(ValueError):
    """压缩包损坏或格式不支持。"""


@dataclass(frozen=True)
class ArchiveEntry:
    name: str
    size: int
    is_dir: bool = False


@dataclass
class ArchiveListing:
    format: str
    entries: list[ArchiveEntry] = field(default_factory=list)
    total_uncompressed_bytes: int = 0

    @property
    def summary(self) -> str:
        return (
            f"{self.format} 归档，{len(self.entries)} 项，"
            f"解压预估 {self.total_uncompressed_bytes / 1024 / 1024:.1f} MiB"
        )


def list_archive(path: Path) -> ArchiveListing:
    """只枚举 zip/tar(.gz/.bz2/.xz) 条目；不写入任何解压文件。"""
    if not path.exists():
        raise ArchiveError(f"文件不存在：{path}")
    suffix = path.suffix.lower()

    if suffix == ".zip":
        return _list_zip(path)
    if suffix in {".tar", ".gz", ".bz2", ".xz"} or ".tar." in path.name.lower():
        return _list_tar(path)
    raise ArchiveError(
        f"不支持的压缩格式：{path.suffix or '未知'}（支持 zip/tar.gz/tar.bz2/tar.xz）"
    )


def _list_zip(path: Path) -> ArchiveListing:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ENTRIES:
                raise ArchiveError(f"条目数超过 {_MAX_ENTRIES} 限制")
            entries = [ArchiveEntry(i.filename, i.file_size, i.is_dir()) for i in infos]
            return ArchiveListing(
                format="zip",
                entries=entries,
                total_uncompressed_bytes=sum(entry.size for entry in entries),
            )
    except ArchiveError:
        raise
    except Exception as exc:
        raise ArchiveError(f"zip 读取失败：{exc}") from exc


def _list_tar(path: Path) -> ArchiveListing:
    try:
        with tarfile.open(path) as archive:
            members = archive.getmembers()
            if len(members) > _MAX_ENTRIES:
                raise ArchiveError(f"条目数超过 {_MAX_ENTRIES} 限制")
            entries = [ArchiveEntry(m.name, m.size, m.isdir()) for m in members]
            return ArchiveListing(
                format="tar",
                entries=entries,
                total_uncompressed_bytes=sum(entry.size for entry in entries),
            )
    except ArchiveError:
        raise
    except Exception as exc:
        raise ArchiveError(f"tar 读取失败：{exc}") from exc
