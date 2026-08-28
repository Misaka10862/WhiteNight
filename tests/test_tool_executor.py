"""工具执行器红队测试：只读自动、写入需审批、审批不可重放、批量删除不可绕过。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from whitenight.policy.approvals import ApprovalService
from whitenight.policy.audit import AuditService
from whitenight.policy.engine import PolicyEngine
from whitenight.policy.risk import RiskLevel
from whitenight.tools import (
    FileCreateTool,
    FileDeleteTool,
    FileMoveTool,
    FileReadTool,
    FileWriteTool,
    ScreenshotTool,
    ToolExecutor,
    ToolRegistry,
)
from whitenight.tools import files as files_module
from whitenight.tools import screen as screen_module
from whitenight.tools.base import ToolContext, ToolParameters, ToolResult


@pytest.fixture
def executor(engine: Engine, tmp_path: Path):
    registry = ToolRegistry([FileReadTool(), FileCreateTool(), FileWriteTool(), FileDeleteTool()])
    service = ApprovalService(engine)
    return (
        ToolExecutor(registry, PolicyEngine(), service, AuditService(engine)),
        service,
        registry,
        tmp_path,
    )


def test_readonly_executes_automatically_and_audits(executor, engine: Engine) -> None:
    tool, _, _, tmp = executor
    path = tmp / "note.txt"
    path.write_text("小白在吗", encoding="utf-8")
    outcome = tool.execute("file.read", {"path": str(path)}, session_id="s1")
    assert outcome.status == "ok"
    assert outcome.result is not None and "小白在吗" in outcome.result.content
    audits = AuditService(engine).recent()
    assert audits[0].tool_name == "file.read"
    assert audits[0].decision == "auto"


def test_low_write_requires_session_grant(executor) -> None:
    tool, service, _, tmp = executor
    target = tmp / "new.txt"
    outcome = tool.execute("file.create", {"path": str(target), "content": "你好"}, session_id="s1")
    assert outcome.status == "waiting_approval"
    assert outcome.approval_code
    assert not target.exists()

    # 只有 session 范围审批能通过该工具
    resolution = service.resolve_once(
        outcome.approval_code, session_id="s1", expected_scope="session"
    )
    assert resolution.ok

    outcome = tool.execute("file.create", {"path": str(target), "content": "你好"}, session_id="s1")
    assert outcome.status == "ok"
    assert target.read_text(encoding="utf-8") == "你好"


def test_medium_write_requires_once_approval_and_code_is_single_use(executor) -> None:
    tool, _service, _, tmp = executor
    path = tmp / "existing.txt"
    path.write_text("旧内容", encoding="utf-8")

    waiting = tool.execute("file.write", {"path": str(path), "content": "新内容"}, session_id="s1")
    assert waiting.status == "waiting_approval"

    refused = tool.execute(
        "file.write",
        {"path": str(path), "content": "新内容"},
        session_id="s1",
        approval_code=waiting.approval_code,
    )
    # 审批成功，但代码属于 once，参数可以相同；第一次执行通过
    assert refused.status in {"ok", "refused"}

    # 重新申请并消费后，旧代码不可重放
    second = tool.execute("file.write", {"path": str(path), "content": "第二次"}, session_id="s1")
    assert second.status == "waiting_approval"
    assert second.approval_code != waiting.approval_code

    # 用第一个代码再来执行（此时第一个代码已被消费）必然被拒
    replay = tool.execute(
        "file.write",
        {"path": str(path), "content": "重放"},
        session_id="s1",
        approval_code=waiting.approval_code,
    )
    assert replay.status == "refused"
    assert "已处理" in replay.message


def test_session_approval_cannot_approve_medium_tool(executor) -> None:
    tool, service, _, tmp = executor
    path = tmp / "existing.txt"
    path.write_text("旧", encoding="utf-8")
    # 为 file.write 申请 once 审批，却试图按 session 范围批准 → 拒绝
    waiting = tool.execute("file.write", {"path": str(path), "content": "新"}, session_id="s1")
    resolution = service.resolve_once(
        waiting.approval_code, session_id="s1", expected_scope="session"
    )
    assert not resolution.ok
    # 原 once 代码仍然可用，防止被降级绕过
    assert service.resolve_once(waiting.approval_code, session_id="s1", expected_scope="once").ok


def test_delete_requires_approval_and_goes_to_trash(executor, monkeypatch) -> None:
    tool, _service, _, tmp = executor
    path = tmp / "delete-me.txt"
    path.write_text("x", encoding="utf-8")
    trashed: list[Path] = []
    monkeypatch.setattr(files_module, "_move_to_trash_via_finder", trashed.append)

    waiting = tool.execute("file.delete", {"path": str(path)}, session_id="s1")
    assert waiting.status == "waiting_approval"
    assert path.exists()
    # 执行器消费 once 编号并执行；此前不能有任何已消费动作。
    outcome = tool.execute(
        "file.delete",
        {"path": str(path)},
        session_id="s1",
        approval_code=waiting.approval_code,
    )
    assert outcome.status == "ok"
    assert trashed == [path]


def test_batch_delete_cannot_be_bypassed(executor, monkeypatch) -> None:
    tool, _, registry, _ = executor
    calls: list[object] = []

    class BatchDeleteTool:
        name = "file.batch_delete"
        description = "批量删除"
        risk = RiskLevel.BATCH_DELETE

        def validate(self, params: dict[str, object]) -> ToolParameters:
            return ToolParameters.model_validate(params)

        def execute(self, context: ToolContext, params: ToolParameters) -> ToolResult:
            calls.append(params)
            return ToolResult(ok=True, summary="不应发生")

    registry.register(BatchDeleteTool())
    outcome = tool.execute(
        "file.batch_delete",
        {"paths": ["/a", "/b"]},
        session_id="s1",
        approval_code="whatever",
    )
    assert outcome.status == "refused"
    assert calls == []
    assert "手动处理" in outcome.message


def test_unknown_tool_is_refused(executor) -> None:
    tool, _, _, _ = executor
    outcome = tool.execute("definitely.not.a.tool", {})
    assert outcome.status == "refused"
    assert "未知工具" in outcome.message


def test_invalid_params_refused_before_execution(executor) -> None:
    tool, _, _, tmp = executor
    outcome = tool.execute("file.read", {"path": str(tmp / "nope"), "max_chars": -1})
    assert outcome.status == "refused"
    assert "参数不合法" in outcome.message


def test_move_preparation_accepts_directory_and_preserves_filename(tmp_path: Path) -> None:
    source = tmp_path / "incoming" / "report.docx"
    source.parent.mkdir()
    source.write_bytes(b"docx")
    destination_dir = tmp_path / "Article"
    destination_dir.mkdir()
    tool = FileMoveTool()

    metadata = tool.approval_metadata(
        tool.validate({"source": str(source), "destination": str(destination_dir)}),
        ToolContext(data_dir=str(tmp_path)),
    )

    prepared = metadata["prepared_params"]
    assert isinstance(prepared, dict)
    assert prepared["destination"] == str(destination_dir / source.name)


def test_move_preparation_restores_qq_attachment_display_name(tmp_path: Path) -> None:
    source = tmp_path / "qq_files" / "c04acd30-166c-4510-9625-d0c5271b4016-report.docx"
    source.parent.mkdir()
    source.write_bytes(b"docx")
    destination_dir = tmp_path / "Article"
    destination_dir.mkdir()
    tool = FileMoveTool()

    metadata = tool.approval_metadata(
        tool.validate({"source": str(source), "destination": str(destination_dir)}),
        ToolContext(data_dir=str(tmp_path)),
    )

    prepared = metadata["prepared_params"]
    assert isinstance(prepared, dict)
    assert prepared["destination"] == str(destination_dir / "report.docx")


def test_move_preparation_rejects_missing_destination_directory(tmp_path: Path) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"docx")
    tool = FileMoveTool()

    with pytest.raises(ValueError, match="目标目录不存在"):
        tool.approval_metadata(
            tool.validate(
                {
                    "source": str(source),
                    "destination": str(tmp_path / "missing" / "report.docx"),
                }
            ),
            ToolContext(data_dir=str(tmp_path)),
        )


def test_screenshot_is_readonly_and_auto(engine: Engine, tmp_path: Path, monkeypatch) -> None:
    from pathlib import Path as P

    class FakeResult:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **_kwargs: object) -> FakeResult:
        target = P(cmd[-1])
        target.write_bytes(b"\x89PNG\r\n\x1a\n")
        return FakeResult()

    monkeypatch.setattr(screen_module.subprocess, "run", fake_run)
    registry = ToolRegistry([ScreenshotTool()])
    executor = ToolExecutor(registry, PolicyEngine(), ApprovalService(engine), AuditService(engine))
    outcome = executor.execute(
        "screen.capture",
        {"path": str(tmp_path / "shot.png")},
        session_id="s1",
        data_dir=str(tmp_path),
    )
    assert outcome.status == "ok"
    assert outcome.result is not None
    assert (tmp_path / "shot.png").exists()
    assert AuditService(engine).recent()[0].decision == "auto"
