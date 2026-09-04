"""Codex MCP Adapter：官方 stdio MCP，支持可恢复线程。

阶段 1 已实测 initialize/tools 握手；本适配器只消费 MCP 协议输出，
不解析终端文本。任务级调用需要用户已登录 Codex（~/.codex/auth.json）。
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import asdict
from typing import Any

from whitenight.delegates.base import DelegateCapabilities, DelegateError, DelegateUnavailableError
from whitenight.delegates.events import DelegateEvent, DelegationRequest

_PROTOCOL_VERSION = "2025-03-26"
_TOOL_NEW = "codex"
_TOOL_RESUME = "codex-reply"


class CodexMcpClient:
    """最小 JSON-RPC/stdio MCP 客户端。"""

    def __init__(
        self,
        command: str = "codex",
        timeout_s: float = 1800.0,
        startup_timeout_s: float = 60.0,
    ) -> None:
        self._command = command
        self._timeout_s = timeout_s
        self._startup_timeout_s = startup_timeout_s
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._close_lock = asyncio.Lock()
        self._reader: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._process is not None:
            return
        try:
            self._process = await asyncio.create_subprocess_exec(
                self._command,
                "mcp-server",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise DelegateUnavailableError(
                "codex CLI 未安装：npm install -g @openai/codex"
            ) from exc
        assert self._process.stdout is not None
        self._reader = asyncio.create_task(self._read_loop())
        await self._request(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "whitenight", "version": "0.1.0"},
            },
        )
        await self._notify("notifications/initialized", {})

    async def _read_loop(self) -> None:
        assert self._process and self._process.stdout
        stdout = self._process.stdout
        while True:
            line = await stdout.readline()
            if not line:
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(DelegateError("Codex MCP 进程意外退出"))
                self._pending.clear()
                return
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in message and message["id"] in self._pending:
                future = self._pending.pop(message["id"])
                if future.done():
                    continue
                if "error" in message:
                    future.set_exception(DelegateError(str(message["error"])))
                else:
                    future.set_result(message.get("result", {}))

    async def _request(
        self,
        method: str,
        params: dict[str, Any],
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        if self._process is None or self._process.stdin is None:
            raise DelegateError("Codex MCP 客户端未启动")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self._process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await self._process.stdin.drain()
        try:
            return await asyncio.wait_for(
                future,
                timeout=self._startup_timeout_s if timeout_s is None else timeout_s,
            )
        finally:
            self._pending.pop(request_id, None)

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await self._process.stdin.drain()

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._request("tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            return []
        return [dict(tool) for tool in tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self._request(
                "tools/call",
                {"name": name, "arguments": arguments},
                timeout_s=self._timeout_s,
            )
        except TimeoutError as exc:
            raise DelegateError("Codex 任务超时") from exc
        if result.get("isError") is True:
            detail, _ = _extract_codex_result(result)
            message = detail or "Codex MCP 工具返回失败"
            if any(marker in message.lower() for marker in ("403", "401", "cloudflare")):
                raise DelegateUnavailableError(message)
            raise DelegateError(message)
        return result

    async def close(self) -> None:
        async with self._close_lock:
            if self._process is None:
                return
            process = self._process
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
                # The MCP parent may exit before children that ignored SIGTERM.
                # The session belongs to this task, so terminate any remaining group members.
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            self._process = None
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(DelegateError("Codex 执行进程已停止"))
            self._pending.clear()
            if self._reader is not None:
                self._reader.cancel()
                await asyncio.gather(self._reader, return_exceptions=True)
                self._reader = None


class CodexAdapter:
    """Codex 编码任务执行器（MCP stdio）。"""

    name = "codex"
    capabilities = DelegateCapabilities(read_only=True)

    def __init__(self, command: str = "codex", timeout_s: float = 1800.0) -> None:
        self._command = command
        self._timeout_s = timeout_s
        self._clients: dict[str, CodexMcpClient] = {}
        self._starts: dict[str, asyncio.Task[None]] = {}

    async def health(self) -> dict[str, object]:
        client = CodexMcpClient(self._command)
        try:
            await client.start()
            tools = await client.list_tools()
            return {
                "provider": "codex-mcp",
                "available": True,
                "tools": [tool.get("name") for tool in tools],
                "execution_capabilities": asdict(self.capabilities),
                "limitation": "仅支持明确只读任务；写任务需要逐动作策略契约",
            }
        except Exception as exc:
            return {"provider": "codex-mcp", "available": False, "error": str(exc)}
        finally:
            await client.close()

    async def submit(self, request: DelegationRequest) -> AsyncIterator[DelegateEvent]:
        if request.sandbox != "read-only" or request.thread_id:
            # codex-reply cannot override an existing thread's sandbox. Never resume
            # a thread whose original permissions have not been verified locally.
            raise DelegateUnavailableError("Codex 当前仅允许新建只读隔离任务")
        client = CodexMcpClient(self._command, timeout_s=self._timeout_s)
        self._clients[request.task_id] = client
        try:
            start = asyncio.create_task(client.start())
            self._starts[request.task_id] = start
            await start
            yield DelegateEvent(
                task_id=request.task_id,
                executor="codex",
                type="started",
                step="codex-mcp",
                label="Codex 会话已启动",
                detail="官方 MCP 协议；不解析终端文本",
            )
            if request.thread_id:
                result = await client.call_tool(
                    _TOOL_RESUME,
                    {"threadId": request.thread_id, "prompt": request.prompt},
                )
            else:
                arguments: dict[str, Any] = {"prompt": request.prompt}
                if request.cwd:
                    arguments["cwd"] = request.cwd
                if request.sandbox:
                    arguments["sandbox"] = request.sandbox
                else:
                    arguments["sandbox"] = "workspace-write"
                arguments["approval-policy"] = "never"
                result = await client.call_tool(_TOOL_NEW, arguments)

            content, thread_id = _extract_codex_result(result)
            yield DelegateEvent(
                task_id=request.task_id,
                executor="codex",
                type="result",
                step="codex-mcp",
                label="Codex 任务完成",
                detail=content,
                payload={"thread_id": thread_id} if thread_id else {},
            )
        except DelegateError:
            raise
        except Exception as exc:
            raise DelegateError(f"Codex MCP 调用失败：{exc}") from exc
        finally:
            await client.close()
            self._clients.pop(request.task_id, None)
            self._starts.pop(request.task_id, None)

    async def abort(self, task_id: str, thread_id: str | None = None) -> bool:
        del thread_id
        client = self._clients.get(task_id)
        if client is None:
            return False
        start = self._starts.get(task_id)
        if start is not None:
            # Do not report stopped while subprocess startup can still complete.
            with suppress(Exception):
                await asyncio.shield(start)
        await client.close()
        return True


def _extract_codex_result(result: dict[str, Any]) -> tuple[str, str | None]:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        content = structured.get("content")
        thread_id = structured.get("threadId")
        return (
            content if isinstance(content, str) else "",
            thread_id if isinstance(thread_id, str) else None,
        )

    text_parts: list[str] = []
    for item in result.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            text = str(item.get("text", ""))
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                text_parts.append(text)
            else:
                if isinstance(payload, dict) and isinstance(payload.get("content"), str):
                    text_parts.append(payload["content"])
                    if not isinstance(result.get("threadId"), str) and isinstance(
                        payload.get("threadId"), str
                    ):
                        result = {**result, "threadId": payload["threadId"]}
                else:
                    text_parts.append(text)
    thread_id = None
    if isinstance(result.get("threadId"), str):
        thread_id = result["threadId"]
    return "\n".join(text_parts), thread_id
