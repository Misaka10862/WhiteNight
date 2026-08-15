"""API 空壳服务测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from whitenight.config import Settings


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


def test_status_reports_database(client: TestClient, settings: Settings) -> None:
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "WhiteNight"
    assert body["host"] == "127.0.0.1"
    assert body["database"] == {"url_backend": "sqlite", "reachable": True}


def test_status_binds_to_localhost_only(settings: Settings) -> None:
    assert settings.host == "127.0.0.1"


def test_websocket_echo(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws") as websocket:
        websocket.send_text("ping")
        assert websocket.receive_text() == "ping"
