"""OneBot 11 私有消息类型与 CQ 段解析。"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class OneBotSegment(BaseModel):
    type: str
    data: dict[str, str] = Field(default_factory=dict)


class OneBotPrivateMessageEvent(BaseModel):
    post_type: str = "message"
    message_type: str = "private"
    message_id: int | str = 0
    user_id: int
    raw_message: str = ""
    message: list[OneBotSegment] = Field(default_factory=list)
    self_id: int | None = None


@dataclass
class ParsedOneBotMessage:
    text: str = ""
    image_data_url: str | None = None
    file_path: str | None = None
    file_name: str | None = None
    file_id: str | None = None
    is_poke: bool = False
    poke_type: str | None = None
    poke_id: str | None = None
    segments: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (
            self.text.strip()
            or self.image_data_url
            or self.file_path
            or self.file_id
            or self.is_poke
        )


def parse_segments(event: OneBotPrivateMessageEvent) -> ParsedOneBotMessage:
    """只提取文本与多媒体元数据；后续 fetch 由适配器执行（本函数不做网络）。"""
    parsed = ParsedOneBotMessage()
    for segment in event.message:
        parsed.segments.append(segment.type)
        if segment.type == "text":
            parsed.text += segment.data.get("text", "")
        elif segment.type == "image":
            parsed.image_data_url = _image_data_url(segment.data)
        elif segment.type in {"record", "file"}:
            parsed.file_path = segment.data.get("url") or segment.data.get("file")
            parsed.file_name = segment.data.get("file")
            parsed.file_id = segment.data.get("file_id") or segment.data.get("id")
        elif segment.type == "poke":
            parsed.is_poke = True
            parsed.poke_type = segment.data.get("type")
            parsed.poke_id = segment.data.get("id")
    if not parsed.text and event.raw_message:
        parsed.text = event.raw_message
    return parsed


def _image_data_url(data: dict[str, str]) -> str | None:
    url = data.get("url") or ""
    if url.startswith("http://") or url.startswith("https://"):
        return url  # 适配器统一下载后转 data URL
    file = data.get("file") or ""
    if file.startswith("base64://"):
        return f"data:image/png;base64,{file[len('base64://') :]}"
    return None
