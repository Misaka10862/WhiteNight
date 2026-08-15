"""嵌入 Provider 接口：语义检索按需加载，避免与 8B 模型争抢内存。"""

from __future__ import annotations

from typing import Protocol

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
