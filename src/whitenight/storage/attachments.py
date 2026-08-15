"""聊天图片附件落盘与恢复。

阶段 2：只接受常见图片 data URL，大小受限，落盘到 data/attachments。
文件保留策略（默认一年）在阶段 4 与记忆保留一起实现。
"""

from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path
from uuid import uuid4

_DATA_URL_RE = re.compile(r"^data:(?P<mime>image/(?:png|jpeg|gif|webp));base64,(?P<data>.+)$", re.S)

_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class AttachmentError(ValueError):
    """图片附件不合法或超限。"""


def save_image_data_url(data_url: str, attachments_dir: Path, max_bytes: int) -> tuple[str, str]:
    """保存 data URL 图片，返回 (相对路径, mime)。"""
    match = _DATA_URL_RE.match(data_url)
    if not match:
        raise AttachmentError("仅支持 png/jpeg/gif/webp 的 data URL 图片")
    mime = match.group("mime")
    try:
        raw = base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AttachmentError(f"图片 base64 解码失败：{exc}") from exc
    if not raw:
        raise AttachmentError("图片内容为空")
    if len(raw) > max_bytes:
        raise AttachmentError(f"图片超过大小限制（{max_bytes // 1024 // 1024} MiB）")

    attachments_dir.mkdir(parents=True, exist_ok=True)
    relative = f"{uuid4()}{_EXTENSIONS[mime]}"
    (attachments_dir / relative).write_bytes(raw)
    return relative, mime


def image_path_to_data_url(attachments_dir: Path, relative_path: str, mime: str) -> str | None:
    """把已保存图片读回 data URL；文件缺失时返回 None 而不是伪造内容。"""
    path = attachments_dir / relative_path
    if not path.exists():
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"
