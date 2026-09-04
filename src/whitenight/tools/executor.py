"""工具执行器：PolicyEngine 决策 → 审批 → 执行 → 审计。

模型输出永远不能越过这一层；工具参数由各工具 Schema 严格验证。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from whitenight.policy.approvals import ApprovalService, Resolution
from whitenight.policy.audit import AuditService
from whitenight.policy.engine import ApprovalMode, PolicyEngine
from whitenight.tools.base import FileDeliveryProvider, ToolContext, ToolRegistry, ToolResult


@dataclass
class ExecutionOutcome:
    status: str  # ok | waiting_approval | refused | error
    message: str
    result: ToolResult | None = None
    approval_id: str | None = None
    approval_code: str | None = None
    approval_scope: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def summarize_params(params: dict[str, Any]) -> str:
    """参数摘要：内容类字段只保留长度，避免审计记录膨胀或泄露全文。"""
    safe: dict[str, Any] = {}
    for key, value in params.items():
        if key in {"content"} and isinstance(value, str):
            safe[key] = f"<{len(value)} chars>"
        else:
            text = str(value)
            safe[key] = text[:200]
    return json.dumps(safe, ensure_ascii=False, default=str)


class ToolExecutor:
    """唯一允许执行现实动作的入口。"""

    def __init__(
        self,
        registry: ToolRegistry,
        policy: PolicyEngine,
        approvals: ApprovalService,
        audit: AuditService,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._approvals = approvals
        self._audit = audit

    def execute(
        self,
        tool_name: str,
        params: dict[str, Any],
        *,
        session_id: str | None = None,
        channel: str | None = None,
        actor: str = "whitenight",
        approval_code: str | None = None,
        approval_id: str | None = None,
        data_dir: str = "data",
        channel_target: str | None = None,
        file_delivery: FileDeliveryProvider | None = None,
    ) -> ExecutionOutcome:
        decision = self._policy.evaluate(tool_name)
        tool = self._registry.get(tool_name)
        summary = summarize_params(params)

        if tool is None or not decision.allowed or decision.mode is ApprovalMode.BLOCKED:
            self._audit.record(
                actor=actor,
                action="tool.refused",
                decision="refused",
                tool_name=tool_name,
                risk=decision.risk.value,
                params_summary=summary,
                result_summary=decision.reason,
                session_id=session_id,
                channel=channel,
            )
            return ExecutionOutcome(status="refused", message=decision.reason)

        try:
            validated = tool.validate(params)
        except ValidationError as exc:
            self._audit.record(
                actor=actor,
                action="tool.invalid_params",
                decision="refused",
                tool_name=tool_name,
                risk=decision.risk.value,
                params_summary=summary,
                result_summary=str(exc),
                session_id=session_id,
                channel=channel,
            )
            return ExecutionOutcome(status="refused", message=f"参数不合法：{exc}")

        context = ToolContext(
            data_dir=data_dir,
            actor=actor,
            channel=channel,
            channel_target=channel_target,
            file_delivery=file_delivery,
        )
        approval_metadata: dict[str, Any] = {}
        prepare = getattr(tool, "approval_metadata", None)
        if callable(prepare):
            try:
                approval_metadata = dict(prepare(validated, context))
                prepared = approval_metadata.get("prepared_params")
                if isinstance(prepared, dict):
                    params = prepared
                    validated = tool.validate(prepared)
                approval_summary = approval_metadata.get("approval_summary")
                if isinstance(approval_summary, dict):
                    summary = summarize_params(approval_summary)
            except (ValidationError, ValueError) as exc:
                return ExecutionOutcome(status="refused", message=f"参数不合法：{exc}")

        consumed_approval_id: str | None = None
        bound_params = validated.model_dump(mode="json")

        if approval_id is not None:
            expected_scope = "session" if decision.mode is ApprovalMode.SESSION else "once"
            resolution = self._approvals.consume_approved(
                approval_id,
                session_id=session_id,
                expected_scope=expected_scope,
                tool_name=tool_name,
                params=bound_params,
                channel=channel,
                channel_target=channel_target,
            )
            if not resolution.ok:
                return self._refused_resolution(
                    tool_name, decision, summary, resolution, actor, session_id, channel
                )
            consumed_approval_id = resolution.approval_id

        if approval_id is not None or decision.mode is ApprovalMode.AUTO:
            pass
        elif decision.mode is ApprovalMode.SESSION:
            if session_id and self._approvals.has_session_grant(
                session_id,
                tool_name,
                channel=channel,
                channel_target=channel_target,
            ):
                pass
            elif approval_code:
                resolution = self._approvals.resolve_once(
                    approval_code,
                    session_id=session_id,
                    expected_scope="session",
                    tool_name=tool_name,
                    params=bound_params,
                    channel=channel,
                    channel_target=channel_target,
                )
                if not resolution.ok:
                    return self._refused_resolution(
                        tool_name, decision, summary, resolution, actor, session_id, channel
                    )
                consumed_approval_id = resolution.approval_id
            else:
                request = self._approvals.request(
                    tool_name=tool_name,
                    risk=decision.risk.value,
                    scope="session",
                    params_summary=summary,
                    session_id=session_id,
                    channel=channel,
                    channel_target=channel_target,
                    params=bound_params,
                )
                return ExecutionOutcome(
                    status="waiting_approval",
                    message=f"{tool_name} 需要审批，可选择单次或会话授权",
                    approval_id=request.id,
                    approval_code=request.code,
                    approval_scope="session",
                    metadata=approval_metadata,
                )
        elif decision.mode is ApprovalMode.ONCE:
            if not approval_code:
                request = self._approvals.request(
                    tool_name=tool_name,
                    risk=decision.risk.value,
                    scope="once",
                    params_summary=summary,
                    session_id=session_id,
                    channel=channel,
                    channel_target=channel_target,
                    params=bound_params,
                )
                return ExecutionOutcome(
                    status="waiting_approval",
                    message=f"{tool_name} 需要逐次审批",
                    approval_id=request.id,
                    approval_code=request.code,
                    approval_scope="once",
                    metadata=approval_metadata,
                )
            resolution = self._approvals.resolve_once(
                approval_code,
                session_id=session_id,
                expected_scope="once",
                tool_name=tool_name,
                params=bound_params,
                channel=channel,
                channel_target=channel_target,
            )
            if not resolution.ok:
                return self._refused_resolution(
                    tool_name, decision, summary, resolution, actor, session_id, channel
                )
            consumed_approval_id = resolution.approval_id
        else:  # 理论不可达：defense in depth
            return ExecutionOutcome(status="refused", message="未知审批模式")

        try:
            result = tool.execute(context, validated)
        except Exception as exc:  # 工具异常如实记录，不吞掉也不执行后续动作
            self._audit.record(
                actor=actor,
                action="tool.error",
                decision="error",
                tool_name=tool_name,
                risk=decision.risk.value,
                params_summary=summary,
                result_summary=str(exc),
                session_id=session_id,
                channel=channel,
                approval_id=consumed_approval_id,
            )
            return ExecutionOutcome(status="error", message=f"{tool_name} 执行失败：{exc}")

        decision_label = "approved" if consumed_approval_id else ("auto" if result.ok else "error")
        self._audit.record(
            actor=actor,
            action=f"tool.{'ok' if result.ok else 'failed'}",
            decision=decision_label,
            tool_name=tool_name,
            risk=decision.risk.value,
            params_summary=summary,
            result_summary=result.summary if result.ok else (result.error or ""),
            session_id=session_id,
            channel=channel,
            approval_id=consumed_approval_id,
        )
        return ExecutionOutcome(
            status="ok" if result.ok else "error",
            message=result.summary if result.ok else (result.error or "工具失败"),
            result=result,
            approval_id=consumed_approval_id,
        )

    def _refused_resolution(
        self,
        tool_name: str,
        decision: Any,
        summary: str,
        resolution: Resolution,
        actor: str,
        session_id: str | None,
        channel: str | None,
    ) -> ExecutionOutcome:
        self._audit.record(
            actor=actor,
            action="tool.approval_rejected",
            decision="refused",
            tool_name=tool_name,
            risk=decision.risk.value,
            params_summary=summary,
            result_summary=resolution.reason,
            session_id=session_id,
            channel=channel,
        )
        return ExecutionOutcome(status="refused", message=resolution.reason)
