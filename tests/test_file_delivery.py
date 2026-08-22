from __future__ import annotations

from whitenight.policy.approvals import ApprovalService
from whitenight.policy.audit import AuditService
from whitenight.policy.engine import PolicyEngine
from whitenight.tools import ChannelFileSendTool, ToolContext, ToolExecutor, ToolRegistry


class FakeDelivery:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def upload_file(self, target: str, path: str, name: str) -> None:
        self.sent.append((target, path, name))


def test_qq_file_send_needs_no_confirmation_and_binds_target(engine, tmp_path):
    path = tmp_path / "general.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    approvals = ApprovalService(engine)
    executor = ToolExecutor(
        ToolRegistry([ChannelFileSendTool()]),
        PolicyEngine(),
        approvals,
        AuditService(engine),
    )
    delivery = FakeDelivery()
    outcome = executor.execute(
        "channel.file.send",
        {"path": str(path)},
        session_id="s1",
        channel="onebot",
        channel_target="10001",
        file_delivery=delivery,
    )
    assert outcome.status == "ok"
    assert approvals.list_pending() == []
    assert delivery.sent == [("10001", str(path), "general.jsonl")]


def test_qq_file_send_rejects_changed_file(engine, tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"before")
    approvals = ApprovalService(engine)
    executor = ToolExecutor(
        ToolRegistry([ChannelFileSendTool()]), PolicyEngine(), approvals, AuditService(engine)
    )
    delivery = FakeDelivery()
    tool = ChannelFileSendTool()
    prepared = tool.approval_metadata(
        tool.validate({"path": str(path)}),
        ToolContext(data_dir=str(tmp_path), channel="onebot", channel_target="10001"),
    )["prepared_params"]
    assert isinstance(prepared, dict)
    path.write_bytes(b"after")
    outcome = executor.execute(
        "channel.file.send",
        prepared,
        session_id="s1",
        channel="onebot",
        channel_target="10001",
        file_delivery=delivery,
    )
    assert outcome.status == "error"
    assert delivery.sent == []
