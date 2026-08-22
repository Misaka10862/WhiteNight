from __future__ import annotations

import asyncio
import json

from whitenight.delegates.events import DelegationRequest
from whitenight.delegates.hermes_ws import ManagedHermesGatewayAdapter
from whitenight.policy.approvals import ApprovalService


class FakeManager:
    async def ensure_started(self) -> None:
        pass

    async def health(self) -> dict[str, object]:
        return {"available": True}

    async def stop(self) -> None:
        pass


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


def test_managed_hermes_uses_deepseek_jsonrpc(engine, monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(
        "whitenight.delegates.hermes_ws.connect", lambda *_args, **_kwargs: FakeConnect(connection)
    )
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
    assert events[-1].detail == "completed"
    create = next(item for item in connection.sent if item["method"] == "session.create")
    assert create["params"]["provider"] == "deepseek"  # type: ignore[index]
    assert create["params"]["model"] == "deepseek-v4-flash-vision-exp"  # type: ignore[index]
