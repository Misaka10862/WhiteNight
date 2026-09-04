"""Validated HTTP request shapes, separate from runtime assembly."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from whitenight.application.configuration import _build_memory_extractor as _build_memory_extractor
from whitenight.personality.types import CharacterCard, LorebookData, PromptBlock


class ExtractRequest(BaseModel):
    session_id: str


class ResolveRequest(BaseModel):
    keep: bool = True


class SessionRename(BaseModel):
    title: str


class ApprovalAction(BaseModel):
    session_id: str | None = None
    scope: Literal["once", "session"] = "once"


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
