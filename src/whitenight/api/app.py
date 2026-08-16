"""FastAPI 应用工厂：会话 CRUD、WebSocket 流式聊天与运行状态。

首版 API 只监听 127.0.0.1；所有入口共用同一会话存储与 Agent 服务。
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ValidationError

from whitenight import __version__
from whitenight.agent.context import load_soul
from whitenight.agent.service import ChatService, create_chat_service
from whitenight.channels.onebot import ChannelSessionStore, OneBotAdapter, OneBotSender
from whitenight.channels.types import (
    ChatEvent,
    ChatRequest,
    MessageRecord,
    SessionCreate,
    SessionSummary,
)
from whitenight.config import DEFAULT_CONFIG_PATH, Settings, load_settings
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
from whitenight.policy.approvals import ApprovalService, SessionGrantRecord
from whitenight.policy.audit import AuditService
from whitenight.policy.engine import PolicyEngine
from whitenight.routing.engine import OllamaRoutingRouter, RoutingEngine
from whitenight.routing.rules import RuleRouter
from whitenight.scheduler import LogSender, NullSender, ProactiveService, ProactiveStore
from whitenight.scheduler.types import PauseRequest, ProactiveConfig, ProactiveStatus
from whitenight.storage.engine import backend_of, build_engine, ping, resolve_database_key
from whitenight.storage.migrate import upgrade_to_head
from whitenight.storage.sessions import SessionNotFoundError, SessionStore


class ExtractRequest(BaseModel):
    session_id: str


class ResolveRequest(BaseModel):
    keep: bool = True


class SessionRename(BaseModel):
    title: str


class ApprovalAction(BaseModel):
    session_id: str | None = None


class RuleUpdate(BaseModel):
    content: str


class ModelKeepAliveUpdate(BaseModel):
    keep_alive: str


_MODEL_KEEP_ALIVE_OPTIONS = ("-1", "5m", "30m", "1h", "6h", "12h")


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


def create_app(
    settings: Settings | None = None,
    model_provider: ModelProvider | None = None,
    memory_extractor: MemoryExtractor | None = None,
) -> FastAPI:
    """构建应用。测试可注入临时 Settings、Fake Provider 与记忆提取器。"""
    settings = settings or load_settings()
    settings.ensure_dirs()
    setup_logging(
        level=settings.log_level,
        json_logs=settings.log_json,
        log_file=str(settings.data_dir / "logs" / "whitenight.log"),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_dirs()
        if settings.auto_migrate:
            upgrade_to_head(settings)
            # alembic env.py 的 fileConfig 会替换 root handlers（并可能禁用业务
            # logger），必须在迁移后恢复 WhiteNight 的日志配置。
            setup_logging(
                level=settings.log_level,
                json_logs=settings.log_json,
                log_file=str(settings.data_dir / "logs" / "whitenight.log"),
            )
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
            base_url=settings.ollama_base_url,
            model=settings.model_name,
            max_output_tokens=settings.model_max_output_tokens,
            keep_alive=settings.ollama_keep_alive,
        )
        audit = AuditService(engine)
        approvals = ApprovalService(engine)
        extractor = memory_extractor or _build_memory_extractor(settings, provider)
        embedding_provider = (
            OllamaEmbeddingProvider(settings.ollama_base_url, settings.embedding_model)
            if settings.embedding_model
            else NullEmbeddingProvider()
        )
        memory_service = MemoryService(MemoryStore(engine), extractor, embedding_provider, audit)
        proactive_store = ProactiveStore(engine)
        proactive_sender: LogSender | NullSender | OneBotSender
        if settings.proactive_sender == "qq" and settings.qq_owner_ids:
            proactive_sender = OneBotSender(settings.qq_onebot_api_url, settings.qq_reply_max_chars)
        else:
            proactive_sender = (
                LogSender(settings.data_dir / "logs" / "proactive.jsonl")
                if settings.proactive_sender in {"log", "qq"}
                else NullSender()
            )
        proactive_service = ProactiveService(
            proactive_store, provider, memory_service, proactive_sender, settings
        )
        proactive_stop = asyncio.Event()
        proactive_task = asyncio.create_task(proactive_service.run_forever(proactive_stop))
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
        chat_service = create_chat_service(
            store,
            provider,
            settings,
            memory_service,
            router,
            delegate_manager,
            proactive_service,
        )
        channel_sessions = ChannelSessionStore(engine, store)
        onebot_adapter = OneBotAdapter(
            settings,
            store,
            channel_sessions,
            chat_service,
            approvals,
            OneBotSender(settings.qq_onebot_api_url, settings.qq_reply_max_chars),
        )
        _app.state.engine = engine
        _app.state.store = store
        _app.state.memory_service = memory_service
        _app.state.approvals = approvals
        _app.state.audit = audit
        _app.state.policy = PolicyEngine()
        _app.state.proactive_service = proactive_service
        _app.state.task_store = task_store
        _app.state.delegate_manager = delegate_manager
        _app.state.channel_sessions = channel_sessions
        _app.state.onebot_adapter = onebot_adapter
        _app.state.chat_service = chat_service
        yield
        proactive_stop.set()
        try:
            await asyncio.wait_for(proactive_task, timeout=10)
        except TimeoutError:
            proactive_task.cancel()
            await asyncio.gather(proactive_task, return_exceptions=True)
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

    @app.patch("/api/v1/sessions/{session_id}", response_model=SessionSummary)
    async def rename_session(session_id: str, payload: SessionRename) -> SessionSummary:
        store: SessionStore = app.state.store
        try:
            return store.rename_session(session_id, payload.title)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="会话不存在") from exc

    @app.delete("/api/v1/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str) -> None:
        store: SessionStore = app.state.store
        audit: AuditService = app.state.audit
        try:
            store.delete_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="会话不存在") from exc
        audit.record(
            actor="user",
            action="session.deleted",
            decision="approved",
            params_summary=f"session_id={session_id}",
            result_summary="已删除（正文不入审计）",
        )

    @app.get("/api/v1/sessions/{session_id}/export", response_class=PlainTextResponse)
    async def export_session(
        session_id: str, fmt: str = Query(default="markdown", pattern="^(markdown|jsonl)$")
    ) -> str:
        store: SessionStore = app.state.store
        return store.export_session(session_id, fmt)

    # ---- 审批与权限（WebUI 阶段 6） ------------------------------------

    @app.get("/api/v1/approvals/pending")
    async def list_pending_approvals() -> list[dict[str, object]]:
        service: ApprovalService = app.state.approvals
        return [item.__dict__ for item in service.list_pending()]

    @app.post("/api/v1/approvals/{code}/approve")
    async def approve_request(code: str, payload: ApprovalAction) -> dict[str, object]:
        service: ApprovalService = app.state.approvals
        pending = [item for item in service.list_pending() if item.code == code]
        scope = pending[0].scope if pending else "once"
        resolution = service.resolve_once(code, session_id=payload.session_id, expected_scope=scope)
        return {"ok": resolution.ok, "reason": resolution.reason, "scope": resolution.scope}

    @app.post("/api/v1/approvals/{code}/reject")
    async def reject_request(code: str) -> dict[str, object]:
        service: ApprovalService = app.state.approvals
        resolution = service.reject(code)
        return {"ok": resolution.ok, "reason": resolution.reason}

    @app.get("/api/v1/policy/rules")
    async def policy_rules() -> list[dict[str, str]]:
        policy: PolicyEngine = app.state.policy
        return [{"tool": name, "risk": risk.value} for name, risk in sorted(policy.rules().items())]

    @app.get("/api/v1/policy/grants", response_model=list[SessionGrantRecord])
    async def session_grants() -> list[SessionGrantRecord]:
        service: ApprovalService = app.state.approvals
        return service.list_session_grants()

    @app.delete("/api/v1/policy/grants/{grant_id}", status_code=204)
    async def revoke_grant(grant_id: str) -> None:
        service: ApprovalService = app.state.approvals
        service.revoke_session_grant(grant_id)

    @app.get("/api/v1/proactive/status", response_model=ProactiveStatus)
    async def proactive_status() -> ProactiveStatus:
        service: ProactiveService = app.state.proactive_service
        return service.status()

    @app.put("/api/v1/proactive/config", response_model=ProactiveStatus)
    async def proactive_config(payload: ProactiveConfig) -> ProactiveStatus:
        service: ProactiveService = app.state.proactive_service
        return service.update_config(payload)

    @app.post("/api/v1/proactive/pause", response_model=ProactiveStatus)
    async def proactive_pause(payload: PauseRequest) -> ProactiveStatus:
        service: ProactiveService = app.state.proactive_service
        return service.pause(payload)

    @app.post("/api/v1/proactive/resume", response_model=ProactiveStatus)
    async def proactive_resume() -> ProactiveStatus:
        service: ProactiveService = app.state.proactive_service
        return service.resume()

    @app.get("/api/v1/model/config")
    async def model_config() -> dict[str, object]:
        provider = app.state.chat_service.provider
        keep_alive = getattr(provider, "keep_alive", settings.ollama_keep_alive)
        return {"ollama_keep_alive": keep_alive, "options": list(_MODEL_KEEP_ALIVE_OPTIONS)}

    @app.put("/api/v1/model/config")
    async def update_model_config(payload: ModelKeepAliveUpdate) -> dict[str, object]:
        if payload.keep_alive not in _MODEL_KEEP_ALIVE_OPTIONS:
            allowed = ", ".join(_MODEL_KEEP_ALIVE_OPTIONS)
            raise HTTPException(status_code=400, detail=f"keep_alive 仅支持：{allowed}")
        provider = app.state.chat_service.provider
        if isinstance(provider, OllamaProvider):
            provider.keep_alive = payload.keep_alive
        settings.ollama_keep_alive = payload.keep_alive

        path = Path(os.environ.get("WHITENIGHT_CONFIG", str(DEFAULT_CONFIG_PATH)))
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {}
        if path.exists():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise HTTPException(status_code=500, detail="配置文件格式损坏")
            data = loaded
            backup = path.with_suffix(f".bak-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}")
            shutil.copy2(path, backup)
        data["ollama_keep_alive"] = payload.keep_alive
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=True), encoding="utf-8")
        return {"ollama_keep_alive": payload.keep_alive, "persisted": True}

    @app.get("/api/v1/system/health")
    async def system_health() -> dict[str, object]:
        engine = app.state.engine
        provider = app.state.chat_service.provider
        model_status: dict[str, object]
        try:
            model_status = await provider.health()
        except Exception as exc:
            model_status = {"error": str(exc)}
        delegate_status: dict[str, object] = {}
        for name, delegate in app.state.delegate_manager.providers().items():
            try:
                delegate_status[name] = await delegate.health()
            except Exception as exc:
                delegate_status[name] = {"error": str(exc)}
        return {
            "database": {
                "backend": backend_of(str(settings.database_url)),
                "reachable": ping(engine),
            },
            "model": model_status,
            "delegates": delegate_status,
            "onebot": {
                "enabled": app.state.onebot_adapter.enabled(),
                "owner_ids": app.state.onebot_adapter.owner_ids(),
                "api_url": settings.qq_onebot_api_url,
            },
        }

    @app.get("/api/v1/rules/{name}", response_class=PlainTextResponse)
    async def get_rule_file(name: str) -> str:
        if name not in {"SOUL", "AGENTS"}:
            raise HTTPException(status_code=404, detail="规则文件不存在")
        path = settings.soul_file if name == "SOUL" else Path("AGENTS.md")
        if path.exists():
            return path.read_text(encoding="utf-8")
        if name == "SOUL":
            return load_soul(path)
        return "# AGENTS.md（尚未创建，保存后生效）\n"

    @app.put("/api/v1/rules/{name}", response_class=PlainTextResponse)
    async def update_rule_file(name: str, payload: RuleUpdate) -> str:
        if name not in {"SOUL", "AGENTS"}:
            raise HTTPException(status_code=404, detail="规则文件不存在")
        path = settings.soul_file if name == "SOUL" else Path("AGENTS.md")
        path.write_text(payload.content, encoding="utf-8")
        return "saved"

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

    # ---- OneBot / QQ（阶段 8） ------------------------------------------

    @app.post("/api/v1/onebot/events")
    async def onebot_events(payload: dict[str, object]) -> dict[str, object]:
        adapter: OneBotAdapter = app.state.onebot_adapter
        return await adapter.handle_event(payload)

    @app.get("/api/v1/onebot/status")
    async def onebot_status() -> dict[str, object]:
        adapter: OneBotAdapter = app.state.onebot_adapter
        return {
            "enabled": adapter.enabled(),
            "owner_ids": adapter.owner_ids(),
            "api_url": settings.qq_onebot_api_url,
        }

    @app.get("/api/v1/logs", response_class=PlainTextResponse)
    async def read_logs(lines: int = Query(default=100, ge=1, le=1000)) -> str:
        path = settings.data_dir / "logs" / "whitenight.log"
        if not path.exists():
            return ""
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])

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
