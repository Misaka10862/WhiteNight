"""End-to-end local model tool loop and approval continuation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from whitenight.agent.service import ChatService
from whitenight.channels.types import ChannelContext, ChatRequest
from whitenight.models.base import (
    ModelCapabilities,
    ModelChunk,
    ProviderMessage,
    ToolCall,
    ToolSpec,
)
from whitenight.policy.approvals import ApprovalService
from whitenight.policy.audit import AuditService
from whitenight.policy.engine import PolicyEngine
from whitenight.storage.sessions import SessionStore
from whitenight.tools import (
    ChannelFileSendTool,
    FileFindTool,
    FileMoveTool,
    FileReadTool,
    FileWriteTool,
    ToolExecutor,
    ToolRegistry,
)
from whitenight.tools.pending import PendingToolStore


class FindProvider:
    capabilities = ModelCapabilities(tools=True)

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        assert tools and any(tool.name == "file.find" for tool in tools)
        tool_message = next((message for message in messages if message.role == "tool"), None)
        if tool_message is None:
            yield ModelChunk(
                done=True,
                tool_calls=[
                    ToolCall(
                        id="find-1",
                        name="file.find",
                        arguments={"names": ["adult.jsonl"]},
                    )
                ],
            )
        else:
            assert "adult.jsonl" in tool_message.content
            yield ModelChunk(delta="找到了 adult.jsonl。")
            yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class AttachmentContextProvider:
    capabilities = ModelCapabilities(tools=True)

    def __init__(self, attachment: Path) -> None:
        self.attachment = attachment

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        del tools
        context = next(
            message.content
            for message in messages
            if message.role == "system"
            and "服务器已验证当前会话最近收到的 QQ 附件" in message.content
        )
        assert f"绝对路径：{self.attachment.resolve()}" in context
        yield ModelChunk(delta="已识别附件。")
        yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class WriteProvider:
    capabilities = ModelCapabilities(tools=True)

    def __init__(self, path: Path) -> None:
        self.path = path

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        if not any(message.role == "tool" for message in messages):
            yield ModelChunk(
                done=True,
                tool_calls=[
                    ToolCall(
                        id="write-1",
                        name="file.write",
                        arguments={"path": str(self.path), "content": "new"},
                    )
                ],
            )
        else:
            yield ModelChunk(delta="文件已经修改。")
            yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class RepeatingInvalidMoveProvider:
    capabilities = ModelCapabilities(tools=True)

    """Models a small model retrying an unchanged invalid move call."""

    def __init__(self, source: Path, destination: Path) -> None:
        self.source = source
        self.destination = destination

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        assert tools and any(tool.name == "file.move" for tool in tools)
        tool_messages = [message for message in messages if message.role == "tool"]
        if len(tool_messages) < 2:
            yield ModelChunk(
                done=True,
                tool_calls=[
                    ToolCall(
                        id=f"move-{len(tool_messages)}",
                        name="file.move",
                        arguments={
                            "source": str(self.source),
                            "destination": str(self.destination),
                        },
                    )
                ],
            )
            return
        assert "已跳过模型重复调用" in tool_messages[-1].content
        yield ModelChunk(delta="请重新发送可用的源文件。")
        yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class UnexpectedProviderCall:
    capabilities = ModelCapabilities(tools=True)

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        del messages, tools
        raise AssertionError("provider must not be called when the attachment is unavailable")
        yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class UnexpectedMoveProvider:
    capabilities = ModelCapabilities(tools=True)

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        del messages, tools
        raise AssertionError("direct attachment move should not call the model")
        yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class ParallelReadProvider:
    capabilities = ModelCapabilities(tools=True)

    def __init__(self, first: Path, second: Path) -> None:
        self.first = first
        self.second = second

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        tool_messages = [message for message in messages if message.role == "tool"]
        if not tool_messages:
            yield ModelChunk(
                done=True,
                tool_calls=[
                    ToolCall(id="read-1", name="file.read", arguments={"path": str(self.first)}),
                    ToolCall(id="read-2", name="file.read", arguments={"path": str(self.second)}),
                ],
            )
        else:
            assert [message.tool_call_id for message in tool_messages] == ["read-1", "read-2"]
            assert "first" in tool_messages[0].content
            assert "second" in tool_messages[1].content
            yield ModelChunk(delta="两个文件都读取完成。")
            yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class StallingFileDeliveryProvider:
    capabilities = ModelCapabilities(tools=True)

    def __init__(self, root: Path) -> None:
        self.root = root

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        assert tools and any(tool.name == "channel.file.send" for tool in tools)
        tool_messages = [message for message in messages if message.role == "tool"]
        sent = [message for message in tool_messages if message.name == "channel.file.send"]
        found = [message for message in tool_messages if message.name == "file.find"]
        if sent:
            assert len(sent) == 2
            yield ModelChunk(delta="两个文件已经发送。")
            yield ModelChunk(done=True)
        elif found:
            yield ModelChunk(delta="我马上把两个文件发给你。")
            yield ModelChunk(done=True)
        else:
            yield ModelChunk(
                done=True,
                tool_calls=[
                    ToolCall(
                        id="find-for-send",
                        name="file.find",
                        arguments={
                            "names": ["adult.jsonl", "general.jsonl"],
                            "root": str(self.root),
                        },
                    )
                ],
            )

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class FakeDelivery:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def upload_file(self, target: str, path: str, name: str) -> None:
        self.sent.append((target, path, name))


class FailingDelivery:
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def upload_file(self, target: str, path: str, name: str) -> None:
        del target, name
        self.attempts.append(path)
        raise RuntimeError("NapCat rejected upload")


class UnauthorizedSendProvider:
    capabilities = ModelCapabilities(tools=True)

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        del messages
        assert tools and all(tool.name != "channel.file.send" for tool in tools)
        yield ModelChunk(
            done=True,
            tool_calls=[
                ToolCall(
                    id="unauthorized-send",
                    name="channel.file.send",
                    arguments={"path": "/tmp/not-authorized.txt"},
                )
            ],
        )

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class AmbiguousFileDeliveryProvider:
    capabilities = ModelCapabilities(tools=True)

    def __init__(self, root: Path) -> None:
        self.root = root

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        del messages
        assert tools and any(tool.name == "channel.file.send" for tool in tools)
        yield ModelChunk(
            done=True,
            tool_calls=[
                ToolCall(
                    id="ambiguous-find",
                    name="file.find",
                    arguments={
                        "names": ["report.txt"],
                        "root": str(self.root),
                        "match_mode": "fuzzy",
                        "expected_count": 1,
                        "similarity_threshold": 0.6,
                    },
                )
            ],
        )

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class WrongRootFileDeliveryProvider:
    capabilities = ModelCapabilities(tools=True)

    def __init__(self, wrong_root: Path) -> None:
        self.wrong_root = wrong_root

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncGenerator[ModelChunk, None]:
        assert tools and any(tool.name == "channel.file.send" for tool in tools)
        if any(message.role == "tool" for message in messages):
            yield ModelChunk(done=True)
            return
        yield ModelChunk(
            done=True,
            tool_calls=[
                ToolCall(
                    id="wrong-root-find",
                    name="file.find",
                    arguments={
                        "names": ["Methods_4改.docx"],
                        "root": str(self.wrong_root),
                    },
                )
            ],
        )

    async def health(self) -> dict[str, object]:
        return {"ok": True}


def _service(engine, settings, provider, tools, file_delivery=None):
    store = SessionStore(engine)
    approvals = ApprovalService(engine)
    policy = PolicyEngine()
    registry = ToolRegistry(tools)
    executor = ToolExecutor(registry, policy, approvals, AuditService(engine))
    return (
        ChatService(
            store,
            provider,
            settings,
            tool_registry=registry,
            tool_executor=executor,
            approvals=approvals,
            pending_tools=PendingToolStore(engine),
            policy=policy,
            file_delivery=file_delivery,
        ),
        store,
        approvals,
    )


def test_chat_executes_find_and_returns_grounded_answer(engine, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "adult.jsonl").write_text("{}\n", encoding="utf-8")
    service, store, _ = _service(engine, settings, FindProvider(), [FileFindTool()])
    session = store.create_session()

    async def run():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(session_id=session.id, text="找一下 adult.jsonl")
            )
        ]

    events = asyncio.run(run())
    assert any(event.type == "tool" for event in events)
    assert events[-1].text == "找到了 adult.jsonl。"


def test_write_approval_resumes_original_call(engine, settings, tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("old", encoding="utf-8")
    service, store, approvals = _service(
        engine, settings, WriteProvider(path), [FileReadTool(), FileWriteTool()]
    )
    session = store.create_session()

    async def request():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(session_id=session.id, text="修改这个文件")
            )
        ]

    events = asyncio.run(request())
    assert events[-2].type == "approval"
    assert path.read_text(encoding="utf-8") == "old"
    code = approvals.list_pending()[0].code
    resumed = asyncio.run(service.resume_approval(code, ChannelContext(channel="web")))
    assert resumed[-1].type == "done"
    assert path.read_text(encoding="utf-8") == "new"


def test_repeated_invalid_move_call_is_returned_to_model_without_crashing(
    engine, settings, tmp_path
):
    source = tmp_path / "missing.exe"
    destination = tmp_path / "Desktop" / "pvzHE" / "missing.exe"
    destination.parent.mkdir(parents=True)
    service, store, _ = _service(
        engine,
        settings,
        RepeatingInvalidMoveProvider(source, destination),
        [FileMoveTool()],
    )
    session = store.create_session()

    async def run():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(session_id=session.id, text="把这个文件移动到桌面 pvzHE 文件夹")
            )
        ]

    events = asyncio.run(run())

    assert not any(event.type == "error" for event in events)
    assert events[-1].type == "done"
    assert events[-1].text == "请重新发送可用的源文件。"


def test_missing_qq_attachment_blocks_move_before_model_guess(engine, settings):
    service, store, _ = _service(
        engine,
        settings,
        UnexpectedProviderCall(),
        [FileMoveTool()],
    )
    session = store.create_session()
    store.record_attachment_message(
        session.id,
        "AdobeAnimateEditor.exe",
        channel="onebot",
        error="文件接收失败：超过当前 16 MiB 限制",
    )

    async def run():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(session_id=session.id, text="把这个文件放到桌面的 pvzHE 文件夹下")
            )
        ]

    events = asyncio.run(run())

    assert events[-1].type == "done"
    assert events[-1].text == (
        "刚才的文件没有成功接收：文件接收失败：超过当前 16 MiB 限制。请重新发送文件后，我再帮你移动。"
    )


def test_recent_qq_attachment_move_gets_deterministic_approval(
    engine, settings, tmp_path, monkeypatch
):
    attachment = settings.data_dir / "qq_files" / "received.zip"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"zip")
    destination = tmp_path / "Desktop" / "pvzHE"
    destination.mkdir(parents=True)
    service, store, approvals = _service(
        engine,
        settings,
        UnexpectedMoveProvider(),
        [FileMoveTool()],
    )
    session = store.create_session()
    store.record_attachment_message(session.id, "received.zip", channel="onebot", path=attachment)

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    async def run():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(session_id=session.id, text="把这个文件放到桌面 pvzHE 文件夹下")
            )
        ]

    events = asyncio.run(run())

    assert events[-1].type == "done"
    assert "需要审批" in events[-1].text
    assert len(approvals.list_pending()) == 1


def test_chat_accepts_parallel_tool_calls_and_returns_each_result(engine, settings, tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    service, store, _ = _service(
        engine, settings, ParallelReadProvider(first, second), [FileReadTool()]
    )
    session = store.create_session()

    async def run():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(session_id=session.id, text="读取两个文件")
            )
        ]

    events = asyncio.run(run())
    tool_events = [event for event in events if event.type == "tool"]
    assert [event.extra["tool_name"] for event in tool_events] == ["file.read", "file.read"]
    assert all(event.extra["status"] == "ok" for event in tool_events)
    assert events[-1].text == "两个文件都读取完成。"


def test_file_delivery_goal_recovers_when_model_only_promises(engine, settings, tmp_path):
    adult = tmp_path / "adult.jsonl"
    general = tmp_path / "general.jsonl"
    adult.write_text("adult", encoding="utf-8")
    general.write_text("general", encoding="utf-8")
    delivery = FakeDelivery()
    service, store, approvals = _service(
        engine,
        settings,
        StallingFileDeliveryProvider(tmp_path),
        [FileFindTool(), ChannelFileSendTool()],
        delivery,
    )
    session = store.create_session()

    async def run():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(
                    session_id=session.id,
                    text="找到 adult.jsonl 和 general.jsonl 两个文件发给我",
                ),
                ChannelContext(channel="onebot", target="10001"),
            )
        ]

    events = asyncio.run(run())
    assert approvals.list_pending() == []
    assert sorted((path, name) for _, path, name in delivery.sent) == [
        (str(adult), "adult.jsonl"),
        (str(general), "general.jsonl"),
    ]
    orchestrated = [
        event
        for event in events
        if event.type == "tool" and event.extra and event.extra.get("orchestrated")
    ]
    assert len(orchestrated) == 2
    assert events[-1].type == "done"
    assert events[-1].text == "已发送 2 个文件。"
    assert "马上" not in store.list_messages(session.id)[-1].content


def test_file_delivery_goal_stops_after_provider_failure(engine, settings, tmp_path):
    for name in ("adult.jsonl", "general.jsonl"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    delivery = FailingDelivery()
    service, store, _ = _service(
        engine,
        settings,
        StallingFileDeliveryProvider(tmp_path),
        [FileFindTool(), ChannelFileSendTool()],
        delivery,
    )
    session = store.create_session()

    async def run():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(session_id=session.id, text="找到两个 jsonl 文件发给我"),
                ChannelContext(channel="onebot", target="10001"),
            )
        ]

    events = asyncio.run(run())
    assert len(delivery.attempts) == 2
    assert events[-1].type == "error"
    assert events[-1].message and "文件发送失败" in events[-1].message
    assert len(store.list_messages(session.id)) == 1


def test_send_tool_cannot_run_without_current_delivery_intent(engine, settings):
    delivery = FakeDelivery()
    service, store, _ = _service(
        engine,
        settings,
        UnauthorizedSendProvider(),
        [FileReadTool(), ChannelFileSendTool()],
        delivery,
    )
    session = store.create_session()

    async def run():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(session_id=session.id, text="你好"),
                ChannelContext(channel="onebot", target="10001"),
            )
        ]

    events = asyncio.run(run())
    assert delivery.sent == []
    assert events[-1].type == "error"
    assert events[-1].message and "模型调用失败" in events[-1].message


def test_ambiguous_file_delivery_asks_before_sending(engine, settings, tmp_path):
    (tmp_path / "report-final.txt").write_text("one", encoding="utf-8")
    (tmp_path / "report-draft.txt").write_text("two", encoding="utf-8")
    delivery = FakeDelivery()
    service, store, _ = _service(
        engine,
        settings,
        AmbiguousFileDeliveryProvider(tmp_path),
        [FileFindTool(), ChannelFileSendTool()],
        delivery,
    )
    session = store.create_session()

    async def run():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(session_id=session.id, text="找到 report.txt 文件发给我"),
                ChannelContext(channel="onebot", target="10001"),
            )
        ]

    events = asyncio.run(run())

    assert delivery.sent == []
    assert events[-1].type == "done"
    assert events[-1].text and events[-1].text.startswith("找到的文件候选需要你确认")
    assert "1." in events[-1].text and "2." in events[-1].text
    assert store.list_messages(session.id)[-1].content == events[-1].text


def test_candidate_selection_followup_restores_current_delivery_intent(engine, settings):
    service, store, _ = _service(engine, settings, FindProvider(), [FileFindTool()])
    session = store.create_session()
    store.add_message(session.id, "user", "找到 report.txt 文件发给我")
    store.add_message(
        session.id,
        "assistant",
        "找到的文件候选需要你确认：你要求 1 个，当前找到 2 个。\n"
        "1. /tmp/report-final.txt\n2. /tmp/report-draft.txt",
    )
    current = store.add_message(session.id, "user", "第 2 个")
    history = store.list_messages(session.id)

    assert history[-1].id == current.id
    assert service._files._requires_file_delivery(
        "第 2 个", history, ChannelContext(channel="onebot", target="10001")
    )
    assert not service._files._requires_file_delivery(
        "算了", history, ChannelContext(channel="onebot", target="10001")
    )


def test_natural_send_me_phrase_enables_file_delivery(engine, settings):
    service, store, _ = _service(engine, settings, FindProvider(), [FileFindTool()])
    session = store.create_session()
    current = store.add_message(
        session.id,
        "user",
        "小白，把桌面 new_trial 文件夹中一个 Methods_4改.docx 发我",
    )
    history = store.list_messages(session.id)

    assert history[-1].id == current.id
    assert service._files._requires_file_delivery(
        current.content,
        history,
        ChannelContext(channel="onebot", target="10001"),
    )


def test_location_hint_overrides_model_wrong_root_and_delivers_recursively(
    engine, settings, tmp_path, monkeypatch
):
    home = tmp_path / "home"
    target_dir = home / "Desktop" / "new_trial" / "Article"
    target_dir.mkdir(parents=True)
    target = target_dir / "Methods_4改.docx"
    target.write_text("document", encoding="utf-8")
    wrong_root = tmp_path / "project"
    wrong_root.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    delivery = FakeDelivery()
    service, store, _ = _service(
        engine,
        settings,
        WrongRootFileDeliveryProvider(wrong_root),
        [FileFindTool(), ChannelFileSendTool()],
        delivery,
    )
    session = store.create_session()

    async def run():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(
                    session_id=session.id,
                    text="小白 把桌面new_trial文件夹中一个Methods_4改.docx发我",
                ),
                ChannelContext(channel="onebot", target="10001"),
            )
        ]

    events = asyncio.run(run())

    assert delivery.sent == [("10001", str(target), "Methods_4改.docx")]
    assert events[-1].type == "done"
    assert events[-1].text == "已发送 1 个文件。"


def test_local_model_receives_verified_recent_qq_attachment(engine, settings) -> None:
    attachment = settings.data_dir / "qq_files" / "received-report.docx"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"docx")
    service, store, _ = _service(
        engine,
        settings,
        AttachmentContextProvider(attachment),
        [],
    )
    session = store.create_session()
    store.record_attachment_message(session.id, "report.docx", channel="onebot", path=attachment)

    async def run():
        return [
            event
            async for event in service.stream_reply(
                ChatRequest(session_id=session.id, text="把这个文件移动到 Article 文件夹")
            )
        ]

    events = asyncio.run(run())

    assert events[-1].type == "done"
    assert events[-1].text == "已识别附件。"
