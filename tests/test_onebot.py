"""OneBot Adapter 契约测试：白名单、去重、顺序、审批与发送重试。"""

from __future__ import annotations

import httpx
from sqlalchemy import Engine

from whitenight.agent.service import ChatService, DummyProvider
from whitenight.channels.onebot import (
    ChannelSessionStore,
    EventDeduplicator,
    OneBotAdapter,
    OneBotSender,
    RateLimiter,
    split_text,
)
from whitenight.config import Settings
from whitenight.policy.approvals import ApprovalService
from whitenight.storage.sessions import SessionStore


class FakeQQ:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    def send_private_message(self, user_id: int, text: str) -> int:
        self.messages.append((user_id, text))
        return 1


def _adapter(engine: Engine, settings: Settings, sender: FakeQQ):
    qq_settings = settings.model_copy(
        update={"qq_enabled": True, "qq_owner_ids": [10001], "qq_rate_limit_seconds": 0.0}
    )
    sessions = SessionStore(engine, attachments_dir=qq_settings.data_dir / "attachments")
    channel_sessions = ChannelSessionStore(engine, sessions)
    chat = ChatService(sessions, DummyProvider("在的，主人"), qq_settings)
    approvals = ApprovalService(engine)
    return OneBotAdapter(
        qq_settings,
        sessions,
        channel_sessions,
        chat,
        approvals,
        sender=sender,  # type: ignore[arg-type]
    )


def _private(message_id: int, text: str, user_id: int = 10001) -> dict[str, object]:
    return {
        "post_type": "message",
        "message_type": "private",
        "message_id": message_id,
        "user_id": user_id,
        "raw_message": text,
        "message": [{"type": "text", "data": {"text": text}}],
    }


def test_text_message_replies_and_shared_session(engine: Engine, settings: Settings) -> None:
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    first = asyncio_run(adapter.handle_event(_private(1, "你好")))
    assert first["status"] == "replied"
    assert sender.messages[-1][1] == "在的，主人"

    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    assert len(sessions.list_sessions()) == 1
    session_id = sessions.list_sessions()[0].id
    assert any(message.content == "你好" for message in sessions.list_messages(session_id))

    # 同一会话重复事件必须丢弃，不产生重复回复
    before = len(sender.messages)
    duplicate = asyncio_run(adapter.handle_event(_private(1, "你好")))
    assert duplicate["status"] == "duplicate"
    assert len(sender.messages) == before


def test_clear_rotates_context_without_deleting_history(engine: Engine, settings: Settings) -> None:
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    first = asyncio_run(adapter.handle_event(_private(101, "旧上下文")))
    old_session_id = str(first["session_id"])

    cleared = asyncio_run(adapter.handle_event(_private(102, "/clear")))
    assert cleared["status"] == "context_reset"
    assert cleared["previous_session_id"] == old_session_id
    new_session_id = str(cleared["session_id"])
    assert new_session_id != old_session_id
    assert sender.messages[-1][1] == "上下文窗口已清空，旧会话记录仍保留。"

    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    assert any(message.content == "旧上下文" for message in sessions.list_messages(old_session_id))
    assert sessions.list_messages(new_session_id) == []

    after = asyncio_run(adapter.handle_event(_private(103, "新上下文")))
    assert after["session_id"] == new_session_id
    new_messages = sessions.list_messages(new_session_id)
    assert any(message.content == "新上下文" for message in new_messages)
    assert all(message.content != "/clear" for message in new_messages)


def test_non_owner_and_group_ignored(engine: Engine, settings: Settings) -> None:
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    assert (
        asyncio_run(adapter.handle_event(_private(2, "你好", user_id=99999)))["status"]
        == "ignored_not_owner"
    )
    group = _private(3, "你好")
    group["message_type"] = "group"
    assert asyncio_run(adapter.handle_event(group))["status"] == "ignored_group"
    assert sender.messages == []


