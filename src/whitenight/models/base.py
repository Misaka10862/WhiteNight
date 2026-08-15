"""模型 Provider 接口。

所有推理后端（Ollama、未来 Provider）都实现本接口；Agent 循环只依赖本接口，
不感知具体协议。接口语义在 docs/contracts/provider-interface.md 固化。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ProviderMessage(BaseModel):
    """发送给模型的统一消息；images 为 base64（不含 data URL 前缀）。"""

    role: str
    content: str = ""
    images: list[str] = Field(default_factory=list)


class ModelChunk(BaseModel):
    """模型流式输出片段。"""

    delta: str = ""
    thinking: str = ""
    done: bool = False


class ModelProviderError(RuntimeError):
    """Provider 调用失败（网络、超时、协议错误）。"""


@runtime_checkable
class ModelProvider(Protocol):
    """模型 Provider 协议。

    注意：方法声明为返回 ``AsyncIterator`` / ``Awaitable`` 的普通 def，
    这样 async generator 实现（调用即返回迭代器）能结构性满足协议。
    """

    def stream_chat(self, messages: list[ProviderMessage]) -> AsyncIterator[ModelChunk]:
        """流式生成；yield 可见内容 delta 与可选 thinking。"""

    def health(self) -> Awaitable[dict[str, object]]:
        """返回版本、模型列表与延迟信息。"""
