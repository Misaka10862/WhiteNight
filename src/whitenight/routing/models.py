"""路由决策模型。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from whitenight.policy.risk import RiskLevel


class TaskCategory(StrEnum):
    CHAT = "chat"
    COMPANIONSHIP = "companionship"
    IMAGE_QA = "image_qa"
    MEMORY = "memory"
    SEARCH = "search"
    FILE_OP = "file_op"
    GUI = "gui"
    CODE = "code"


class ExecutorChoice(StrEnum):
    WHITENIGHT = "whitenight"
    HERMES = "hermes"
    CODEX = "codex"


class RoutingPlan(BaseModel):
    """结构化路由计划：任务类别、执行者、风险等级与预期结果。"""

    category: TaskCategory
    executor: ExecutorChoice
    risk: RiskLevel = RiskLevel.READ_ONLY
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""
    user_override: bool = False
    needs_approval: bool = False
    expected_artifacts: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        self.needs_approval = self.risk.default_approval
