"""Bounded, reproducible SillyTavern-compatible lorebook activation engine."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable
from dataclasses import dataclass, field

import regex  # type: ignore[import-untyped]

from whitenight.personality.types import LorebookEntry, LorebookRecord

_MAX_PATTERN = 500
_MAX_SCAN_CHARS = 200_000
_REGEX_TIMEOUT_S = 0.02


@dataclass
class ActivatedLore:
    entry_key: str
    book_id: str
    entry: LorebookEntry
    reason: str


@dataclass
class WorldbookResult:
    seed: str
    by_position: dict[str, list[LorebookEntry]] = field(default_factory=dict)
    activated: list[ActivatedLore] = field(default_factory=list)
    effects: dict[str, dict[str, int]] = field(default_factory=dict)


def _seed(session_id: str, sequence: int, attempt: int) -> str:
    return hashlib.sha256(f"{session_id}:{sequence}:{attempt}".encode()).hexdigest()


def _regex_parts(value: str) -> tuple[str, int] | None:
    if len(value) < 3 or not value.startswith("/"):
        return None
    end = value.rfind("/")
    if end <= 0:
        return None
    flags = regex.IGNORECASE if "i" in value[end + 1 :] else 0
    return value[1:end], flags


def _matches(text: str, key: str, entry: LorebookEntry) -> bool:
    parsed = _regex_parts(key)
    if parsed:
        pattern, flags = parsed
        if not pattern or len(pattern) > _MAX_PATTERN:
            return False
        try:
            return bool(regex.search(pattern, text, flags=flags, timeout=_REGEX_TIMEOUT_S))
        except (regex.error, TimeoutError):
            return False
    haystack = text if entry.case_sensitive else text.casefold()
    needle = key if entry.case_sensitive else key.casefold()
    if not needle:
        return False
    if entry.match_whole_words:
        try:
            return bool(
                regex.search(
                    rf"(?<!\w){regex.escape(needle)}(?!\w)",
                    haystack,
                    timeout=_REGEX_TIMEOUT_S,
                )
            )
        except TimeoutError:
            return False
    return needle in haystack


def _secondary_ok(text: str, entry: LorebookEntry) -> bool:
    if not entry.secondary_keys:
        return True
    values = [_matches(text, key, entry) for key in entry.secondary_keys]
    return {
        "and_any": any(values),
        "and_all": all(values),
        "not_any": not any(values),
        "not_all": not all(values),
    }[entry.secondary_logic]


class WorldbookEngine:
    def activate(
        self,
        books: list[LorebookRecord],
        history: list[str],
        *,
        session_id: str,
        sequence: int,
        attempt: int = 0,
        generation_type: str = "normal",
        persona: str = "",
        character: str = "",
        scenario: str = "",
        effects: dict[str, dict[str, int]] | None = None,
        count_tokens: Callable[[str], int | None] | None = None,
    ) -> WorldbookResult:
        seed = _seed(session_id, sequence, attempt)
        rng = random.Random(seed)
        result = WorldbookResult(seed=seed, effects=dict(effects or {}))
        newest = list(reversed(history))
        recursive_text: list[str] = []
        activated_keys: set[str] = set()
        candidates: list[tuple[LorebookRecord, LorebookEntry, str]] = []
        max_steps = max((book.data.max_recursion_steps for book in books), default=1)

        max_steps = max(max_steps, min(len(history), 32))
        for step in range(max_steps):
            newly_activated: list[str] = []
            for book in books:
                default_depth = book.data.scan_depth
                for entry in book.data.entries:
                    entry_key = f"{book.id}:{entry.id}"
                    if entry_key in activated_keys or not entry.enabled:
                        continue
                    if entry.triggers and generation_type not in entry.triggers:
                        continue
                    state = result.effects.get(entry_key, {})
                    if state.get("delayed_until", 0) > sequence:
                        continue
                    if (
                        state.get("cooldown_until", 0) > sequence
                        and state.get("sticky_until", 0) <= sequence
                    ):
                        continue
                    sticky = state.get("sticky_until", 0) > sequence
                    if entry.delay_until_recursion > step:
                        continue
                    expand = step if len(candidates) < book.data.min_activations else 0
                    depth = (entry.scan_depth or default_depth) + expand
                    scan_parts = newest[:depth]
                    if step and not entry.exclude_recursion:
                        scan_parts += recursive_text
                    if entry.match_persona:
                        scan_parts.append(persona)
                    if entry.match_character:
                        scan_parts.append(character)
                    if entry.match_scenario:
                        scan_parts.append(scenario)
                    scan = "\n".join(scan_parts)[-_MAX_SCAN_CHARS:]
                    primary = (
                        entry.constant
                        or sticky
                        or any(_matches(scan, key, entry) for key in entry.keys)
                    )
                    if not primary or not _secondary_ok(scan, entry):
                        continue
                    if rng.random() > entry.probability:
                        continue
                    reason = "constant" if entry.constant else "sticky" if sticky else "keyword"
                    candidates.append((book, entry, reason))
                    activated_keys.add(entry_key)
                    if entry.content and not entry.prevent_recursion:
                        newly_activated.append(entry.content)
            needs_minimum = any(
                book.data.min_activations
                > len([candidate for candidate in candidates if candidate[0].id == book.id])
                for book in books
            )
            if not needs_minimum and (
                not newly_activated or not any(book.data.recursive for book in books)
            ):
                break
            recursive_text.extend(newly_activated)

        grouped: dict[str, list[tuple[LorebookRecord, LorebookEntry, str]]] = {}
        ungrouped: list[tuple[LorebookRecord, LorebookEntry, str]] = []
        for item in candidates:
            (
                grouped.setdefault(item[1].group, []).append(item)
                if item[1].group
                else ungrouped.append(item)
            )
        selected = list(ungrouped)
        for items in grouped.values():
            overrides = [item for item in items if item[1].group_override]
            pool = overrides or items
            total = sum(item[1].group_weight for item in pool)
            selected.append(
                rng.choices(pool, weights=[item[1].group_weight for item in pool], k=1)[0]
                if total
                else pool[0]
            )

        used_by_book: dict[str, int] = {}
        for book, entry, reason in sorted(selected, key=lambda item: item[1].order):
            entry_key = f"{book.id}:{entry.id}"
            cost = count_tokens(entry.content) if count_tokens else None
            used = used_by_book.get(book.id, 0)
            if (
                cost is not None
                and not entry.ignore_budget
                and used + cost > book.data.token_budget
            ):
                continue
            if cost is not None:
                used_by_book[book.id] = used + cost
            result.activated.append(
                ActivatedLore(entry_key=entry_key, book_id=book.id, entry=entry, reason=reason)
            )
            result.by_position.setdefault(entry.position, []).append(entry)
            state = result.effects.setdefault(entry_key, {})
            if entry.sticky:
                state["sticky_until"] = sequence + entry.sticky
            if entry.cooldown:
                state["cooldown_until"] = sequence + entry.cooldown
            if entry.delay:
                state["delayed_until"] = sequence + entry.delay
        return result
