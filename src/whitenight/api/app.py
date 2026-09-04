"""FastAPI 应用工厂：会话 CRUD、WebSocket 流式聊天与运行状态。

首版 API 只监听 127.0.0.1；所有入口共用同一会话存储与 Agent 服务。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError

from whitenight import __version__
from whitenight.agent.service import ChatService
from whitenight.api.boundary import LocalBoundaryMiddleware
from whitenight.api.memory_routes import register_memory_routes
from whitenight.api.personality_routes import register_personality_routes
from whitenight.api.resources import resource_router
from whitenight.api.schemas import (
    ApprovalAction,
    ModelKeepAliveUpdate,
    ModelListRequest,
    ModelProviderUpdate,
    SessionRename,
    TokenizerPathUpdate,
)
from whitenight.application.configuration import ModelConfigurationService, _persist_config_values
from whitenight.application.configuration import _build_memory_extractor as _build_memory_extractor
from whitenight.application.health import monitor_snapshot
from whitenight.application.runtime import runtime_lifespan
from whitenight.channels.onebot import OneBotAdapter
from whitenight.channels.types import (
    ChannelContext,
    ChatEvent,
    ChatRequest,
    MessageRecord,
    SessionCreate,
    SessionSummary,
)
from whitenight.config import ConfigError, Settings, load_settings
from whitenight.credentials.keychain import KeychainError
from whitenight.delegates.manager import DelegateManager, TaskRecord, TaskStore
from whitenight.memory import (
    MemoryExtractor,
)
from whitenight.models.base import ModelProvider, ModelProviderError
from whitenight.models.ollama import OllamaProvider
from whitenight.models.openai import OpenAIProvider
from whitenight.personality.store import PersonalityNotFoundError, PersonalityStore
from whitenight.personality.token_counter import build_token_counter
from whitenight.policy.approvals import ApprovalService, SessionGrantRecord
from whitenight.policy.audit import AuditService
from whitenight.policy.engine import PolicyEngine
from whitenight.scheduler import ProactiveService
from whitenight.scheduler.types import (
    PauseRequest,
    ProactiveConfig,
    ProactiveDelivery,
    ProactiveStatus,
)
from whitenight.storage.engine import backend_of, ping
from whitenight.storage.sessions import SessionNotFoundError, SessionStore

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


def create_app(
    settings: Settings | None = None,
    model_provider: ModelProvider | None = None,
    memory_extractor: MemoryExtractor | None = None,
) -> FastAPI:
    """构建应用。测试可注入临时 Settings、Fake Provider 与记忆提取器。"""
    settings = settings or load_settings()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lambda app: runtime_lifespan(app, settings, model_provider, memory_extractor),
    )

    @app.exception_handler(ConfigError)
    async def config_error(_request: Request, _error: ConfigError) -> JSONResponse:
        return JSONResponse({"detail": "配置更新失败，请检查本地配置与诊断记录"}, status_code=500)

    app.state.settings = settings
    app.include_router(resource_router(settings))

    # 首版 WebUI 与本 API 同源开发；即使启用 CORS 也仅允许本机回环地址。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        LocalBoundaryMiddleware,
        allowed_origins=settings.web_origins,
        testing=settings.app_env == "test",
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
            model_status = {"error_type": type(exc).__name__, "ok": False}
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
            "monitor": await monitor_snapshot(app.state.task_store),
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
                code,
                ChannelContext(channel="web"),
                grant_scope=payload.scope,
            )
            final = events[-1] if events else ChatEvent(type="error", message="审批恢复无结果")
            return {
                "ok": final.type != "error",
                "reason": final.message or final.text or "已执行",
                "scope": payload.scope,
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
        resolution = service.resolve_once(
            code,
            session_id=payload.session_id,
            expected_scope=scope,
            grant_scope=payload.scope,
            channel="web",
        )
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
        _persist_config_values({"ollama_keep_alive": payload.keep_alive})
        provider = app.state.chat_service.provider
        if isinstance(provider, OllamaProvider):
            provider.keep_alive = payload.keep_alive
        settings.ollama_keep_alive = payload.keep_alive

        return {"ollama_keep_alive": payload.keep_alive, "persisted": True}

    @app.put("/api/v1/model/provider")
    async def update_model_provider(payload: ModelProviderUpdate) -> dict[str, object]:
        base_url = _validate_model_base_url(payload.base_url)
        try:
            configuration: ModelConfigurationService = app.state.model_configuration
            return configuration.update(
                payload.provider, payload.model_name, base_url, payload.api_key
            )
        except ConfigError as exc:
            raise HTTPException(400, str(exc)) from exc
        except KeychainError as exc:
            raise HTTPException(500, "无法访问 macOS Keychain") from exc

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
        _persist_config_values({"model_tokenizer_path": str(path)})
        settings.model_tokenizer_path = path
        app.state.prompt_compiler.set_token_counter(counter)
        return {"path": str(path), "available": counter.available, "persisted": True}

    # ---- 角色、Persona、世界书与 Prompt 编排 --------------------------

    register_personality_routes(app, settings)

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

    register_memory_routes(app, settings)

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

    @app.post("/api/v1/tasks/{task_id}/retry", response_model=TaskRecord, status_code=202)
    async def retry_task(task_id: str) -> TaskRecord:
        store: TaskStore = app.state.task_store
        try:
            previous = store.get(task_id)
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc
        if previous.status != "failed" or previous.risk != "read_only":
            raise HTTPException(409, "仅已明确失败的只读任务可重试；其他任务需先核验执行结果")
        record = store.create(
            executor=previous.executor,
            category=previous.category,
            risk=previous.risk,
            prompt=previous.prompt,
            session_id=previous.session_id,
            cwd=previous.cwd,
        )

        async def run() -> None:
            async for _event in app.state.delegate_manager.run(
                executor=record.executor,
                category=record.category,
                risk=record.risk,
                prompt=record.prompt,
                session_id=record.session_id,
                cwd=record.cwd,
                task_id=record.id,
            ):
                pass

        task = asyncio.create_task(run())
        app.state.control_tasks.add(task)
        task.add_done_callback(app.state.control_tasks.discard)
        return record

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

    @app.post("/api/v1/chat/{request_id}/cancel")
    async def cancel_chat(request_id: str) -> dict[str, object]:
        cancelled = await app.state.chat_service.conversations.cancel(request_id)
        return {"ok": cancelled, "status": "aborted" if cancelled else "not_running"}

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
