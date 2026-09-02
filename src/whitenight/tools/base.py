"""工具层基类：每个工具自带风险等级、参数 Schema 与有来源的结果。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, get_type_hints

from pydantic import BaseModel, Field

from whitenight.models.base import ToolSpec
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


class FileDeliveryProvider(Protocol):
    def upload_file(self, target: str, path: str, name: str) -> None: ...


class StickerDeliveryProvider(Protocol):
    def send_sticker(self, target: str, sticker_id: str) -> None: ...


@dataclass(frozen=True)
class ToolContext:
    """工具执行上下文：只包含执行所需的最小授权信息。"""

    data_dir: str
    actor: str = "whitenight"
    channel: str | None = None
    channel_target: str | None = None
    file_delivery: FileDeliveryProvider | None = None
    sticker_delivery: StickerDeliveryProvider | None = None


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

    def specs(self, names: set[str] | None = None) -> list[ToolSpec]:
        """Return OpenAI-compatible schemas derived from each validate method."""
        specs: list[ToolSpec] = []
        for name, tool in sorted(self._tools.items()):
            if names is not None and name not in names:
                continue
            model = get_type_hints(tool.validate).get("return")
            if not isinstance(model, type) or not issubclass(model, ToolParameters):
                raise TypeError(f"工具 {name} 的 validate 必须声明 ToolParameters 返回类型")
            schema = model.model_json_schema()
            properties = schema.get("properties")
            if isinstance(properties, dict):
                for field_name in list(properties):
                    if field_name.startswith("approved_"):
                        properties.pop(field_name)
            specs.append(
                ToolSpec(
                    name=name,
                    description=tool.description,
                    parameters=schema,
                )
            )
        return specs
