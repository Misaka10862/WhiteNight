#!/usr/bin/env python3
"""服务级 E2E 冒烟（阶段 10，非破坏性，使用临时数据目录）。

默认 DummyProvider；--real-model 使用本机 Ollama qwen3-vl:8b。
覆盖：健康检查 → 会话/WebSocket 流式聊天 → 记忆提取 → 主动消息状态 → 加密备份。
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from whitenight.agent.service import DummyProvider
from whitenight.api.app import create_app
from whitenight.config import Settings
from whitenight.memory.extraction import RuleBasedMemoryExtractor
from whitenight.models.base import ModelProvider
from whitenight.models.ollama import OllamaProvider
from whitenight.storage.backup import create_backup, verify_backup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-model", action="store_true")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = Settings(
            app_env="test",
            data_dir=tmp_path / "data",
            database_url=f"sqlite:///{tmp_path / 'data' / 'whitenight.db'}",
            keychain_backend="memory",
            memory_extractor="rules",
            log_level="WARNING",
        )
        provider: ModelProvider
        if args.real_model:
            provider = OllamaProvider(settings.ollama_base_url, settings.model_name)
        else:
            provider = DummyProvider("E2E 回复")
        app = create_app(
            settings,
            model_provider=provider,
            memory_extractor=RuleBasedMemoryExtractor(),
        )
        with TestClient(app) as client:
            assert client.get("/healthz").status_code == 200
            session = client.post("/api/v1/sessions", json={"title": "E2E"}).json()
            with client.websocket_connect("/api/v1/chat/ws") as websocket:
                websocket.send_json({"session_id": session["id"], "text": "我喜欢抹茶冰淇淋"})
                chunks: list[str] = []
                while True:
                    event = websocket.receive_json()
                    if event["type"] == "chunk":
                        chunks.append(event["delta"])
                    elif event["type"] == "done":
                        assert "".join(chunks).strip()
                        break
                    elif event["type"] == "error":
                        raise RuntimeError(event)
            messages = client.get(f"/api/v1/sessions/{session['id']}/messages").json()
            assert [message["role"] for message in messages] == ["user", "assistant"]
            extracted = client.post(
                "/api/v1/memory/extract", json={"session_id": session["id"]}
            ).json()
            # 聊天完成后的异步提取可能已先写入；只要求事实最终存在且无重复。
            assert extracted["facts_added"] <= 1
            facts = client.get("/api/v1/memory/facts").json()
            assert any(fact["value"] == "抹茶冰淇淋" for fact in facts)
            proactive = client.get("/api/v1/proactive/status").json()
            assert proactive["config"]["enabled"] is False

            backup_path = tmp_path / "backup.bak"
            create_backup(settings, backup_path, "e2e-恢复密钥")
            assert verify_backup(backup_path, "e2e-恢复密钥")["counts"]["sessions"] == 1

        print(f"E2E SMOKE OK ({'real-ollama' if args.real_model else 'dummy'})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
