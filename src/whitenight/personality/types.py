"""Strict, provider-independent personality and prompt domain types."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PromptRole = Literal["system", "user", "assistant"]
PromptPosition = Literal["relative", "in_chat"]
LorePosition = Literal[
    "before",
    "after",
    "examples_before",
    "examples_after",
    "author_note_top",
    "author_note_bottom",
    "at_depth",
    "outlet",
]
SecondaryLogic = Literal["and_any", "and_all", "not_any", "not_all"]


class CharacterCardData(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=64_000)
    personality: str = Field(default="", max_length=32_000)
    scenario: str = Field(default="", max_length=32_000)
    first_mes: str = Field(default="", max_length=32_000)
    mes_example: str = Field(default="", max_length=64_000)
    creator_notes: str = Field(default="", max_length=32_000)
    system_prompt: str = Field(default="", max_length=64_000)
    post_history_instructions: str = Field(default="", max_length=32_000)
    alternate_greetings: list[str] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=100)
    creator: str = Field(default="", max_length=200)
    character_version: str = Field(default="", max_length=100)
    extensions: dict[str, Any] = Field(default_factory=dict)
    character_book: dict[str, Any] | None = None


class CharacterCard(BaseModel):
    model_config = ConfigDict(extra="allow")

    spec: Literal["chara_card_v2", "chara_card_v3"]
    spec_version: str
    data: CharacterCardData

    @model_validator(mode="before")
    @classmethod
    def validate_wire_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = value.get("data")
        if value.get("spec") == "chara_card_v2" and isinstance(data, dict):
            required = {
                "name",
                "description",
                "personality",
                "scenario",
                "first_mes",
                "mes_example",
                "creator_notes",
                "system_prompt",
                "post_history_instructions",
                "alternate_greetings",
                "tags",
                "creator",
                "character_version",
                "extensions",
            }
            missing = sorted(required - set(data))
            if missing:
                raise ValueError("CCv2 缺少字段：" + ", ".join(missing))
        if len(json.dumps(value, ensure_ascii=False, default=str)) > 1_000_000:
            raise ValueError("角色卡元数据超过 1,000,000 字符")
        return value

    @model_validator(mode="after")
    def validate_version(self) -> CharacterCard:
        try:
            version = float(self.spec_version)
        except ValueError as exc:
            raise ValueError("spec_version 必须是数字版本") from exc
        if self.spec == "chara_card_v2" and version != 2.0:
            raise ValueError("chara_card_v2 仅支持 spec_version=2.0")
        if self.spec == "chara_card_v3" and not 3.0 <= version < 4.0:
            raise ValueError("chara_card_v3 仅支持 3.x")
        return self


class PromptBlock(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    role: PromptRole = "system"
    content: str = Field(default="", max_length=64_000)
    enabled: bool = True
    position: PromptPosition = "relative"
    depth: int = Field(default=0, ge=0, le=10_000)
    order: int = Field(default=100, ge=0, le=100_000)
    triggers: list[str] = Field(default_factory=list)
    outlet: str | None = Field(default=None, max_length=100)


class LorebookEntry(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    comment: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=64_000)
    keys: list[str] = Field(default_factory=list, max_length=100)
    secondary_keys: list[str] = Field(default_factory=list, max_length=100)
    secondary_logic: SecondaryLogic = "and_any"
    enabled: bool = True
    constant: bool = False
    position: LorePosition = "before"
    depth: int = Field(default=4, ge=0, le=10_000)
    role: PromptRole = "system"
    order: int = Field(default=100, ge=0, le=100_000)
    probability: float = Field(default=1.0, ge=0.0, le=1.0)
    group: str = Field(default="", max_length=100)
    group_override: bool = False
    group_weight: float = Field(default=1.0, ge=0.0, le=1000.0)
    sticky: int = Field(default=0, ge=0, le=10_000)
    cooldown: int = Field(default=0, ge=0, le=10_000)
    delay: int = Field(default=0, ge=0, le=10_000)
    scan_depth: int | None = Field(default=None, ge=1, le=1000)
    case_sensitive: bool = False
    match_whole_words: bool = False
    prevent_recursion: bool = False
    exclude_recursion: bool = False
    delay_until_recursion: int = Field(default=0, ge=0, le=100)
    triggers: list[str] = Field(default_factory=list)
    ignore_budget: bool = False
    outlet: str = Field(default="", max_length=100)
    match_persona: bool = False
    match_character: bool = False
    match_scenario: bool = False
    extensions: dict[str, Any] = Field(default_factory=dict)


class LorebookData(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    entries: list[LorebookEntry] = Field(default_factory=list, max_length=5000)
    scan_depth: int = Field(default=2, ge=1, le=1000)
    token_budget: int = Field(default=2048, ge=1, le=100_000)
    recursive: bool = False
    max_recursion_steps: int = Field(default=8, ge=1, le=32)
    min_activations: int = Field(default=0, ge=0, le=100)
    extensions: dict[str, Any] = Field(default_factory=dict)


class CharacterRecord(BaseModel):
    id: str
    name: str
    revision_id: str
    revision: int
    card: CharacterCard
    content_hash: str
    avatar_path: str | None = None
    is_default: bool = False
    archived_at: datetime | None = None


class PersonaRecord(BaseModel):
    id: str
    name: str
    description: str
    content_hash: str
    revision: int = 1


class PromptProfileRecord(BaseModel):
    id: str
    character_id: str
    revision: int
    blocks: list[PromptBlock]
    content_hash: str


class LorebookRecord(BaseModel):
    id: str
    revision: int
    data: LorebookData
    content_hash: str
    globally_enabled: bool = False
    archived_at: datetime | None = None


class PromptManifestItem(BaseModel):
    id: str
    name: str
    role: PromptRole
    source: str
    enabled: bool = True
    depth: int = 0
    token_count: int | None = None
    content_hash: str


class PromptPreview(BaseModel):
    messages: list[dict[str, Any]]
    manifest: list[PromptManifestItem]
    activated_lore: list[dict[str, Any]] = Field(default_factory=list)
    seed: str
    tokenizer: Literal["exact", "unavailable"] = "unavailable"
    total_tokens: int | None = None
    character_revision_id: str
    prompt_profile_revision: int
