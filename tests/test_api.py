"""API 空壳服务测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
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


def test_model_config_get_returns_keep_alive_options(client: TestClient) -> None:
    response = client.get("/api/v1/model/config")
    assert response.status_code == 200
    body = response.json()
    assert body["ollama_keep_alive"] == "-1"
    assert "-1" in body["options"]
    assert "5m" in body["options"]


def test_model_config_put_rejects_unknown_keep_alive(client: TestClient) -> None:
    response = client.put("/api/v1/model/config", json={"keep_alive": "forever"})
    assert response.status_code == 400


def test_model_config_put_persists_and_applies(
    client: TestClient, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config" / "whitenight.yaml"
    monkeypatch.setenv("WHITENIGHT_CONFIG", str(config_path))

    response = client.put("/api/v1/model/config", json={"keep_alive": "1h"})
    assert response.status_code == 200
    assert response.json() == {"ollama_keep_alive": "1h", "persisted": True}
    assert settings.ollama_keep_alive == "1h"

    persisted = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert persisted["ollama_keep_alive"] == "1h"

    current = client.get("/api/v1/model/config").json()
    assert current["ollama_keep_alive"] == "1h"


def test_model_provider_requires_cloud_key(client: TestClient) -> None:
    response = client.put(
        "/api/v1/model/provider",
        json={
            "provider": "openai",
            "model_name": "gpt-test",
            "base_url": "https://api.test/v1",
        },
    )
    assert response.status_code == 400
    assert "API Key" in response.json()["detail"]


def test_model_provider_rejects_invalid_base_url(client: TestClient) -> None:
    response = client.put(
        "/api/v1/model/provider",
        json={"provider": "ollama", "model_name": "qwen3:8b", "base_url": "not-a-url"},
    )
    assert response.status_code == 400


def test_model_provider_writes_keychain_and_switches_runtime(
    client: TestClient, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config" / "whitenight.yaml"
    monkeypatch.setenv("WHITENIGHT_CONFIG", str(config_path))
    response = client.put(
        "/api/v1/model/provider",
        json={
            "provider": "openai",
            "model_name": "gpt-test",
            "base_url": "https://api.test/v1",
            "api_key": "secret-not-returned",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "provider": "openai",
        "model_name": "gpt-test",
        "base_url": "https://api.test/v1",
        "api_key_configured": True,
        "persisted": True,
    }
    assert "secret-not-returned" not in response.text
    assert settings.model_provider == "openai"
    assert client.get("/api/v1/model/config").json()["api_key_configured"] is True
    persisted = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert persisted["model_provider"] == "openai"
    assert "api_key" not in persisted


def test_service_restart_requires_launchd(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XPC_SERVICE_NAME", raising=False)
    response = client.post("/api/v1/service/restart")
    assert response.status_code == 409


def test_model_list_rejects_cloud_without_key(client: TestClient) -> None:
    response = client.post(
        "/api/v1/model/models",
        json={"provider": "openai", "base_url": "https://api.test/v1"},
    )
    assert response.status_code == 400
    assert "API Key" in response.json()["detail"]


def test_model_list_rejects_invalid_base_url(client: TestClient) -> None:
    response = client.post(
        "/api/v1/model/models",
        json={"provider": "ollama", "base_url": "not-a-url"},
    )
    assert response.status_code == 400


def test_model_list_uses_temporary_cloud_key_without_persisting(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_list_models(self) -> list[str]:
        assert self.api_key == "temporary-secret"
        return ["gpt-test", "another-model"]

    monkeypatch.setattr("whitenight.models.openai.OpenAIProvider.list_models", fake_list_models)
    response = client.post(
        "/api/v1/model/models",
        json={
            "provider": "openai",
            "base_url": "https://api.test/v1",
            "api_key": "temporary-secret",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "provider": "openai",
        "models": ["gpt-test", "another-model"],
    }
    assert "temporary-secret" not in response.text
    assert client.app.state.credentials.get("com.whitenight.credentials", "openai_api_key") is None
