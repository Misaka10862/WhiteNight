#!/usr/bin/env python3
"""Disposable browser acceptance server: fake inference, no production services.

Run .venv/bin/python scripts/browser_fixture.py, then run Vite with
WHITENIGHT_API_URL=http://127.0.0.1:8769 npm --prefix apps/web run dev -- --port 5179 --strictPort.
The printed temporary directory is retained for inspection; never reuse production data.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from whitenight.api.app import create_app
from whitenight.config import Settings
from whitenight.models.base import ModelCapabilities, ModelChunk, ProviderMessage, ToolSpec


class BrowserFixtureProvider:
    capabilities = ModelCapabilities(tools=False, vision=True)

    async def health(self) -> dict[str, object]:
        return {"provider": "browser-fixture", "model": "deterministic-local-fixture", "ok": True}

    async def stream_chat(
        self, messages: list[ProviderMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[ModelChunk]:
        del tools
        prompt = next(
            (message.content for message in reversed(messages) if message.role == "user"), ""
        )
        label = "B" if "B测试" in prompt else "A"
        for index in range(24):
            await asyncio.sleep(0.25)
            yield ModelChunk(delta=f"{label}-{index + 1} ")
            if "故障测试" in prompt and index == 2:
                raise RuntimeError("Synthetic browser fixture failure")
        yield ModelChunk(delta="测试回复完成。", done=True)


def make_fixture() -> FastAPI:
    directory = Path(tempfile.mkdtemp(prefix="whitenight-browser-fixture-"))
    soul = directory / "fixture-persona.md"
    soul.write_text("# Test persona\nOnly deterministic browser acceptance data.\n")
    settings = Settings(
        app_env="test",
        data_dir=directory / "data",
        database_url=f"sqlite:///{directory / 'data' / 'fixture.db'}",
        keychain_backend="memory",
        keychain_service="com.whitenight.browser-fixture",
        memory_extractor="none",
        qq_enabled=False,
        proactive_enabled=False,
        proactive_sender="none",
        hermes_enabled=False,
        codex_command="/usr/bin/false",
        auto_migrate=True,
        soul_file=soul,
        model_supports_vision=True,
        port=8769,
        web_origins=["http://127.0.0.1:5179", "http://localhost:5179"],
    )
    app = create_app(settings, model_provider=BrowserFixtureProvider())
    previous_lifespan = app.router.lifespan_context
    state: dict[str, object] = {
        "data_directory": str(directory),
        "api": "http://127.0.0.1:8769",
        "web": "http://127.0.0.1:5179",
    }

    @asynccontextmanager
    async def fixture_lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with previous_lifespan(application):
            personality = application.state.personality_store
            store = application.state.store
            sessions = [
                store.create_session(
                    f"浏览器{label}测试",
                    character_id=personality.default_character_id(),
                    persona_id=personality.default_persona_id(),
                )
                for label in ("A", "B")
            ]
            state["session_A"] = sessions[0].id
            state["session_B"] = sessions[1].id
            for label in ("单次授权检查", "会话授权检查"):
                application.state.approvals.request(
                    "file.create",
                    "low_write",
                    "session",
                    label,
                    session_id=sessions[0].id,
                    channel="web",
                )
            print(json.dumps(state, ensure_ascii=False), flush=True)
            yield

    app.router.lifespan_context = fixture_lifespan

    @app.get("/api/v1/fixture/state")
    async def fixture_state() -> dict[str, object]:
        return {
            **state,
            "grants": [grant.__dict__ for grant in app.state.approvals.list_session_grants()],
        }

    @app.post("/api/v1/fixture/approvals")
    async def fresh_approvals() -> dict[str, bool]:
        app.state.approvals.request(
            "file.create",
            "low_write",
            "session",
            "重新生成会话授权检查",
            session_id=str(state["session_A"]),
            channel="web",
        )
        return {"ok": True}

    return app


if __name__ == "__main__":
    uvicorn.run(make_fixture(), host="127.0.0.1", port=8769, access_log=False, log_level="warning")
