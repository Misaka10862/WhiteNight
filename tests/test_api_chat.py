"""最小纵向链路 API 测试：WebSocket 流式聊天、图片与会话恢复。"""

from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from whitenight.agent.service import DummyProvider
from whitenight.api.app import create_app
from whitenight.config import Settings


def _chat_payload(
    session_id: str, text: str = "你好", image: str | None = None
) -> dict[str, object]:
    return {"session_id": session_id, "text": text, "image_data_url": image}


def _collect_events(websocket) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    while True:
        event = json.loads(websocket.receive_text())
        events.append(event)
        if event["type"] in ("done", "error"):
            return events


def test_streaming_chat_persists_and_survives_restart(
    chat_client: TestClient, settings: Settings
) -> None:
    session = chat_client.post("/api/v1/sessions", json={"title": "链路测试"}).json()

    with chat_client.websocket_connect("/api/v1/chat/ws") as websocket:
        websocket.send_json(_chat_payload(session["id"], "你好"))
        events = _collect_events(websocket)

    assert events[0]["type"] == "start"
    deltas = [event["delta"] for event in events if event["type"] == "chunk"]
    assert "".join(deltas) == "好的，主人"
    assert events[-1]["type"] == "done"
    assert events[-1]["text"] == "好的，主人"

    messages = chat_client.get(f"/api/v1/sessions/{session['id']}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "你好"
    assert messages[1]["content"] == "好的，主人"

    # 重启恢复：新应用实例连接同一数据库，历史仍在。
    with TestClient(create_app(settings, model_provider=DummyProvider())) as restarted:
        restored = restarted.get(f"/api/v1/sessions/{session['id']}/messages").json()
        assert [m["role"] for m in restored] == ["user", "assistant"]
        sessions = restarted.get("/api/v1/sessions").json()
        assert sessions[0]["id"] == session["id"]
        assert sessions[0]["title"] == "链路测试"


def test_image_message_saved_and_recovered(chat_client: TestClient) -> None:
    session = chat_client.post("/api/v1/sessions", json={}).json()
    image = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    with chat_client.websocket_connect("/api/v1/chat/ws") as websocket:
        websocket.send_json(_chat_payload(session["id"], "看这张图", image=image))
        events = _collect_events(websocket)
    assert events[-1]["type"] == "done"

    messages = chat_client.get(f"/api/v1/sessions/{session['id']}/messages").json()
    user = messages[0]
    assert user["kind"] == "image"
    assert user["image_data_url"] == image


def test_invalid_image_reports_error(chat_client: TestClient) -> None:
    session = chat_client.post("/api/v1/sessions", json={}).json()
    with chat_client.websocket_connect("/api/v1/chat/ws") as websocket:
        websocket.send_json(_chat_payload(session["id"], "图", image="data:text/plain;base64,aGk="))
        event = json.loads(websocket.receive_text())
    assert event["type"] == "error"
    assert "图片无法使用" in event["message"]


def test_unknown_session_reports_error(chat_client: TestClient) -> None:
    with chat_client.websocket_connect("/api/v1/chat/ws") as websocket:
        websocket.send_json(_chat_payload("missing-session"))
        event = json.loads(websocket.receive_text())
    assert event["type"] == "error"
    assert "会话不存在" in event["message"]


def test_messages_endpoint_404(chat_client: TestClient) -> None:
    response = chat_client.get("/api/v1/sessions/missing/messages")
    assert response.status_code == 404
