"""配置分层测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from whitenight.config import ConfigError, load_settings


def test_defaults_are_local_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = load_settings(Path(tmp_path / "missing.yaml"))
    assert settings.host == "127.0.0.1"
    assert settings.app_env == "development"
    assert settings.keychain_backend == "macos"


def test_yaml_provides_mid_layer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "whitenight.yaml"
    config.write_text("app_env: production\nport: 9999\n", encoding="utf-8")
    settings = load_settings(config)
    assert settings.app_env == "production"
    assert settings.port == 9999


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHITENIGHT_PORT", "1234")
    config = tmp_path / "whitenight.yaml"
    config.write_text("port: 9999\n", encoding="utf-8")
    settings = load_settings(config)
    assert settings.port == 1234


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    config = tmp_path / "bad.yaml"
    config.write_text("app_env: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(config)


def test_ensure_dirs(tmp_path: Path) -> None:
    from whitenight.config import Settings

    settings = Settings(data_dir=tmp_path / "nested" / "data")
    settings.ensure_dirs()
    assert (tmp_path / "nested" / "data" / "logs").is_dir()
    assert (tmp_path / "nested" / "data" / "backups").is_dir()
