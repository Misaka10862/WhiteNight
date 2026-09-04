"""Composition root: adapters, application services, lifecycle and storage lock."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from whitenight.agent.service import create_chat_service
from whitenight.application.configuration import (
    ModelConfigurationService,
    _build_memory_extractor,
    _build_model_provider,
)
from whitenight.channels.onebot import ChannelSessionStore, OneBotAdapter, OneBotSender
from whitenight.config import Settings
from whitenight.credentials.keychain import get_keychain
from whitenight.delegates.base import DelegateProvider
from whitenight.delegates.codex import CodexAdapter
from whitenight.delegates.hermes_ws import HermesProcessManager, ManagedHermesGatewayAdapter
from whitenight.delegates.manager import DelegateManager, TaskStore
from whitenight.logging_config import setup_logging
from whitenight.memory import (
    MemoryExtractor,
    MemoryService,
    MemoryStore,
    NullEmbeddingProvider,
    OllamaEmbeddingProvider,
)
from whitenight.models.base import ModelProvider
from whitenight.personality.compiler import PromptCompiler
from whitenight.personality.store import PersonalityStore
from whitenight.personality.token_counter import build_token_counter
from whitenight.policy.approvals import ApprovalService
from whitenight.policy.audit import AuditService
from whitenight.policy.engine import PolicyEngine
from whitenight.routing.engine import OllamaRoutingRouter, RoutingEngine
from whitenight.routing.rules import RuleRouter
from whitenight.scheduler import LogSender, NullSender, ProactiveService, ProactiveStore
from whitenight.stickers import StickerCatalog, StickerCatalogError
from whitenight.storage.backup import _require_clean_journal, recover_interrupted_restore
from whitenight.storage.engine import build_engine, resolve_database_key
from whitenight.storage.maintenance import MaintenanceLock
from whitenight.storage.migrate import upgrade_to_head
from whitenight.storage.sessions import SessionStore
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

logger = logging.getLogger(__name__)


@asynccontextmanager
async def runtime_lifespan(
    _app: FastAPI,
    settings: Settings,
    model_provider: ModelProvider | None = None,
    memory_extractor: MemoryExtractor | None = None,
) -> AsyncIterator[None]:
    with MaintenanceLock(settings, exclusive=settings.auto_migrate) as maintenance_lock:
        settings.ensure_dirs()
        if settings.auto_migrate:
            recover_interrupted_restore(settings, maintenance_lock=maintenance_lock)
            upgrade_to_head(settings, maintenance_lock=maintenance_lock)
        else:
            # A shared service lock cannot recover a half-installed generation.
            # Refuse startup before opening any database connections instead.
            _require_clean_journal(settings)
        setup_logging(
            level=settings.log_level,
            json_logs=settings.log_json,
            log_file=str(settings.data_dir / "logs" / "whitenight.log"),
        )
        if settings.auto_migrate:
            maintenance_lock.downgrade()
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

        def install_model(next_provider: ModelProvider, next_extractor: MemoryExtractor) -> None:
            chat_service.set_provider(next_provider)
            llm_router.set_provider(next_provider)
            proactive_service.set_provider(next_provider)
            memory_service._extractor = next_extractor
            _app.state.extractor = next_extractor

        _app.state.model_configuration = ModelConfigurationService(
            settings, credential_store, install_model
        )
        _app.state.control_tasks = set()
        chat_service.conversations.recover()
        chat_service.start()
        proactive_task = asyncio.create_task(proactive_service.run_forever(proactive_stop))
        try:
            yield
        finally:
            proactive_stop.set()
            for task in list(_app.state.control_tasks):
                task.cancel()
            await asyncio.gather(*_app.state.control_tasks, return_exceptions=True)
            await chat_service.close()
            if hermes_adapter is not None:
                await hermes_adapter.close()
            try:
                await asyncio.wait_for(proactive_task, timeout=10)
            except TimeoutError:
                proactive_task.cancel()
                await asyncio.gather(proactive_task, return_exceptions=True)
            engine.dispose()
