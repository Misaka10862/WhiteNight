"""OneBot 11 Adapter：幂等去重、所有者白名单、顺序处理、限频与回复分片。

群聊事件一律忽略（首版只支持私聊）。QQ 内审批使用一次性编号。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from collections import OrderedDict
from pathlib import Path
from uuid import uuid4

import httpx
from pydantic import ValidationError

from whitenight.agent.service import ChatService
from whitenight.channels.onebot.sender import OneBotSender
from whitenight.channels.onebot.session_map import ChannelSessionStore
from whitenight.channels.onebot.types import OneBotPrivateMessageEvent, parse_segments
from whitenight.channels.types import ChatRequest
from whitenight.config import Settings
from whitenight.policy.approvals import ApprovalService
from whitenight.storage.sessions import SessionStore

logger = logging.getLogger(__name__)

_APPROVE_RE = re.compile(r"^(?:同意|批准|允许)\s+([A-Za-z0-9_-]{6,16})$")
_REJECT_RE = re.compile(r"^(?:拒绝|不同意)\s+([A-Za-z0-9_-]{6,16})$")


class EventDeduplicator:
    """消息去重：message_id 命中缓存直接丢弃；TTL 后自然过期。"""

    def __init__(self, ttl_s: float = 600.0, max_entries: int = 10_000) -> None:
        self._ttl = ttl_s
        self._max = max_entries
        self._seen: OrderedDict[str, float] = OrderedDict()

    def accept(self, message_id: str, user_id: int) -> bool:
        key = f"{user_id}:{message_id}"
        now = time.monotonic()
        if key in self._seen and now - self._seen[key] < self._ttl:
            return False
        self._seen[key] = now
        self._seen.move_to_end(key)
        while len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return True


class RateLimiter:
    """按用户限频；返回需要等待的秒数（0 表示可立即处理）。"""

    def __init__(self, interval_s: float) -> None:
        self._interval = max(0.0, interval_s)
        self._next: dict[int, float] = {}

    def wait_seconds(self, user_id: int) -> float:
        now = time.monotonic()
        allowed = self._next.get(user_id, 0.0)
        delay = max(0.0, allowed - now)
        self._next[user_id] = now + delay + self._interval
        return delay


class OneBotAdapter:
    """HTTP POST 事件接收 + OneBot API 发送；渠道状态不进入 Core 之外。"""

    def __init__(
        self,
        settings: Settings,
        sessions: SessionStore,
        channel_sessions: ChannelSessionStore,
        chat_service: ChatService,
        approvals: ApprovalService,
        sender: OneBotSender | None = None,
    ) -> None:
        self._settings = settings
        self._sessions = sessions
        self._channel_sessions = channel_sessions
        self._chat = chat_service
        self._approvals = approvals
        self._sender = sender or OneBotSender(
            settings.qq_onebot_api_url, settings.qq_reply_max_chars
        )
        self._dedupe = EventDeduplicator()
        self._rate = RateLimiter(settings.qq_rate_limit_seconds)
        self._locks: dict[int, asyncio.Lock] = {}

    def enabled(self) -> bool:
        return self._settings.qq_enabled

    def owner_ids(self) -> list[int]:
        return list(self._settings.qq_owner_ids)

    async def handle_event(self, payload: dict[str, object]) -> dict[str, object]:
        if not self.enabled():
            return {"status": "qq_disabled"}

        try:
            event = OneBotPrivateMessageEvent.model_validate(payload)
        except ValidationError as exc:
            return {"status": "invalid_event", "error": str(exc)}
        if event.message_type != "private":
            return {"status": "ignored_group"}

        user_id = event.user_id
        if user_id not in self.owner_ids():
            return {"status": "ignored_not_owner"}

        if not self._dedupe.accept(str(event.message_id), user_id):
            return {"status": "duplicate"}

        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            delay = self._rate.wait_seconds(user_id)
            if delay > 0:
                await asyncio.sleep(delay)
            return await self._process_owner_message(event)

    async def _process_owner_message(self, event: OneBotPrivateMessageEvent) -> dict[str, object]:
        parsed = parse_segments(event)
        session_id = self._channel_sessions.get_or_create("onebot", str(event.user_id))

        approval = await self._handle_approval_command(event, parsed.text, session_id)
        if approval is not None:
            return approval

        if parsed.file_path and not parsed.image_data_url:
            saved = await self._save_qq_file(event.user_id, parsed.file_path, parsed.file_name)
            if saved:
                self._sessions.add_message(
                    session_id,
                    "user",
                    f"[QQ 文件] {saved['name']} 已保存到 {saved['path']}",
                    kind="text",
                )
                await self._send(event.user_id, f"收到文件：{saved['name']}（{saved['path']}）")
            else:
                await self._send(event.user_id, "文件下载失败，请稍后重试")
            return {"status": "file_received"}

        image_data_url = parsed.image_data_url
        if image_data_url and image_data_url.startswith("http"):
            image_data_url = (await self._download_as_data_url(image_data_url)) or None

        request = ChatRequest(
            session_id=session_id,
            text=parsed.text,
            image_data_url=image_data_url,
        )
        reply: str | None = None
        task_note_sent = False
        owner_user_id = event.user_id
        async for chat_event in self._chat.stream_reply(request):
            if chat_event.type == "task" and not task_note_sent:
                delegate = (chat_event.extra or {}).get("delegate_event", {})
                if isinstance(delegate, dict) and delegate.get("type") in {"started", "error"}:
                    await self._send(
                        owner_user_id,
                        f"[任务] {delegate.get('label', '')}",
                    )
                    task_note_sent = True
            elif chat_event.type == "done" and chat_event.text:
                reply = chat_event.text
            elif chat_event.type == "error" and chat_event.message:
                reply = f"小白遇到问题：{chat_event.message}"

        await self._send(owner_user_id, reply or "小白没有生成回复，请重试")
        return {"status": "replied", "session_id": session_id}

    async def _handle_approval_command(
        self, event: OneBotPrivateMessageEvent, text: str, session_id: str
    ) -> dict[str, object] | None:
        approve_match = _APPROVE_RE.match(text.strip())
        reject_match = _REJECT_RE.match(text.strip())
        if not approve_match and not reject_match:
            return None
        match = approve_match if approve_match else reject_match
        assert match is not None
        code = match.group(1)
        pending = [item for item in self._approvals.list_pending() if item.code == code]
        if not pending:
            await self._send(event.user_id, "审批编号无效、已过期或已处理")
            return {"status": "approval_invalid"}

        item = pending[0]
        if approve_match:
            resolution = self._approvals.resolve_once(
                code, session_id=item.session_id, expected_scope=item.scope
            )
            await self._send(
                event.user_id,
                f"已批准 {item.tool_name}（{item.risk}，{item.scope}）"
                if resolution.ok
                else f"审批失败：{resolution.reason}",
            )
        else:
            resolution = self._approvals.reject(code)
            await self._send(
                event.user_id,
                f"已拒绝 {item.tool_name}" if resolution.ok else f"拒绝失败：{resolution.reason}",
            )
        return {"status": "approval_handled"}

    async def _send(self, user_id: int, text: str) -> None:
        try:
            self._sender.send_private_message(user_id, text)
        except Exception:
            logger.exception("QQ 回复发送失败 user=%s", user_id)

    async def _save_qq_file(
        self, user_id: int, source: str, name: str | None
    ) -> dict[str, str] | None:
        target_dir = self._settings.data_dir / "qq_files"
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(name or "file").name or f"file-{uuid4()}"
        target = target_dir / f"{uuid4()}-{safe_name}"
        if source.startswith("http://") or source.startswith("https://"):
            try:
                content = await self._download(source)
                target.write_bytes(content)
            except Exception:
                logger.exception("QQ 文件下载失败 url=%s", source)
                return None
        elif Path(source).exists():
            target.write_bytes(Path(source).read_bytes())
        else:
            return None
        return {"name": safe_name, "path": str(target)}

    async def _download(self, url: str, max_bytes: int = 16 * 1024 * 1024) -> bytes:
        trust_env = url.startswith(("https://",))
        async with httpx.AsyncClient(timeout=30.0, trust_env=trust_env) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content[:max_bytes]

    async def _download_as_data_url(self, url: str) -> str | None:
        try:
            content = await self._download(url)
            mime = "image/png"
            if url.lower().endswith((".jpg", ".jpeg")):
                mime = "image/jpeg"
            elif url.lower().endswith(".gif"):
                mime = "image/gif"
            elif url.lower().endswith(".webp"):
                mime = "image/webp"
            encoded = base64.b64encode(content).decode("ascii")
            return f"data:{mime};base64,{encoded}"
        except Exception:
            logger.exception("QQ 图片下载失败 url=%s", url)
            return None
