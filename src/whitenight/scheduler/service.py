"""主动消息服务：泊松候选、到期判定、组合发送、有限重试、过期不补发。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
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
    ) -> None:
        self._store = store
        self._provider = provider
        self._memory = memory
        self._sender = sender
        self._settings = settings
        self._personalities = personalities
        self._audit = audit
        self._last_delivery_error: str | None = None

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
        local_now = local_now or datetime.now()
        status = self._store.status()
        if not status.config.enabled:
            return SendOutcome(action="skipped_disabled", reason="主动消息已关闭")
        if status.paused:
            if status.paused_until and utc_naive_to_local(status.paused_until) < local_now:
                self._store.resume()
                status = self._store.status()
            else:
                return SendOutcome(action="skipped_paused", reason="暂停中")

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

        message = await self._compose_message()
        if not message:
            self._schedule_next(local_now)
            return SendOutcome(action="skipped_expired", reason="消息生成失败，重新调度")

        sent = await self._send_with_retries(message)
        if not sent:
            self._schedule_next(local_now)
            return SendOutcome(action="skipped_expired", reason="发送失败（有限重试后）")

        self._store.mark_sent()
        self._schedule_next(local_now)
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
            hits = self._memory.retrieve(
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

    async def _send_with_retries(self, message: str, max_attempts: int = 2) -> bool:
        owner_user_id = self._settings.qq_owner_ids[0] if self._settings.qq_owner_ids else None
        channel = self._settings.proactive_sender
        for attempt in range(1, max_attempts + 1):
            try:
                metadata: dict[str, object] = {"channel": channel, "attempt": attempt}
                if owner_user_id is not None:
                    metadata["user_id"] = owner_user_id
                if self._sender.send(message, metadata):
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
                self._last_delivery_error = str(exc)
                logger.warning("主动消息发送失败 attempt=%s：%s", attempt, exc)
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
