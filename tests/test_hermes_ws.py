from __future__ import annotations

import asyncio
import json

import pytest

from whitenight.delegates.base import DelegateError
from whitenight.delegates.events import DelegationRequest
from whitenight.delegates.hermes_ws import HermesProcessManager, ManagedHermesGatewayAdapter
from whitenight.policy.approvals import ApprovalService


class FakeManager:
    async def ensure_started(self) -> None:
        pass

    async def health(self) -> dict[str, object]:
        return {"available": True}

    async def stop(self) -> None:
        pass

    def websocket_url(self) -> str:
        return "ws://127.0.0.1:9119/api/ws?token=test-token"


class FakeConnection:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.responses = [
            {"jsonrpc": "2.0", "method": "event", "params": {"type": "gateway.ready"}},
            {
                "jsonrpc": "2.0",
                "id": "session",
                "result": {"session_id": "live-1", "stored_session_id": "stored-1"},
            },
            {"jsonrpc": "2.0", "id": "prompt", "result": {"status": "streaming"}},
            {
                "jsonrpc": "2.0",
                "method": "event",
                "params": {
                    "type": "message.delta",
                    "session_id": "live-1",
                    "payload": {"text": "done"},
                },
            },
            {
                "jsonrpc": "2.0",
                "method": "event",
                "params": {
                    "type": "message.complete",
                    "session_id": "live-1",
                    "payload": {"text": "completed"},
                },
            },
        ]

    async def recv(self) -> str:
        return json.dumps(self.responses.pop(0))

    async def send(self, value: str) -> None:
        self.sent.append(json.loads(value))


class FakeConnect:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, *_args) -> None:
        pass


def test_managed_hermes_websocket_url_has_runtime_token() -> None:
    manager = HermesProcessManager("http://127.0.0.1:9119", "hermes", lambda: None, managed=True)
    url = manager.websocket_url()
    assert url.startswith("ws://127.0.0.1:9119/api/ws?token=")
    assert len(url.rsplit("=", 1)[1]) >= 32


def test_managed_hermes_uses_deepseek_jsonrpc(engine, monkeypatch) -> None:
    connection = FakeConnection()
    connected_urls: list[str] = []

    def fake_connect(url: str, **_kwargs):
        connected_urls.append(url)
        return FakeConnect(connection)

    monkeypatch.setattr("whitenight.delegates.hermes_ws.connect", fake_connect)
    adapter = ManagedHermesGatewayAdapter(
        FakeManager(),  # type: ignore[arg-type]
        ApprovalService(engine),
        base_url="http://127.0.0.1:9119",
    )

    async def run():
        return [
            event
            async for event in adapter.submit(
                DelegationRequest(task_id="t1", prompt="hello", cwd="/tmp")
            )
        ]

    events = asyncio.run(run())
    assert connected_urls == ["ws://127.0.0.1:9119/api/ws?token=test-token"]
    assert events[-1].detail == "completed"
    create = next(item for item in connection.sent if item["method"] == "session.create")
    assert create["params"]["provider"] == "deepseek"  # type: ignore[index]
    assert create["params"]["model"] == "deepseek-v4-flash-vision-exp"  # type: ignore[index]


def test_managed_hermes_normalizes_gateway_disconnect(engine, monkeypatch) -> None:
    class BrokenConnect:
        async def __aenter__(self):
            raise RuntimeError("socket closed")

        async def __aexit__(self, *_args):
            pass

    monkeypatch.setattr(
        "whitenight.delegates.hermes_ws.connect", lambda *_args, **_kwargs: BrokenConnect()
    )
    adapter = ManagedHermesGatewayAdapter(
        FakeManager(), ApprovalService(engine), base_url="http://127.0.0.1:9119"
    )

    async def run():
        return [
            event async for event in adapter.submit(DelegationRequest(task_id="t1", prompt="hello"))
        ]

    with pytest.raises(DelegateError, match="通信失败"):
        asyncio.run(run())
