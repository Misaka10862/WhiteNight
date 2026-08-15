"""会话与消息仓储测试。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine

from whitenight.storage.sessions import SessionNotFoundError, SessionStore


def test_create_and_list_sessions(engine: Engine) -> None:
    store = SessionStore(engine)
    first = store.create_session("测试会话")
    second = store.create_session()
    sessions = store.list_sessions()
    assert [s.id for s in sessions] == [second.id, first.id]  # 最新在前
    assert second.title == "新会话"
    assert first.message_count == 0


def test_messages_ordered_and_title_from_first_user_message(engine: Engine) -> None:
    store = SessionStore(engine)
    session = store.create_session()
    first = store.add_message(session.id, "user", "  帮我看一下这份文档  ")
    second = store.add_message(session.id, "assistant", "好的，主人")
    messages = store.list_messages(session.id)
    assert [m.sequence for m in messages] == [1, 2]
    assert messages[0].id == first.id
    assert messages[1].id == second.id
    assert store.get_session(session.id).title == "帮我看一下这份文档"


def test_image_message_roundtrip_with_attachment_dir(engine: Engine, tmp_path: Path) -> None:
    attachments = tmp_path / "attachments"
    attachments.mkdir()
    store = SessionStore(engine, attachments_dir=attachments)
    session = store.create_session()
    image_path, mime = "abc.png", "image/png"
    (attachments / image_path).write_bytes(b"\x89PNG\r\n\x1a\n")
    store.add_message(
        session.id, "user", "看图", kind="image", image_path=image_path, image_mime=mime
    )
    loaded = store.list_messages(session.id)[0]
    assert loaded.kind == "image"
    assert loaded.image_data_url == "data:image/png;base64,iVBORw0KGgo="


def test_unknown_session_raises(engine: Engine) -> None:
    store = SessionStore(engine)
    try:
        store.get_session("missing")
    except SessionNotFoundError:
        pass
    else:
        raise AssertionError("应当抛出 SessionNotFoundError")
