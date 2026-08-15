"""PDF 解析：PyMuPDF 提取文本与版面信息；扫描页按需 OCR。"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from whitenight.documents.ocr import OcrUnavailableError, ocr_image


class PdfParseError(ValueError):
    """PDF 打开或解析失败。"""


@dataclass
class PdfReading:
    text: str
    page_count: int
    page_texts: list[str] = field(default_factory=list)
    scanned_pages: list[int] = field(default_factory=list)
    needs_ocr: bool = False
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def sourced(self) -> bool:
        """是否产生了有来源的文本（文本页或成功 OCR 的扫描页）。"""
        return bool(self.text.strip())


def parse_pdf(
    path: Path,
    max_pages: int = 200,
    ocr_enabled: bool = True,
    max_chars: int = 200_000,
) -> PdfReading:
    if not path.exists():
        raise PdfParseError(f"文件不存在：{path}")
    try:
        import fitz  # type: ignore[import-untyped]  # pymupdf
    except ImportError as exc:  # 依赖损坏时的明确错误
        raise PdfParseError("缺少 pymupdf 依赖") from exc

    try:
        with fitz.open(path) as document:
            page_count = min(len(document), max_pages)
            page_texts: list[str] = []
            scanned_pages: list[int] = []
            ocr_failed_pages: list[int] = []
            for page_index in range(page_count):
                page = document[page_index]
                text = page.get_text("text").strip()
                if ocr_enabled and len(text) < 20:
                    # 扫描页：渲染 200 DPI 后走 Apple Vision OCR。
                    try:
                        pixmap = page.get_pixmap(dpi=200)
                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                            tmp_path = Path(tmp.name)
                            pixmap.save(str(tmp_path))
                        try:
                            ocr = ocr_image(tmp_path)
                        finally:
                            tmp_path.unlink(missing_ok=True)
                        if ocr.text.strip():
                            text = ocr.text.strip()
                            scanned_pages.append(page_index + 1)
                        else:
                            ocr_failed_pages.append(page_index + 1)
                    except OcrUnavailableError:
                        ocr_failed_pages.append(page_index + 1)
                elif not ocr_enabled and len(text) < 20:
                    ocr_failed_pages.append(page_index + 1)
                page_texts.append(text)
            text = "\n\n".join(page_texts).strip()
            truncated = len(text) > max_chars
            return PdfReading(
                text=text[:max_chars],
                page_count=page_count,
                page_texts=page_texts,
                scanned_pages=scanned_pages,
                needs_ocr=bool(ocr_failed_pages),
                metadata={
                    "format": "pdf",
                    "page_count": page_count,
                    "scanned_pages": scanned_pages,
                    "ocr_failed_pages": ocr_failed_pages,
                    "truncated": truncated,
                },
            )
    except PdfParseError:
        raise
    except Exception as exc:
        raise PdfParseError(f"PDF 解析失败（说明失败格式与页数，不伪造内容）：{exc}") from exc
