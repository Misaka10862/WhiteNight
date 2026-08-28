"""长期记忆领域类型（API 与内部共用）。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ConflictState = Literal["none", "conflicted", "resolved"]
FactStatus = Literal["active", "superseded", "deleted"]


class FactCandidate(BaseModel):
    key: str = Field(max_length=200)
    value: str = Field(max_length=2000)
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    source_message_ids: list[str] = Field(default_factory=list)
    character_id: str | None = None
    owner_namespace: str = "local-user"


class EpisodeCandidate(BaseModel):
    content: str = Field(max_length=4000)
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    source_message_ids: list[str] = Field(default_factory=list)
    character_id: str | None = None
    owner_namespace: str = "local-user"


class ExtractionResult(BaseModel):
    facts: list[FactCandidate] = Field(default_factory=list)
    episodes: list[EpisodeCandidate] = Field(default_factory=list)


class FactRecord(BaseModel):
    id: str
    key: str
    value: str
    confidence: float
    source_message_ids: list[str] = Field(default_factory=list)
    status: FactStatus = "active"
    conflict_state: ConflictState = "none"
    created_at: datetime
    updated_at: datetime
    character_id: str | None = None
    owner_namespace: str = "local-user"


class EpisodeRecord(BaseModel):
    id: str
    content: str
    confidence: float
    importance: float
    source_message_ids: list[str] = Field(default_factory=list)
    access_count: int = 0
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    character_id: str | None = None
    owner_namespace: str = "local-user"


class MemoryHit(BaseModel):
    item_type: Literal["fact", "episode"]
    item_id: str
    content: str
    score: float
    lexical_score: float
    semantic_score: float | None = None


class FactUpsert(BaseModel):
    key: str = Field(max_length=200)
    value: str = Field(max_length=2000)
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    source_message_ids: list[str] = Field(default_factory=list)
    character_id: str | None = None
    owner_namespace: str = "local-user"


class FactUpdate(BaseModel):
    value: str = Field(max_length=2000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class EpisodeCreate(BaseModel):
    content: str = Field(max_length=4000)
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    source_message_ids: list[str] = Field(default_factory=list)
    character_id: str | None = None
    owner_namespace: str = "local-user"
