"""Regression evidence for the pre-persona context gap.

The memory subsystem can retrieve a stored fact, while the legacy context builder has no
input for that result. This classifies the missing recall as a deterministic integration gap,
not an 8B-model capability limitation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from whitenight.agent.context import build_provider_messages
from whitenight.channels.types import MessageRecord


def test_legacy_context_builder_cannot_include_retrieved_memory() -> None:
    history = [
        MessageRecord(
            id="m1",
            session_id="s1",
            sequence=1,
            role="user",
            content="今天想喝点什么？",
            created_at=datetime(2026, 8, 26, tzinfo=UTC),
        )
    ]
    messages = build_provider_messages(history, "人格", 10_000)
    assert all("抹茶" not in message.content for message in messages)
