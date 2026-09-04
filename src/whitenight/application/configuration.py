"""Provider construction and atomic non-secret runtime configuration."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from whitenight.config import DEFAULT_CONFIG_PATH, ConfigError, Settings
from whitenight.credentials.keychain import Keychain
from whitenight.memory import (
    MemoryExtractor,
    NullMemoryExtractor,
    OllamaMemoryExtractor,
    RuleBasedMemoryExtractor,
)
from whitenight.models.base import ModelProvider
from whitenight.models.ollama import OllamaProvider
from whitenight.models.openai import OpenAIProvider


def _build_model_provider(settings: Settings, credentials: Keychain) -> ModelProvider:
    """Capture credentials in memory for this provider generation."""
    if settings.model_provider == "openai":
        return OpenAIProvider(
            base_url=settings.openai_base_url,
            model=settings.model_name,
            api_key=credentials.get(settings.keychain_service, settings.openai_api_key_account),
            timeout_s=settings.openai_timeout_s,
            max_output_tokens=settings.model_max_output_tokens,
        )
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.model_name,
        max_output_tokens=settings.model_max_output_tokens,
        keep_alive=settings.ollama_keep_alive,
    )


def _persist_config_values(updates: dict[str, object]) -> None:
    """Persist non-secret runtime settings and keep the existing backup behavior."""
    path = Path(os.environ.get("WHITENIGHT_CONFIG", str(DEFAULT_CONFIG_PATH)))
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ConfigError("配置文件格式损坏")
        data = loaded
        backup = path.with_suffix(
            f".bak-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        )
        shutil.copy2(path, backup)
    data.update(updates)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        os.chmod(temporary, 0o600)
        handle.write(yaml.safe_dump(data, allow_unicode=True, sort_keys=True))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _build_memory_extractor(settings: Settings, provider: ModelProvider) -> MemoryExtractor:
    if settings.memory_extractor == "ollama":
        if isinstance(provider, OllamaProvider):
            # 记忆提取复用同一模型，但用更小的输出上限：提取只需 JSON，
            # 2048 token 会把唯一推理槽占住几分钟，拖慢下一条聊天。
            extractor_provider = OllamaProvider(
                base_url=provider.base_url,
                model=provider.model,
                max_output_tokens=settings.memory_extract_max_tokens,
                keep_alive=provider.keep_alive,
            )
            return OllamaMemoryExtractor(extractor_provider)
        return OllamaMemoryExtractor(provider)
    if settings.memory_extractor == "rules":
        return RuleBasedMemoryExtractor()
    return NullMemoryExtractor()


class ModelConfigurationService:
    """Install one validated configuration generation across application consumers."""

    def __init__(
        self,
        settings: Settings,
        credentials: Keychain,
        install: Callable[[ModelProvider, MemoryExtractor], None],
    ) -> None:
        self.settings = settings
        self.credentials = credentials
        self.install = install

    def update(
        self, provider: str, model_name: str, base_url: str, api_key: str | None
    ) -> dict[str, object]:
        if provider not in {"ollama", "openai"} or not model_name.strip():
            raise ConfigError("模型或Provider无效")
        settings = self.settings
        key = (api_key or "").strip()
        account = settings.openai_api_key_account
        if provider == "openai":
            previous_key = self.credentials.get(
                settings.keychain_service, settings.openai_api_key_account
            )
            if not key and not previous_key:
                raise ConfigError("云端 Provider 未配置 API Key")
            if key:
                # The YAML's account reference is the commit point. Never overwrite
                # the previous generation: write failure/crash must leave its key
                # paired with the old endpoint, including after process restart.
                account = f"openai_api_key.{uuid4().hex}"
                self.credentials.set(settings.keychain_service, account, key)
        updates: dict[str, object] = {
            "model_provider": provider,
            "model_name": model_name.strip(),
            "ollama_base_url": base_url if provider == "ollama" else settings.ollama_base_url,
            "openai_base_url": base_url if provider == "openai" else settings.openai_base_url,
            "openai_api_key_account": account,
        }
        next_settings = settings.model_copy(update=updates)
        next_provider = _build_model_provider(next_settings, self.credentials)
        extractor_settings = next_settings.model_copy(
            update={"model_max_output_tokens": settings.memory_extract_max_tokens}
        )
        extractor_provider = _build_model_provider(extractor_settings, self.credentials)
        extractor = _build_memory_extractor(extractor_settings, extractor_provider)
        _persist_config_values(updates)
        for name in updates:
            setattr(settings, name, getattr(next_settings, name))
        self.install(next_provider, extractor)
        return {
            "provider": provider,
            "model_name": settings.model_name,
            "base_url": base_url,
            "api_key_configured": bool(
                provider == "openai"
                and self.credentials.get(settings.keychain_service, settings.openai_api_key_account)
            ),
            "persisted": True,
        }
