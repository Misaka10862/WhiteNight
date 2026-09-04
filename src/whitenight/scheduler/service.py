"""主动消息服务：泊松候选、到期判定、组合发送、有限重试、过期不补发。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from whitenight.agent.context import load_soul
from whitenight.config import Settings
from whitenight.memory.service import MemoryService
from whitenight.models.base import ModelProvider, ProviderMessage
from whitenight.personality.store import PersonalityStore
from whitenight.policy.audit import AuditService
from whitenight.scheduler.poisson import (
    _in_quiet,
    local_naive_to_utc,
    next_candidate,
    utc_naive_to_local,
)
from whitenight.scheduler.store import ProactiveStore
from whitenight.scheduler.types import (
    PauseRequest,
    ProactiveConfig,
    ProactiveStatus,
    SendOutcome,
)

logger = logging.getLogger(__name__)


class ProactiveSender(Protocol):
    def send(self, message: str, metadata: dict[str, object]) -> bool: ...


class LogSender:
    """本地审计发送器：只写元数据，不写主动消息正文。"""

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path

    def send(self, message: str, metadata: dict[str, object]) -> bool:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {
                "ts": datetime.now(UTC).isoformat(),
                "message_chars": len(message),
                "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
                **metadata,
            },
            ensure_ascii=False,
        )
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return True


class NullSender:
    def send(self, message: str, metadata: dict[str, object]) -> bool:
        del message, metadata
        return True


class ProactiveService:
    def __init__(
        self,
        store: ProactiveStore,
        provider: ModelProvider,
        memory: MemoryService,
        sender: ProactiveSender,
        settings: Settings,
        personalities: PersonalityStore | None = None,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._memory = memory
        self._sender = sender
        self._settings = settings
        self._personalities = personalities
        self._audit = audit
        self._last_delivery_error: str | None = None
        self._clock = clock or datetime.now
        self._tick_lock = asyncio.Lock()
        self._delivery_skip: SendOutcome | None = None

    def set_provider(self, provider: ModelProvider) -> None:
        """Replace the provider used by future proactive messages."""
        self._provider = provider

    def set_sender(self, sender: ProactiveSender) -> None:
        """Replace the delivery channel used by future proactive messages."""
        self._sender = sender

    @property
    def last_delivery_error(self) -> str | None:
        return self._last_delivery_error

    def status(self) -> ProactiveStatus:
        return self._store.status()

    def update_config(self, config: ProactiveConfig) -> ProactiveStatus:
        status = self._store.update_config(config)
        if config.enabled and status.next_candidate_at is None:
            self._schedule_next(datetime.now())
        return self.status()

    def pause(self, request: PauseRequest) -> ProactiveStatus:
        self._store.pause(request.until)
        return self.status()

    def resume(self) -> ProactiveStatus:
        self._store.resume()
        status = self.status()
        if status.config.enabled and status.next_candidate_at is None:
            self._schedule_next(datetime.now())
        return self.status()

    def mark_activity(self) -> None:
        self._store.mark_activity()

    def _schedule_next(self, local_now: datetime) -> None:
        status = self._store.status()
        last_local = (
            utc_naive_to_local(status.last_activity_at) if status.last_activity_at else None
        )
        candidate = next_candidate(local_now, status.config, last_local)
        self._store.set_next_candidate(local_naive_to_utc(candidate))

    async def tick(self, local_now: datetime | None = None) -> SendOutcome:
        async with self._tick_lock:
            return await self._tick(local_now)

    def _current_status(self, local_now: datetime) -> ProactiveStatus:
        status = self._store.status()
        if (
            status.paused
            and status.paused_until
            and utc_naive_to_local(status.paused_until) <= local_now
        ):
            self._store.resume()
            return self._store.status()
        return status

    @staticmethod
    def _eligibility(status: ProactiveStatus, local_now: datetime) -> SendOutcome | None:
        if not status.config.enabled:
            return SendOutcome(action="skipped_disabled", reason="主动消息已关闭")
        if status.paused:
            return SendOutcome(action="skipped_paused", reason="暂停中")
        if _in_quiet(local_now, status.config):
            return SendOutcome(action="skipped_quiet", reason="当前处于静默时段")
        if status.last_activity_at and local_now < (
            utc_naive_to_local(status.last_activity_at)
            + timedelta(minutes=status.config.suppress_minutes)
        ):
            return SendOutcome(action="skipped_activity", reason="最近有会话活动")
        return None

    async def _tick(self, local_now: datetime | None = None) -> SendOutcome:
        started = time.monotonic()
        fixed_now = local_now
        local_now = local_now or self._clock()

        def current_time() -> datetime:
            return (
                fixed_now + timedelta(seconds=time.monotonic() - started)
                if fixed_now is not None
                else self._clock()
            )

        status = self._current_status(local_now)
        if not status.config.enabled or status.paused:
            return self._eligibility(status, local_now) or SendOutcome(action="not_due")

        if status.next_candidate_at is None:
            self._schedule_next(local_now)
            return SendOutcome(action="not_due", reason="已生成首个候选时间")

        candidate_local = utc_naive_to_local(status.next_candidate_at)
        if local_now < candidate_local:
            return SendOutcome(
                action="not_due", reason=f"候选时间 {candidate_local.isoformat(timespec='minutes')}"
            )

        grace = status.config.skip_grace_minutes
        if local_now > candidate_local + timedelta(minutes=grace):
            # 睡眠/断网后过期：不集中补发，直接重新调度。
            self._schedule_next(local_now)
            return SendOutcome(
                action="skipped_expired",
                reason=f"候选已过期（>{grace} 分钟），重新调度且不补发",
            )

        blocked = self._eligibility(status, local_now)
        if blocked is not None:
            self._schedule_next(local_now)
            return blocked

        def check_delivery() -> SendOutcome | None:
            now = current_time()
            current = self._current_status(now)
            failure = self._eligibility(current, now)
            if failure is not None:
                return failure
            if current.last_activity_at != status.last_activity_at:
                return SendOutcome(action="skipped_activity", reason="生成期间出现了新会话活动")
            if current.next_candidate_at != status.next_candidate_at:
                return SendOutcome(action="not_due", reason="候选状态已更新")
            if now > candidate_local + timedelta(minutes=current.config.skip_grace_minutes):
                return SendOutcome(action="skipped_expired", reason="生成期间候选已过期")
            return None

        message = await self._compose_message()
        if not message:
            self._schedule_next(local_now)
            return SendOutcome(action="skipped_expired", reason="消息生成失败，重新调度")

        self._delivery_skip = None
        sent = await self._send_with_retries(message, check_eligibility=check_delivery)
        if self._delivery_skip is not None:
            if self._delivery_skip.action in {
                "skipped_activity",
                "skipped_quiet",
                "skipped_expired",
            }:
                self._schedule_next(current_time())
            return self._delivery_skip
        if not sent:
            self._schedule_next(local_now)
            return SendOutcome(action="skipped_expired", reason="发送失败（有限重试后）")

        self._store.mark_sent(local_naive_to_utc(current_time()))
        self._schedule_next(current_time())
        return SendOutcome(action="sent", message=message)

    async def _compose_message(self) -> str | None:
        try:
            character_id = None
            soul = load_soul(self._settings.soul_file)
            if self._personalities is not None:
                character_id = self._personalities.default_character_id()
                soul = (
                    self._personalities.get_character(character_id).card.data.system_prompt or soul
                )
            hits = await self._memory.aretrieve(
                "主人 偏好 称呼 喜好 最近 纪念", limit=6, character_id=character_id
            )
            memory_lines = "\n".join(f"- {hit.content}" for hit in hits[:6]) or "（暂无长期记忆）"
            prompt = (
                f"{soul}\n\n# 主动消息\n"
                f"参考以下主人偏好与共同经历（如无把握不要编造）：\n{memory_lines}\n\n"
                "请给主人写一条主动私聊消息：自然、简短（2-3 句）、不打扰、不要求回复；"
                "只输出消息正文。"
            )
            chunks = self._provider.stream_chat([ProviderMessage(role="user", content=prompt)])
            parts: list[str] = []
            async for chunk in chunks:
                if chunk.delta:
                    parts.append(chunk.delta)
                if chunk.done:
                    break
            text = "".join(parts).strip()
            return text[:300] or None
        except Exception:
            logger.exception("主动消息生成失败")
            return None

    async def _send_with_retries(
        self,
        message: str,
        max_attempts: int = 2,
        *,
        check_eligibility: Callable[[], SendOutcome | None] | None = None,
    ) -> bool:
        owner_user_id = self._settings.qq_owner_ids[0] if self._settings.qq_owner_ids else None
        channel = self._settings.proactive_sender
        for attempt in range(1, max_attempts + 1):
            if check_eligibility is not None:
                self._delivery_skip = check_eligibility()
                if self._delivery_skip is not None:
                    return False
            try:
                metadata: dict[str, object] = {"channel": channel, "attempt": attempt}
                if owner_user_id is not None:
                    metadata["user_id"] = owner_user_id
                if await asyncio.to_thread(self._sender.send, message, metadata):
                    self._last_delivery_error = None
                    if self._audit:
                        self._audit.record(
                            actor="scheduler",
                            action="proactive.sent",
                            decision="auto",
                            params_summary=(
                                f"channel={channel} user_id={owner_user_id} "
                                f"message_chars={len(message)} "
                                f"message_sha256={hashlib.sha256(message.encode('utf-8')).hexdigest()} "
                                f"attempt={attempt}"
                            ),
                            result_summary="主动消息发送成功（不含正文）",
                            channel=channel,
                        )
                    return True
            except Exception as exc:
                self._last_delivery_error = type(exc).__name__
                logger.warning(
                    "主动消息发送失败 attempt=%s error_type=%s", attempt, type(exc).__name__
                )
            if attempt < max_attempts:
                await asyncio.sleep(2 * attempt)
        if self._audit:
            self._audit.record(
                actor="scheduler",
                action="proactive.failed",
                decision="error",
                params_summary=(
                    f"channel={channel} user_id={owner_user_id} message_chars={len(message)} "
                    f"message_sha256={hashlib.sha256(message.encode('utf-8')).hexdigest()} "
                    f"attempts={max_attempts}"
                ),
                result_summary=f"主动消息发送失败：{self._last_delivery_error or 'sender returned false'}",
                channel=channel,
            )
        return False

    async def run_forever(self, stop: asyncio.Event, interval_s: int = 30) -> None:
        while not stop.is_set():
            try:
                outcome = await self.tick()
                if outcome.action == "sent":
                    logger.info("已发送主动消息 chars=%s", len(outcome.message or ""))
            except Exception:
                logger.exception("主动消息循环异常")
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_s)
            except TimeoutError:
                continue
