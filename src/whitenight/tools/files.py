"""文件与文档工具。

- 文件读取范围为本机全部文件，不设置默认目录白名单（构建计划第 9.2 节）；
- 删除只进 macOS 废纸篓，禁止永久删除；
- 批量删除与目录清空由 PolicyEngine 拒绝，工具本身也不实现执行路径。
"""

from __future__ import annotations

import shutil
import subprocess
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


class FileCreateParams(ToolParameters):
    path: str = Field(description="新建文件的绝对路径")
    content: str = Field(default="", max_length=500_000)
    overwrite: bool = False


class FileCreateTool:
    name = "file.create"
    description = "新建文件并写入内容；默认不覆盖已有文件"
    risk = RiskLevel.LOW_WRITE

    def validate(self, params: dict[str, object]) -> FileCreateParams:
        return FileCreateParams.model_validate(params)

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, FileCreateParams)
        del context
        path = Path(params.path).expanduser().resolve()
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


class FileWriteTool:
    name = "file.write"
    description = "覆盖修改已有文件（中风险，逐次审批）"
    risk = RiskLevel.MEDIUM

    def validate(self, params: dict[str, object]) -> FileWriteParams:
        return FileWriteParams.model_validate(params)

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, FileWriteParams)
        del context
        path = Path(params.path).expanduser().resolve()
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


class FileMoveTool:
    name = "file.move"
    description = "移动/重命名文件（中风险，逐次审批）"
    risk = RiskLevel.MEDIUM

    def validate(self, params: dict[str, object]) -> FileMoveParams:
        return FileMoveParams.model_validate(params)

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, FileMoveParams)
        del context
        source = Path(params.source).expanduser().resolve()
        destination = Path(params.destination).expanduser().resolve()
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


class FileDeleteTool:
    name = "file.delete"
    description = "删除单个文件到 macOS 废纸篓（明确审批后执行）"
    risk = RiskLevel.DELETE

    def validate(self, params: dict[str, object]) -> FileDeleteParams:
        return FileDeleteParams.model_validate(params)

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, FileDeleteParams)
        del context
        path = Path(params.path).expanduser().resolve()
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
