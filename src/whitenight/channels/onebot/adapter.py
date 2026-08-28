"""OneBot 11 Adapter：幂等去重、所有者白名单、顺序处理、限频与回复分片。

群聊事件一律忽略（首版只支持私聊）。QQ 内审批使用一次性编号。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
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
from whitenight.channels.types import ChannelContext, ChatRequest
from whitenight.config import Settings
from whitenight.personality.store import PersonalityStore
from whitenight.policy.approvals import ApprovalService
from whitenight.storage.sessions import SessionStore

logger = logging.getLogger(__name__)

_APPROVE_RE = re.compile(r"^(?:同意|批准|允许)\s+([A-Za-z0-9_-]{6,16})$")
_REJECT_RE = re.compile(r"^(?:拒绝|不同意)\s+([A-Za-z0-9_-]{6,16})$")
_APPROVAL_WITHOUT_CODE_RE = re.compile(r"^(?:同意|批准|允许|允许操作)[！!。.]?$")
_CHARACTER_RE = re.compile(r"^/角色(?:\s+(.+))?$")


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
        personalities: PersonalityStore | None = None,
    ) -> None:
        self._settings = settings
        self._sessions = sessions
        self._channel_sessions = channel_sessions
        self._chat = chat_service
        self._approvals = approvals
        self._sender = sender or OneBotSender(
            settings.qq_onebot_api_url, settings.qq_reply_max_chars
        )
        self._personalities = personalities
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
        if event.post_type != "message":
            return {"status": "ignored_post_type"}
        if event.message_type != "private":
            return {"status": "ignored_group"}

        user_id = event.user_id
        if user_id not in self.owner_ids():
            return {"status": "ignored_not_owner"}

        if not self._dedupe.accept(str(event.message_id), user_id):
            return {"status": "duplicate"}

        raw_text = event.raw_message.strip()
        if _APPROVE_RE.match(raw_text) or _REJECT_RE.match(raw_text):
            return await self._process_owner_message(event)

        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            delay = self._rate.wait_seconds(user_id)
            if delay > 0:
                await asyncio.sleep(delay)
            return await self._process_owner_message(event)

    async def _process_owner_message(self, event: OneBotPrivateMessageEvent) -> dict[str, object]:
        parsed = parse_segments(event)
        logger.info(
            "QQ 私聊处理 user_id=%s message_id=%s segments=%s poke=%s text=%r",
            event.user_id,
            event.message_id,
            parsed.segments,
            parsed.is_poke,
            parsed.text[:50],
        )

        if parsed.empty:
            return {"status": "ignored_empty"}

        session_id = self._channel_sessions.get_or_create("onebot", str(event.user_id))

        character_command = _CHARACTER_RE.fullmatch(parsed.text.strip())
        if character_command and self._personalities is not None:
            requested = (character_command.group(1) or "").strip()
            if not requested:
                current_id, _persona_id = self._personalities.session_identity(session_id)
                current = self._personalities.get_character(current_id)
                names = "、".join(item.name for item in self._personalities.list_characters())
                await self._send(event.user_id, f"当前角色：{current.name}\n可用角色：{names}")
                return {"status": "character_list", "session_id": session_id}
            character = self._personalities.find_character(requested)
            if character is None:
                await self._send(event.user_id, f"没有找到角色：{requested}")
                return {"status": "character_not_found", "session_id": session_id}
            previous_id, new_session_id = self._channel_sessions.reset(
                "onebot",
                str(event.user_id),
                character_id=character.id,
                persona_id=self._personalities.default_persona_id(),
                greeting=character.card.data.first_mes or None,
            )
            await self._send(event.user_id, f"已切换到角色：{character.name}")
            if character.card.data.first_mes:
                await self._send(event.user_id, character.card.data.first_mes)
            return {
                "status": "character_switched",
                "previous_session_id": previous_id,
                "session_id": new_session_id,
                "character_id": character.id,
            }

        approval = await self._handle_approval_command(event, parsed.text, session_id)
        if approval is not None:
            return approval

        if parsed.text.strip().lower() == "/clear":
            previous_id, new_session_id = self._channel_sessions.reset("onebot", str(event.user_id))
            logger.info(
                "QQ 上下文已重置 user_id=%s previous_session=%s new_session=%s",
                event.user_id,
                previous_id,
                new_session_id,
            )
            await self._send(event.user_id, "上下文窗口已清空，旧会话记录仍保留。")
            return {
                "status": "context_reset",
                "previous_session_id": previous_id,
                "session_id": new_session_id,
            }

        if (parsed.file_path or parsed.file_id) and not parsed.image_data_url:
            saved = await self._save_qq_file(
                event.user_id,
                parsed.file_path or "",
                parsed.file_name,
                parsed.file_id,
            )
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

        # NapCat 会把“戳一戳”上报成 poke 消息段（文本为空）。转为显式上下文，
        # 让模型知道发生了什么，同时在会话里留下可见记录而不是“（空消息）”。
        request_text = parsed.text
        if parsed.is_poke and not request_text.strip():
            request_text = f"（主人刚刚在QQ上戳了戳我，戳一戳类型：{parsed.poke_type or '未知'}）"

        request = ChatRequest(
            session_id=session_id,
            text=request_text,
            image_data_url=image_data_url,
        )
        reply: str | None = None
        task_note_sent = False
        owner_user_id = event.user_id
        async for chat_event in self._chat.stream_reply(
            request, ChannelContext(channel="onebot", target=str(event.user_id))
        ):
            if chat_event.type == "task" and not task_note_sent:
                delegate = (chat_event.extra or {}).get("delegate_event", {})
                if isinstance(delegate, dict) and delegate.get("type") in {"started", "error"}:
                    await self._send(
                        owner_user_id,
                        f"[任务] {delegate.get('label', '')}",
                    )
                    task_note_sent = True
            elif chat_event.type == "task":
                delegate = (chat_event.extra or {}).get("delegate_event", {})
                if isinstance(delegate, dict) and delegate.get("type") == "approval_required":
                    await self._send(
                        owner_user_id,
                        f"[审批] {delegate.get('label', '')}：{delegate.get('detail', '')}",
                    )
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
            if _APPROVAL_WITHOUT_CODE_RE.fullmatch(text.strip()):
                pending = [
                    item
                    for item in self._approvals.list_pending()
                    if item.session_id == session_id and item.channel == "onebot"
                ]
                if len(pending) == 1:
                    code = pending[0].code
                    await self._send(
                        event.user_id,
                        f"审批必须带一次性编号。请回复：同意 {code}，或：拒绝 {code}。",
                    )
                    return {"status": "approval_code_required"}
                if len(pending) > 1:
                    choices = "；".join(f"{item.tool_name}：{item.code}" for item in pending)
                    await self._send(
                        event.user_id,
                        f"有多个待审批操作，请带编号回复“同意 <编号>”或“拒绝 <编号>”：{choices}",
                    )
                    return {"status": "approval_code_required"}
                await self._send(event.user_id, "当前没有有效的待审批操作，请重新发起文件操作。")
                return {"status": "approval_invalid"}
            return None
        match = approve_match if approve_match else reject_match
        assert match is not None
        code = match.group(1)
        pending = [item for item in self._approvals.list_pending() if item.code == code]
        if not pending:
            await self._send(event.user_id, "审批编号无效、已过期或已处理")
            return {"status": "approval_invalid"}

        item = pending[0]
        if item.tool_name == "delegate.hermes.action":
            delegates = self._chat._delegates
            hermes = delegates.providers().get("hermes") if delegates else None
            responder = getattr(hermes, "respond_approval", None)
            ok = bool(responder and await responder(code, bool(approve_match)))
            await self._send(
                event.user_id,
                (
                    "已批准并恢复 Hermes"
                    if ok and approve_match
                    else "已拒绝 Hermes 操作"
                    if ok
                    else "Hermes 审批无法恢复"
                ),
            )
            return {"status": "approval_handled" if ok else "approval_failed"}
        if approve_match:
            continuation = (
                self._chat._pending_tools.get_by_code(code) if self._chat._pending_tools else None
            )
            if continuation is not None:
                events = await self._chat.resume_approval(
                    code,
                    ChannelContext(channel="onebot", target=str(event.user_id)),
                )
                final = events[-1] if events else None
                if final is not None and final.type == "done":
                    await self._send(event.user_id, final.text or "操作已完成")
                    return {"status": "approval_handled"}
                await self._send(
                    event.user_id,
                    f"审批后执行失败：{(final.message if final else None) or '未知错误'}",
                )
                return {"status": "approval_failed"}
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
            continuation = (
                self._chat._pending_tools.get_by_code(code) if self._chat._pending_tools else None
            )
            if continuation is not None:
                reason = await self._chat.reject_approval(
                    code,
                    ChannelContext(channel="onebot", target=str(event.user_id)),
                )
                await self._send(event.user_id, reason)
                return {"status": "approval_handled"}
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
        self,
        user_id: int,
        source: str,
        name: str | None,
        file_id: str | None = None,
    ) -> dict[str, str] | None:
        target_dir = (self._settings.data_dir / "qq_files").resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(name or "file").name or f"file-{uuid4()}"
        target = target_dir / f"{uuid4()}-{safe_name}"
        resolved_source = source
        if not self._is_usable_file_source(resolved_source) and file_id:
            try:
                metadata = self._sender.get_file(file_id)
                resolved_source = self._file_source_from_metadata(metadata) or ""
                resolved_name = metadata.get("file_name") or metadata.get("name")
                if isinstance(resolved_name, str) and resolved_name:
                    safe_name = Path(resolved_name).name or safe_name
                    target = target_dir / f"{uuid4()}-{safe_name}"
            except Exception:
                logger.exception("QQ 文件元数据获取失败 file_id=%s", file_id)
                return None
        if resolved_source.startswith("http://") or resolved_source.startswith("https://"):
            try:
                content = await self._download(resolved_source)
                target.write_bytes(content)
            except Exception:
                logger.exception("QQ 文件下载失败 url=%s", resolved_source)
                return None
        elif resolved_source.startswith("base64://"):
            try:
                content = base64.b64decode(resolved_source.removeprefix("base64://"), validate=True)
            except (ValueError, binascii.Error):
                logger.warning("QQ 文件 base64 内容无效 file_id=%s", file_id)
                return None
            if len(content) > 16 * 1024 * 1024:
                logger.warning("QQ 文件超过接收大小限制 file_id=%s", file_id)
                return None
            target.write_bytes(content)
        elif Path(resolved_source).is_file() and not Path(resolved_source).is_symlink():
            source_path = Path(resolved_source)
            if source_path.stat().st_size > 16 * 1024 * 1024:
                logger.warning("QQ 文件超过接收大小限制 path=%s", source_path)
                return None
            target.write_bytes(source_path.read_bytes())
        else:
            return None
        return {"name": safe_name, "path": str(target)}

    @staticmethod
    def _is_usable_file_source(source: str) -> bool:
        return bool(
            source.startswith(("http://", "https://", "base64://"))
            or (Path(source).is_file() and not Path(source).is_symlink())
        )

    @staticmethod
    def _file_source_from_metadata(metadata: dict[str, object]) -> str | None:
        for key in ("url", "file", "path"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                return value
        encoded = metadata.get("base64")
        if isinstance(encoded, str) and encoded:
            return encoded if encoded.startswith("base64://") else f"base64://{encoded}"
        return None

    async def _download(self, url: str, max_bytes: int = 16 * 1024 * 1024) -> bytes:
        content, _ = await self._download_content(url, max_bytes=max_bytes)
        return content

    async def _download_content(
        self, url: str, max_bytes: int = 16 * 1024 * 1024
    ) -> tuple[bytes, str | None]:
        # OneBot/NapCat URLs are often local HTTP endpoints. Never inherit a
        # desktop proxy here: it can turn a valid local download into a 502.
        async with (
            httpx.AsyncClient(timeout=30.0, trust_env=False, follow_redirects=True) as client,
            client.stream("GET", url) as response,
        ):
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                raise ValueError("下载文件超过大小限制")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("下载文件超过大小限制")
                chunks.append(chunk)
            return b"".join(chunks), response.headers.get("content-type")

    async def _download_as_data_url(self, url: str) -> str | None:
        try:
            content, content_type = await self._download_content(url)
            mime = (content_type or "").split(";", 1)[0].strip() or ""
            if not mime.startswith("image/"):
                mime = "image/png"
                if url.lower().split("?", 1)[0].endswith((".jpg", ".jpeg")):
                    mime = "image/jpeg"
                elif url.lower().split("?", 1)[0].endswith(".gif"):
                    mime = "image/gif"
                elif url.lower().split("?", 1)[0].endswith(".webp"):
                    mime = "image/webp"
            encoded = base64.b64encode(content).decode("ascii")
            return f"data:{mime};base64,{encoded}"
        except Exception:
            logger.exception("QQ 图片下载失败 url=%s", url)
            return None
