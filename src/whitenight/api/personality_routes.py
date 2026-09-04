"""personality HTTP adapters; all state is owned by application services."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException

from whitenight.api.schemas import (
    CharacterImport,
    LorebookCreate,
    PersonaUpdate,
    PromptPreviewRequest,
    PromptProfileUpdate,
)
from whitenight.application.configuration import _build_memory_extractor as _build_memory_extractor
from whitenight.channels.types import (
    MessageRecord,
)
from whitenight.config import Settings
from whitenight.personality.compiler import PromptCompiler
from whitenight.personality.store import PersonalityNotFoundError, PersonalityStore
from whitenight.personality.types import CharacterCard, LorebookData
from whitenight.storage.attachments import image_path_to_data_url, save_image_data_url
from whitenight.storage.sessions import SessionStore


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


def register_personality_routes(app: FastAPI, settings: Settings) -> None:
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
