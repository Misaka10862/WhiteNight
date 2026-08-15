"""FastAPI 应用工厂：会话 CRUD、WebSocket 流式聊天与运行状态。

首版 API 只监听 127.0.0.1；所有入口共用同一会话存储与 Agent 服务。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from whitenight import __version__
from whitenight.agent.service import ChatService, create_chat_service
from whitenight.channels.types import (
    ChatEvent,
    ChatRequest,
    MessageRecord,
    SessionCreate,
    SessionSummary,
)
from whitenight.config import Settings, load_settings
from whitenight.logging_config import setup_logging
from whitenight.models.base import ModelProvider
from whitenight.models.ollama import OllamaProvider
from whitenight.storage.engine import backend_of, build_engine, ping, resolve_database_key
from whitenight.storage.migrate import upgrade_to_head
from whitenight.storage.sessions import SessionNotFoundError, SessionStore


def create_app(
    settings: Settings | None = None,
    model_provider: ModelProvider | None = None,
) -> FastAPI:
    """构建应用。测试可注入临时 Settings 与 Fake Provider。"""
    settings = settings or load_settings()
    setup_logging(level=settings.log_level, json_logs=settings.log_json)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_dirs()
        if settings.auto_migrate:
            upgrade_to_head(settings)
        engine = build_engine(
            str(settings.database_url),
            key=resolve_database_key(
                str(settings.database_url),
                keychain_backend=settings.keychain_backend,
                keychain_service=settings.keychain_service,
            ),
        )
        store = SessionStore(engine, attachments_dir=settings.data_dir / "attachments")
        provider = model_provider or OllamaProvider(
            base_url=settings.ollama_base_url, model=settings.model_name
        )
        _app.state.engine = engine
        _app.state.store = store
        _app.state.chat_service = create_chat_service(store, provider, settings)
        yield
        engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings

    # 首版 WebUI 与本 API 同源开发；即使启用 CORS 也仅允许本机回环地址。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", response_class=PlainTextResponse)
    async def root() -> str:
        return f"{settings.app_name} API v{__version__} — 本机服务"

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> str:
        return "ok"

    @app.get("/api/v1/status")
    async def status() -> dict[str, object]:
        engine = app.state.engine
        provider = app.state.chat_service.provider
        model_status: dict[str, object] = {}
        try:
            model_status = await provider.health()
        except Exception as exc:  # 状态接口吞掉并报告
            model_status = {"error": str(exc)}
        return {
            "name": settings.app_name,
            "version": __version__,
            "env": settings.app_env,
            "host": settings.host,
            "port": settings.port,
            "database": {
                "url_backend": backend_of(str(settings.database_url)),
                "reachable": ping(engine),
            },
            "model": model_status,
        }

    @app.post("/api/v1/sessions", response_model=SessionSummary)
    async def create_session(payload: SessionCreate) -> SessionSummary:
        store: SessionStore = app.state.store
        return store.create_session(payload.title)

    @app.get("/api/v1/sessions", response_model=list[SessionSummary])
    async def list_sessions() -> list[SessionSummary]:
        store: SessionStore = app.state.store
        return store.list_sessions()

    @app.get("/api/v1/sessions/{session_id}", response_model=SessionSummary)
    async def get_session(session_id: str) -> SessionSummary:
        store: SessionStore = app.state.store
        try:
            return store.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="会话不存在") from exc

    @app.get("/api/v1/sessions/{session_id}/messages", response_model=list[MessageRecord])
    async def list_messages(session_id: str) -> list[MessageRecord]:
        store: SessionStore = app.state.store
        try:
            return store.list_messages(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="会话不存在") from exc

    @app.websocket("/api/v1/chat/ws")
    async def chat_ws(websocket: WebSocket) -> None:
        """统一流式聊天入口。事件格式见 docs/contracts/event-envelope.md（简化版）。"""
        await websocket.accept()
        service: ChatService = app.state.chat_service
        try:
            while True:
                raw = await websocket.receive_json()
                try:
                    request = ChatRequest.model_validate(raw)
                except ValidationError as exc:
                    await websocket.send_text(
                        ChatEvent(type="error", message=f"消息格式不合法：{exc}").model_dump_json()
                    )
                    continue
                async for event in service.stream_reply(request):
                    await websocket.send_text(event.model_dump_json())
        except WebSocketDisconnect:
            return

    @app.websocket("/api/v1/ws")
    async def ws_events(websocket: WebSocket) -> None:
        """阶段 0 回显端点；后续替换为标准化事件流。"""
        await websocket.accept()
        try:
            while True:
                message = await websocket.receive_text()
                await websocket.send_text(message)
        except WebSocketDisconnect:
            return

    return app


app = create_app()
