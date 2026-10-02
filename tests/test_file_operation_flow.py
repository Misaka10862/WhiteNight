"""Incident regressions: directory discovery, repeated approval and durable execution."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from test_chat_tools import UnexpectedProviderCall, _service
from whitenight.agent.files import FileTaskCoordinator
from whitenight.agent.service import DummyProvider
from whitenight.channels.types import ChannelContext, ChatRequest
from whitenight.policy.approvals import ApprovalService, _now
from whitenight.policy.commands import parse_approval_command
from whitenight.storage.models import Approval, AuditEvent
from whitenight.tools import FileFindTool, FileMoveTool, FileWriteTool
from whitenight.tools.base import ToolContext


def prepare(service, session, source, destination, *, presented=True, channel="web", target=None):
    result = service._tool_executor.execute(
        "file.move",
        {"source": str(source), "destination": str(destination)},
        session_id=session,
        channel=channel,
        channel_target=target,
    )
    assert result.status == "waiting_approval", result.message
    row = service._pending_tools.create(
        approval_id=result.approval_id,
        session_id=session,
        channel=channel,
        channel_target=target,
        tool_call_id="direct-move-" + result.approval_id,
        tool_name="file.move",
        params=result.metadata["prepared_params"],
        assistant_content="",
    )
    if presented:
        service._approvals.mark_presented([result.approval_code])
    return row


async def say(service, session, text):
    return [
        event async for event in service.stream_reply(ChatRequest(session_id=session, text=text))
    ]


@pytest.mark.parametrize("text", ["同意KSUcL45w", "同意 KSUcL45w", "同意KSUcL45w！"])
def test_no_space_approval_commands(text):
    assert parse_approval_command(text).code == "KSUcL45w"


@pytest.mark.parametrize("text", ["全部同意！", "全部同意", "全都允许。"])
def test_bulk_commands(text):
    command = parse_approval_command(text)
    assert command.allow and command.all_pending
    assert parse_approval_command("请阅读文档里的全部同意") is None


def test_find_directory_and_exact_hierarchy(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    directory = tmp_path / "Desktop/new_trial/article"
    directory.mkdir(parents=True)
    (tmp_path / "Desktop/article.txt").write_text("noise")
    tool = FileFindTool()
    result = tool.execute(
        ToolContext(data_dir=str(tmp_path)),
        tool.validate(
            {
                "names": ["new_trial"],
                "root": str(tmp_path / "Desktop"),
                "entry_type": "directory",
                "recursive": False,
                "match_mode": "exact",
            }
        ),
    )
    assert [s.uri for s in result.sources] == [str(directory.parent)]
    assert result.metadata["candidates"][0]["entry_type"] == "directory"
    for text in (
        "把这份文件移到new_trial的article文件夹下",
        "把这份文件移到桌面的new_trial文件夹里的article文件夹下",
    ):
        assert FileTaskCoordinator.move_destination(text) == (directory, None)
    path, error = FileTaskCoordinator.move_destination("把文件移到桌面的new_trial的missing文件夹")
    assert path is None and "不存在" in error  # Never silently move to Desktop or new_trial.


def test_repeated_move_asks_once_and_status_never_calls_model(engine, settings, tmp_path):
    service, store, approvals = _service(
        engine, settings, UnexpectedProviderCall(), [FileMoveTool()]
    )
    session = store.create_session().id
    source, destination = tmp_path / "报告.txt", tmp_path / "已移动.txt"
    source.write_text("preserve this")
    first = prepare(service, session, source, destination)
    second = prepare(service, session, source, destination)
    assert first.id == second.id
    assert len(approvals.list_pending()) == 1
    events = asyncio.run(say(service, session, "完成了吗？"))
    assert "等待审批" in events[-1].text
    assert len(approvals.list_pending()) == 1
    events = asyncio.run(say(service, session, "同意" + first.approval_code))
    assert events[-1].extra["ok"]
    assert destination.read_text() == "preserve this" and not source.exists()
    assert "已移动" in asyncio.run(say(service, session, "完成了吗"))[-1].text
    assert not asyncio.run(say(service, session, "同意" + first.approval_code))[-1].extra["ok"]
    with Session(engine) as orm:
        assert len(orm.scalars(select(AuditEvent).where(AuditEvent.action == "tool.ok")).all()) == 1


def test_case_aliases_deduplicate_only_on_actual_case_insensitive_volume(
    engine, settings, tmp_path
):
    folder = tmp_path / "Article"
    folder.mkdir()
    alias = tmp_path / "article"
    if not alias.exists():
        alias.mkdir()
        assert not folder.samefile(alias)
        return
    service, store, approvals = _service(engine, settings, DummyProvider(), [FileMoveTool()])
    source = tmp_path / "source.txt"
    source.write_text("content")
    session = store.create_session().id
    first = prepare(service, session, source, folder)
    second = prepare(service, session, source, alias)
    assert first.id == second.id and len(approvals.list_pending()) == 1


def test_concurrent_requests_and_confirmations_execute_once(engine, settings, tmp_path):
    service, store, approvals = _service(
        engine, settings, UnexpectedProviderCall(), [FileMoveTool()]
    )
    session = store.create_session().id
    source, target = tmp_path / "a.txt", tmp_path / "b.txt"
    source.write_text("content")
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: prepare(service, session, source, target), range(4)))
    assert len({row.id for row in rows}) == 1

    async def run():
        return await asyncio.gather(
            *[
                service.decide_approvals([rows[0].approval_code], session, ChannelContext())
                for _ in range(4)
            ]
        )

    results = asyncio.run(run())
    assert sum(bool(events[-1].extra["ok"]) for events in results) == 1
    assert target.read_text() == "content"
    assert not approvals.list_pending()


def test_bulk_is_current_presented_snapshot_and_single_done(engine, settings, tmp_path):
    service, store, approvals = _service(
        engine, settings, UnexpectedProviderCall(), [FileMoveTool()]
    )
    session, other = store.create_session().id, store.create_session().id
    rows = []
    for index in range(4):
        source = tmp_path / f"{index}.txt"
        source.write_text(str(index))
        rows.append(
            prepare(
                service,
                other if index == 3 else session,
                source,
                tmp_path / f"moved-{index}.txt",
                presented=index != 2,
            )
        )
    events = asyncio.run(say(service, session, "全部同意！"))
    assert len([event for event in events if event.type == "done"]) == 1
    assert {item["code"] for item in events[-1].extra["results"]} == {
        r.approval_code for r in rows[:2]
    }
    assert {item.code for item in approvals.list_pending()} == {r.approval_code for r in rows[2:]}


def test_new_approval_created_during_bulk_is_not_approved(engine, settings, tmp_path, monkeypatch):
    service, store, approvals = _service(
        engine, settings, UnexpectedProviderCall(), [FileMoveTool()]
    )
    session = store.create_session().id
    source = tmp_path / "a"
    source.write_text("a")
    row = prepare(service, session, source, tmp_path / "b")
    original = FileMoveTool.execute

    def execute(tool, context, params):
        item = approvals.request("file.write", "medium", "once", "new operation", session, "web")
        approvals.mark_presented([item.code])
        return original(tool, context, params)

    monkeypatch.setattr(FileMoveTool, "execute", execute)
    events = asyncio.run(say(service, session, "全部同意"))
    assert events[-1].extra["ok"]
    assert events[-1].extra["results"][0]["code"] == row.approval_code
    assert len(approvals.list_pending()) == 1


def test_changed_destination_supersedes_old_approval(engine, settings, tmp_path):
    service, store, approvals = _service(engine, settings, DummyProvider(), [FileMoveTool()])
    session = store.create_session().id
    source = tmp_path / "a"
    source.write_text("a")
    first = prepare(service, session, source, tmp_path / "b")
    second = prepare(service, session, source, tmp_path / "c")
    assert [item.code for item in approvals.list_pending()] == [second.approval_code]
    assert service._pending_tools.get_by_code(first.approval_code).status == "superseded"
    events = asyncio.run(service.decide_approvals([first.approval_code], session, ChannelContext()))
    assert not events[-1].extra["ok"] and source.exists()


def test_file_change_fails_and_stops_later_actions(engine, settings, tmp_path):
    service, store, _ = _service(engine, settings, UnexpectedProviderCall(), [FileMoveTool()])
    session = store.create_session().id
    sources = [tmp_path / "a", tmp_path / "c"]
    rows = []
    for source in sources:
        source.write_text("original")
        rows.append(prepare(service, session, source, source.with_suffix(".moved")))
    sources[0].write_text("changed after approval")
    events = asyncio.run(
        service.decide_approvals([row.approval_code for row in rows], session, ChannelContext())
    )
    assert [item["status"] for item in events[-1].extra["results"]] == ["failed", "blocked"]
    assert all(source.exists() for source in sources)


def test_cross_session_and_expired_approvals_cannot_execute(engine, settings, tmp_path):
    service, store, _ = _service(engine, settings, DummyProvider(), [FileMoveTool()])
    session, other = store.create_session().id, store.create_session().id
    source = tmp_path / "a"
    source.write_text("a")
    row = prepare(service, session, source, tmp_path / "b")
    events = asyncio.run(service.decide_approvals([row.approval_code], other, ChannelContext()))
    assert not events[-1].extra["ok"]
    with engine.begin() as connection:
        connection.execute(
            update(Approval)
            .where(Approval.id == row.approval_id)
            .values(expires_at=_now() - timedelta(seconds=1))
        )
    assert not asyncio.run(
        service.decide_approvals([row.approval_code], session, ChannelContext())
    )[-1].extra["ok"]
    assert source.exists()


def test_crash_recovery_does_not_reexecute_uncertain_move(engine, settings, tmp_path):
    service, store, _ = _service(engine, settings, DummyProvider(), [FileMoveTool()])
    session = store.create_session().id
    source = tmp_path / "a"
    source.write_text("a")
    row = prepare(service, session, source, tmp_path / "b")
    assert service._pending_tools.claim(row.id)
    service._pending_tools.recover()
    recovered = service._pending_tools.get_by_code(row.approval_code)
    assert recovered.status == "awaiting_review" and "source 存在" in recovered.error
    outcome = service._tool_executor.execute(
        "file.move",
        {"source": str(source), "destination": str(tmp_path / "c")},
        session_id=session,
        channel="web",
    )
    assert outcome.status == "refused" and source.exists()


def test_mixed_bulk_continues_model_once_with_both_results(engine, settings, tmp_path):
    class Provider:
        calls = 0

        async def stream_chat(self, messages, tools=None):
            from whitenight.models.base import ModelChunk

            self.calls += 1
            assert len([message for message in messages if message.role == "tool"]) == 2
            yield ModelChunk(delta="都处理好了", done=True)

    provider = Provider()
    service, store, approvals = _service(
        engine, settings, provider, [FileMoveTool(), FileWriteTool()]
    )
    session = store.create_session().id
    source = tmp_path / "a"
    source.write_text("a")
    first = prepare(service, session, source, tmp_path / "b")
    existing = tmp_path / "c"
    existing.write_text("old")
    outcome = service._tool_executor.execute(
        "file.write", {"path": str(existing), "content": "new"}, session_id=session, channel="web"
    )
    service._pending_tools.create(
        approval_id=outcome.approval_id,
        session_id=session,
        channel="web",
        channel_target=None,
        tool_call_id="write",
        tool_name="file.write",
        params=outcome.metadata["prepared_params"],
        assistant_content="",
    )
    approvals.mark_presented([outcome.approval_code])
    events = asyncio.run(
        service.decide_approvals(
            [first.approval_code, outcome.approval_code], session, ChannelContext()
        )
    )
    assert provider.calls == 1
    assert len([event for event in events if event.type == "done"]) == 1
    assert existing.read_text() == "new"


def test_literal_chinese_directory_and_spaces(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for name in ("上海资料", "我的文件夹", "new trial"):
        folder = tmp_path / "Desktop" / name
        folder.mkdir(parents=True, exist_ok=True)
        assert FileTaskCoordinator.move_destination(f"把文件移到桌面的{name}文件夹下") == (
            folder,
            None,
        )
        assert FileTaskCoordinator.move_destination(f'把文件移到"{folder}"') == (folder, None)


def test_destination_overwrite_change_is_not_approved(engine, settings, tmp_path):
    service, store, approvals = _service(
        engine, settings, UnexpectedProviderCall(), [FileMoveTool()]
    )
    session = store.create_session().id
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_text("source")
    target.write_text("old")
    refusal = service._tool_executor.execute(
        "file.move",
        {"source": str(source), "destination": str(target)},
        session_id=session,
        channel="web",
    )
    assert refusal.status == "refused" and not approvals.list_pending()
    params = {"source": str(source), "destination": str(target), "overwrite": True}
    result = service._tool_executor.execute("file.move", params, session_id=session, channel="web")
    row = service._pending_tools.create(
        approval_id=result.approval_id,
        session_id=session,
        channel="web",
        channel_target=None,
        tool_call_id="overwrite",
        tool_name="file.move",
        params=result.metadata["prepared_params"],
        assistant_content="",
    )
    target.write_text("replaced after approval")
    events = asyncio.run(service.decide_approvals([row.approval_code], session, ChannelContext()))
    assert not events[-1].extra["ok"]
    assert target.read_text() == "replaced after approval" and source.exists()


def test_recovery_uses_audit_receipt_after_result_persistence_crash(engine, settings, tmp_path):
    service, store, approvals = _service(
        engine, settings, UnexpectedProviderCall(), [FileMoveTool()]
    )
    session = store.create_session().id
    source = tmp_path / "a"
    source.write_text("content")
    row = prepare(service, session, source, tmp_path / "b")
    assert service._pending_tools.claim(row.id)
    assert approvals.approve(row.approval_code, session_id=session, channel="web").ok
    outcome = service._tool_executor.execute(
        "file.move", row.params, approval_id=row.approval_id, session_id=session, channel="web"
    )
    assert outcome.status == "ok"
    service._pending_tools.recover()
    assert service._pending_tools.get_by_code(row.approval_code).status == "succeeded"
    assert "已移动" in service.operation_status(session, ChannelContext())


def test_permission_failure_is_not_reported_as_missing(monkeypatch, tmp_path):
    tool = FileFindTool()
    original = Path.stat

    def stat(path, *args, **kwargs):
        if path == tmp_path:
            raise PermissionError(13, "Access denied", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    result = tool.execute(
        ToolContext(data_dir="data"),
        tool.validate({"names": ["article"], "root": str(tmp_path), "entry_type": "directory"}),
    )
    assert not result.ok and "没有访问权限" in result.error and "不存在" not in result.error


def test_batch_api_requires_same_session_and_reports_item_results(client, tmp_path):
    app = client.app
    session = app.state.store.create_session().id
    other = app.state.store.create_session().id
    source = tmp_path / "a"
    source.write_text("content")
    row = prepare(app.state.chat_service, session, source, tmp_path / "b")
    bad = client.post(
        "/api/v1/approvals/batch", json={"session_id": other, "codes": [row.approval_code]}
    ).json()
    assert not bad["ok"] and source.exists()
    response = client.post(
        "/api/v1/approvals/batch", json={"session_id": session, "codes": [row.approval_code]}
    ).json()
    assert response["ok"] and response["results"][0]["status"] == "succeeded"
    replay = client.post(
        f"/api/v1/approvals/{row.approval_code}/approve", json={"session_id": session}
    ).json()
    assert not replay["ok"]


def test_bulk_rejection_keeps_files(engine, settings, tmp_path):
    service, store, approvals = _service(
        engine, settings, UnexpectedProviderCall(), [FileMoveTool()]
    )
    session = store.create_session().id
    for index in range(2):
        source = tmp_path / str(index)
        source.write_text("content")
        prepare(service, session, source, source.with_suffix(".moved"))
    events = asyncio.run(say(service, session, "全部拒绝！"))
    assert events[-1].extra["ok"] and not approvals.list_pending()
    assert (tmp_path / "0").exists() and (tmp_path / "1").exists()


def test_migration_downgrade_upgrade_preserves_evidence(engine, settings):
    import json

    from alembic import command

    from test_personality_migrations import _config
    from whitenight.storage.migrate import upgrade_to_head

    approvals = ApprovalService(engine)
    first = approvals.request("file.move", "medium", "once", "legacy first")
    second = approvals.request("file.move", "medium", "once", "legacy second")
    binding = json.dumps({"binding_version": 1, "params_digest": "same", "summary": "same move"})
    with engine.begin() as connection:
        connection.execute(
            update(Approval)
            .where(Approval.id.in_([first.id, second.id]))
            .values(params_summary=binding)
        )
    config = _config(settings)
    command.downgrade(config, "0012")
    upgrade_to_head(settings)
    with Session(engine) as orm:
        rows = orm.scalars(select(Approval).where(Approval.id.in_([first.id, second.id]))).all()
        assert len(rows) == 2
        assert sorted(row.status for row in rows) == ["pending", "revoked"]
    assert list((settings.data_dir / "backups").glob("pre-migrate-0012-*.db"))


def test_model_multi_file_move_exposes_all_approvals_and_finishes_batch(engine, settings, tmp_path):
    from whitenight.models.base import ModelCapabilities, ModelChunk, ToolCall

    sources = [tmp_path / "first.txt", tmp_path / "second.txt"]
    for source in sources:
        source.write_text(source.name)

    class Provider:
        capabilities = ModelCapabilities(tools=True)
        calls = 0

        async def stream_chat(self, messages, tools=None):
            self.calls += 1
            results = [message for message in messages if message.role == "tool"]
            if not results:
                yield ModelChunk(
                    done=True,
                    tool_calls=[
                        ToolCall(
                            id=f"move-{index}",
                            name="file.move",
                            arguments={
                                "source": str(source),
                                "destination": str(source.with_suffix(".moved")),
                            },
                        )
                        for index, source in enumerate(sources)
                    ],
                )
            else:
                assert len(results) == 2
                yield ModelChunk(delta="两份文件已经移动。", done=True)

    provider = Provider()
    service, store, approvals = _service(engine, settings, provider, [FileMoveTool()])
    session = store.create_session().id
    first = asyncio.run(say(service, session, "把这两份文件移动到新位置"))
    assert first[-1].type == "done"
    assert len(approvals.list_pending()) == 2
    assert all(source.exists() for source in sources)
    events = asyncio.run(say(service, session, "全部同意"))
    assert events[-1].extra["ok"] and provider.calls == 2
    assert len([event for event in events if event.type == "done"]) == 1
    assert all(source.with_suffix(".moved").read_text() == source.name for source in sources)


@pytest.mark.parametrize("all_pending", [False, True])
def test_qq_confirmation_bypasses_collection_window(engine, settings, all_pending):
    from test_onebot import FakeQQ, _adapter, _private

    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    session = str(asyncio.run(adapter.handle_event(_private(1, "你好")))["session_id"])
    adapter._settings.qq_message_window_seconds = 30
    items = [
        adapter._approvals.request(
            "file.write",
            "medium",
            "once",
            f"operation {index}",
            session_id=session,
            channel="onebot",
            channel_target="10001",
        )
        for index in range(2 if all_pending else 1)
    ]
    adapter._approvals.mark_presented([item.code for item in items])
    text = "全部同意！" if all_pending else "同意" + items[0].code

    async def run():
        return await asyncio.wait_for(adapter.handle_event(_private(2, text)), timeout=0.5)

    assert asyncio.run(run())["status"] == "approval_handled"
    assert not adapter._approvals.list_pending()


def test_delegated_approvals_are_not_merged_across_provider_requests(engine):
    approvals = ApprovalService(engine)
    items = [
        approvals.request(
            "delegate.hermes.action",
            "high",
            "once",
            "provider request",
            session_id="session",
            channel="web",
            params={"tool": "same-tool"},
        )
        for _ in range(2)
    ]
    assert items[0].code != items[1].code
