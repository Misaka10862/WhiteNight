"""配置分层：默认值 < config/whitenight.yaml < WHITENIGHT_* 环境变量 < 显式参数。

分层顺序（低优先在前）：
1. `Settings` 字段默认值；
2. YAML 配置文件（默认 `config/whitenight.yaml`，可用 `WHITENIGHT_CONFIG` 覆盖路径）；
3. `WHITENIGHT_*` 环境变量（例如 `WHITENIGHT_PORT=9000`）。

任何现实动作的授权都不能由配置文件以外的不可信输入（网页、文档、聊天内容）修改。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_PATH = Path("config/whitenight.yaml")


class ConfigError(RuntimeError):
    """配置文件缺失、损坏或类型错误。"""


class Settings(BaseSettings):
    """WhiteNight 运行时配置。"""

    model_config = SettingsConfigDict(env_prefix="WHITENIGHT_", env_file=None, extra="ignore")

    app_name: str = "WhiteNight"
    app_env: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"  # 首版强制本机监听，见 ADR-0002
    port: int = 8765
    log_level: str = "INFO"
    log_json: bool = False
    data_dir: Path = Field(default=Path("data"))
    database_url: str = "sqlite:///data/whitenight.db"
    keychain_backend: Literal["macos", "memory"] = "macos"
    keychain_service: str = "com.whitenight.credentials"

    # 模型与上下文（阶段 2 最小纵向链路；阶段 4 记忆）
    model_name: str = "qwen3-vl:8b"
    ollama_base_url: str = "http://127.0.0.1:11434"
    context_budget_chars: int = 12_000
    max_image_bytes: int = 8 * 1024 * 1024  # 8 MiB
    soul_file: Path = Field(default=Path("SOUL.md"))
    auto_migrate: bool = True
    memory_extractor: Literal["ollama", "rules", "none"] = "ollama"
    embedding_model: str = ""  # 为空则仅词法检索；小模型按需加载

    def ensure_dirs(self) -> None:
        """创建运行时目录（数据、日志、备份）。"""
        for directory in (self.data_dir, self.data_dir / "logs", self.data_dir / "backups"):
            directory.mkdir(parents=True, exist_ok=True)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"无法解析配置文件 {path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件 {path} 顶层必须是映射，实际是 {type(raw).__name__}")
    return raw


def _env_overrides() -> dict[str, Any]:
    prefix = "WHITENIGHT_"
    return {
        key[len(prefix) :].lower(): value
        for key, value in os.environ.items()
        if key.startswith(prefix)
    }


def load_settings(config_path: Path | None = None) -> Settings:
    """按分层顺序装配配置。显式传入的 YAML 值 + 环境变量一起交给 pydantic 校验。"""
    if config_path is None:
        config_path = Path(os.environ.get("WHITENIGHT_CONFIG", DEFAULT_CONFIG_PATH))
    yaml_values = _read_yaml(config_path)
    merged = {**yaml_values, **_env_overrides()}
    return Settings(**merged)
