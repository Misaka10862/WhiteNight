"""FastAPI 应用工厂：会话 CRUD、WebSocket 流式聊天与运行状态。

首版 API 只监听 127.0.0.1；所有入口共用同一会话存储与 Agent 服务。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ValidationError

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
from whitenight.delegates.codex import CodexAdapter
from whitenight.delegates.hermes import HermesGatewayAdapter
from whitenight.delegates.manager import DelegateManager, TaskRecord, TaskStore
from whitenight.logging_config import setup_logging
from whitenight.memory import (
    MemoryExtractor,
    MemoryService,
    MemoryStore,
    NullEmbeddingProvider,
    NullMemoryExtractor,
    OllamaEmbeddingProvider,
    OllamaMemoryExtractor,
    RuleBasedMemoryExtractor,
)
from whitenight.memory.types import (
    EpisodeCreate,
    EpisodeRecord,
    FactRecord,
    FactUpdate,
    FactUpsert,
    MemoryHit,
)
from whitenight.models.base import ModelProvider
from whitenight.models.ollama import OllamaProvider
from whitenight.policy.audit import AuditService
from whitenight.routing.engine import OllamaRoutingRouter, RoutingEngine
from whitenight.routing.rules import RuleRouter
from whitenight.storage.engine import backend_of, build_engine, ping, resolve_database_key
from whitenight.storage.migrate import upgrade_to_head
from whitenight.storage.sessions import SessionNotFoundError, SessionStore


class ExtractRequest(BaseModel):
    session_id: str


class ResolveRequest(BaseModel):
    keep: bool = True


def _build_memory_extractor(settings: Settings, provider: ModelProvider) -> MemoryExtractor:
    if settings.memory_extractor == "ollama":
        return OllamaMemoryExtractor(provider)
    if settings.memory_extractor == "rules":
        return RuleBasedMemoryExtractor()
    return NullMemoryExtractor()


def create_app(
    settings: Settings | None = None,
    model_provider: ModelProvider | None = None,
    memory_extractor: MemoryExtractor | None = None,
) -> FastAPI:
    """构建应用。测试可注入临时 Settings、Fake Provider 与记忆提取器。"""
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
        audit = AuditService(engine)
        extractor = memory_extractor or _build_memory_extractor(settings, provider)
        embedding_provider = (
            OllamaEmbeddingProvider(settings.ollama_base_url, settings.embedding_model)
            if settings.embedding_model
            else NullEmbeddingProvider()
        )
        memory_service = MemoryService(MemoryStore(engine), extractor, embedding_provider, audit)
        task_store = TaskStore(engine)
        delegate_manager = DelegateManager(
            task_store,
            {
                "codex": CodexAdapter(settings.codex_command, settings.codex_timeout_s),
                "hermes": HermesGatewayAdapter(settings.hermes_gateway_url),
            },
        )
        router = RoutingEngine(
            rule_router=RuleRouter(),
            llm_router=OllamaRoutingRouter(provider),
        )
        _app.state.engine = engine
        _app.state.store = store
        _app.state.memory_service = memory_service
        _app.state.task_store = task_store
        _app.state.delegate_manager = delegate_manager
        _app.state.chat_service = create_chat_service(
            store, provider, settings, memory_service, router, delegate_manager
        )
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

    # ---- 长期记忆（阶段 4） --------------------------------------------

    @app.get("/api/v1/memory/facts", response_model=list[FactRecord])
    async def list_facts() -> list[FactRecord]:
        memory: MemoryService = app.state.memory_service
        return memory.list_facts()

    @app.post("/api/v1/memory/facts", response_model=FactRecord)
    async def upsert_fact(payload: FactUpsert) -> FactRecord:
        memory: MemoryService = app.state.memory_service
        return memory.upsert_fact(payload)

    @app.put("/api/v1/memory/facts/{fact_id}", response_model=FactRecord)
    async def update_fact(fact_id: str, payload: FactUpdate) -> FactRecord:
        memory: MemoryService = app.state.memory_service
        try:
            return memory.update_fact(fact_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="记忆不存在") from exc

    @app.delete("/api/v1/memory/facts/{fact_id}", status_code=204)
    async def delete_fact(fact_id: str) -> None:
        memory: MemoryService = app.state.memory_service
        try:
            memory.delete_fact(fact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="记忆不存在") from exc

    @app.post("/api/v1/memory/facts/{fact_id}/resolve", response_model=FactRecord | None)
    async def resolve_fact(fact_id: str, payload: ResolveRequest) -> FactRecord | None:
        memory: MemoryService = app.state.memory_service
        try:
            return memory.resolve_conflict(fact_id, payload.keep)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="记忆不存在") from exc

    @app.get("/api/v1/memory/episodes", response_model=list[EpisodeRecord])
    async def list_episodes() -> list[EpisodeRecord]:
        memory: MemoryService = app.state.memory_service
        return memory.list_episodes()

    @app.post("/api/v1/memory/episodes", response_model=EpisodeRecord)
    async def add_episode(payload: EpisodeCreate) -> EpisodeRecord:
        memory: MemoryService = app.state.memory_service
        return memory.add_episode(payload)

    @app.delete("/api/v1/memory/episodes/{episode_id}", status_code=204)
    async def delete_episode(episode_id: str) -> None:
        memory: MemoryService = app.state.memory_service
        try:
            memory.delete_episode(episode_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="记忆不存在") from exc

    @app.post("/api/v1/memory/extract")
    async def extract_memories(payload: ExtractRequest) -> dict[str, int]:
        memory: MemoryService = app.state.memory_service
        store: SessionStore = app.state.store
        messages = store.list_messages(payload.session_id)
        return await memory.extract_and_store(messages, payload.session_id)

    @app.get("/api/v1/memory/retrieve", response_model=list[MemoryHit])
    async def retrieve_memory(
        query: str = Query(min_length=1, max_length=200), limit: int = Query(default=8, ge=1, le=20)
    ) -> list[MemoryHit]:
        memory: MemoryService = app.state.memory_service
        return memory.retrieve(query, limit=limit)

    @app.get("/api/v1/memory/export", response_class=PlainTextResponse)
    async def export_memory(fmt: str = Query(default="jsonl", pattern="^(jsonl|markdown)$")) -> str:
        memory: MemoryService = app.state.memory_service
        return memory.export(fmt)

    @app.get("/api/v1/sessions/{session_id}/summary")
    async def get_summary(session_id: str) -> dict[str, str | None]:
        memory: MemoryService = app.state.memory_service
        return {"summary": memory.get_session_summary(session_id)}

    @app.post("/api/v1/sessions/{session_id}/summarize")
    async def summarize_session(session_id: str) -> dict[str, str | None]:
        memory: MemoryService = app.state.memory_service
        store: SessionStore = app.state.store
        provider = app.state.chat_service.provider
        summary = await memory.summarize_session(
            store.list_messages(session_id), session_id, provider
        )
        return {"summary": summary}

    # ---- 委派任务（阶段 5） --------------------------------------------

    @app.get("/api/v1/tasks", response_model=list[TaskRecord])
    async def list_tasks(session_id: str | None = None) -> list[TaskRecord]:
        task_store: TaskStore = app.state.task_store
        return task_store.list(session_id=session_id)

    @app.get("/api/v1/tasks/{task_id}", response_model=TaskRecord)
    async def get_task(task_id: str) -> TaskRecord:
        task_store: TaskStore = app.state.task_store
        try:
            return task_store.get(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc

    @app.post("/api/v1/tasks/{task_id}/abort", response_model=TaskRecord)
    async def abort_task(task_id: str) -> TaskRecord:
        manager: DelegateManager = app.state.delegate_manager
        await manager.abort(task_id)
        task_store: TaskStore = app.state.task_store
        return task_store.get(task_id)

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
