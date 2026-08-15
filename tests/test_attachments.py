"""图片附件保存测试。"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from whitenight.storage.attachments import AttachmentError, save_image_data_url


def _data_url(mime: str = "image/png", raw: bytes = b"\x89PNG\r\n\x1a\n") -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def test_save_valid_png(tmp_path: Path) -> None:
    relative, mime = save_image_data_url(_data_url(), tmp_path / "attachments", 1024 * 1024)
    assert mime == "image/png"
    assert relative.endswith(".png")
    assert (tmp_path / "attachments" / relative).read_bytes() == b"\x89PNG\r\n\x1a\n"


def test_reject_non_image_mime(tmp_path: Path) -> None:
    with pytest.raises(AttachmentError, match="仅支持"):
        save_image_data_url(_data_url("text/plain", b"hello"), tmp_path, 1024)


def test_reject_oversized(tmp_path: Path) -> None:
    with pytest.raises(AttachmentError, match="大小限制"):
        save_image_data_url(_data_url(raw=b"x" * 64), tmp_path, max_bytes=16)


def test_reject_bad_base64(tmp_path: Path) -> None:
    with pytest.raises(AttachmentError):
        save_image_data_url("data:image/png;base64,!!!", tmp_path, 1024)
