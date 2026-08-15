"""统一消息与渠道无关的领域类型。

所有渠道（Web、OneBot、未来渠道）都必须先把输入标准化为这里的类型，
再由 Agent 循环消费；渠道适配器不得持有模型、记忆、权限或人格状态。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

MessageRole = Literal["system", "user", "assistant"]
MessageKind = Literal["text", "image", "tool_result"]


class ChatAttachment(BaseModel):
    """聊天消息携带的图片附件（阶段 2 仅支持常见图片）。"""

    data_url: str = Field(description="data:image/...;base64,...")
    mime: str | None = None
    path: str | None = Field(default=None, description="服务端相对存储路径")


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class SessionSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class MessageRecord(BaseModel):
    id: str
    session_id: str
    sequence: int = 0
    role: MessageRole
    kind: MessageKind = "text"
    content: str = ""
    image_data_url: str | None = None
    created_at: datetime


class ChatRequest(BaseModel):
    """WebSocket 聊天请求：渠道无关的统一入站消息。"""

    session_id: str
    text: str = Field(default="", max_length=64_000)
    image_data_url: str | None = Field(default=None, max_length=16_000_000)


class ChatEvent(BaseModel):
    """标准化聊天事件（WebSocket 传输用）。"""

    type: Literal["start", "chunk", "done", "error", "task"]
    session_id: str | None = None
    delta: str | None = None
    message_id: str | None = None
    text: str | None = None
    message: str | None = None
    extra: dict[str, Any] | None = None
