"""Delegated execution must preserve risk, cancellation and retry boundaries."""

import asyncio

from whitenight.delegates.base import DelegateCapabilities, DelegateError
from whitenight.delegates.codex import CodexAdapter
from whitenight.delegates.events import DelegateEvent
from whitenight.delegates.manager import DelegateManager, TaskStore
from whitenight.policy.risk import RiskLevel


class UnknownOutcomeProvider:
    name = "codex"
    capabilities = DelegateCapabilities(read_only=True, action_policy=True)

    def __init__(self):
        self.calls = 0

    async def submit(self, request):
        self.calls += 1
        yield DelegateEvent(
            task_id=request.task_id,
            executor="codex",
            type="started",
            payload={"thread_id": "persist-before-result"},
        )
        raise DelegateError("connection lost after a possible write")

    async def abort(self, *args):
        return False


def test_unknown_outcome_is_not_retried_and_thread_is_saved(engine):
    async def run():
        provider = UnknownOutcomeProvider()
        store = TaskStore(engine)
        manager = DelegateManager(store, {"codex": provider}, retry_delay_s=0)
        events = [
            event
            async for event in manager.run(
                executor="codex", category="code", risk="high", prompt="synthetic"
            )
        ]
        assert provider.calls == 1
        assert events[-1].type == "error"
        record = store.list()[0]
        assert record.status == "awaiting_review"
        assert record.thread_id == "persist-before-result"

    asyncio.run(run())


def test_batch_delete_and_missing_policy_never_reach_provider(engine):
    async def run():
        provider = UnknownOutcomeProvider()
        provider.capabilities = DelegateCapabilities(read_only=True)
        manager = DelegateManager(TaskStore(engine), {"codex": provider}, retry_delay_s=0)
        for risk in (RiskLevel.BATCH_DELETE.value, RiskLevel.HIGH.value):
            events = [
                event
                async for event in manager.run(
                    executor="codex", category="code", risk=risk, prompt="synthetic"
                )
            ]
            assert events[-1].type == "error"
        assert provider.calls == 0

    asyncio.run(run())


def test_codex_abort_closes_active_client_and_keeps_terminal_state(engine, monkeypatch):
    async def run():
        started = asyncio.Event()
        released = asyncio.Event()
        clients = []

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.closed = False
                clients.append(self)

            async def start(self):
                pass

            async def call_tool(self, name, args):
                assert args["sandbox"] == "read-only"
                assert args["approval-policy"] == "never"
                started.set()
                await released.wait()
                return {"structuredContent": {"content": "late result", "threadId": "t"}}

            async def close(self):
                self.closed = True
                released.set()

        monkeypatch.setattr("whitenight.delegates.codex.CodexMcpClient", FakeClient)
        store = TaskStore(engine)
        manager = DelegateManager(store, {"codex": CodexAdapter()})

        async def consume():
            return [
                e
                async for e in manager.run(
                    executor="codex", category="code", risk="read_only", prompt="synthetic"
                )
            ]

        running = asyncio.create_task(consume())
        await started.wait()
        task_id = store.list()[0].id
        event = await manager.abort(task_id)
        assert clients[0].closed
        assert event.type == "aborted"
        await running
        assert store.get(task_id).status == "aborted"

    asyncio.run(run())


def test_unconfirmed_abort_does_not_claim_aborted(engine):
    store = TaskStore(engine)
    task = store.create(executor="codex", category="code", risk="high", prompt="synthetic")
    manager = DelegateManager(store, {"codex": UnknownOutcomeProvider()})
    event = asyncio.run(manager.abort(task.id))
    assert event.type != "aborted"
    assert store.get(task.id).status == "cancel_failed"


def test_activity_snapshot_filters_finished_tasks_before_limit(engine):
    store = TaskStore(engine)
    pending = store.create(
        executor="codex", category="code", risk="read_only", prompt="private pending"
    )
    for _ in range(3):
        done = store.create(
            executor="codex", category="code", risk="read_only", prompt="private done"
        )
        store.update(done.id, status="succeeded")
    snapshot = store.activity_snapshot(limit=1)
    assert snapshot["tasks_complete"] is True
    assert len(snapshot["tasks"]) == 1
    assert snapshot["tasks"][0]["id"] == pending.id
    assert "prompt" not in snapshot["tasks"][0]
