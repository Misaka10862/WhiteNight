"""权限与审批引擎的核心类型（阶段 0 骨架）。

风险分级与默认行为以构建计划第 9 节为准；后续审批状态机在此包实现。
"""

from __future__ import annotations

from enum import StrEnum


class RiskLevel(StrEnum):
    READ_ONLY = "read_only"
    LOW_WRITE = "low_write"
    MEDIUM = "medium"
    HIGH = "high"
    DELETE = "delete"
    BATCH_DELETE = "batch_delete"

    @property
    def default_approval(self) -> bool:
        """该等级默认是否需要审批。"""
        return self in {
            RiskLevel.MEDIUM,
            RiskLevel.HIGH,
            RiskLevel.DELETE,
        }

    @property
    def executable_by_agent(self) -> bool:
        """批量删除不允许任何 Agent 自动执行，只列出目标供用户手动处理。"""
        return self is not RiskLevel.BATCH_DELETE
