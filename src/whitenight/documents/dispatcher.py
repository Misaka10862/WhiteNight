"""文档解析分发器：按扩展名选择解析器，统一返回有来源的结果。

旧版 .doc/.xls/.ppt、宏与嵌入脚本一律不执行；不支持的格式如实报告。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from whitenight.documents.archives import ArchiveListing, list_archive
from whitenight.documents.ocr import OcrUnavailableError, ocr_image
from whitenight.documents.office import parse_office
from whitenight.documents.pdf import parse_pdf
from whitenight.documents.text import read_text_file

_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".log",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".xml",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".py",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".swift",
    ".sh",
    ".zsh",
    ".bash",
    ".sql",
    ".rb",
    ".php",
    ".pl",
    ".r",
    ".m",
}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}
_ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".bz2", ".xz"}
_LEGACY_OFFICE_SUFFIXES = {".doc", ".xls", ".ppt"}


class DocumentParseError(ValueError):
    """文档无法解析；调用方必须保留原文错误信息。"""


@dataclass
class ParsedDocument:
    origin: str
    kind: str
    text: str = ""
    truncated: bool = False
    metadata: dict[str, object] = field(default_factory=dict)
    error: str | None = None

    @property
    def sources(self) -> list[str]:
        """有来源的结果：本地路径或解析器标识，绝不伪造网页来源。"""
        return [self.origin]


def parse_document(
    path: Path,
    *,
    ocr_enabled: bool = True,
    max_chars: int = 200_000,
) -> ParsedDocument:
    """按扩展名解析常见文件；失败返回带 error 的结果而不是抛异常。"""
    if not path.exists():
        return ParsedDocument(origin=str(path), kind="missing", error="文件不存在")

    suffix = path.suffix.lower()
    try:
        if suffix in _TEXT_SUFFIXES:
            reading = read_text_file(path, max_chars=max_chars)
            return ParsedDocument(
                origin=str(path),
                kind="text",
                text=reading.text,
                truncated=reading.truncated,
                metadata={"format": suffix or "text", "encoding": reading.encoding},
            )
        if suffix == ".pdf":
            pdf = parse_pdf(path, ocr_enabled=ocr_enabled, max_chars=max_chars)
            return ParsedDocument(
                origin=str(path),
                kind="pdf",
                text=pdf.text,
                truncated=bool(pdf.metadata.get("truncated")),
                metadata=pdf.metadata,
                error="扫描页 OCR 不可用" if pdf.needs_ocr and not pdf.text else None,
            )
        if suffix in {".docx", ".xlsx", ".pptx"}:
            office = parse_office(path, max_chars=max_chars)
            return ParsedDocument(
                origin=str(path),
                kind="office",
                text=office.text,
                truncated=bool(office.metadata.get("truncated")),
                metadata=office.metadata,
            )
        if suffix in _IMAGE_SUFFIXES:
            try:
                ocr = ocr_image(path)
                return ParsedDocument(
                    origin=str(path),
                    kind="image",
                    text=ocr.text,
                    metadata={
                        "format": suffix,
                        "ocr": "apple-vision",
                        "ocr_confidence": ocr.confidence,
                    },
                )
            except OcrUnavailableError as exc:
                return ParsedDocument(
                    origin=str(path),
                    kind="image",
                    error=str(exc),
                    metadata={"format": suffix, "ocr": "unavailable"},
                )
        if suffix in _ARCHIVE_SUFFIXES or ".tar." in path.name.lower():
            listing = list_archive(path)
            return ParsedDocument(
                origin=str(path),
                kind="archive",
                text=listing.summary + "\n" + "\n".join(entry.name for entry in listing.entries),
                metadata={
                    "format": listing.format,
                    "entries": [
                        {"name": entry.name, "size": entry.size, "is_dir": entry.is_dir}
                        for entry in listing.entries
                    ],
                    "total_uncompressed_bytes": listing.total_uncompressed_bytes,
                },
            )
        if suffix in _LEGACY_OFFICE_SUFFIXES:
            return ParsedDocument(
                origin=str(path),
                kind="legacy_office",
                error=(
                    f"{suffix} 旧版格式需通过受控转换器生成临时现代格式后读取"
                    "（不自动执行转换，避免宏/嵌入脚本风险）"
                ),
            )
        return ParsedDocument(
            origin=str(path),
            kind="unsupported",
            error=f"不支持的格式：{suffix or '无扩展名'}（不伪造内容）",
        )
    except Exception as exc:  # 解析器失败必须说明原因，不伪造内容
        return ParsedDocument(origin=str(path), kind="error", error=str(exc))


def list_archive_listing(path: Path) -> ArchiveListing:
    """直接返回压缩包条目（供工具层使用）。"""
    return list_archive(path)
