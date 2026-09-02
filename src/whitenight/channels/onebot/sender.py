"""OneBot 11 发送器：私聊文字/原生表情/文件 + 限频 + 分片 + 有限重试。"""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import cast

import httpx

logger = logging.getLogger(__name__)


class OneBotSendError(RuntimeError):
    """OneBot API 发送失败。"""


def split_text(text: str, max_chars: int = 4000) -> list[str]:
    """按段落边界把长回复切成不超过 max_chars 的分片。"""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n"):
        while len(paragraph) > max_chars:
            chunks.append(paragraph[:max_chars])
            paragraph = paragraph[max_chars:]
        if current and len(current) + 1 + len(paragraph) > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


class OneBotSender:
    """经 OneBot HTTP API 发送消息；失败有限重试并返回错误。"""

    def __init__(
        self,
        api_url: str,
        reply_max_chars: int = 4000,
        timeout_s: float = 20.0,
        max_attempts: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.reply_max_chars = reply_max_chars
        self.timeout = httpx.Timeout(timeout_s, connect=5.0)
        self.max_attempts = max_attempts
        self._transport = transport
        self._last_error: str | None = None

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, trust_env=False, transport=self._transport)

    def send_private_message(self, user_id: int, text: str) -> int:
        """分片发送；返回成功发送的分片数。"""
        if not text:
            return 0
        sent = 0
        for chunk in split_text(text, self.reply_max_chars):
            self._post("/send_private_msg", json={"user_id": user_id, "message": chunk})
            sent += 1
        return sent

    def send_private_mface(
        self,
        user_id: int,
        *,
        segment_type: str,
        emoji_id: str,
        emoji_package_id: str | None = None,
        key: str | None = None,
    ) -> int:
        """Send a registered QQ native animated/custom face segment."""
        if segment_type not in {"mface", "market_face"} or not emoji_id:
            raise OneBotSendError("QQ 原生表情标识不完整")
        data: dict[str, str] = {"emoji_id": emoji_id}
        if emoji_package_id:
            data["emoji_package_id"] = emoji_package_id
        if key:
            data["key"] = key
        self._post(
            "/send_private_msg",
            json={
                "user_id": user_id,
                "message": [{"type": segment_type, "data": data}],
            },
        )
        return 1

    def upload_private_file(self, user_id: int, path: str | Path, name: str) -> None:
        path = Path(path)
        if not path.is_file() or path.is_symlink():
            raise OneBotSendError(f"文件不存在：{path}")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        self._post(
            "/upload_private_file",
            json={"user_id": user_id, "file": f"base64://{encoded}", "name": name},
        )

    def upload_file(self, target: str, path: str, name: str) -> None:
        try:
            user_id = int(target)
        except ValueError as exc:
            raise OneBotSendError("QQ 文件目标必须是数字帐号") from exc
        self.upload_private_file(user_id, path, name)

    def get_file(self, file_id: str) -> dict[str, object]:
        """Resolve OneBot file metadata without trusting fields from the chat event."""
        payload = self._post("/get_file", json={"file_id": file_id})
        data = payload.get("data")
        if not isinstance(data, dict):
            raise OneBotSendError("OneBot get_file 返回缺少 data")
        return cast(dict[str, object], data)

    def get_message(self, message_id: int | str) -> dict[str, object]:
        """Fetch the original OneBot message referenced by a reply segment."""
        payload = self._post("/get_msg", json={"message_id": message_id})
        data = payload.get("data")
        if not isinstance(data, dict):
            raise OneBotSendError("OneBot get_msg 返回缺少 data")
        return cast(dict[str, object], data)

    def get_image(self, file_id: str) -> dict[str, object]:
        """Resolve an image reference through OneBot's standard get_image action."""
        payload = self._post("/get_image", json={"file": file_id})
        data = payload.get("data")
        if not isinstance(data, dict):
            raise OneBotSendError("OneBot get_image 返回缺少 data")
        return cast(dict[str, object], data)

    def health(self) -> bool:
        """Return whether the OneBot HTTP endpoint is reachable and logged in."""
        return bool(self.health_detail()["logged_in"])

    def health_detail(self) -> dict[str, object]:
        """Return safe, structured OneBot reachability/login diagnostics."""
        try:
            with self._client() as client:
                response = client.get(f"{self.api_url}/get_login_info")
            if response.status_code != 200:
                return {
                    "reachable": True,
                    "logged_in": False,
                    "http_status": response.status_code,
                    "reason": "http_error",
                    "last_error": self._last_error,
                }
            payload = response.json()
            if not isinstance(payload, dict):
                return {
                    "reachable": True,
                    "logged_in": False,
                    "reason": "invalid_json",
                    "last_error": self._last_error,
                }
            ok = payload.get("status") == "ok" and payload.get("retcode", 0) == 0
            return {
                "reachable": True,
                "logged_in": bool(ok),
                "reason": "ok" if ok else "not_logged_in",
                "last_error": self._last_error,
            }
        except httpx.ConnectError:
            return {
                "reachable": False,
                "logged_in": False,
                "reason": "connection_refused",
                "last_error": self._last_error,
            }
        except httpx.TimeoutException:
            return {
                "reachable": False,
                "logged_in": False,
                "reason": "timeout",
                "last_error": self._last_error,
            }
        except (httpx.HTTPError, ValueError):
            logger.debug("OneBot health probe failed", exc_info=True)
            return {
                "reachable": False,
                "logged_in": False,
                "reason": "probe_failed",
                "last_error": self._last_error,
            }

    def _post(
        self,
        endpoint: str,
        *,
        json: dict[str, object] | None = None,
    ) -> dict[str, object]:
        last_error = "unknown"
        for attempt in range(1, self.max_attempts + 1):
            try:
                with self._client() as client:
                    response = client.post(f"{self.api_url}{endpoint}", json=json)
            except httpx.HTTPError as exc:
                last_error = str(exc)
                self._last_error = f"{type(exc).__name__}: {last_error[:200]}"
                if attempt < self.max_attempts:
                    time.sleep(0.5 * attempt)
                    continue
                break

            body = response.text[:1000]
            if response.status_code >= 500:
                last_error = f"HTTP {response.status_code}: {body}"
                self._last_error = f"HTTP {response.status_code}"
                if attempt < self.max_attempts:
                    time.sleep(0.5 * attempt)
                    continue
                break
            if response.status_code != 200:
                self._last_error = f"HTTP {response.status_code}"
                raise OneBotSendError(f"HTTP {response.status_code}: {body}")
            try:
                payload = response.json()
            except ValueError as exc:
                self._last_error = "invalid_json"
                raise OneBotSendError("OneBot 返回了无效 JSON") from exc
            if payload.get("retcode") not in (0, None) or payload.get("status") == "failed":
                self._last_error = "onebot_business_error"
                raise OneBotSendError(str(payload))
            self._last_error = None
            return dict(payload)
        raise OneBotSendError(last_error)

    def send(self, message: str, metadata: dict[str, object]) -> bool:
        """ProactiveSender 协议适配（同步）：目标 QQ 号来自 metadata。"""
        user_id = metadata.get("user_id")
        if not isinstance(user_id, int) or user_id <= 0:
            return False
        try:
            return self.send_private_message(user_id, message) > 0
        except OneBotSendError:
            return False
