"""截图工具：调用 macOS screencapture。

截图属只读观察，但内容可能敏感：执行自动完成并审计，结果文件不进入聊天附件白名单。
Screen Recording 权限缺失时如实报错。
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from whitenight.policy.risk import RiskLevel
from whitenight.tools.base import Source, ToolContext, ToolParameters, ToolResult


class ScreenshotParams(ToolParameters):
    path: str | None = Field(default=None, description="输出路径；为空则自动生成")


class ScreenshotTool:
    name = "screen.capture"
    description = "截图并保存 PNG，供模型理解屏幕内容"
    risk = RiskLevel.READ_ONLY

    def validate(self, params: dict[str, object]) -> ScreenshotParams:
        return ScreenshotParams.model_validate(params)

    def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
        assert isinstance(params, ScreenshotParams)
        captures = Path(context.data_dir) / "captures"
        captures.mkdir(parents=True, exist_ok=True)
        if params.path:
            target = Path(params.path).expanduser().resolve()
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            target = captures / f"screen-{stamp}.png"
        result = subprocess.run(
            ["/usr/sbin/screencapture", "-x", str(target)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return ToolResult.failure(
                "截图失败",
                result.stderr.strip() or "screencapture 失败（可能缺少系统设置中的屏幕录制权限）",
            )
        return ToolResult(
            ok=True,
            summary=f"已截图：{target}",
            content=f"截图已保存：{target}",
            sources=[Source(label=target.name, uri=str(target), kind="screen")],
            metadata={"path": str(target), "size": target.stat().st_size},
        )
