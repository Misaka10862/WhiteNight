"""Public resource flows use isolated data and the same policy-gated services."""

from whitenight.channels.types import ChatRequest


def test_upload_is_session_bound_and_receipt_persists(client):
    first = client.post("/api/v1/sessions", json={}).json()["id"]
    other = client.post("/api/v1/sessions", json={}).json()["id"]
    upload = client.post(
        f"/api/v1/sessions/{first}/attachments?filename=note.txt", content=b"fixture document"
    )
    assert upload.status_code == 200
    receipt = upload.json()
    assert receipt["status"] == "ready" and receipt["size"] == 16
    with client.websocket_connect(
        "/api/v1/chat/ws", headers={"Origin": "http://127.0.0.1:5173"}
    ) as ws:
        ws.send_json(
            ChatRequest(session_id=other, text="read", attachment_ids=[receipt["id"]]).model_dump()
        )
        assert ws.receive_json()["type"] == "error"
    assert client.get(f"/api/v1/sessions/{other}/messages").json() == []
    with client.websocket_connect(
        "/api/v1/chat/ws", headers={"Origin": "http://127.0.0.1:5173"}
    ) as ws:
        ws.send_json(
            ChatRequest(session_id=first, text="read", attachment_ids=[receipt["id"]]).model_dump()
        )
        while (event := ws.receive_json())["type"] not in {"done", "error"}:
            pass
        assert event["type"] == "done"
    messages = client.get(f"/api/v1/sessions/{first}/messages").json()
    assert messages[0]["attachments"][0]["id"] == receipt["id"]


def test_upload_limit_is_checked_before_persistence(client):
    session = client.post("/api/v1/sessions", json={}).json()["id"]
    client.app.state.settings.max_file_bytes = 2
    response = client.post(
        f"/api/v1/sessions/{session}/attachments?filename=large.txt", content=b"123"
    )
    assert response.status_code == 413


def test_backup_create_verify_preview_download(client):
    client.post("/api/v1/sessions", json={"title": "backup fixture"})
    created = client.post("/api/v1/backups")
    assert created.status_code == 200, created.text
    backup_id = created.json()["id"]
    assert any(item["id"] == backup_id for item in client.get("/api/v1/backups").json())
    assert client.post(f"/api/v1/backups/{backup_id}/verify").status_code == 200
    preview = client.post(f"/api/v1/backups/{backup_id}/preview").json()
    assert preview["counts"]["sessions"] == 1
    assert client.get(f"/api/v1/backups/{backup_id}/download").content.startswith(b"WNBK1")
    assert client.post(f"/api/v1/backups/{backup_id}/restore").status_code == 404


def test_monitor_exposes_metadata_without_task_prompts(client):
    task = client.app.state.task_store.create(
        executor="codex", category="coding", risk="read_only", prompt="private synthetic prompt"
    )
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    monitor = response.json()["monitor"]
    assert monitor["pid"] > 0 and monitor["rss_bytes"] > 0
    assert monitor["tasks"][0]["id"] == task.id
    assert "private synthetic prompt" not in response.text