def test_image_segment_is_understood(engine: Engine, settings: Settings) -> None:
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    import base64

    image = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    event = {
        "post_type": "message",
        "message_type": "private",
        "message_id": 5,
        "user_id": 10001,
        "raw_message": "看这张图",
        "message": [
            {"type": "text", "data": {"text": "看这张图"}},
            {"type": "image", "data": {"file": f"base64://{image.split(',', 1)[1]}"}},
        ],
    }
    assert asyncio_run(adapter.handle_event(event))["status"] == "replied"
    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    message = sessions.list_messages(sessions.list_sessions()[0].id)[0]
    assert message.kind == "image"
    assert message.image_data_url == image


def test_file_segment_saves_local_copy(engine: Engine, settings: Settings, tmp_path) -> None:
    source = tmp_path / "data.bin"
    source.write_bytes(b"hello qq")
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    event = {
        "post_type": "message",
        "message_type": "private",
        "message_id": 6,
        "user_id": 10001,
        "raw_message": "",
        "message": [{"type": "file", "data": {"file": str(source)}}],
    }
    status = asyncio_run(adapter.handle_event(event))
    assert status["status"] == "file_received"
    assert "收到文件" in sender.messages[-1][1]
    qq_files = list((settings.data_dir / "qq_files").glob("*.bin"))
    assert len(qq_files) == 1
    assert qq_files[0].read_bytes() == b"hello qq"


def test_poke_segment_is_recognized_and_visible(engine: Engine, settings: Settings) -> None:
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    event = {
        "post_type": "message",
        "message_type": "private",
        "message_id": 7,
        "user_id": 10001,
        "raw_message": "",
        "message": [{"type": "poke", "data": {"type": "戳一戳", "id": "1000"}}],
    }
    status = asyncio_run(adapter.handle_event(event))
    assert status["status"] == "replied"
    assert sender.messages[-1][1] == "在的，主人"

    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    session_id = sessions.list_sessions()[0].id
    contents = [message.content for message in sessions.list_messages(session_id)]
    assert any("戳了戳我" in content for content in contents)


def test_qq_approval_commands(engine: Engine, settings: Settings) -> None:
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    approvals: ApprovalService = adapter._approvals
    request = approvals.request("file.write", "medium", "once", '{"path":"/x"}', session_id=None)

    event = _private(10, f"同意 {request.code}")
    assert asyncio_run(adapter.handle_event(event))["status"] == "approval_handled"
    assert "已批准" in sender.messages[-1][1]

    replay = _private(11, f"同意 {request.code}")
    assert asyncio_run(adapter.handle_event(replay))["status"] == "approval_invalid"
    assert "无效" in sender.messages[-1][1]

    other = approvals.request("file.delete", "delete", "once", '{"path":"/y"}')
    reject = _private(12, f"拒绝 {other.code}")
    assert asyncio_run(adapter.handle_event(reject))["status"] == "approval_handled"
    assert "已拒绝" in sender.messages[-1][1]


def test_dedupe_ttl_and_rate_limit() -> None:
    dedupe = EventDeduplicator(ttl_s=600.0)
    assert dedupe.accept("1", 10001)
    assert not dedupe.accept("1", 10001)
    assert dedupe.accept("2", 10001)

    limiter = RateLimiter(interval_s=1.0)
    assert limiter.wait_seconds(10001) == 0.0
    assert limiter.wait_seconds(10001) > 0.9


def test_split_text() -> None:
    text = "好" * 5000
    chunks = split_text(text, max_chars=2000)
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text


def test_onebot_sender_retries(monkeypatch) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500, request=request)
        return httpx.Response(200, json={"retcode": 0}, request=request)

    sender = OneBotSender("http://mock", transport=httpx.MockTransport(handler), max_attempts=2)
    assert sender.send_private_message(10001, "你好") == 1
    assert len(calls) == 2


def test_download_follows_redirects_without_proxy(monkeypatch) -> None:
    import asyncio

    from whitenight.channels.onebot.adapter import OneBotAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/file"}, request=request)
        return httpx.Response(
            200,
            headers={"content-type": "application/octet-stream"},
            content=b"ok",
            request=request,
        )

    adapter = object.__new__(OneBotAdapter)
    original = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    assert asyncio.run(adapter._download("http://local/start")) == b"ok"


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
