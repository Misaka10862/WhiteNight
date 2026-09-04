"""嵌入 Provider 接口：语义检索按需加载，避免与 8B 模型争抢内存。"""

from __future__ import annotations

import time
from typing import Protocol
from uuid import uuid4

import httpx


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class NullEmbeddingProvider:
    """语义不可用时的降级实现。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        del texts
        return []


class OllamaEmbeddingProvider:
    """Ollama /api/embed；模型未安装时返回空向量（词法检索兜底）。"""

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._model_digest: str | None = None
        self._digest_checked_at = float("-inf")
        self._unknown_revision = uuid4().hex

    def cache_identity(self) -> str:
        """Resolve mutable Ollama tags to a digest outside the event loop.

        If revision discovery is unavailable, reuse is confined to this provider
        instance instead of trusting stale vectors from another process.
        """
        if self.model and time.monotonic() - self._digest_checked_at >= 300:
            self._digest_checked_at = time.monotonic()
            try:
                response = httpx.get(f"{self.base_url}/api/tags", timeout=5.0, trust_env=False)
                response.raise_for_status()
                models = response.json().get("models", [])
                self._model_digest = next(
                    (
                        str(item["digest"])
                        for item in models
                        if isinstance(item, dict)
                        and item.get("name") in {self.model, f"{self.model}:latest"}
                        and item.get("digest")
                    ),
                    None,
                )
            except Exception:
                self._model_digest = None
        return f"ollama|{self.base_url}|{self.model}|{self._model_digest or self._unknown_revision}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.model or not texts:
            return []
        try:
            response = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": texts},
                timeout=httpx.Timeout(30.0, connect=5.0),
                trust_env=False,  # 本机服务，绕开系统代理
            )
            if response.status_code != 200:
                return []
            payload = response.json()
            embeddings = payload.get("embeddings") or []
            return [list(item) for item in embeddings]
        except Exception:
            return []
