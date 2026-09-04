"""OneBot 11 私有消息类型与 CQ 段解析。"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


class OneBotSegment(BaseModel):
    type: str
    # NapCat does not keep segment values homogeneous: ids are often numbers
    # and some extensions include nested objects.  Treat the event as an
    # untrusted wire envelope and normalize individual values at parse time.
    data: dict[str, Any] = Field(default_factory=dict)


class OneBotPrivateMessageEvent(BaseModel):
    post_type: str = "message"
    message_type: str = "private"
    message_id: int | str = 0
    user_id: int
    raw_message: str = ""
    # OneBot allows either the structured array or the legacy CQ-code string.
    message: list[OneBotSegment] | str = Field(default_factory=list)
    self_id: int | None = None


@dataclass
class ParsedOneBotMessage:
    text: str = ""
    image_data_url: str | None = None
    image_file_id: str | None = None
    file_path: str | None = None
    file_name: str | None = None
    file_id: str | None = None
    file_size: int | None = None
    is_poke: bool = False
    poke_type: str | None = None
    poke_id: str | None = None
    reply_id: str | None = None
    segments: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (
            self.text.strip()
            or self.image_data_url
            or self.image_file_id
            or self.file_path
            or self.file_id
            or self.is_poke
            or self.reply_id
        )


def parse_segments(event: OneBotPrivateMessageEvent) -> ParsedOneBotMessage:
    """只提取文本与多媒体元数据；后续 fetch 由适配器执行（本函数不做网络）。"""
    parsed = ParsedOneBotMessage()
    segments = (
        event.message if isinstance(event.message, list) else _parse_cq_message(event.message)
    )
    for segment in segments:
        parsed.segments.append(segment.type)
        if segment.type == "text":
            parsed.text += _as_text(segment.data.get("text"))
        elif segment.type in {"image", "flash"}:
            parsed.image_data_url = _image_data_url(segment.data)
            parsed.image_file_id = _first_string(segment.data, "file_id", "id")
        elif segment.type in {"mface", "market_face", "marketface", "sticker", "emoji"}:
            # NapCat uses mface/market_face for animated and custom QQ
            # stickers.  Most versions expose a downloadable URL (or cache
            # path) even though the segment is not named ``image``.
            source = _image_data_url(segment.data)
            parsed.image_file_id = _first_string(segment.data, "file_id", "id", "key", "emoji_id")
            if source:
                parsed.image_data_url = source
            else:
                parsed.text += _face_label(segment.data)
        elif segment.type == "face":
            # Built-in QQ faces generally have no retrievable bitmap in the
            # event.  If a NapCat extension does expose a URL, route it
            # through the same visual path; otherwise keep a deterministic
            # marker so the model knows a face was sent.
            source = _image_data_url(segment.data)
            if source:
                parsed.image_data_url = source
                parsed.image_file_id = _first_string(segment.data, "file_id", "id")
            else:
                parsed.text += _face_label(segment.data)
        elif segment.type in {"record", "file"}:
            parsed.file_path = _first_string(segment.data, "url", "file")
            parsed.file_name = _first_string(segment.data, "file")
            parsed.file_id = _first_string(segment.data, "file_id", "id")
            raw_size = segment.data.get("file_size", segment.data.get("size"))
            if isinstance(raw_size, (int, float)) and not isinstance(raw_size, bool):
                parsed.file_size = int(raw_size)
        elif segment.type == "poke":
            parsed.is_poke = True
            parsed.poke_type = _first_string(segment.data, "type")
            parsed.poke_id = _first_string(segment.data, "id")
        elif segment.type == "reply":
            parsed.reply_id = _first_string(segment.data, "id", "message_id")
    if not parsed.text and event.raw_message and not _contains_cq_only(event.raw_message):
        parsed.text = event.raw_message
    return parsed


_CQ_RE = re.compile(r"\[CQ:(?P<type>[^,\]]+)(?P<params>(?:,[^\]]*)?)\]")


def _decode_cq(value: str) -> str:
    # CQ escaping is deliberately decoded only for display/context fields;
    # it is never interpreted as a command or permission grant.
    return html.unescape(value.replace("&#91;", "[").replace("&#93;", "]").replace("&#44;", ","))


def _parse_cq_message(raw: str) -> list[OneBotSegment]:
    segments: list[OneBotSegment] = []
    cursor = 0
    for match in _CQ_RE.finditer(raw):
        if match.start() > cursor:
            segments.append(
                OneBotSegment(type="text", data={"text": _decode_cq(raw[cursor : match.start()])})
            )
        data: dict[str, Any] = {}
        params = match.group("params").lstrip(",")
        for item in params.split(",") if params else []:
            if "=" in item:
                key, value = item.split("=", 1)
                data[key] = _decode_cq(value)
        segments.append(OneBotSegment(type=match.group("type"), data=data))
        cursor = match.end()
    if cursor < len(raw):
        segments.append(OneBotSegment(type="text", data={"text": _decode_cq(raw[cursor:])}))
    return segments


def _contains_cq_only(raw: str) -> bool:
    return bool(raw.strip()) and _CQ_RE.sub("", raw).strip() == ""


def _as_text(value: object) -> str:
    return value if isinstance(value, str) else str(value) if value is not None else ""


def _first_string(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


def _image_data_url(data: dict[str, Any]) -> str | None:
    # Different NapCat versions use all of these names for custom emoji
    # media.  Prefer a URL/path over an opaque id so the adapter can download
    # the actual bitmap and pass it to a vision-capable provider.
    url = _first_string(data, "url", "image_url", "emoji_url", "src") or ""
    if url:
        # Keep local paths and opaque NapCat tokens too; the adapter will
        # validate the path or resolve the token through get_image/get_file.
        return url
    file = _first_string(data, "file", "path") or ""
    if file.startswith("data:image/"):
        return file
    if file.startswith("base64://"):
        return f"data:image/png;base64,{file[len('base64://') :]}"
    # NapCat may put a regular local cache path in ``file`` and omit ``url``.
    # The adapter validates and reads it; keeping the source here avoids
    # silently converting an image-only message into an empty event.
    if file:
        return file
    return None


def _face_label(data: dict[str, Any]) -> str:
    summary = _first_string(data, "summary", "name", "text", "raw")
    face_id = _first_string(data, "id", "emoji_id")
    if summary:
        return f"（QQ表情：{summary}）"
    if face_id:
        return f"（QQ表情 id={face_id}）"
    return "（主人发送了一个QQ表情）"
