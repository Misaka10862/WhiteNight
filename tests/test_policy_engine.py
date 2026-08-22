"""权限引擎与审批状态机测试。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import Engine

from whitenight.policy.approvals import ApprovalService
from whitenight.policy.engine import ApprovalMode, PolicyEngine
from whitenight.policy.risk import RiskLevel


def test_default_rules_and_unknown_tools() -> None:
    engine = PolicyEngine()
    assert engine.evaluate("file.read").mode is ApprovalMode.AUTO
    assert engine.evaluate("file.create").mode is ApprovalMode.SESSION
    assert engine.evaluate("file.write").mode is ApprovalMode.ONCE
    assert engine.evaluate("file.delete").mode is ApprovalMode.ONCE
    assert engine.evaluate("channel.file.send").mode is ApprovalMode.AUTO
    assert engine.evaluate("channel.file.send").risk is RiskLevel.MEDIUM
    unknown = engine.evaluate("evil.pwn")
    assert unknown.mode is ApprovalMode.BLOCKED
    assert not unknown.allowed


def test_batch_delete_never_executable_by_agent() -> None:
    decision = PolicyEngine().evaluate("file.batch_delete")
    assert decision.mode is ApprovalMode.BLOCKED
    assert not decision.allowed
    assert "手动处理" in decision.reason


def test_approval_once_is_single_use(engine: Engine) -> None:
    service = ApprovalService(engine)
    request = service.request("file.write", "medium", "once", '{"path":"/a"}')
    assert service.resolve_once(request.code).ok
    replay = service.resolve_once(request.code)
    assert not replay.ok
    assert "已处理" in replay.reason


def test_approval_session_scope_creates_grant(engine: Engine) -> None:
    service = ApprovalService(engine)
    request = service.request(
        "file.create", "low_write", "session", '{"path":"/a"}', session_id="s1"
    )
    resolution = service.resolve_once(request.code, session_id="s1", expected_scope="session")
    assert resolution.ok
    assert service.has_session_grant("s1", "file.create")
    # 编号本身同样不可重放
    assert not service.resolve_once(request.code, session_id="s1", expected_scope="session").ok


def test_approval_scope_mismatch_rejected(engine: Engine) -> None:
    service = ApprovalService(engine)
    request = service.request("file.write", "medium", "once", '{"path":"/a"}')
    resolution = service.resolve_once(request.code, expected_scope="session")
    assert not resolution.ok
    assert "范围不匹配" in resolution.reason


def test_approval_expires(engine: Engine) -> None:
    service = ApprovalService(engine, once_ttl=timedelta(seconds=-1))
    request = service.request("file.write", "medium", "once", '{"path":"/a"}')
    resolution = service.resolve_once(request.code)
    assert not resolution.ok
    assert "过期" in resolution.reason


def test_session_grant_absent_by_default(engine: Engine) -> None:
    assert not ApprovalService(engine).has_session_grant("s", "file.create")


def test_risk_defaults() -> None:
    assert not RiskLevel.READ_ONLY.default_approval
    assert not RiskLevel.LOW_WRITE.default_approval
    assert RiskLevel.MEDIUM.default_approval
    assert not RiskLevel.BATCH_DELETE.executable_by_agent


@pytest.mark.parametrize("tool_name", ["file.read", "web.search", "document.parse"])
def test_readonly_tools_are_auto(tool_name: str) -> None:
    assert PolicyEngine().evaluate(tool_name).mode is ApprovalMode.AUTO
