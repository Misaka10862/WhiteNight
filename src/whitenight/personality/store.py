"""Persistence for characters, persona, prompt profiles, lorebooks and traces."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session as OrmSession

from whitenight.personality.types import (
    CharacterCard,
    CharacterRecord,
    LorebookData,
    LorebookRecord,
    PersonaRecord,
    PromptBlock,
    PromptProfileRecord,
)
from whitenight.storage.models import (
    AppMeta,
    CharacterLorebook,
    CharacterProfile,
    CharacterRevision,
    GenerationTrace,
    Lorebook,
    LorebookRevision,
    PersonaProfile,
    PersonaRevision,
    PromptProfile,
    PromptProfileRevision,
    Session,
    SessionLorebook,
    WorldEffectState,
)


class PersonalityNotFoundError(KeyError):
    pass


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class PersonalityStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def _orm(self) -> OrmSession:
        return OrmSession(self._engine, expire_on_commit=False)

    def default_character_id(self) -> str:
        return self._meta("default_character_id")

    def default_persona_id(self) -> str:
        return self._meta("default_persona_id")

    def session_identity(self, session_id: str) -> tuple[str, str]:
        with self._orm() as orm:
            row = orm.get(Session, session_id)
            if row is None:
                raise PersonalityNotFoundError(session_id)
            return (
                row.character_id or self.default_character_id(),
                row.persona_id or self.default_persona_id(),
            )

    def _meta(self, key: str) -> str:
        with self._orm() as orm:
            row = orm.get(AppMeta, key)
            if row is None:
                raise PersonalityNotFoundError(key)
            return row.value

    def list_characters(self, include_archived: bool = False) -> list[CharacterRecord]:
        with self._orm() as orm:
            query = select(CharacterProfile).order_by(
                CharacterProfile.is_default.desc(), CharacterProfile.name
            )
            rows = list(orm.scalars(query))
            if not include_archived:
                rows = [row for row in rows if row.archived_at is None]
            return [self._character_record(orm, row) for row in rows]

    def get_character(self, character_id: str) -> CharacterRecord:
        with self._orm() as orm:
            row = orm.get(CharacterProfile, character_id)
            if row is None:
                raise PersonalityNotFoundError(character_id)
            return self._character_record(orm, row)

    def find_character(self, name: str) -> CharacterRecord | None:
        folded = name.strip().casefold()
        return next(
            (item for item in self.list_characters() if item.name.casefold() == folded), None
        )

    def create_character(
        self, card: CharacterCard, avatar_path: str | None = None
    ) -> CharacterRecord:
        raw = stable_json(card.model_dump(mode="json"))
        with self._orm() as orm:
            profile = CharacterProfile(name=card.data.name, avatar_path=avatar_path)
            orm.add(profile)
            orm.flush()
            revision = CharacterRevision(
                character_id=profile.id,
                revision=1,
                card_json=raw,
                content_hash=content_hash(raw),
            )
            orm.add(revision)
            orm.flush()
            profile.active_revision_id = revision.id
            blocks = "[]"
            prompt_profile = PromptProfile(
                character_id=profile.id,
                blocks_json=blocks,
                content_hash=content_hash(blocks),
            )
            orm.add(prompt_profile)
            orm.flush()
            orm.add(
                PromptProfileRevision(
                    profile_id=prompt_profile.id,
                    revision=1,
                    blocks_json=blocks,
                    content_hash=content_hash(blocks),
                )
            )
            orm.commit()
            return self._character_record(orm, profile)

    def update_character(self, character_id: str, card: CharacterCard) -> CharacterRecord:
        raw = stable_json(card.model_dump(mode="json"))
        with self._orm() as orm:
            profile = orm.get(CharacterProfile, character_id)
            if profile is None:
                raise PersonalityNotFoundError(character_id)
            next_revision = (
                int(
                    orm.scalar(
                        select(func.max(CharacterRevision.revision)).where(
                            CharacterRevision.character_id == character_id
                        )
                    )
                    or 0
                )
                + 1
            )
            revision = CharacterRevision(
                character_id=character_id,
                revision=next_revision,
                card_json=raw,
                content_hash=content_hash(raw),
            )
            orm.add(revision)
            orm.flush()
            profile.name = card.data.name
            profile.active_revision_id = revision.id
            profile.updated_at = datetime.now(UTC)
            orm.commit()
            return self._character_record(orm, profile)

    def restore_character_revision(self, character_id: str, revision_id: str) -> CharacterRecord:
        with self._orm() as orm:
            profile = orm.get(CharacterProfile, character_id)
            revision = orm.get(CharacterRevision, revision_id)
            if profile is None or revision is None or revision.character_id != character_id:
                raise PersonalityNotFoundError(revision_id)
            profile.active_revision_id = revision.id
            profile.name = CharacterCard.model_validate_json(revision.card_json).data.name
            profile.updated_at = datetime.now(UTC)
            orm.commit()
            return self._character_record(orm, profile)

    def list_character_revisions(self, character_id: str) -> list[dict[str, Any]]:
        with self._orm() as orm:
            rows = orm.scalars(
                select(CharacterRevision)
                .where(CharacterRevision.character_id == character_id)
                .order_by(CharacterRevision.revision.desc())
            )
            return [
                {
                    "id": row.id,
                    "revision": row.revision,
                    "content_hash": row.content_hash,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def archive_character(self, character_id: str) -> None:
        with self._orm() as orm:
            row = orm.get(CharacterProfile, character_id)
            if row is None:
                raise PersonalityNotFoundError(character_id)
            if row.is_default:
                raise ValueError("默认角色不能归档")
            row.archived_at = datetime.now(UTC)
            orm.commit()

    def get_persona(self) -> PersonaRecord:
        with self._orm() as orm:
            row = orm.get(PersonaProfile, self.default_persona_id())
            if row is None:
                raise PersonalityNotFoundError("persona")
            return PersonaRecord(
                id=row.id,
                name=row.name,
                description=row.description,
                content_hash=row.content_hash,
                revision=row.revision,
            )

    def update_persona(self, name: str, description: str) -> PersonaRecord:
        with self._orm() as orm:
            row = orm.get(PersonaProfile, self.default_persona_id())
            if row is None:
                raise PersonalityNotFoundError("persona")
            row.name, row.description = name.strip(), description
            row.revision += 1
            row.content_hash = content_hash(f"{row.name}\n{description}")
            row.updated_at = datetime.now(UTC)
            orm.add(
                PersonaRevision(
                    persona_id=row.id,
                    revision=row.revision,
                    name=row.name,
                    description=row.description,
                    content_hash=row.content_hash,
                )
            )
            orm.commit()
            return PersonaRecord(
                id=row.id,
                name=row.name,
                description=row.description,
                content_hash=row.content_hash,
                revision=row.revision,
            )

    def list_persona_revisions(self) -> list[dict[str, Any]]:
        persona_id = self.default_persona_id()
        with self._orm() as orm:
            rows = orm.scalars(
                select(PersonaRevision)
                .where(PersonaRevision.persona_id == persona_id)
                .order_by(PersonaRevision.revision.desc())
            )
            return [
                {"id": row.id, "revision": row.revision, "content_hash": row.content_hash}
                for row in rows
            ]

    def restore_persona_revision(self, revision_id: str) -> PersonaRecord:
        with self._orm() as orm:
            revision = orm.get(PersonaRevision, revision_id)
            if revision is None or revision.persona_id != self.default_persona_id():
                raise PersonalityNotFoundError(revision_id)
            name, description = revision.name, revision.description
        return self.update_persona(name, description)

    def get_prompt_profile(self, character_id: str) -> PromptProfileRecord:
        with self._orm() as orm:
            row = orm.scalar(
                select(PromptProfile).where(PromptProfile.character_id == character_id)
            )
            if row is None:
                raise PersonalityNotFoundError(character_id)
            blocks = [PromptBlock.model_validate(item) for item in json.loads(row.blocks_json)]
            return PromptProfileRecord(
                id=row.id,
                character_id=character_id,
                revision=row.revision,
                blocks=blocks,
                content_hash=row.content_hash,
            )

    def update_prompt_profile(
        self, character_id: str, blocks: list[PromptBlock]
    ) -> PromptProfileRecord:
        raw = stable_json([block.model_dump(mode="json") for block in blocks])
        with self._orm() as orm:
            row = orm.scalar(
                select(PromptProfile).where(PromptProfile.character_id == character_id)
            )
            if row is None:
                raise PersonalityNotFoundError(character_id)
            row.blocks_json = raw
            row.content_hash = content_hash(raw)
            row.revision += 1
            row.updated_at = datetime.now(UTC)
            orm.add(
                PromptProfileRevision(
                    profile_id=row.id,
                    revision=row.revision,
                    blocks_json=raw,
                    content_hash=row.content_hash,
                )
            )
            orm.commit()
        return self.get_prompt_profile(character_id)

    def list_lorebooks(self, include_archived: bool = False) -> list[LorebookRecord]:
        with self._orm() as orm:
            rows = list(orm.scalars(select(Lorebook).order_by(Lorebook.name)))
            if not include_archived:
                rows = [row for row in rows if row.archived_at is None]
            return [self._lorebook_record(row) for row in rows]

    def get_lorebook(self, lorebook_id: str) -> LorebookRecord:
        with self._orm() as orm:
            row = orm.get(Lorebook, lorebook_id)
            if row is None:
                raise PersonalityNotFoundError(lorebook_id)
            return self._lorebook_record(row)

    def create_lorebook(self, data: LorebookData, globally_enabled: bool = False) -> LorebookRecord:
        raw = stable_json(data.model_dump(mode="json"))
        with self._orm() as orm:
            row = Lorebook(
                name=data.name,
                book_json=raw,
                content_hash=content_hash(raw),
                globally_enabled=int(globally_enabled),
            )
            orm.add(row)
            orm.flush()
            orm.add(
                LorebookRevision(
                    lorebook_id=row.id,
                    revision=1,
                    book_json=raw,
                    content_hash=row.content_hash,
                )
            )
            orm.commit()
            return self._lorebook_record(row)

    def update_lorebook(self, lorebook_id: str, data: LorebookData) -> LorebookRecord:
        raw = stable_json(data.model_dump(mode="json"))
        with self._orm() as orm:
            row = orm.get(Lorebook, lorebook_id)
            if row is None:
                raise PersonalityNotFoundError(lorebook_id)
            row.name, row.book_json = data.name, raw
            row.revision += 1
            row.content_hash = content_hash(raw)
            row.updated_at = datetime.now(UTC)
            orm.add(
                LorebookRevision(
                    lorebook_id=row.id,
                    revision=row.revision,
                    book_json=raw,
                    content_hash=row.content_hash,
                )
            )
            orm.commit()
            return self._lorebook_record(row)

    def list_prompt_revisions(self, character_id: str) -> list[dict[str, Any]]:
        with self._orm() as orm:
            profile = orm.scalar(
                select(PromptProfile).where(PromptProfile.character_id == character_id)
            )
            if profile is None:
                raise PersonalityNotFoundError(character_id)
            rows = orm.scalars(
                select(PromptProfileRevision)
                .where(PromptProfileRevision.profile_id == profile.id)
                .order_by(PromptProfileRevision.revision.desc())
            )
            return [
                {"id": row.id, "revision": row.revision, "content_hash": row.content_hash}
                for row in rows
            ]

    def restore_prompt_revision(self, character_id: str, revision_id: str) -> PromptProfileRecord:
        with self._orm() as orm:
            profile = orm.scalar(
                select(PromptProfile).where(PromptProfile.character_id == character_id)
            )
            revision = orm.get(PromptProfileRevision, revision_id)
            if profile is None or revision is None or revision.profile_id != profile.id:
                raise PersonalityNotFoundError(revision_id)
            blocks = [PromptBlock.model_validate(item) for item in json.loads(revision.blocks_json)]
        return self.update_prompt_profile(character_id, blocks)

    def list_lorebook_revisions(self, lorebook_id: str) -> list[dict[str, Any]]:
        with self._orm() as orm:
            rows = orm.scalars(
                select(LorebookRevision)
                .where(LorebookRevision.lorebook_id == lorebook_id)
                .order_by(LorebookRevision.revision.desc())
            )
            return [
                {"id": row.id, "revision": row.revision, "content_hash": row.content_hash}
                for row in rows
            ]

    def restore_lorebook_revision(self, lorebook_id: str, revision_id: str) -> LorebookRecord:
        with self._orm() as orm:
            revision = orm.get(LorebookRevision, revision_id)
            if revision is None or revision.lorebook_id != lorebook_id:
                raise PersonalityNotFoundError(revision_id)
            data = LorebookData.model_validate_json(revision.book_json)
        return self.update_lorebook(lorebook_id, data)

    def archive_lorebook(self, lorebook_id: str) -> None:
        with self._orm() as orm:
            row = orm.get(Lorebook, lorebook_id)
            if row is None:
                raise PersonalityNotFoundError(lorebook_id)
            row.archived_at = datetime.now(UTC)
            orm.commit()

    def attach_lorebook(self, character_id: str, lorebook_id: str) -> None:
        with self._orm() as orm:
            exists = orm.scalar(
                select(CharacterLorebook).where(
                    CharacterLorebook.character_id == character_id,
                    CharacterLorebook.lorebook_id == lorebook_id,
                )
            )
            if exists is None:
                orm.add(CharacterLorebook(character_id=character_id, lorebook_id=lorebook_id))
                orm.commit()

    def active_lorebooks(self, character_id: str, session_id: str) -> list[LorebookRecord]:
        with self._orm() as orm:
            attached = set(
                orm.scalars(
                    select(CharacterLorebook.lorebook_id).where(
                        CharacterLorebook.character_id == character_id
                    )
                )
            )
            attached.update(
                orm.scalars(
                    select(SessionLorebook.lorebook_id).where(
                        SessionLorebook.session_id == session_id
                    )
                )
            )
            rows = list(
                orm.scalars(
                    select(Lorebook).where(
                        Lorebook.archived_at.is_(None),
                        (Lorebook.globally_enabled == 1) | (Lorebook.id.in_(attached)),
                    )
                )
            )
            return [self._lorebook_record(row) for row in rows]

    def get_world_effects(self, session_id: str) -> dict[str, dict[str, int]]:
        with self._orm() as orm:
            rows = orm.scalars(
                select(WorldEffectState).where(WorldEffectState.session_id == session_id)
            )
            return {
                row.entry_key: {
                    "sticky_until": row.sticky_until,
                    "cooldown_until": row.cooldown_until,
                    "delayed_until": row.delayed_until,
                }
                for row in rows
            }

    def save_world_effect(self, session_id: str, entry_key: str, values: dict[str, int]) -> None:
        with self._orm() as orm:
            row = orm.scalar(
                select(WorldEffectState).where(
                    WorldEffectState.session_id == session_id,
                    WorldEffectState.entry_key == entry_key,
                )
            )
            if row is None:
                row = WorldEffectState(session_id=session_id, entry_key=entry_key)
                orm.add(row)
            row.sticky_until = values.get("sticky_until", 0)
            row.cooldown_until = values.get("cooldown_until", 0)
            row.delayed_until = values.get("delayed_until", 0)
            orm.commit()

    def save_trace(
        self,
        session_id: str,
        character_revision_id: str,
        prompt_profile_revision: int,
        seed: str,
        manifest: dict[str, Any],
        assistant_message_id: str | None = None,
    ) -> str:
        with self._orm() as orm:
            row = GenerationTrace(
                session_id=session_id,
                assistant_message_id=assistant_message_id,
                character_revision_id=character_revision_id,
                prompt_profile_revision=prompt_profile_revision,
                seed=seed,
                manifest_json=stable_json(manifest),
            )
            orm.add(row)
            orm.commit()
            return row.id

    def bind_trace_message(self, trace_id: str, message_id: str) -> None:
        with self._orm() as orm:
            row = orm.get(GenerationTrace, trace_id)
            if row is not None:
                row.assistant_message_id = message_id
                orm.commit()

    def list_traces(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._orm() as orm:
            rows = orm.scalars(
                select(GenerationTrace)
                .where(GenerationTrace.session_id == session_id)
                .order_by(GenerationTrace.created_at.desc())
                .limit(limit)
            )
            return [
                {
                    "id": row.id,
                    "session_id": row.session_id,
                    "assistant_message_id": row.assistant_message_id,
                    "character_revision_id": row.character_revision_id,
                    "prompt_profile_revision": row.prompt_profile_revision,
                    "seed": row.seed,
                    "manifest": json.loads(row.manifest_json),
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    @staticmethod
    def _character_record(orm: OrmSession, row: CharacterProfile) -> CharacterRecord:
        revision = orm.get(CharacterRevision, row.active_revision_id)
        if revision is None:
            raise PersonalityNotFoundError(row.active_revision_id or row.id)
        return CharacterRecord(
            id=row.id,
            name=row.name,
            revision_id=revision.id,
            revision=revision.revision,
            card=CharacterCard.model_validate_json(revision.card_json),
            content_hash=revision.content_hash,
            avatar_path=row.avatar_path,
            is_default=bool(row.is_default),
            archived_at=row.archived_at,
        )

    @staticmethod
    def _lorebook_record(row: Lorebook) -> LorebookRecord:
        return LorebookRecord(
            id=row.id,
            revision=row.revision,
            data=LorebookData.model_validate_json(row.book_json),
            content_hash=row.content_hash,
            globally_enabled=bool(row.globally_enabled),
            archived_at=row.archived_at,
        )
