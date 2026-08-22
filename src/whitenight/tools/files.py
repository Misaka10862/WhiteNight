"""文件与文档工具。

- 文件读取范围为本机全部文件，不设置默认目录白名单（构建计划第 9.2 节）；
- 删除只进 macOS 废纸篓，禁止永久删除；
- 批量删除与目录清空由 PolicyEngine 拒绝，工具本身也不实现执行路径。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path

from pydantic import Field

from whitenight.documents.dispatcher import parse_document
from whitenight.documents.text import read_text_file
from whitenight.policy.risk import RiskLevel
from whitenight.tools.base import Source, ToolContext, ToolParameters, ToolResult


class FileReadParams(ToolParameters):
    path: str = Field(description="要读取的绝对路径")
    max_chars: int = Field(default=50_000, ge=1, le=200_000)


class FileReadTool:
    name = "file.read"
    description = "读取本机文本/代码文件，返回有来源的原文"
    risk = RiskLevel.READ_ONLY

    def validate(self, params: dict[str, object]) -> FileReadParams:
        return FileReadParams.model_validate(params)

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, FileReadParams)
        path = Path(params.path).expanduser().resolve()
        try:
            reading = read_text_file(path, max_chars=params.max_chars)
        except ValueError as exc:
            return ToolResult.failure(f"无法读取 {path}", str(exc))
        return ToolResult(
            ok=True,
            summary=f"读取 {path}（{len(reading.text)} 字符，{reading.encoding}）",
            content=reading.text,
            sources=[Source(label=path.name, uri=str(path), kind="file")],
            metadata={
                "path": str(path),
                "encoding": reading.encoding,
                "truncated": reading.truncated,
            },
        )


class FileFindParams(ToolParameters):
    names: list[str] = Field(min_length=1, max_length=20, description="要查找的精确文件名")
    root: str | None = Field(default=None, description="绝对搜索根目录；默认当前用户主目录")
    max_results: int = Field(default=100, ge=1, le=500)
    timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)


class FileFindTool:
    name = "file.find"
    description = "按一个或多个精确文件名查找本机文件；默认搜索当前用户主目录"
    risk = RiskLevel.READ_ONLY

    def validate(self, params: dict[str, object]) -> FileFindParams:
        return FileFindParams.model_validate(params)

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, FileFindParams)
        del context
        root = Path(params.root).expanduser().resolve() if params.root else Path.home().resolve()
        if not root.is_dir():
            return ToolResult.failure("文件查找失败", f"搜索根目录不存在：{root}")

        wanted = {name.casefold() for name in params.names if Path(name).name == name}
        if len(wanted) != len(params.names):
            return ToolResult.failure("文件查找失败", "names 只能包含文件名，不能包含路径")

        deadline = time.monotonic() + params.timeout_seconds
        matches: list[Path] = []
        denied = 0
        timed_out = False

        def onerror(error: OSError) -> None:
            nonlocal denied
            denied += 1

        for directory, dirs, files in os.walk(
            root, topdown=True, followlinks=False, onerror=onerror
        ):
            if time.monotonic() >= deadline:
                timed_out = True
                break
            dirs[:] = [name for name in dirs if not Path(directory, name).is_symlink()]
            for index, filename in enumerate(files):
                if index % 128 == 0 and time.monotonic() >= deadline:
                    timed_out = True
                    break
                if filename.casefold() in wanted:
                    candidate = Path(directory, filename)
                    if candidate.is_file() and not candidate.is_symlink():
                        matches.append(candidate.resolve())
                        if len(matches) >= params.max_results:
                            break
            if len(matches) >= params.max_results:
                break
            if timed_out or time.monotonic() >= deadline:
                timed_out = True
                break

        matches.sort(key=lambda path: str(path).casefold())
        content = "\n".join(str(path) for path in matches)
        partial = timed_out or len(matches) >= params.max_results or denied > 0
        return ToolResult(
            ok=True,
            summary=(
                f"在 {root} 找到 {len(matches)} 个匹配文件"
                + ("（结果可能不完整）" if partial else "")
            ),
            content=content,
            sources=[Source(label=path.name, uri=str(path), kind="file") for path in matches],
            metadata={
                "root": str(root),
                "names": params.names,
                "count": len(matches),
                "permission_denied": denied,
                "timed_out": timed_out,
                "truncated": len(matches) >= params.max_results,
            },
        )


class ChannelFileSendParams(ToolParameters):
    path: str = Field(description="要发送的单个文件绝对路径")
    name: str | None = Field(default=None, description="接收方看到的文件名")
    approved_sha256: str | None = None
    approved_size: int | None = None


class ChannelFileSendTool:
    name = "channel.file.send"
    description = "把单个本地文件发送到当前可信聊天渠道；目标由服务器绑定"
    risk = RiskLevel.MEDIUM

    def __init__(self, max_bytes: int = 100 * 1024 * 1024) -> None:
        self.max_bytes = max_bytes

    def validate(self, params: dict[str, object]) -> ChannelFileSendParams:
        return ChannelFileSendParams.model_validate(params)

    def approval_metadata(self, params: ToolParameters, context: ToolContext) -> dict[str, object]:
        assert isinstance(params, ChannelFileSendParams)
        path = Path(params.path).expanduser().resolve()
        if params.approved_sha256 is not None and params.approved_size is not None:
            return {
                "prepared_params": params.model_dump(),
                "approval_summary": {
                    "path": str(path),
                    "name": params.name or path.name,
                    "size": params.approved_size,
                    "sha256": params.approved_sha256,
                    "channel": context.channel,
                    "target": context.channel_target,
                },
            }
        if not path.is_file() or path.is_symlink():
            raise ValueError("只能发送存在的普通文件，不能发送目录或符号链接")
        size = path.stat().st_size
        if size > self.max_bytes:
            raise ValueError(f"文件超过发送上限：{size} > {self.max_bytes}")
        digest = _sha256_file(path)
        return {
            "prepared_params": {
                "path": str(path),
                "name": params.name or path.name,
                "approved_sha256": digest,
                "approved_size": size,
            },
            "approval_summary": {
                "path": str(path),
                "name": params.name or path.name,
                "size": size,
                "sha256": digest,
                "channel": context.channel,
                "target": context.channel_target,
            },
        }

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, ChannelFileSendParams)
        path = Path(params.path).expanduser().resolve()
        if context.channel != "onebot" or not context.channel_target:
            return ToolResult.failure("文件未发送", "当前渠道不允许文件外发")
        if context.file_delivery is None:
            return ToolResult.failure("文件未发送", "渠道文件发送 Provider 未配置")
        if not path.is_file() or path.is_symlink():
            return ToolResult.failure("文件未发送", "目标已不存在或不是普通文件")
        size = path.stat().st_size
        digest = _sha256_file(path)
        if params.approved_size != size or params.approved_sha256 != digest:
            return ToolResult.failure("文件未发送", "文件在发送前发生变化，请重试")
        name = params.name or path.name
        context.file_delivery.upload_file(context.channel_target, str(path), name)
        return ToolResult(
            ok=True,
            summary=f"已发送 {path} 到 QQ {context.channel_target}",
            content=f"已发送文件：{name}",
            sources=[Source(label=path.name, uri=str(path), kind="file")],
            metadata={"path": str(path), "name": name, "size": size, "sha256": digest},
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FileCreateParams(ToolParameters):
    path: str = Field(description="新建文件的绝对路径")
    content: str = Field(default="", max_length=500_000)
    overwrite: bool = False
    approved_exists: bool | None = None


class FileCreateTool:
    name = "file.create"
    description = "新建文件并写入内容；默认不覆盖已有文件"
    risk = RiskLevel.LOW_WRITE

    def validate(self, params: dict[str, object]) -> FileCreateParams:
        return FileCreateParams.model_validate(params)

    def approval_metadata(self, params: ToolParameters, context: ToolContext) -> dict[str, object]:
        assert isinstance(params, FileCreateParams)
        del context
        path = Path(params.path).expanduser().resolve()
        exists = params.approved_exists if params.approved_exists is not None else path.exists()
        prepared = params.model_dump()
        prepared["path"] = str(path)
        prepared["approved_exists"] = exists
        return {
            "prepared_params": prepared,
            "approval_summary": {"path": str(path), "exists": exists, "action": "create"},
        }

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, FileCreateParams)
        del context
        path = Path(params.path).expanduser().resolve()
        if params.approved_exists is not None and path.exists() != params.approved_exists:
            return ToolResult.failure(f"未新建 {path}", "目标状态在审批后发生变化")
        if path.exists() and params.overwrite:
            return ToolResult.failure(f"未新建 {path}", "覆盖已有文件必须使用 file.write")
        if path.exists() and not params.overwrite:
            return ToolResult.failure(
                f"未新建 {path}", "目标已存在，需要 overwrite=true 或改用 file.write"
            )
        if not path.parent.is_dir():
            return ToolResult.failure(f"未新建 {path}", f"父目录不存在：{path.parent}")
        path.write_text(params.content, encoding="utf-8")
        return ToolResult(
            ok=True,
            summary=f"已新建 {path}（{len(params.content)} 字符）",
            content=f"已写入 {path}",
            sources=[Source(label=path.name, uri=str(path), kind="file")],
            metadata={"path": str(path), "size": path.stat().st_size},
        )


class FileWriteParams(ToolParameters):
    path: str = Field(description="要修改的绝对路径")
    content: str = Field(default="", max_length=500_000)
    approved_stat: str | None = None


class FileWriteTool:
    name = "file.write"
    description = "覆盖修改已有文件（中风险，逐次审批）"
    risk = RiskLevel.MEDIUM

    def validate(self, params: dict[str, object]) -> FileWriteParams:
        return FileWriteParams.model_validate(params)

    def approval_metadata(self, params: ToolParameters, context: ToolContext) -> dict[str, object]:
        assert isinstance(params, FileWriteParams)
        del context
        path = Path(params.path).expanduser().resolve()
        fingerprint = params.approved_stat or _stat_fingerprint(path)
        prepared = params.model_dump()
        prepared.update({"path": str(path), "approved_stat": fingerprint})
        return {
            "prepared_params": prepared,
            "approval_summary": {"path": str(path), "stat": fingerprint, "action": "write"},
        }

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, FileWriteParams)
        del context
        path = Path(params.path).expanduser().resolve()
        if params.approved_stat is not None and _stat_fingerprint(path) != params.approved_stat:
            return ToolResult.failure(f"未修改 {path}", "文件状态在审批后发生变化")
        if not path.is_file():
            return ToolResult.failure(f"未修改 {path}", "目标不是已有文件；新建请用 file.create")
        path.write_text(params.content, encoding="utf-8")
        return ToolResult(
            ok=True,
            summary=f"已修改 {path}（{len(params.content)} 字符）",
            content=f"已写入 {path}",
            sources=[Source(label=path.name, uri=str(path), kind="file")],
            metadata={"path": str(path), "size": path.stat().st_size},
        )


class FileMoveParams(ToolParameters):
    source: str = Field(description="源文件绝对路径")
    destination: str = Field(description="目标绝对路径")
    overwrite: bool = False
    approved_source_stat: str | None = None
    approved_destination_exists: bool | None = None


class FileMoveTool:
    name = "file.move"
    description = "移动/重命名文件（中风险，逐次审批）"
    risk = RiskLevel.MEDIUM

    def validate(self, params: dict[str, object]) -> FileMoveParams:
        return FileMoveParams.model_validate(params)

    def approval_metadata(self, params: ToolParameters, context: ToolContext) -> dict[str, object]:
        assert isinstance(params, FileMoveParams)
        del context
        source = Path(params.source).expanduser().resolve()
        destination = Path(params.destination).expanduser().resolve()
        source_stat = params.approved_source_stat or _stat_fingerprint(source)
        destination_exists = (
            params.approved_destination_exists
            if params.approved_destination_exists is not None
            else destination.exists()
        )
        prepared = params.model_dump()
        prepared.update(
            {
                "source": str(source),
                "destination": str(destination),
                "approved_source_stat": source_stat,
                "approved_destination_exists": destination_exists,
            }
        )
        return {
            "prepared_params": prepared,
            "approval_summary": {
                "source": str(source),
                "destination": str(destination),
                "source_stat": source_stat,
                "destination_exists": destination_exists,
            },
        }

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, FileMoveParams)
        del context
        source = Path(params.source).expanduser().resolve()
        destination = Path(params.destination).expanduser().resolve()
        if (
            params.approved_source_stat is not None
            and _stat_fingerprint(source) != params.approved_source_stat
        ):
            return ToolResult.failure(f"未移动 {source}", "源文件在审批后发生变化")
        if (
            params.approved_destination_exists is not None
            and destination.exists() != params.approved_destination_exists
        ):
            return ToolResult.failure(f"未移动 {source}", "目标状态在审批后发生变化")
        if not source.is_file():
            return ToolResult.failure(f"未移动 {source}", "源文件不存在")
        if destination.exists() and not params.overwrite:
            return ToolResult.failure(f"未移动 {source}", "目标已存在，需要 overwrite=true")
        if not destination.parent.is_dir():
            return ToolResult.failure(f"未移动 {source}", f"目标目录不存在：{destination.parent}")
        shutil.move(str(source), str(destination))
        return ToolResult(
            ok=True,
            summary=f"已移动 {source} -> {destination}",
            content=f"已移动 {source} -> {destination}",
            sources=[Source(label=destination.name, uri=str(destination), kind="file")],
            metadata={"source": str(source), "destination": str(destination)},
        )


class FileDeleteParams(ToolParameters):
    path: str = Field(description="要删除的单个文件绝对路径")
    approved_stat: str | None = None


class FileDeleteTool:
    name = "file.delete"
    description = "删除单个文件到 macOS 废纸篓（明确审批后执行）"
    risk = RiskLevel.DELETE

    def validate(self, params: dict[str, object]) -> FileDeleteParams:
        return FileDeleteParams.model_validate(params)

    def approval_metadata(self, params: ToolParameters, context: ToolContext) -> dict[str, object]:
        assert isinstance(params, FileDeleteParams)
        del context
        path = Path(params.path).expanduser().resolve()
        fingerprint = params.approved_stat or _stat_fingerprint(path)
        prepared = params.model_dump()
        prepared.update({"path": str(path), "approved_stat": fingerprint})
        return {
            "prepared_params": prepared,
            "approval_summary": {"path": str(path), "stat": fingerprint, "action": "trash"},
        }

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, FileDeleteParams)
        del context
        path = Path(params.path).expanduser().resolve()
        if params.approved_stat is not None and _stat_fingerprint(path) != params.approved_stat:
            return ToolResult.failure(f"未删除 {path}", "文件状态在审批后发生变化")
        if not path.is_file():
            return ToolResult.failure(f"未删除 {path}", "文件不存在")
        if path.is_symlink():
            return ToolResult.failure(f"未删除 {path}", "符号链接必须由用户手动处理")
        try:
            _move_to_trash_via_finder(path)
        except subprocess.SubprocessError as exc:
            return ToolResult.failure(f"未删除 {path}", f"废纸篓操作失败：{exc}")
        return ToolResult(
            ok=True,
            summary=f"已移入废纸篓：{path}",
            content=f"已移入废纸篓：{path}（未永久删除）",
            sources=[Source(label=path.name, uri=str(path), kind="file")],
            metadata={"path": str(path), "trashed": True},
        )


def _move_to_trash_via_finder(path: Path) -> None:
    script = f'tell application "Finder" to delete (POSIX file "{path}")'
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise subprocess.SubprocessError(
            result.stderr.strip() or f"osascript exit {result.returncode}"
        )


def _stat_fingerprint(path: Path) -> str:
    try:
        stat = path.stat()
    except OSError as exc:
        raise ValueError(f"无法读取文件状态：{path}: {exc}") from exc
    return f"{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}"


class DocumentParseParams(ToolParameters):
    path: str = Field(description="文档绝对路径")
    ocr_enabled: bool = True


class DocumentParseTool:
    name = "document.parse"
    description = "解析 PDF/Office/文本/代码/图片，图片与扫描 PDF 使用 Apple Vision OCR"
    risk = RiskLevel.READ_ONLY

    def validate(self, params: dict[str, object]) -> DocumentParseParams:
        return DocumentParseParams.model_validate(params)

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, DocumentParseParams)
        del context
        path = Path(params.path).expanduser().resolve()
        parsed = parse_document(path, ocr_enabled=params.ocr_enabled)
        return ToolResult(
            ok=parsed.error is None,
            summary=(
                f"{path.name}（{parsed.kind}）：{len(parsed.text)} 字符"
                if parsed.text
                else f"{path.name}（{parsed.kind}）解析失败"
            ),
            content=parsed.text,
            sources=[Source(label=path.name, uri=str(path), kind=parsed.kind)],
            metadata=parsed.metadata,
            error=parsed.error,
        )


class ArchiveListParams(ToolParameters):
    path: str = Field(description="压缩包绝对路径")


class ArchiveListTool:
    name = "archive.list"
    description = "只列出压缩包内容与预估大小，不自动解压"
    risk = RiskLevel.READ_ONLY

    def validate(self, params: dict[str, object]) -> ArchiveListParams:
        return ArchiveListParams.model_validate(params)

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, ArchiveListParams)
        del context
        from whitenight.documents.archives import list_archive

        path = Path(params.path).expanduser().resolve()
        try:
            listing = list_archive(path)
        except ValueError as exc:
            return ToolResult.failure(f"无法列出 {path}", str(exc))
        return ToolResult(
            ok=True,
            summary=listing.summary,
            content="\n".join(entry.name for entry in listing.entries),
            sources=[Source(label=path.name, uri=str(path), kind="archive")],
            metadata={
                "path": str(path),
                "format": listing.format,
                "entries": len(listing.entries),
                "total_uncompressed_bytes": listing.total_uncompressed_bytes,
            },
        )
