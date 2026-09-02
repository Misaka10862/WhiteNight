"""Validated local sticker catalog.

Sticker files are runtime data rather than repository assets.  The catalog only
accepts relative paths below its configured root, so a model-selected sticker
ID can never turn into an arbitrary filesystem read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StickerCatalogError(ValueError):
    """The sticker catalog is missing, malformed, or unsafe."""


class StickerRecord(BaseModel):
    """One selectable sticker and the natural-language hints shown to a model."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    file: str = Field(min_length=1, max_length=512)
    label: str = Field(min_length=1, max_length=200)
    use_when: list[str] = Field(default_factory=list, max_length=20)
    avoid_when: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True
    segment_type: Literal["mface", "market_face"] = "mface"
    emoji_id: str | None = None
    emoji_package_id: str | None = None
    key: str | None = None

    @property
    def native_ready(self) -> bool:
        return bool(self.emoji_id and (self.key or self.emoji_package_id))


class _StickerManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1, le=1)
    stickers: list[StickerRecord] = Field(default_factory=list, max_length=200)


class StickerCatalog:
    """Load and validate ``catalog.json`` under a trusted runtime directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.path = self.root / "catalog.json"
        self._records = self._load()

    def _load(self) -> dict[str, StickerRecord]:
        if not self.path.exists() and not self.path.is_symlink():
            return {}
        if self.path.is_symlink() or not self.path.is_file():
            raise StickerCatalogError(f"表情目录清单不是普通文件：{self.path}")
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            manifest = _StickerManifest.model_validate(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise StickerCatalogError(f"表情目录清单无效：{self.path}") from exc

        records: dict[str, StickerRecord] = {}
        for record in manifest.stickers:
            if record.id in records:
                raise StickerCatalogError(f"表情 ID 重复：{record.id}")
            relative = Path(record.file)
            if relative.is_absolute() or ".." in relative.parts:
                raise StickerCatalogError(f"表情文件必须位于目录内：{record.file}")
            if relative.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                raise StickerCatalogError(f"表情文件必须是常见图片格式：{record.file}")
            candidate = self.root / relative
            if candidate.is_symlink():
                raise StickerCatalogError(f"表情文件不能是符号链接：{record.file}")
            path = candidate.resolve()
            if not path.is_relative_to(self.root):
                raise StickerCatalogError(f"表情文件越过目录边界：{record.file}")
            if path.is_symlink() or not path.is_file():
                raise StickerCatalogError(f"表情文件不存在：{record.file}")
            records[record.id] = record
        return records

    def records(
        self, *, enabled_only: bool = True, native_only: bool = False
    ) -> list[StickerRecord]:
        records: list[StickerRecord] = list(self._records.values())
        if enabled_only:
            records = [record for record in records if record.enabled]
        if native_only:
            records = [record for record in records if record.native_ready]
        return records

    def get(self, sticker_id: str, *, native_only: bool = False) -> StickerRecord | None:
        record = self._records.get(sticker_id)
        return (
            record
            if record is not None and record.enabled and (not native_only or record.native_ready)
            else None
        )

    def path_for(self, record: StickerRecord) -> Path:
        """Return a validated path for a record from this catalog."""
        relative = Path(record.file)
        candidate = self.root / relative
        path = candidate.resolve()
        if candidate.is_symlink() or not path.is_relative_to(self.root) or not path.is_file():
            raise StickerCatalogError(f"表情文件不可用：{record.file}")
        return path

    def prompt_text(self, *, native_only: bool = False) -> str:
        """Render only labels and usage hints; never expose local paths to a model."""
        lines = []
        for record in self.records(native_only=native_only):
            use = "、".join(record.use_when) or "情绪合适时"
            avoid = "、".join(record.avoid_when) or "无明确需要时"
            lines.append(f"- {record.id}: {record.label}；适合：{use}；避免：{avoid}")
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._records)

    @staticmethod
    def manifest_payload(records: list[StickerRecord]) -> dict[str, Any]:
        return {"version": 1, "stickers": [record.model_dump(mode="json") for record in records]}
