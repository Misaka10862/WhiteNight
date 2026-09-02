"""Policy-facing sticker selection tool."""

from __future__ import annotations

from pydantic import Field

from whitenight.policy.risk import RiskLevel
from whitenight.stickers.catalog import StickerCatalog
from whitenight.tools.base import Source, ToolContext, ToolParameters, ToolResult


class StickerSendParams(ToolParameters):
    sticker_id: str = Field(description="目录中表情的稳定 ID")


class StickerSendTool:
    name = "channel.sticker.send"
    description = (
        "根据情绪选择一张本地表情包；每轮最多一张。仅在 QQ 私聊中可用，"
        "只能使用目录中的 sticker_id；严肃或任务型对话通常不要调用。"
    )
    risk = RiskLevel.MEDIUM

    def __init__(self, catalog: StickerCatalog, owner_ids: list[int] | None = None) -> None:
        self.catalog = catalog
        self.owner_ids = set(owner_ids or [])

    def available(self) -> bool:
        return bool(self.catalog.records(native_only=True))

    def validate(self, params: dict[str, object]) -> StickerSendParams:
        return StickerSendParams.model_validate(params)

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, StickerSendParams)
        if context.channel != "onebot" or not context.channel_target:
            return ToolResult.failure("表情未发送", "当前渠道不允许发送表情包")
        try:
            target = int(context.channel_target)
        except ValueError:
            return ToolResult.failure("表情未发送", "当前 QQ 目标无效")
        if not self.owner_ids or target not in self.owner_ids:
            return ToolResult.failure("表情未发送", "当前 QQ 目标不在主人白名单中")
        record = self.catalog.get(params.sticker_id, native_only=True)
        if record is None:
            return ToolResult.failure("表情未发送", "sticker_id 不存在、已停用或不在目录中")
        return ToolResult(
            ok=True,
            summary=f"已选择表情：{record.label}",
            content=f"已准备发送表情：{record.label}",
            sources=[Source(label=record.label, uri=f"sticker:{record.id}", kind="sticker")],
            metadata={
                "sticker_id": record.id,
                "label": record.label,
                "segment_type": record.segment_type,
                "emoji_id": record.emoji_id,
                "emoji_package_id": record.emoji_package_id,
                "key": record.key,
            },
        )
