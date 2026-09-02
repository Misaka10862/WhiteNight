"""FastAPI 应用工厂：会话 CRUD、WebSocket 流式聊天与运行状态。

首版 API 只监听 127.0.0.1；所有入口共用同一会话存储与 Agent 服务。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, ValidationError

from whitenight import __version__
from whitenight.agent.service import ChatService, create_chat_service
from whitenight.channels.onebot import ChannelSessionStore, OneBotAdapter, OneBotSender
from whitenight.channels.types import (
    ChannelContext,
    ChatEvent,
    ChatRequest,
    MessageRecord,
    SessionCreate,
    SessionSummary,
)
from whitenight.config import DEFAULT_CONFIG_PATH, Settings, load_settings
from whitenight.credentials.keychain import Keychain, KeychainError, get_keychain
from whitenight.delegates.base import DelegateProvider
from whitenight.delegates.codex import CodexAdapter
from whitenight.delegates.hermes_ws import HermesProcessManager, ManagedHermesGatewayAdapter
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
from whitenight.models.base import ModelProvider, ModelProviderError
from whitenight.models.ollama import OllamaProvider
from whitenight.models.openai import OpenAIProvider
from whitenight.personality.compiler import PromptCompiler
from whitenight.personality.store import PersonalityNotFoundError, PersonalityStore
from whitenight.personality.token_counter import build_token_counter
from whitenight.personality.types import CharacterCard, LorebookData, PromptBlock
from whitenight.policy.approvals import ApprovalService, SessionGrantRecord
from whitenight.policy.audit import AuditService
from whitenight.policy.engine import PolicyEngine
from whitenight.routing.engine import OllamaRoutingRouter, RoutingEngine
from whitenight.routing.rules import RuleRouter
from whitenight.scheduler import LogSender, NullSender, ProactiveService, ProactiveStore
from whitenight.scheduler.types import (
    PauseRequest,
    ProactiveConfig,
    ProactiveDelivery,
    ProactiveStatus,
)
from whitenight.stickers import StickerCatalog, StickerCatalogError
from whitenight.storage.attachments import image_path_to_data_url, save_image_data_url
from whitenight.storage.engine import backend_of, build_engine, ping, resolve_database_key
from whitenight.storage.migrate import upgrade_to_head
from whitenight.storage.sessions import SessionNotFoundError, SessionStore
from whitenight.tools import (
    ArchiveListTool,
    ChannelFileSendTool,
    DocumentParseTool,
    FileCreateTool,
    FileDeleteTool,
    FileFindTool,
    FileMoveTool,
    FileReadTool,
    FileWriteTool,
    ScreenshotTool,
    ToolExecutor,
    ToolRegistry,
    VolcGlobalSearchProvider,
    WebFetchTool,
    WebSearchTool,
)
from whitenight.tools.base import Tool
from whitenight.tools.pending import PendingToolStore
from whitenight.tools.stickers import StickerSendTool


class ExtractRequest(BaseModel):
    session_id: str


class ResolveRequest(BaseModel):
    keep: bool = True


class SessionRename(BaseModel):
    title: str


class ApprovalAction(BaseModel):
    session_id: str | None = None


class ModelKeepAliveUpdate(BaseModel):
    keep_alive: str


class ModelProviderUpdate(BaseModel):
    provider: Literal["ollama", "openai"]
    model_name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)


class ModelListRequest(BaseModel):
    provider: Literal["ollama", "openai"]
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)


class CharacterImport(BaseModel):
    card: CharacterCard
    avatar_data_url: str | None = Field(default=None, max_length=16_000_000)


class PersonaUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=64_000)


class PromptProfileUpdate(BaseModel):
    blocks: list[PromptBlock] = Field(default_factory=list, max_length=200)


class LorebookCreate(BaseModel):
    data: LorebookData
    globally_enabled: bool = False
    character_id: str | None = None


class PromptPreviewRequest(BaseModel):
    text: str = Field(default="", max_length=64_000)


class TokenizerPathUpdate(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


_MODEL_KEEP_ALIVE_OPTIONS = ("-1", "5m", "30m", "1h", "6h", "12h")
_MODEL_PROVIDERS = ("ollama", "openai")
_LAUNCHD_SERVICE_LABEL = "com.whitenight.service"
logger = logging.getLogger(__name__)


def _validate_model_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Base URL 必须是完整的 HTTP(S) 地址")
    return value


def _build_model_provider(settings: Settings, credentials: Keychain) -> ModelProvider:
    """Construct the configured provider; credentials are resolved lazily."""
    keychain = credentials
    if settings.model_provider == "openai":
        return OpenAIProvider(
            base_url=settings.openai_base_url,
            model=settings.model_name,
            api_key=None,
            timeout_s=settings.openai_timeout_s,
            max_output_tokens=settings.model_max_output_tokens,
            key_provider=lambda: keychain.get(
                settings.keychain_service, settings.openai_api_key_account
            ),
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
            raise HTTPException(status_code=500, detail="配置文件格式损坏")
        data = loaded
        backup = path.with_suffix(f".bak-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}")
        shutil.copy2(path, backup)
    data.update(updates)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=True), encoding="utf-8")


def _embedded_lorebook(card: CharacterCard) -> LorebookData | None:
    raw = card.data.character_book
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
        return None
    entries: list[dict[str, object]] = []
    for index, item in enumerate(raw["entries"]):
        if not isinstance(item, dict):
            continue
        raw_extensions = item.get("extensions")
        extensions: dict[str, object] = (
            {str(key): value for key, value in raw_extensions.items()}
            if isinstance(raw_extensions, dict)
            else {}
        )
        position = item.get("position", "before_char")
        entries.append(
            {
                "id": str(item.get("id", item.get("uid", index))),
                "comment": str(item.get("name", item.get("comment", ""))),
                "content": str(item.get("content", "")),
                "keys": item.get("keys", item.get("key", [])),
                "secondary_keys": item.get("secondary_keys", item.get("keysecondary", [])),
                "enabled": bool(item.get("enabled", not item.get("disable", False))),
                "constant": bool(item.get("constant", False)),
                "position": "before" if position in {"before_char", "before", 0} else "after",
                "order": int(item.get("insertion_order") or item.get("order") or 100),
                "probability": float(str(extensions.get("probability") or 100)) / 100.0,
                "depth": int(str(extensions.get("depth") or 4)),
                "extensions": extensions,
            }
        )
    return LorebookData(
        name=str(raw.get("name") or f"{card.data.name} 的世界书"),
        entries=entries,  # type: ignore[arg-type]
        extensions={str(key): value for key, value in raw["extensions"].items()}
        if isinstance(raw.get("extensions"), dict)
        else {},
    )


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
        credential_store = get_keychain(settings.keychain_backend)
        provider = model_provider or _build_model_provider(settings, credential_store)
        audit = AuditService(engine)
        approvals = ApprovalService(engine)
        policy = PolicyEngine()
        onebot_sender = OneBotSender(settings.qq_onebot_api_url, settings.qq_reply_max_chars)
        sticker_catalog: StickerCatalog | None = None
        try:
            sticker_catalog = StickerCatalog(settings.data_dir / "stickers")
        except StickerCatalogError:
            logger.exception("表情目录加载失败，将暂时停用情绪表情包")
        volc_search = VolcGlobalSearchProvider(
            lambda: credential_store.get(
                settings.keychain_service, settings.volc_search_api_key_account
            ),
            endpoint=settings.volc_search_endpoint,
            timeout_s=settings.volc_search_timeout_s,
        )
        registered_tools: list[Tool] = [
            FileFindTool(),
            FileReadTool(),
            FileCreateTool(),
            FileWriteTool(),
            FileMoveTool(),
            FileDeleteTool(),
            DocumentParseTool(),
            ArchiveListTool(),
            ScreenshotTool(),
            WebSearchTool(volc_search),
            WebFetchTool(volc_search),
            ChannelFileSendTool(settings.qq_file_send_max_bytes),
        ]
        if sticker_catalog is not None and sticker_catalog.records(native_only=True):
            registered_tools.append(StickerSendTool(sticker_catalog, settings.qq_owner_ids))
        tool_registry = ToolRegistry(registered_tools)
        tool_executor = ToolExecutor(tool_registry, policy, approvals, audit)
        pending_tools = PendingToolStore(engine)
        extractor = memory_extractor or _build_memory_extractor(settings, provider)
        embedding_provider = (
            OllamaEmbeddingProvider(settings.ollama_base_url, settings.embedding_model)
            if settings.embedding_model
            else NullEmbeddingProvider()
        )
        memory_service = MemoryService(MemoryStore(engine), extractor, embedding_provider, audit)
        personality_store = PersonalityStore(engine)
        prompt_compiler = PromptCompiler(
            personality_store,
            memory_service,
            build_token_counter(settings.model_tokenizer_path),
            settings.model_context_tokens,
            settings.model_max_output_tokens,
        )
        proactive_store = ProactiveStore(engine)
        proactive_sender: LogSender | NullSender | OneBotSender
        if settings.proactive_sender == "qq":
            proactive_sender = onebot_sender
        else:
            proactive_sender = (
                LogSender(settings.data_dir / "logs" / "proactive.jsonl")
                if settings.proactive_sender == "log"
                else NullSender()
            )
        proactive_service = ProactiveService(
            proactive_store,
            provider,
            memory_service,
            proactive_sender,
            settings,
            personality_store,
            audit,
        )
        proactive_stop = asyncio.Event()
        proactive_task = asyncio.create_task(proactive_service.run_forever(proactive_stop))
        task_store = TaskStore(engine)
        delegate_providers: dict[str, DelegateProvider] = {
            "codex": CodexAdapter(settings.codex_command, settings.codex_timeout_s),
        }
        hermes_adapter: ManagedHermesGatewayAdapter | None = None
        if settings.hermes_enabled:
            hermes_process = HermesProcessManager(
                settings.hermes_gateway_url,
                settings.hermes_command,
                lambda: credential_store.get(
                    settings.keychain_service, settings.deepseek_api_key_account
                ),
                settings.hermes_startup_timeout_s,
                settings.hermes_managed,
                settings.hermes_inference_base_url,
            )
            hermes_adapter = ManagedHermesGatewayAdapter(
                hermes_process,
                approvals,
                base_url=settings.hermes_gateway_url,
                provider=settings.hermes_provider,
                model=settings.hermes_model,
                timeout_s=settings.codex_timeout_s,
            )
            delegate_providers["hermes"] = hermes_adapter
        delegate_manager = DelegateManager(
            task_store,
            delegate_providers,
        )
        llm_router = OllamaRoutingRouter(provider, allow_hermes=settings.hermes_enabled)
        router = RoutingEngine(
            rule_router=RuleRouter(allow_hermes=settings.hermes_enabled),
            llm_router=llm_router,
        )
        chat_service = create_chat_service(
            store,
            provider,
            settings,
            memory_service,
            router,
            delegate_manager,
            proactive_service,
            tool_registry,
            tool_executor,
            approvals,
            pending_tools,
            policy,
            onebot_sender,
            prompt_compiler,
            personality_store,
            sticker_catalog,
        )
        channel_sessions = ChannelSessionStore(engine, store)
        onebot_adapter = OneBotAdapter(
            settings,
            store,
            channel_sessions,
            chat_service,
            approvals,
            onebot_sender,
            personality_store,
            sticker_catalog,
            audit,
        )
        _app.state.engine = engine
        _app.state.settings = settings
        _app.state.credentials = credential_store
        _app.state.extractor = extractor
        _app.state.llm_router = llm_router
        _app.state.onebot_sender = onebot_sender
        _app.state.sticker_catalog = sticker_catalog
        _app.state.store = store
        _app.state.memory_service = memory_service
        _app.state.personality_store = personality_store
        _app.state.prompt_compiler = prompt_compiler
        _app.state.approvals = approvals
        _app.state.audit = audit
        _app.state.policy = policy
        _app.state.tool_registry = tool_registry
        _app.state.tool_executor = tool_executor
        _app.state.pending_tools = pending_tools
        _app.state.proactive_service = proactive_service
        _app.state.task_store = task_store
        _app.state.delegate_manager = delegate_manager
        _app.state.channel_sessions = channel_sessions
        _app.state.onebot_adapter = onebot_adapter
        _app.state.chat_service = chat_service
        yield
        proactive_stop.set()
        if hermes_adapter is not None:
            await hermes_adapter.close()
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
        personalities: PersonalityStore = app.state.personality_store
        character_id = payload.character_id or personalities.default_character_id()
        persona_id = payload.persona_id or personalities.default_persona_id()
        try:
            character = personalities.get_character(character_id)
            persona = personalities.get_persona()
        except PersonalityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="角色或 Persona 不存在") from exc
        greetings = [character.card.data.first_mes, *character.card.data.alternate_greetings]
        greeting: str | None = None
        if payload.greeting_index is not None:
            if payload.greeting_index >= len(greetings):
                raise HTTPException(status_code=400, detail="开场消息索引越界")
            greeting = greetings[payload.greeting_index]
        return store.create_session(
            payload.title,
            character_id=character_id,
            persona_id=persona_id or persona.id,
            greeting=greeting,
        )

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
        pending = app.state.pending_tools.get_by_code(code)
        if pending is not None:
            events = await app.state.chat_service.resume_approval(
                code, ChannelContext(channel="web")
            )
            final = events[-1] if events else ChatEvent(type="error", message="审批恢复无结果")
            return {
                "ok": final.type != "error",
                "reason": final.message or final.text or "已执行",
                "scope": "once",
                "execution_status": "succeeded" if final.type != "error" else "failed",
                "message_id": final.message_id,
            }
        pending_items = [item for item in service.list_pending() if item.code == code]
        if pending_items and pending_items[0].tool_name == "delegate.hermes.action":
            hermes = app.state.delegate_manager.providers().get("hermes")
            responder = getattr(hermes, "respond_approval", None)
            ok = bool(responder and await responder(code, True))
            return {
                "ok": ok,
                "reason": "已批准并恢复 Hermes" if ok else "Hermes 审批无法恢复",
                "scope": "once",
                "execution_status": "running" if ok else "failed",
                "message_id": None,
            }
        scope = pending_items[0].scope if pending_items else "once"
        resolution = service.resolve_once(code, session_id=payload.session_id, expected_scope=scope)
        return {"ok": resolution.ok, "reason": resolution.reason, "scope": resolution.scope}

    @app.post("/api/v1/approvals/{code}/reject")
    async def reject_request(code: str) -> dict[str, object]:
        service: ApprovalService = app.state.approvals
        pending = app.state.pending_tools.get_by_code(code)
        if pending is not None:
            reason = await app.state.chat_service.reject_approval(
                code, ChannelContext(channel="web")
            )
            return {"ok": reason == "已拒绝", "reason": reason}
        pending_items = [item for item in service.list_pending() if item.code == code]
        if pending_items and pending_items[0].tool_name == "delegate.hermes.action":
            hermes = app.state.delegate_manager.providers().get("hermes")
            responder = getattr(hermes, "respond_approval", None)
            ok = bool(responder and await responder(code, False))
            return {"ok": ok, "reason": "已拒绝 Hermes 操作" if ok else "拒绝失败"}
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
        status = service.status()
        target = settings.qq_owner_ids[0] if settings.qq_owner_ids else None
        if settings.proactive_sender == "qq":
            onebot_reachable = (
                await asyncio.to_thread(app.state.onebot_sender.health)
                if settings.qq_enabled and target
                else False
            )
            available = bool(settings.qq_enabled and target and onebot_reachable)
            delivery = ProactiveDelivery(
                configured_sender="qq",
                active_sender="qq" if available else "unavailable",
                target_user_id=target,
                onebot_reachable=onebot_reachable,
                available=available,
                reason="" if available else "需要启用 QQ、配置 owner_ids 并确保 OneBot 已登录",
            )
        elif settings.proactive_sender == "log":
            delivery = ProactiveDelivery(
                configured_sender="log",
                active_sender="log",
                target_user_id=None,
                onebot_reachable=None,
                available=True,
                reason="仅写入本地最小审计日志",
            )
        else:
            delivery = ProactiveDelivery(
                configured_sender="none",
                active_sender="none",
                target_user_id=None,
                onebot_reachable=None,
                available=True,
                reason="主动消息发送已关闭",
            )
        return status.model_copy(update={"delivery": delivery})

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
        provider_name = settings.model_provider
        api_key_configured = False
        if provider_name == "openai":
            try:
                api_key_configured = bool(
                    app.state.credentials.get(
                        settings.keychain_service, settings.openai_api_key_account
                    )
                )
            except KeychainError:
                api_key_configured = False
        return {
            "provider": provider_name,
            "providers": list(_MODEL_PROVIDERS),
            "model_name": getattr(provider, "model", settings.model_name),
            "base_url": getattr(
                provider,
                "base_url",
                settings.openai_base_url if provider_name == "openai" else settings.ollama_base_url,
            ),
            "api_key_account": settings.openai_api_key_account,
            "api_key_configured": api_key_configured,
            "ollama_keep_alive": keep_alive,
            "options": list(_MODEL_KEEP_ALIVE_OPTIONS),
            "tokenizer_path": str(settings.model_tokenizer_path or ""),
            "tokenizer_available": app.state.prompt_compiler.tokenizer_available,
            "context_tokens": settings.model_context_tokens,
        }

    @app.put("/api/v1/model/config")
    async def update_model_config(payload: ModelKeepAliveUpdate) -> dict[str, object]:
        if payload.keep_alive not in _MODEL_KEEP_ALIVE_OPTIONS:
            allowed = ", ".join(_MODEL_KEEP_ALIVE_OPTIONS)
            raise HTTPException(status_code=400, detail=f"keep_alive 仅支持：{allowed}")
        provider = app.state.chat_service.provider
        if isinstance(provider, OllamaProvider):
            provider.keep_alive = payload.keep_alive
        settings.ollama_keep_alive = payload.keep_alive

        _persist_config_values({"ollama_keep_alive": payload.keep_alive})
        return {"ollama_keep_alive": payload.keep_alive, "persisted": True}

    @app.put("/api/v1/model/provider")
    async def update_model_provider(payload: ModelProviderUpdate) -> dict[str, object]:
        base_url = _validate_model_base_url(payload.base_url)
        model_name = payload.model_name.strip()
        if not model_name:
            raise HTTPException(status_code=400, detail="模型名称不能为空")

        credentials = app.state.credentials
        supplied_key = payload.api_key.strip() if payload.api_key is not None else ""
        if payload.provider == "openai":
            try:
                configured_key = credentials.get(
                    settings.keychain_service, settings.openai_api_key_account
                )
            except KeychainError as exc:
                raise HTTPException(status_code=500, detail="无法读取 macOS Keychain") from exc
            if not supplied_key and not configured_key:
                raise HTTPException(status_code=400, detail="云端 Provider 未配置 API Key")
            if supplied_key:
                try:
                    credentials.set(
                        settings.keychain_service, settings.openai_api_key_account, supplied_key
                    )
                except KeychainError as exc:
                    raise HTTPException(status_code=500, detail="无法写入 macOS Keychain") from exc

        next_settings = settings.model_copy(
            update={
                "model_provider": payload.provider,
                "model_name": model_name,
                "ollama_base_url": base_url
                if payload.provider == "ollama"
                else settings.ollama_base_url,
                "openai_base_url": base_url
                if payload.provider == "openai"
                else settings.openai_base_url,
            }
        )
        next_provider = _build_model_provider(next_settings, credentials)
        _persist_config_values(
            {
                "model_provider": payload.provider,
                "model_name": model_name,
                "ollama_base_url": base_url
                if payload.provider == "ollama"
                else settings.ollama_base_url,
                "openai_base_url": base_url
                if payload.provider == "openai"
                else settings.openai_base_url,
            }
        )

        settings.model_provider = next_settings.model_provider
        settings.model_name = next_settings.model_name
        settings.ollama_base_url = next_settings.ollama_base_url
        settings.openai_base_url = next_settings.openai_base_url
        app.state.chat_service.set_provider(next_provider)
        app.state.llm_router.set_provider(next_provider)
        app.state.proactive_service.set_provider(next_provider)
        extractor = app.state.extractor
        set_extractor_provider = getattr(extractor, "set_provider", None)
        if callable(set_extractor_provider):
            set_extractor_provider(next_provider)
        return {
            "provider": settings.model_provider,
            "model_name": settings.model_name,
            "base_url": base_url,
            "api_key_configured": bool(
                payload.provider == "openai"
                and credentials.get(settings.keychain_service, settings.openai_api_key_account)
            ),
            "persisted": True,
        }

    @app.post("/api/v1/model/models")
    async def list_model_names(payload: ModelListRequest) -> dict[str, object]:
        """Query available models without changing the active Provider configuration."""
        base_url = _validate_model_base_url(payload.base_url)
        credentials = app.state.credentials
        supplied_key = payload.api_key.strip() if payload.api_key is not None else ""
        if payload.provider == "openai":
            if not supplied_key:
                try:
                    supplied_key = (
                        credentials.get(settings.keychain_service, settings.openai_api_key_account)
                        or ""
                    )
                except KeychainError as exc:
                    raise HTTPException(status_code=500, detail="无法读取 macOS Keychain") from exc
            if not supplied_key:
                raise HTTPException(status_code=400, detail="云端 Provider 未配置 API Key")
            provider: OllamaProvider | OpenAIProvider = OpenAIProvider(
                base_url=base_url,
                model=settings.model_name,
                api_key=supplied_key,
                timeout_s=settings.openai_timeout_s,
                max_output_tokens=settings.model_max_output_tokens,
            )
        else:
            provider = OllamaProvider(
                base_url=base_url,
                model=settings.model_name,
                max_output_tokens=settings.model_max_output_tokens,
                keep_alive=settings.ollama_keep_alive,
            )
        try:
            models = await provider.list_models()
        except ModelProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"provider": payload.provider, "models": models}

    @app.post("/api/v1/service/restart", status_code=202)
    async def restart_service() -> dict[str, object]:
        if os.environ.get("XPC_SERVICE_NAME") != _LAUNCHD_SERVICE_LABEL:
            raise HTTPException(status_code=409, detail="WhiteNight 当前不是由 launchd 管理")
        target = f"gui/{os.getuid()}/{_LAUNCHD_SERVICE_LABEL}"

        async def kickstart() -> None:
            await asyncio.sleep(0.2)
            process = await asyncio.create_subprocess_exec(
                "/bin/launchctl",
                "kickstart",
                "-k",
                target,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()

        app.state.restart_task = asyncio.create_task(kickstart())
        return {"accepted": True, "service": _LAUNCHD_SERVICE_LABEL}

    @app.put("/api/v1/model/tokenizer")
    async def update_tokenizer(payload: TokenizerPathUpdate) -> dict[str, object]:
        path = Path(payload.path).expanduser().resolve()
        if not path.is_file() or path.name != "tokenizer.json":
            raise HTTPException(status_code=400, detail="请选择存在的 tokenizer.json 文件")
        try:
            counter = build_token_counter(path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"tokenizer.json 无法加载：{exc}") from exc
        settings.model_tokenizer_path = path
        app.state.prompt_compiler.set_token_counter(counter)
        config_path = Path(os.environ.get("WHITENIGHT_CONFIG", str(DEFAULT_CONFIG_PATH)))
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {}
        if config_path.exists():
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise HTTPException(status_code=500, detail="配置文件格式损坏")
            data = loaded
            backup = config_path.with_suffix(f".bak-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}")
            shutil.copy2(config_path, backup)
        data["model_tokenizer_path"] = str(path)
        config_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=True), encoding="utf-8"
        )
        return {"path": str(path), "available": counter.available, "persisted": True}

    # ---- 角色、Persona、世界书与 Prompt 编排 --------------------------

    @app.get("/api/v1/characters")
    async def list_characters(include_archived: bool = False) -> list[dict[str, object]]:
        service: PersonalityStore = app.state.personality_store
        return [item.model_dump(mode="json") for item in service.list_characters(include_archived)]

    @app.post("/api/v1/characters/import")
    async def import_character(payload: CharacterImport) -> dict[str, object]:
        service: PersonalityStore = app.state.personality_store
        avatar_path = None
        if payload.avatar_data_url:
            avatar_path, _mime = save_image_data_url(
                payload.avatar_data_url,
                settings.data_dir / "characters",
                settings.max_image_bytes,
            )
        character = service.create_character(payload.card, avatar_path=avatar_path)
        embedded = _embedded_lorebook(payload.card)
        if embedded is not None:
            lorebook = service.create_lorebook(embedded)
            service.attach_lorebook(character.id, lorebook.id)
        return character.model_dump(mode="json")

    @app.get("/api/v1/characters/{character_id}")
    async def get_character(character_id: str) -> dict[str, object]:
        service: PersonalityStore = app.state.personality_store
        try:
            return service.get_character(character_id).model_dump(mode="json")
        except PersonalityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="角色不存在") from exc

    @app.put("/api/v1/characters/{character_id}")
    async def update_character(character_id: str, card: CharacterCard) -> dict[str, object]:
        service: PersonalityStore = app.state.personality_store
        try:
            return service.update_character(character_id, card).model_dump(mode="json")
        except PersonalityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="角色不存在") from exc

    @app.post("/api/v1/characters/{character_id}/archive", status_code=204)
    async def archive_character(character_id: str) -> None:
        service: PersonalityStore = app.state.personality_store
        try:
            service.archive_character(character_id)
        except PersonalityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="角色不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v1/characters/{character_id}/revisions")
    async def character_revisions(character_id: str) -> list[dict[str, object]]:
        service: PersonalityStore = app.state.personality_store
        return service.list_character_revisions(character_id)

    @app.post("/api/v1/characters/{character_id}/revisions/{revision_id}/restore")
    async def restore_character_revision(character_id: str, revision_id: str) -> dict[str, object]:
        service: PersonalityStore = app.state.personality_store
        try:
            return service.restore_character_revision(character_id, revision_id).model_dump(
                mode="json"
            )
        except PersonalityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="角色修订不存在") from exc

    @app.get("/api/v1/characters/{character_id}/export")
    async def export_character(character_id: str) -> dict[str, object]:
        service: PersonalityStore = app.state.personality_store
        try:
            character = service.get_character(character_id)
        except PersonalityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="角色不存在") from exc
        avatar = None
        if character.avatar_path:
            suffix = Path(character.avatar_path).suffix.lower()
            mime = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }.get(suffix)
            if mime:
                avatar = image_path_to_data_url(
                    settings.data_dir / "characters", character.avatar_path, mime
                )
        return {"card": character.card.model_dump(mode="json"), "avatar_data_url": avatar}

    @app.get("/api/v1/persona")
    async def get_persona() -> dict[str, object]:
        service: PersonalityStore = app.state.personality_store
        return service.get_persona().model_dump(mode="json")

    @app.put("/api/v1/persona")
    async def update_persona(payload: PersonaUpdate) -> dict[str, object]:
        service: PersonalityStore = app.state.personality_store
        return service.update_persona(payload.name, payload.description).model_dump(mode="json")

    @app.get("/api/v1/persona/revisions")
    async def persona_revisions() -> list[dict[str, object]]:
        service: PersonalityStore = app.state.personality_store
        return service.list_persona_revisions()

    @app.post("/api/v1/persona/revisions/{revision_id}/restore")
    async def restore_persona_revision(revision_id: str) -> dict[str, object]:
        service: PersonalityStore = app.state.personality_store
        try:
            return service.restore_persona_revision(revision_id).model_dump(mode="json")
        except PersonalityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Persona 修订不存在") from exc

    @app.get("/api/v1/prompt-profiles/{character_id}")
    async def get_prompt_profile(character_id: str) -> dict[str, object]:
        service: PersonalityStore = app.state.personality_store
        try:
            return service.get_prompt_profile(character_id).model_dump(mode="json")
        except PersonalityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Prompt 配置不存在") from exc

    @app.put("/api/v1/prompt-profiles/{character_id}")
    async def update_prompt_profile(
        character_id: str, payload: PromptProfileUpdate
    ) -> dict[str, object]:
        if any(block.id in {"kernel", "runtime"} for block in payload.blocks):
            raise HTTPException(status_code=400, detail="固定安全模块不能由自定义 Prompt 覆盖")
        service: PersonalityStore = app.state.personality_store
        try:
            return service.update_prompt_profile(character_id, payload.blocks).model_dump(
                mode="json"
            )
        except PersonalityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Prompt 配置不存在") from exc

    @app.get("/api/v1/prompt-profiles/{character_id}/revisions")
    async def prompt_profile_revisions(character_id: str) -> list[dict[str, object]]:
        service: PersonalityStore = app.state.personality_store
        return service.list_prompt_revisions(character_id)

    @app.post("/api/v1/prompt-profiles/{character_id}/revisions/{revision_id}/restore")
    async def restore_prompt_profile_revision(
        character_id: str, revision_id: str
    ) -> dict[str, object]:
        service: PersonalityStore = app.state.personality_store
        try:
            return service.restore_prompt_revision(character_id, revision_id).model_dump(
                mode="json"
            )
        except PersonalityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Prompt 修订不存在") from exc

    @app.get("/api/v1/lorebooks")
    async def list_lorebooks(include_archived: bool = False) -> list[dict[str, object]]:
        service: PersonalityStore = app.state.personality_store
        return [item.model_dump(mode="json") for item in service.list_lorebooks(include_archived)]

    @app.post("/api/v1/lorebooks")
    async def create_lorebook(payload: LorebookCreate) -> dict[str, object]:
        service: PersonalityStore = app.state.personality_store
        result = service.create_lorebook(payload.data, payload.globally_enabled)
        if payload.character_id:
            service.attach_lorebook(payload.character_id, result.id)
        return result.model_dump(mode="json")

    @app.put("/api/v1/lorebooks/{lorebook_id}")
    async def update_lorebook(lorebook_id: str, data: LorebookData) -> dict[str, object]:
        service: PersonalityStore = app.state.personality_store
        try:
            return service.update_lorebook(lorebook_id, data).model_dump(mode="json")
        except PersonalityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="世界书不存在") from exc

    @app.post("/api/v1/lorebooks/{lorebook_id}/archive", status_code=204)
    async def archive_lorebook(lorebook_id: str) -> None:
        service: PersonalityStore = app.state.personality_store
        try:
            service.archive_lorebook(lorebook_id)
        except PersonalityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="世界书不存在") from exc

    @app.get("/api/v1/lorebooks/{lorebook_id}/revisions")
    async def lorebook_revisions(lorebook_id: str) -> list[dict[str, object]]:
        service: PersonalityStore = app.state.personality_store
        return service.list_lorebook_revisions(lorebook_id)

    @app.post("/api/v1/lorebooks/{lorebook_id}/revisions/{revision_id}/restore")
    async def restore_lorebook_revision(lorebook_id: str, revision_id: str) -> dict[str, object]:
        service: PersonalityStore = app.state.personality_store
        try:
            return service.restore_lorebook_revision(lorebook_id, revision_id).model_dump(
                mode="json"
            )
        except PersonalityNotFoundError as exc:
            raise HTTPException(status_code=404, detail="世界书修订不存在") from exc

    @app.post("/api/v1/sessions/{session_id}/prompt-preview")
    async def prompt_preview(session_id: str, payload: PromptPreviewRequest) -> dict[str, object]:
        store: SessionStore = app.state.store
        history = store.list_messages(session_id)
        if payload.text:
            history.append(
                MessageRecord(
                    id="preview",
                    session_id=session_id,
                    sequence=max((item.sequence for item in history), default=0) + 1,
                    role="user",
                    content=payload.text,
                    created_at=datetime.now(UTC),
                )
            )
        compiler: PromptCompiler = app.state.prompt_compiler
        _messages, preview, _trace = compiler.compile(
            session_id, history, payload.text, persist_trace=False
        )
        return preview.model_dump(mode="json")

    @app.get("/api/v1/generation-traces")
    async def generation_traces(session_id: str, limit: int = 20) -> list[dict[str, object]]:
        service: PersonalityStore = app.state.personality_store
        return service.list_traces(session_id, min(max(limit, 1), 100))

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
        if not settings.hermes_enabled:
            delegate_status["hermes"] = {
                "enabled": False,
                "status": "disabled",
                "reason": "Hermes delegation is disabled by configuration",
            }
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
                "health": await asyncio.to_thread(app.state.onebot_sender.health_detail),
                "stickers": {
                    "configured": bool(
                        getattr(app.state, "sticker_catalog", None)
                        and app.state.sticker_catalog.records(native_only=True)
                    ),
                    "native_ready": len(app.state.sticker_catalog.records(native_only=True))
                    if getattr(app.state, "sticker_catalog", None)
                    else 0,
                },
            },
        }

    # ---- 长期记忆（阶段 4） --------------------------------------------

    @app.get("/api/v1/memory/facts", response_model=list[FactRecord])
    async def list_facts(character_id: str | None = None) -> list[FactRecord]:
        memory: MemoryService = app.state.memory_service
        personalities: PersonalityStore = app.state.personality_store
        return memory.list_facts(character_id or personalities.default_character_id())

    @app.post("/api/v1/memory/facts", response_model=FactRecord)
    async def upsert_fact(payload: FactUpsert) -> FactRecord:
        memory: MemoryService = app.state.memory_service
        if payload.character_id is None:
            payload = payload.model_copy(
                update={"character_id": app.state.personality_store.default_character_id()}
            )
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
    async def list_episodes(character_id: str | None = None) -> list[EpisodeRecord]:
        memory: MemoryService = app.state.memory_service
        personalities: PersonalityStore = app.state.personality_store
        return memory.list_episodes(character_id or personalities.default_character_id())

    @app.post("/api/v1/memory/episodes", response_model=EpisodeRecord)
    async def add_episode(payload: EpisodeCreate) -> EpisodeRecord:
        memory: MemoryService = app.state.memory_service
        if payload.character_id is None:
            payload = payload.model_copy(
                update={"character_id": app.state.personality_store.default_character_id()}
            )
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
        character_id, _persona_id = app.state.personality_store.session_identity(payload.session_id)
        return await memory.extract_and_store(
            messages, payload.session_id, character_id=character_id
        )

    @app.get("/api/v1/memory/retrieve", response_model=list[MemoryHit])
    async def retrieve_memory(
        query: str = Query(min_length=1, max_length=200),
        limit: int = Query(default=8, ge=1, le=20),
        character_id: str | None = None,
    ) -> list[MemoryHit]:
        memory: MemoryService = app.state.memory_service
        personalities: PersonalityStore = app.state.personality_store
        return memory.retrieve(
            query,
            limit=limit,
            character_id=character_id or personalities.default_character_id(),
        )

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
            "health": await asyncio.to_thread(app.state.onebot_sender.health_detail),
            "stickers": {
                "configured": bool(
                    getattr(app.state, "sticker_catalog", None)
                    and app.state.sticker_catalog.records(native_only=True)
                ),
                "native_ready": len(app.state.sticker_catalog.records(native_only=True))
                if getattr(app.state, "sticker_catalog", None)
                else 0,
            },
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
