"""One resumable worker for per-session memory jobs, yielding to foreground chat."""

from __future__ import annotations

import asyncio
import logging

from whitenight.memory.service import MemoryService
from whitenight.models.base import ModelProvider
from whitenight.personality.store import PersonalityStore
from whitenight.storage.sessions import SessionNotFoundError, SessionStore

logger = logging.getLogger(__name__)


class MemoryMaintenance:
    def __init__(
        self,
        memory: MemoryService,
        sessions: SessionStore,
        provider: ModelProvider,
        personalities: PersonalityStore | None = None,
        *,
        delay_s: float = 15.0,
    ) -> None:
        self._memory = memory
        self._store = memory.maintenance_store
        self._sessions = sessions
        self._provider = provider
        self._personalities = personalities
        self._delay_s = delay_s
        self._wake = asyncio.Event()
        self._runner: asyncio.Task[None] | None = None
        self._active: asyncio.Task[int] | None = None
        self._foreground = 0
        self._idle_until = 0.0
        self._closed = False
        self._pass_lock = asyncio.Lock()

    def set_provider(self, provider: ModelProvider) -> None:
        self._provider = provider

    def start(self) -> None:
        """Start after database migration; pre-existing durable jobs are discovered."""
        if self._runner is None or self._runner.done():
            self._closed = False
            self._runner = asyncio.create_task(self._run())

    def enqueue(self, session_id: str, sequence: int | None = None) -> None:
        if sequence is None:
            sequence = max(
                (message.sequence for message in self._sessions.list_messages(session_id)),
                default=0,
            )
        self._store.queue_maintenance(session_id, sequence, self._delay_s)
        self._wake.set()

    def interrupt(self) -> None:
        """Cancel only the current attempt; durable job/checkpoints remain intact."""
        self._idle_until = asyncio.get_running_loop().time() + self._delay_s
        if self._active is not None and not self._active.done():
            self._active.cancel()
        self._wake.set()

    def begin_chat(self) -> None:
        self._foreground += 1
        self.interrupt()

    def end_chat(self) -> None:
        self._foreground = max(0, self._foreground - 1)
        self._idle_until = asyncio.get_running_loop().time() + self._delay_s
        self._wake.set()

    async def close(self) -> None:
        self._closed = True
        if self._active is not None:
            self._active.cancel()
        if self._runner is not None:
            self._runner.cancel()
            await asyncio.gather(self._runner, return_exceptions=True)
        self._runner = None

    async def run_once(self) -> int:
        """Process one ready session; useful for deterministic tests and explicit drains."""
        async with self._pass_lock:
            if self._foreground or asyncio.get_running_loop().time() < self._idle_until:
                return 0
            pending = self._store.pending_maintenance()
            if not pending:
                return 0
            session_id, target = pending[0]
            try:
                history = [
                    message
                    for message in self._sessions.list_messages(session_id)
                    if message.sequence <= target
                ]
                character_id = None
                if self._personalities is not None:
                    character_id, _persona_id = self._personalities.session_identity(session_id)
                await self._memory.extract_and_store(history, session_id, character_id)
                checkpoint = self._store.summary_checkpoint(session_id)
                uncovered = [message for message in history if message.sequence > checkpoint]
                if len(uncovered) >= 10:
                    await self._memory.summarize_session(history, session_id, self._provider)
                self._store.complete_maintenance(session_id, target)
                return 1
            except SessionNotFoundError:
                # A user-deleted session has no remaining source material to maintain.
                self._store.complete_maintenance(session_id, target)
                return 0
            except Exception as exc:
                self._store.defer_maintenance(session_id)
                logger.warning(
                    "记忆维护等待重试 session=%s error_type=%s", session_id, type(exc).__name__
                )
                return 0

    async def _run(self) -> None:
        while not self._closed:
            self._wake.clear()
            self._active = asyncio.create_task(self.run_once())
            try:
                processed = await self._active
            except asyncio.CancelledError:
                if self._closed:
                    return
                processed = 0
            finally:
                self._active = None
            if processed:
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1.0)
            except TimeoutError:
                continue
