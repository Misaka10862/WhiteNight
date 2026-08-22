"""Managed Hermes Gateway adapter using its structured WebSocket JSON-RPC API."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from websockets.asyncio.client import ClientConnection, connect

from whitenight.delegates.base import DelegateError, DelegateUnavailableError
from whitenight.delegates.events import DelegateEvent, DelegationRequest
from whitenight.policy.approvals import ApprovalService


class HermesProcessManager:
    """Own one local Hermes process and never attach to or stop an unknown one."""

    def __init__(
        self,
        base_url: str,
        command: str,
        key_provider: Callable[[], str | None],
        startup_timeout_s: float = 45.0,
        managed: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.command = command
        self.key_provider = key_provider
        self.startup_timeout_s = startup_timeout_s
        self.managed = managed
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def ensure_started(self) -> None:
        if not self.managed:
            if not await self._reachable():
                raise DelegateUnavailableError("Hermes Gateway 未运行")
            return
        async with self._lock:
            if self._process is not None and self._process.returncode is None:
                return
            if await self._reachable():
                raise DelegateUnavailableError(
                    "Hermes Gateway 端口已被非托管进程占用；WhiteNight 不会连接或终止它"
                )
            key = self.key_provider()
            if not key:
                raise DelegateUnavailableError(
                    "DeepSeek API Key 未配置；运行 `uv run whitenight credentials set deepseek`"
                )
            parsed = urlparse(self.base_url)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
                raise DelegateUnavailableError("托管 Hermes Gateway 必须使用本机 HTTP 回环地址")
            port = parsed.port or 9119
            command = shutil.which(self.command)
            if command is None:
                fallback = Path.home() / ".local" / "bin" / self.command
                command = str(fallback) if fallback.is_file() else None
            if command is None:
                raise DelegateUnavailableError(f"找不到 Hermes 命令：{self.command}")
            env = os.environ.copy()
            env["DEEPSEEK_API_KEY"] = key
            self._process = await asyncio.create_subprocess_exec(
                command,
                "serve",
                "--host",
                parsed.hostname or "127.0.0.1",
                "--port",
                str(port),
                "--skip-build",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            if self._process.stderr is not None:
                self._stderr_task = asyncio.create_task(self._drain_stderr(self._process.stderr))
            deadline = asyncio.get_running_loop().time() + self.startup_timeout_s
            while asyncio.get_running_loop().time() < deadline:
                if self._process.returncode is not None:
                    raise DelegateUnavailableError(
                        f"Hermes Gateway 启动失败：exit {self._process.returncode}"
                    )
                if await self._reachable():
                    return
                await asyncio.sleep(0.25)
            await self.stop()
            raise DelegateUnavailableError("Hermes Gateway 启动超时")

    async def health(self) -> dict[str, object]:
        return {
            "provider": "hermes-gateway",
            "available": await self._reachable(),
            "managed": self.managed,
            "owned": self._process is not None and self._process.returncode is None,
            "credential_configured": bool(self.key_provider()),
        }

    async def stop(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                process.kill()
                await process.wait()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            await asyncio.gather(self._stderr_task, return_exceptions=True)
            self._stderr_task = None

    async def _reachable(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=1.0, trust_env=False) as client:
                response = await client.get(f"{self.base_url}/api/status")
            return response.status_code == 200
        except Exception:
            return False

    @staticmethod
    async def _drain_stderr(stream: asyncio.StreamReader) -> None:
        while await stream.readline():
            pass


@dataclass
class _LiveApproval:
    task_id: str
    session_id: str
    connection: ClientConnection
    send_lock: asyncio.Lock


class ManagedHermesGatewayAdapter:
    name = "hermes"

    def __init__(
        self,
        manager: HermesProcessManager,
        approvals: ApprovalService,
        *,
        base_url: str,
        provider: str = "deepseek",
        model: str = "deepseek-v4-flash-vision-exp",
        timeout_s: float = 1800.0,
    ) -> None:
        self.manager = manager
        self.approvals = approvals
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.model = model
        self.timeout_s = timeout_s
        self._approvals: dict[str, _LiveApproval] = {}
        self._runs: dict[str, _LiveApproval] = {}

    async def health(self) -> dict[str, object]:
        status = await self.manager.health()
        status.update({"model": self.model, "inference_provider": self.provider})
        return status

    async def submit(self, request: DelegationRequest) -> AsyncIterator[DelegateEvent]:
        await self.manager.ensure_started()
        parsed = urlparse(self.base_url)
        ws_url = f"ws://{parsed.netloc}/api/ws"
        try:
            async with asyncio.timeout(self.timeout_s):
                async with connect(ws_url, max_size=16 * 1024 * 1024) as websocket:
                    ready = json.loads(await websocket.recv())
                    if ((ready.get("params") or {}).get("type")) != "gateway.ready":
                        raise DelegateError("Hermes Gateway 未发送 gateway.ready")
                    send_lock = asyncio.Lock()
                    session_result = await self._open_session(websocket, request, send_lock)
                    session_id = str(session_result.get("session_id") or "")
                    stored_session_id = str(
                        session_result.get("stored_session_id") or request.thread_id or session_id
                    )
                    live = _LiveApproval(request.task_id, session_id, websocket, send_lock)
                    self._runs[request.task_id] = live
                    yield DelegateEvent(
                        task_id=request.task_id,
                        executor="hermes",
                        type="started",
                        step="gateway",
                        label="Hermes Gateway 已连接",
                        detail=f"provider={self.provider} model={self.model}",
                        payload={"thread_id": stored_session_id},
                    )
                    image_data = request.metadata.get("image_data_url")
                    if isinstance(image_data, str) and image_data:
                        await self._rpc(
                            websocket,
                            send_lock,
                            "image.attach_bytes",
                            {"session_id": session_id, "content_base64": image_data},
                            "attach",
                        )
                    await self._send(
                        websocket,
                        send_lock,
                        "prompt.submit",
                        {"session_id": session_id, "text": request.prompt},
                        "prompt",
                    )
                    async for event in self._read_turn(
                        websocket, request, session_id, stored_session_id, send_lock
                    ):
                        yield event
        except TimeoutError as exc:
            raise DelegateError("Hermes 任务超时") from exc
        finally:
            self._runs.pop(request.task_id, None)
            for code, item in list(self._approvals.items()):
                if item.task_id == request.task_id:
                    self._approvals.pop(code, None)

    async def respond_approval(self, code: str, allow: bool) -> bool:
        live = self._approvals.get(code)
        if live is None:
            return False
        pending = [item for item in self.approvals.list_pending() if item.code == code]
        if not pending:
            return False
        item = pending[0]
        resolution = (
            self.approvals.resolve_once(code, session_id=item.session_id, expected_scope="once")
            if allow
            else self.approvals.reject(code)
        )
        if not resolution.ok:
            return False
        await self._send(
            live.connection,
            live.send_lock,
            "approval.respond",
            {"session_id": live.session_id, "choice": "allow-once" if allow else "deny"},
            f"approval-{code}",
        )
        self._approvals.pop(code, None)
        return True

    async def abort(self, task_id: str, thread_id: str | None = None) -> bool:
        del thread_id
        live = self._runs.get(task_id)
        if live is None:
            return False
        await self._send(
            live.connection,
            live.send_lock,
            "session.interrupt",
            {"session_id": live.session_id},
            f"abort-{task_id}",
        )
        return True

    async def close(self) -> None:
        await self.manager.stop()

    async def _open_session(
        self,
        websocket: ClientConnection,
        request: DelegationRequest,
        send_lock: asyncio.Lock,
    ) -> dict[str, Any]:
        if request.thread_id:
            return await self._rpc(
                websocket,
                send_lock,
                "session.resume",
                {"session_id": request.thread_id, "cwd": request.cwd or ""},
                "session",
            )
        return await self._rpc(
            websocket,
            send_lock,
            "session.create",
            {
                "cwd": request.cwd or "",
                "source": "whitenight",
                "close_on_disconnect": False,
                "provider": self.provider,
                "model": self.model,
            },
            "session",
        )

    async def _read_turn(
        self,
        websocket: ClientConnection,
        request: DelegationRequest,
        session_id: str,
        stored_session_id: str,
        send_lock: asyncio.Lock,
    ) -> AsyncIterator[DelegateEvent]:
        while True:
            payload = json.loads(await websocket.recv())
            if payload.get("error"):
                raise DelegateError(str((payload.get("error") or {}).get("message") or "RPC error"))
            if payload.get("method") != "event":
                continue
            params = payload.get("params") or {}
            if params.get("session_id") not in {None, "", session_id}:
                continue
            event_type = str(params.get("type") or "")
            body = params.get("payload") or {}
            if event_type == "message.delta":
                yield DelegateEvent(
                    task_id=request.task_id,
                    executor="hermes",
                    type="progress",
                    step="model",
                    label="Hermes 正在回复",
                    detail=str(body.get("text") or ""),
                )
            elif event_type in {"tool.start", "tool.complete"}:
                yield DelegateEvent(
                    task_id=request.task_id,
                    executor="hermes",
                    type="progress",
                    step="tool",
                    label=str(body.get("name") or "Hermes 工具"),
                    detail=str(body.get("summary") or ""),
                    payload={"tool_id": body.get("tool_id")},
                )
            elif event_type == "approval.request":
                approval = self.approvals.request(
                    tool_name="delegate.hermes.action",
                    risk=str(request.metadata.get("risk") or "high"),
                    scope="once",
                    params_summary=json.dumps(body, ensure_ascii=False, default=str)[:2000],
                    session_id=(
                        str(request.metadata["whitenight_session_id"])
                        if request.metadata.get("whitenight_session_id")
                        else None
                    ),
                    channel=(
                        str(request.metadata["channel"])
                        if request.metadata.get("channel")
                        else None
                    ),
                )
                self._approvals[approval.code] = _LiveApproval(
                    request.task_id, session_id, websocket, send_lock
                )
                yield DelegateEvent(
                    task_id=request.task_id,
                    executor="hermes",
                    type="approval_required",
                    step="approval",
                    label="Hermes 操作需要审批",
                    detail=f"审批编号：{approval.code}",
                    approval_id=approval.id,
                    payload={"approval_code": approval.code},
                )
            elif event_type == "message.complete":
                yield DelegateEvent(
                    task_id=request.task_id,
                    executor="hermes",
                    type="result",
                    step="complete",
                    label="Hermes 已完成",
                    detail=str(body.get("text") or ""),
                    payload={"thread_id": stored_session_id},
                )
                return
            elif event_type == "error":
                raise DelegateError(str(body.get("message") or "Hermes Gateway 错误"))

    @staticmethod
    async def _send(
        websocket: ClientConnection,
        send_lock: asyncio.Lock,
        method: str,
        params: dict[str, object],
        request_id: str,
    ) -> None:
        async with send_lock:
            await websocket.send(
                json.dumps(
                    {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
                    ensure_ascii=False,
                )
            )

    @classmethod
    async def _rpc(
        cls,
        websocket: ClientConnection,
        send_lock: asyncio.Lock,
        method: str,
        params: dict[str, object],
        request_id: str,
    ) -> dict[str, Any]:
        await cls._send(websocket, send_lock, method, params, request_id)
        while True:
            payload = json.loads(await websocket.recv())
            if payload.get("id") != request_id:
                continue
            if payload.get("error"):
                raise DelegateError(str((payload.get("error") or {}).get("message") or "RPC error"))
            result = payload.get("result") or {}
            return result if isinstance(result, dict) else {}
