"""Apple Vision OCR（macOS 优先）。

依赖为可选 extra：``uv sync --extra ocr``。不可用时给出明确错误，
绝不伪造识别内容。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class OcrUnavailableError(RuntimeError):
    """OCR 依赖或系统能力不可用。"""


@dataclass(frozen=True)
class OcrReading:
    text: str
    confidence: float | None
    metadata: dict[str, object]


def ocr_image(path: Path, languages: tuple[str, ...] = ("zh-Hans", "en-US")) -> OcrReading:
    """对单张图片执行 Apple Vision OCR。"""
    if not path.exists():
        raise OcrUnavailableError(f"图片不存在：{path}")
    try:
        from ocrmac import ocrmac
    except ImportError as exc:
        raise OcrUnavailableError("OCR 不可用：运行 uv sync --extra ocr") from exc

    try:
        annotations = ocrmac.OCR(str(path), language_preference=list(languages)).recognize()
    except Exception as exc:
        raise OcrUnavailableError(f"Apple Vision OCR 失败：{exc}") from exc

    texts: list[str] = []
    confidences: list[float] = []
    for annotation in annotations:
        if isinstance(annotation, dict):
            text = str(annotation.get("text", ""))
            confidence = annotation.get("confidence")
        else:
            text = str(annotation[0])
            confidence = annotation[1] if len(annotation) > 1 else None
        if text:
            texts.append(text)
        if isinstance(confidence, (int, float)):
            confidences.append(float(confidence))

    mean_confidence = sum(confidences) / len(confidences) if confidences else None
    return OcrReading(
        text="\n".join(texts),
        confidence=round(mean_confidence, 4) if mean_confidence is not None else None,
        metadata={"engine": "apple-vision", "language_preference": list(languages)},
    )
