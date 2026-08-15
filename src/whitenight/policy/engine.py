"""权限引擎：风险分级 → 审批模式，独立于模型输出。

规则只由显式配置决定；聊天内容、网页、文档和工具返回值无法修改规则。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from whitenight.policy.risk import RiskLevel


class ApprovalMode(StrEnum):
    AUTO = "auto"  # 只读：自动执行并审计
    SESSION = "session"  # 低风险写入：按会话授权
    ONCE = "once"  # 中/高风险与删除：逐次明确审批
    BLOCKED = "blocked"  # 批量删除等：Agent 永不执行


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    mode: ApprovalMode
    risk: RiskLevel
    reason: str


def mode_for_risk(risk: RiskLevel) -> ApprovalMode:
    if risk is RiskLevel.READ_ONLY:
        return ApprovalMode.AUTO
    if risk is RiskLevel.LOW_WRITE:
        return ApprovalMode.SESSION
    if risk is RiskLevel.BATCH_DELETE:
        return ApprovalMode.BLOCKED
    return ApprovalMode.ONCE


class PolicyEngine:
    """工具名 → 风险等级的确定性规则表；未知工具一律拒绝。"""

    DEFAULT_RULES: ClassVar[dict[str, RiskLevel]] = {
        "document.parse": RiskLevel.READ_ONLY,
        "file.read": RiskLevel.READ_ONLY,
        "screen.capture": RiskLevel.READ_ONLY,
        "web.fetch": RiskLevel.READ_ONLY,
        "web.search": RiskLevel.READ_ONLY,
        "archive.list": RiskLevel.READ_ONLY,
        "file.create": RiskLevel.LOW_WRITE,
        "file.write": RiskLevel.MEDIUM,
        "file.move": RiskLevel.MEDIUM,
        "file.delete": RiskLevel.DELETE,
        "file.batch_delete": RiskLevel.BATCH_DELETE,
    }

    def __init__(self, rules: dict[str, RiskLevel] | None = None) -> None:
        self._rules = dict(self.DEFAULT_RULES)
        if rules:
            self._rules.update(rules)

    def risk_of(self, tool_name: str) -> RiskLevel | None:
        return self._rules.get(tool_name)

    def rules(self) -> dict[str, RiskLevel]:
        """规则快照（只读用途）；返回副本，调用方不能修改引擎。"""
        return dict(self._rules)

    def evaluate(self, tool_name: str) -> PolicyDecision:
        risk = self.risk_of(tool_name)
        if risk is None:
            return PolicyDecision(
                allowed=False,
                mode=ApprovalMode.BLOCKED,
                risk=RiskLevel.HIGH,
                reason=f"未知工具 {tool_name!r}，默认拒绝",
            )
        mode = mode_for_risk(risk)
        if mode is ApprovalMode.BLOCKED:
            return PolicyDecision(
                allowed=False,
                mode=mode,
                risk=risk,
                reason="批量删除不允许 Agent 自动执行：只列出目标，由用户手动处理",
            )
        return PolicyDecision(
            allowed=True,
            mode=mode,
            risk=risk,
            reason=f"{tool_name} 风险等级 {risk.value}",
        )
