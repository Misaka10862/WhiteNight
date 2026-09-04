"""OneBot Adapter 契约测试：白名单、去重、顺序、审批与发送重试。"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from sqlalchemy import Engine

from whitenight.agent.service import ChatService, DummyProvider
from whitenight.channels.onebot import (
    ChannelSessionStore,
    EventDeduplicator,
    OneBotAdapter,
    OneBotSender,
    OneBotSendError,
    RateLimiter,
    split_text,
)
from whitenight.config import Settings
from whitenight.personality.store import PersonalityStore
from whitenight.personality.types import CharacterCard
from whitenight.policy.approvals import ApprovalService
from whitenight.storage.sessions import SessionStore


class FakeQQ:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    def send_private_message(self, user_id: int, text: str) -> int:
        self.messages.append((user_id, text))
        return 1

    def get_file(self, file_id: str) -> dict[str, object]:
        raise AssertionError(f"unexpected get_file call: {file_id}")


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


def test_character_command_is_deterministic_and_rotates_session(
    engine: Engine, settings: Settings
) -> None:
    sender = FakeQQ()
    qq_settings = settings.model_copy(
        update={"qq_enabled": True, "qq_owner_ids": [10001], "qq_rate_limit_seconds": 0.0}
    )
    sessions = SessionStore(engine, attachments_dir=qq_settings.data_dir / "attachments")
    mappings = ChannelSessionStore(engine, sessions)
    personalities = PersonalityStore(engine)
    character = personalities.create_character(
        CharacterCard.model_validate(
            {
                "spec": "chara_card_v3",
                "spec_version": "3.0",
                "data": {"name": "档案员", "first_mes": "请出示档案编号。"},
            }
        )
    )
    adapter = OneBotAdapter(
        qq_settings,
        sessions,
        mappings,
        ChatService(sessions, DummyProvider(), qq_settings),
        ApprovalService(engine),
        sender=sender,  # type: ignore[arg-type]
        personalities=personalities,
    )
    listed = asyncio_run(adapter.handle_event(_private(110, "/角色")))
    assert listed["status"] == "character_list"
    switched = asyncio_run(adapter.handle_event(_private(111, "/角色 档案员")))
    assert switched["status"] == "character_switched"
    assert sessions.get_session(str(switched["session_id"])).character_id == character.id
    assert sessions.list_messages(str(switched["session_id"]))[0].content == "请出示档案编号。"


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


def test_sent_echo_and_empty_event_are_ignored(engine: Engine, settings: Settings) -> None:
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)

    sent_echo = _private(201, "outgoing echo")
    sent_echo["post_type"] = "message_sent"
    assert asyncio_run(adapter.handle_event(sent_echo))["status"] == "ignored_post_type"

    empty = _private(202, "")
    assert asyncio_run(adapter.handle_event(empty))["status"] == "ignored_empty"
    assert sender.messages == []
    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    assert sessions.list_sessions() == []


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


def test_local_image_path_is_resolved_and_sent_to_model(
    engine: Engine, settings: Settings, tmp_path
) -> None:
    source = tmp_path / "qq-cache" / "photo.jpg"
    source.parent.mkdir()
    source.write_bytes(b"\xff\xd8\xff\xe0minimal-jpeg")
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    event = _private(51, "[CQ:image,file=photo.jpg]")
    event["raw_message"] = f"[CQ:image,file={source}]"
    event["message"] = [{"type": "image", "data": {"file": str(source)}}]

    assert asyncio_run(adapter.handle_event(event))["status"] == "replied"
    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    message = sessions.list_messages(sessions.list_sessions()[0].id)[0]
    assert message.kind == "image"
    assert message.image_data_url is not None
    assert message.image_data_url.startswith("data:image/jpeg;base64,")


def test_image_file_id_is_resolved_through_onebot(engine: Engine, settings: Settings) -> None:
    class ImageQQ(FakeQQ):
        def get_file(self, file_id: str) -> dict[str, object]:
            assert file_id == "image-1"
            return {
                "file_name": "photo.png",
                "base64": base64.b64encode(b"\x89PNG\r\n\x1a\nminimal").decode("ascii"),
            }

    sender = ImageQQ()
    adapter = _adapter(engine, settings, sender)
    event = _private(52, "[CQ:image,file=photo.png,file_id=image-1]")
    event["message"] = [{"type": "image", "data": {"file": "photo.png", "file_id": "image-1"}}]

    assert asyncio_run(adapter.handle_event(event))["status"] == "replied"
    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    message = sessions.list_messages(sessions.list_sessions()[0].id)[0]
    assert message.kind == "image"
    assert message.image_data_url is not None


def test_opaque_image_file_token_is_resolved_through_get_image(
    engine: Engine, settings: Settings
) -> None:
    class ImageQQ(FakeQQ):
        def get_image(self, file_id: str) -> dict[str, object]:
            assert file_id == "opaque-image-token"
            return {"base64": base64.b64encode(b"\x89PNG\r\n\x1a\nminimal").decode("ascii")}

    sender = ImageQQ()
    adapter = _adapter(engine, settings, sender)
    event = _private(521, "[CQ:image,file=opaque-image-token]")
    event["message"] = [{"type": "image", "data": {"file": "opaque-image-token"}}]

    assert asyncio_run(adapter.handle_event(event))["status"] == "replied"
    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    message = sessions.list_messages(sessions.list_sessions()[0].id)[0]
    assert message.kind == "image"
    assert message.image_data_url is not None


def test_cq_string_image_message_is_parsed(engine: Engine, settings: Settings) -> None:
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
    event = _private(53, f"看图[CQ:image,file=base64://{encoded}]")
    event["message"] = event["raw_message"]

    assert asyncio_run(adapter.handle_event(event))["status"] == "replied"
    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    message = sessions.list_messages(sessions.list_sessions()[0].id)[0]
    assert message.kind == "image"


def test_custom_qq_sticker_segment_is_read_as_image(
    engine: Engine, settings: Settings, tmp_path
) -> None:
    source = tmp_path / "sticker.webp"
    # Minimal RIFF/WEBP signature is enough for the adapter MIME sniffing.
    source.write_bytes(b"RIFFxxxxWEBPsticker")
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    event = _private(531, "")
    event["message"] = [
        {
            "type": "mface",
            "data": {
                "emoji_id": 12345,
                "emoji_package_id": 9,
                "url": str(source),
                "summary": "[猫猫]",
            },
        }
    ]

    assert asyncio_run(adapter.handle_event(event))["status"] == "replied"
    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    message = sessions.list_messages(sessions.list_sessions()[0].id)[0]
    assert message.kind == "image"
    assert message.image_data_url is not None
    assert message.image_data_url.startswith("data:image/webp;base64,")


def test_numeric_onebot_segment_fields_do_not_reject_event(
    engine: Engine, settings: Settings
) -> None:
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    event = _private(532, "")
    event["message"] = [{"type": "face", "data": {"id": 178, "raw": 1}}]

    assert asyncio_run(adapter.handle_event(event))["status"] == "replied"
    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    message = sessions.list_messages(sessions.list_sessions()[0].id)[0]
    assert "QQ表情" in message.content


def test_reply_segment_fetches_quoted_text(engine: Engine, settings: Settings) -> None:
    class ReplyQQ(FakeQQ):
        def get_message(self, message_id: int | str) -> dict[str, object]:
            assert str(message_id) == "900"
            return {"raw_message": "原消息内容"}

    sender = ReplyQQ()
    adapter = _adapter(engine, settings, sender)
    event = _private(54, "[CQ:reply,id=900]请继续")
    event["message"] = [
        {"type": "reply", "data": {"id": "900"}},
        {"type": "text", "data": {"text": "请继续"}},
    ]

    assert asyncio_run(adapter.handle_event(event))["status"] == "replied"
    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    message = sessions.list_messages(sessions.list_sessions()[0].id)[0]
    assert "QQ引用消息 id=900" in message.content
    assert "原消息内容" in message.content
    assert message.content.endswith("请继续")


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
    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    message = sessions.list_messages(sessions.list_sessions()[0].id)[0]
    assert message.attachments[0].path == str(qq_files[0].resolve())
    assert message.attachments[0].status == "ready"


def test_oversized_file_records_failure_and_explains_how_to_retry(
    engine: Engine, settings: Settings, tmp_path
) -> None:
    source = tmp_path / "too-large.zip"
    source.touch()
    source.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    event = {
        "post_type": "message",
        "message_type": "private",
        "message_id": 61,
        "user_id": 10001,
        "raw_message": "",
        "message": [
            {
                "type": "file",
                "data": {"file": str(source), "file_size": source.stat().st_size},
            }
        ],
    }

    status = asyncio_run(adapter.handle_event(event))

    assert status["status"] == "file_failed"
    assert sender.messages[-1][1] == (
        "文件接收失败：too-large.zip 超过当前 16 MiB 限制，请压缩后或分卷重新发送。"
    )
    sessions = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
    messages = sessions.list_messages(sessions.list_sessions()[0].id)
    assert messages[0].attachments[0].status == "failed"
    assert messages[0].attachments[0].name == "too-large.zip"


def test_file_segment_resolves_file_id_through_onebot(engine: Engine, settings: Settings) -> None:
    class FileQQ(FakeQQ):
        def get_file(self, file_id: str) -> dict[str, object]:
            assert file_id == "qq-file-1"
            return {
                "file_name": "report.txt",
                "base64": base64.b64encode(b"resolved by onebot").decode("ascii"),
            }

    sender = FileQQ()
    adapter = _adapter(engine, settings, sender)
    event = {
        "post_type": "message",
        "message_type": "private",
        "message_id": 7,
        "user_id": 10001,
        "raw_message": "[CQ:file,file=report.txt,file_id=qq-file-1]",
        "message": [
            {
                "type": "file",
                "data": {"file": "report.txt", "file_id": "qq-file-1"},
            }
        ],
    }

    status = asyncio_run(adapter.handle_event(event))

    assert status["status"] == "file_received"
    assert "收到文件：report.txt" in sender.messages[-1][1]
    saved = list((settings.data_dir / "qq_files").glob("*-report.txt"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"resolved by onebot"


def test_approval_without_code_returns_exact_qq_command(engine: Engine, settings: Settings) -> None:
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)
    first = asyncio_run(adapter.handle_event(_private(801, "你好")))
    session_id = str(first["session_id"])
    approval = adapter._approvals.request(
        "file.move",
        "medium",
        "once",
        '{"source":"/tmp/a","destination":"/tmp/b"}',
        session_id=session_id,
        channel="onebot",
    )

    status = asyncio_run(adapter.handle_event(_private(802, "允许操作")))

    assert status["status"] == "approval_code_required"
    assert sender.messages[-1][1] == (
        f"审批必须带一次性编号。请回复：同意 {approval.code}，或：拒绝 {approval.code}。"
    )


def test_approval_without_code_reports_when_nothing_is_pending(
    engine: Engine, settings: Settings
) -> None:
    sender = FakeQQ()
    adapter = _adapter(engine, settings, sender)

    status = asyncio_run(adapter.handle_event(_private(803, "允许操作")))

    assert status["status"] == "approval_invalid"
    assert sender.messages[-1][1] == "当前没有有效的待审批操作，请重新发起文件操作。"


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
    request = approvals.request(
        "file.write",
        "medium",
        "once",
        '{"path":"/x"}',
        session_id=None,
        channel="onebot",
        channel_target="10001",
    )

    event = _private(10, f"同意 {request.code}")
    assert asyncio_run(adapter.handle_event(event))["status"] == "approval_handled"
    assert "已批准" in sender.messages[-1][1]

    replay = _private(11, f"同意 {request.code}")
    assert asyncio_run(adapter.handle_event(replay))["status"] == "approval_invalid"
    assert "无效" in sender.messages[-1][1]

    other = approvals.request(
        "file.delete",
        "delete",
        "once",
        '{"path":"/y"}',
        channel="onebot",
        channel_target="10001",
    )
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


def test_onebot_sender_health_checks_login() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/get_login_info"
        return httpx.Response(200, json={"status": "ok", "retcode": 0}, request=request)

    sender = OneBotSender("http://mock", transport=httpx.MockTransport(handler))
    assert sender.health() is True


def test_upload_private_file_uses_base64_json(tmp_path) -> None:
    source = tmp_path / "data.bin"
    source.write_bytes(b"hello qq file")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"status": "ok", "retcode": 0}, request=request)

    sender = OneBotSender("http://mock", transport=httpx.MockTransport(handler))
    sender.upload_private_file(10001, source, "data.bin")

    assert captured["user_id"] == 10001
    assert captured["name"] == "data.bin"
    encoded = str(captured["file"])
    assert encoded.startswith("base64://")
    assert base64.b64decode(encoded.removeprefix("base64://")) == b"hello qq file"


def test_get_file_uses_onebot_file_id() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "retcode": 0,
                "data": {"file_name": "data.bin", "url": "http://local/data.bin"},
            },
        )

    sender = OneBotSender("http://onebot", transport=httpx.MockTransport(handler))

    metadata = sender.get_file("file-123")

    assert captured == {"file_id": "file-123"}
    assert metadata["url"] == "http://local/data.bin"


def test_fetch_custom_face_detail_uses_onebot_action() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "retcode": 0,
                "data": [{"desc": "卖萌", "url": "https://p.qpic.cn/example"}],
            },
            request=request,
        )

    sender = OneBotSender("http://onebot", transport=httpx.MockTransport(handler))
    details = sender.fetch_custom_face_detail(18)

    assert captured == {"count": 18}
    assert details[0]["desc"] == "卖萌"


def test_onebot_sender_does_not_retry_client_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, text="bad request", request=request)

    sender = OneBotSender("http://mock", transport=httpx.MockTransport(handler), max_attempts=3)
    with pytest.raises(OneBotSendError, match="HTTP 400"):
        sender.send_private_message(10001, "hello")
    assert calls == 1


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
