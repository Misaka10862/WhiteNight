"""Configuration failure must preserve a coherent endpoint and Keychain generation."""

from pathlib import Path

import pytest
import yaml

from whitenight.application.configuration import ModelConfigurationService, _build_model_provider
from whitenight.credentials.keychain import InMemoryKeychain
from whitenight.models.ollama import OllamaProvider
from whitenight.personality.token_counter import UnavailableTokenCounter


def _persist_failure(_updates):
    raise OSError("synthetic configuration write failure")


def test_failed_config_write_preserves_previous_key_generation(settings, monkeypatch):
    settings.model_provider = "openai"
    settings.openai_base_url = "https://old.invalid/v1"
    credentials = InMemoryKeychain()
    previous_account = settings.openai_api_key_account
    credentials.set(settings.keychain_service, previous_account, "synthetic-old-key")
    active = _build_model_provider(settings, credentials)
    installed = []
    service = ModelConfigurationService(
        settings, credentials, lambda *items: installed.append(items)
    )
    monkeypatch.setattr(
        "whitenight.application.configuration._persist_config_values", _persist_failure
    )
    with pytest.raises(OSError):
        service.update("openai", "new-model", "https://new.invalid/v1", "synthetic-new-key")
    assert credentials.get(settings.keychain_service, previous_account) == "synthetic-old-key"
    assert settings.openai_api_key_account == previous_account
    assert settings.openai_base_url == "https://old.invalid/v1"
    assert active.api_key == "synthetic-old-key"
    assert installed == []


def test_successful_config_atomically_persists_new_account_reference(
    settings, tmp_path, monkeypatch
):
    config = tmp_path / "configuration.yaml"
    monkeypatch.setenv("WHITENIGHT_CONFIG", str(config))
    settings.model_provider = "openai"
    settings.openai_base_url = "https://old.invalid/v1"
    credentials = InMemoryKeychain()
    previous_account = settings.openai_api_key_account
    credentials.set(settings.keychain_service, previous_account, "synthetic-old-key")
    active = _build_model_provider(settings, credentials)
    installed = []
    service = ModelConfigurationService(
        settings, credentials, lambda *items: installed.append(items)
    )
    result = service.update("openai", "new-model", "https://new.invalid/v1", "synthetic-new-key")
    persisted = yaml.safe_load(config.read_text())
    assert persisted["openai_api_key_account"] == settings.openai_api_key_account
    assert settings.openai_api_key_account != previous_account
    assert persisted["openai_base_url"] == "https://new.invalid/v1"
    assert credentials.get(settings.keychain_service, previous_account) == "synthetic-old-key"
    assert (
        credentials.get(settings.keychain_service, settings.openai_api_key_account)
        == "synthetic-new-key"
    )
    assert active.api_key == "synthetic-old-key"
    assert installed[-1][0].api_key == "synthetic-new-key"
    assert "synthetic-new-key" not in config.read_text()
    assert set(result) == {"provider", "model_name", "base_url", "api_key_configured", "persisted"}

    account = settings.openai_api_key_account
    service.update("openai", "another-model", "https://new.invalid/v1", None)
    assert settings.openai_api_key_account == account


def test_keep_alive_persistence_failure_does_not_mutate_runtime(client, settings, monkeypatch):
    provider = OllamaProvider("http://synthetic.invalid", "synthetic", keep_alive="-1")
    client.app.state.chat_service.set_provider(provider)
    previous = settings.ollama_keep_alive
    monkeypatch.setattr("whitenight.api.app._persist_config_values", _persist_failure)
    with pytest.raises(OSError):
        client.put("/api/v1/model/config", json={"keep_alive": "1h"})
    assert settings.ollama_keep_alive == previous
    assert provider.keep_alive == "-1"


def test_tokenizer_persistence_failure_does_not_mutate_runtime(
    client, settings, tmp_path, monkeypatch
):
    path: Path = tmp_path / "tokenizer.json"
    path.write_text("{}")
    previous_path = settings.model_tokenizer_path
    previous_counter = client.app.state.prompt_compiler._counter
    monkeypatch.setattr(
        "whitenight.api.app.build_token_counter", lambda _path: UnavailableTokenCounter()
    )
    monkeypatch.setattr("whitenight.api.app._persist_config_values", _persist_failure)
    with pytest.raises(OSError):
        client.put("/api/v1/model/tokenizer", json={"path": str(path)})
    assert settings.model_tokenizer_path == previous_path
    assert client.app.state.prompt_compiler._counter is previous_counter
