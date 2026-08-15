"""FastAPI 应用工厂：健康检查、运行状态与 WebSocket 事件流空壳。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from whitenight import __version__
from whitenight.config import Settings, load_settings
from whitenight.logging_config import setup_logging
from whitenight.storage.engine import backend_of, build_engine, ping, resolve_database_key


def create_app(settings: Settings | None = None) -> FastAPI:
    """构建应用。测试可注入临时 Settings。"""
    settings = settings or load_settings()
    setup_logging(level=settings.log_level, json_logs=settings.log_json)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_dirs()
        yield

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
        database_url = str(settings.database_url)
        engine = build_engine(
            database_url,
            key=resolve_database_key(
                database_url,
                keychain_backend=settings.keychain_backend,
                keychain_service=settings.keychain_service,
            ),
        )
        try:
            reachable = ping(engine)
        finally:
            engine.dispose()
        return {
            "name": settings.app_name,
            "version": __version__,
            "env": settings.app_env,
            "host": settings.host,
            "port": settings.port,
            "database": {"url_backend": backend_of(database_url), "reachable": reachable},
        }

    @app.websocket("/api/v1/ws")
    async def ws_events(websocket: WebSocket) -> None:
        """阶段 0 回显端点；后续替换为标准化事件流（见 docs/contracts/event-envelope.md）。"""
        await websocket.accept()
        try:
            while True:
                message = await websocket.receive_text()
                await websocket.send_text(message)
        except WebSocketDisconnect:
            return

    return app


app = create_app()
