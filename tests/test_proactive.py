"""主动消息调度测试：泊松候选、静默、抑制、过期不补发。"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine

from whitenight.config import Settings
from whitenight.memory import MemoryService, MemoryStore, NullEmbeddingProvider, NullMemoryExtractor
from whitenight.models.base import ModelChunk, ProviderMessage
from whitenight.scheduler import LogSender, ProactiveService, ProactiveStore, next_candidate
from whitenight.scheduler.poisson import active_minutes_per_day
from whitenight.scheduler.types import ProactiveConfig


def _config(**kwargs: object) -> ProactiveConfig:
    values = {
        "enabled": True,
        "expected_per_day": 1.5,
        "quiet_start": "23:00",
        "quiet_end": "08:00",
        "suppress_minutes": 60,
        "skip_grace_minutes": 45,
    }
    values.update(kwargs)
    return ProactiveConfig.model_validate(values)


def test_poisson_avoids_quiet_hours_and_suppression() -> None:
    config = _config()
    now = datetime(2026, 8, 15, 10, 0)
    last = datetime(2026, 8, 15, 9, 55)
    rng = random.Random(7)
    candidates = [next_candidate(now, config, last, rng) for _ in range(200)]
    for candidate in candidates:
        assert not (candidate.hour >= 23 or candidate.hour < 8)
        assert candidate >= last + timedelta(minutes=60)
    assert len({candidate.minute for candidate in candidates}) > 1


def test_active_minutes_excludes_quiet() -> None:
    assert active_minutes_per_day(_config()) == 24 * 60 - 9 * 60
    assert active_minutes_per_day(_config(quiet_start="00:00", quiet_end="00:00")) == 24 * 60


class FakeProvider:
    def __init__(self, reply: str = "在吗，主人") -> None:
        self.reply = reply

    async def stream_chat(
        self, messages: list[ProviderMessage]
    ) -> AsyncGenerator[ModelChunk, None]:
        del messages
        yield ModelChunk(delta=self.reply)
        yield ModelChunk(done=True)

    async def health(self) -> dict[str, object]:
        return {"ok": True}


class FakeSender:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.metadata: list[dict[str, object]] = []

    def send(self, message: str, metadata: dict[str, object]) -> bool:
        self.messages.append(message)
        self.metadata.append(metadata)
        return True


def _service(
    engine: Engine, tmp_path, provider=None, sender=None, qq_owner_ids: list[int] | None = None
) -> tuple[ProactiveService, FakeSender]:
    memory = MemoryService(MemoryStore(engine), NullMemoryExtractor(), NullEmbeddingProvider())
    sender = sender or FakeSender()
    settings = Settings(
        data_dir=tmp_path,
        database_url="sqlite:///unused.db",
        qq_owner_ids=qq_owner_ids or [],
    )
    return (
        ProactiveService(
            ProactiveStore(engine), provider or FakeProvider(), memory, sender, settings
        ),
        sender,
    )


def test_disabled_tick_skips(engine: Engine, tmp_path) -> None:
    service, sender = _service(engine, tmp_path)
    outcome = asyncio.run(service.tick(datetime(2026, 8, 15, 10, 0)))
    assert outcome.action == "skipped_disabled"
    assert sender.messages == []


def test_due_tick_sends_and_reschedules(engine: Engine, tmp_path) -> None:
    store = ProactiveStore(engine)
    store.update_config(_config())
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    store.set_next_candidate(now_utc - timedelta(minutes=1))
    service, sender = _service(engine, tmp_path)
    outcome = asyncio.run(service.tick(datetime.now()))
    assert outcome.action == "sent"
    assert sender.messages == ["在吗，主人"]
    status = store.status()
    assert status.last_sent_at is not None
    assert status.next_candidate_at is not None
    assert status.next_candidate_at > now_utc


def test_proactive_sender_receives_qq_owner(engine: Engine, tmp_path) -> None:
    store = ProactiveStore(engine)
    store.update_config(_config())
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    store.set_next_candidate(now_utc - timedelta(minutes=1))
    service, sender = _service(engine, tmp_path, qq_owner_ids=[10001])
    outcome = asyncio.run(service.tick(datetime.now()))
    assert outcome.action == "sent"
    assert sender.metadata[-1].get("user_id") == 10001


def test_expired_candidate_is_skipped_not_batched(engine: Engine, tmp_path) -> None:
    store = ProactiveStore(engine)
    store.update_config(_config(skip_grace_minutes=45))
    now = datetime.now(UTC).replace(tzinfo=None)
    store.set_next_candidate(now - timedelta(hours=2))
    service, sender = _service(engine, tmp_path)
    outcome = asyncio.run(service.tick(datetime.now()))
    assert outcome.action == "skipped_expired"
    assert sender.messages == []
    assert store.status().next_candidate_at is not None


def test_pause_and_resume(engine: Engine, tmp_path) -> None:
    store = ProactiveStore(engine)
    store.update_config(_config())
    service, _ = _service(engine, tmp_path)
    from whitenight.scheduler.types import PauseRequest

    status = service.pause(PauseRequest(until=None))
    assert status.paused is True
    outcome = asyncio.run(service.tick(datetime.now()))
    assert outcome.action == "skipped_paused"

    status = service.resume()
    assert status.paused is False


def test_mark_activity_updates_store(engine: Engine, tmp_path) -> None:
    service, _ = _service(engine, tmp_path)
    before = datetime.now(UTC).replace(tzinfo=None)
    service.mark_activity()
    assert service.status().last_activity_at is not None
    assert service.status().last_activity_at >= before - timedelta(seconds=1)


def test_log_sender_writes_jsonl(tmp_path) -> None:
    sender = LogSender(tmp_path / "logs" / "proactive.jsonl")
    assert sender.send("你好", {"attempt": 1})
    assert "你好" in (tmp_path / "logs" / "proactive.jsonl").read_text(encoding="utf-8")
