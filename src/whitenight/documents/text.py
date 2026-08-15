"""文本与代码文件读取：确定性编码回退，限制大小，不执行任何内容。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_MAX_FILE_BYTES = 20 * 1024 * 1024


class TextReadError(ValueError):
    """文件不可读或超限。"""


@dataclass(frozen=True)
class TextReading:
    text: str
    encoding: str
    truncated: bool


def read_text_file(path: Path, max_chars: int = 200_000) -> TextReading:
    """读取文本/代码文件。优先 UTF-8，回退中文 GB18030，最后 latin-1 兜底。"""
    if not path.exists():
        raise TextReadError(f"文件不存在：{path}")
    if not path.is_file():
        raise TextReadError(f"不是普通文件：{path}")
    size = path.stat().st_size
    if size > _MAX_FILE_BYTES:
        raise TextReadError(f"文件超过 {_MAX_FILE_BYTES // 1024 // 1024} MiB 限制")

    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1")
        encoding = "latin-1"

    truncated = len(text) > max_chars
    return TextReading(
        text=text[:max_chars],
        encoding=encoding,
        truncated=truncated,
    )
