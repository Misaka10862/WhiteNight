"""工具层基类：每个工具自带风险等级、参数 Schema 与有来源的结果。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, Field

from whitenight.policy.risk import RiskLevel


class Source(BaseModel):
    """结果来源。网页内容永远带来源标记；本地文件来源为路径。"""

    label: str
    uri: str
    kind: str = "local"


class ToolResult(BaseModel):
    ok: bool
    summary: str
    content: str = ""
    sources: list[Source] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @classmethod
    def failure(cls, summary: str, error: str) -> ToolResult:
        return cls(ok=False, summary=summary, error=error)


@dataclass(frozen=True)
class ToolContext:
    """工具执行上下文：只包含执行所需的最小授权信息。"""

    data_dir: str
    actor: str = "whitenight"


class ToolParameters(BaseModel):
    """工具参数基类；每个工具声明严格 Schema。"""


ParametersT = TypeVar("ParametersT", bound=ToolParameters)


class Tool(Protocol):
    name: str
    description: str
    risk: RiskLevel

    def validate(self, params: dict[str, Any]) -> ToolParameters: ...

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult: ...


class ToolRegistry:
    """工具名 → 实现的确定性注册表；模型输出只能引用注册表中的工具名。"""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools = {tool.name: tool for tool in (tools or [])}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重复注册：{tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)
