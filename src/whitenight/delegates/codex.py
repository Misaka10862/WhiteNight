"""Codex MCP Adapter：官方 stdio MCP，支持可恢复线程。

阶段 1 已实测 initialize/tools 握手；本适配器只消费 MCP 协议输出，
不解析终端文本。任务级调用需要用户已登录 Codex（~/.codex/auth.json）。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from whitenight.delegates.base import DelegateError, DelegateUnavailableError
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
        while True:
            line = await self._process.stdout.readline()
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
                if "error" in message:
                    future.set_exception(DelegateError(str(message["error"])))
                else:
                    future.set_result(message.get("result", {}))

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._process is None or self._process.stdin is None:
            raise DelegateError("Codex MCP 客户端未启动")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self._process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await self._process.stdin.drain()
        return await asyncio.wait_for(future, timeout=self._startup_timeout_s)

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
            result = await asyncio.wait_for(
                self._request("tools/call", {"name": name, "arguments": arguments}),
                timeout=self._timeout_s,
            )
        except TimeoutError as exc:
            raise DelegateError("Codex 任务超时") from exc
        return result

    async def close(self) -> None:
        if self._process is None:
            return
        process, self._process = self._process, None
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()
        if getattr(self, "_reader", None):
            self._reader.cancel()


class CodexAdapter:
    """Codex 编码任务执行器（MCP stdio）。"""

    name = "codex"

    def __init__(self, command: str = "codex", timeout_s: float = 1800.0) -> None:
        self._command = command
        self._timeout_s = timeout_s

    async def health(self) -> dict[str, object]:
        client = CodexMcpClient(self._command)
        try:
            await client.start()
            tools = await client.list_tools()
            return {
                "provider": "codex-mcp",
                "available": True,
                "tools": [tool.get("name") for tool in tools],
            }
        except Exception as exc:
            return {"provider": "codex-mcp", "available": False, "error": str(exc)}
        finally:
            await client.close()

    async def submit(self, request: DelegationRequest) -> AsyncIterator[DelegateEvent]:
        client = CodexMcpClient(self._command, timeout_s=self._timeout_s)
        try:
            await client.start()
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
                arguments["approval-policy"] = "on-request"
                result = await client.call_tool(_TOOL_NEW, arguments)

            content, thread_id = _extract_codex_result(result)
            yield DelegateEvent(
                task_id=request.task_id,
                executor="codex",
                type="result",
                step="codex-mcp",
                label="Codex 任务完成",
                detail=content[:2000],
                payload={"thread_id": thread_id} if thread_id else {},
            )
        except DelegateError:
            raise
        except Exception as exc:
            raise DelegateError(f"Codex MCP 调用失败：{exc}") from exc
        finally:
            await client.close()

    async def abort(self, task_id: str, thread_id: str | None = None) -> bool:
        # Codex MCP 没有独立 abort 工具；断开本进程连接。线程可恢复，
        # 下次用 thread_id 走 codex-reply 续接，因此中止是安全的。
        del task_id, thread_id
        return True


def _extract_codex_result(result: dict[str, Any]) -> tuple[str, str | None]:
    text_parts: list[str] = []
    for item in result.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            text_parts.append(str(item.get("text", "")))
    thread_id = None
    if isinstance(result.get("threadId"), str):
        thread_id = result["threadId"]
    return "\n".join(text_parts), thread_id
