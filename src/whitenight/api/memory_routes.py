"""memory HTTP adapters; all state is owned by application services."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse

from whitenight.api.schemas import (
    ExtractRequest,
    ResolveRequest,
)
from whitenight.application.configuration import _build_memory_extractor as _build_memory_extractor
from whitenight.config import Settings
from whitenight.memory import (
    MemoryService,
)
from whitenight.memory.types import (
    EpisodeCreate,
    EpisodeRecord,
    FactRecord,
    FactUpdate,
    FactUpsert,
    MemoryHit,
)
from whitenight.personality.store import PersonalityStore
from whitenight.storage.sessions import SessionStore


def register_memory_routes(app: FastAPI, settings: Settings) -> None:
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
        return await memory.aretrieve(
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
