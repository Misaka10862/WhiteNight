"""Durable tool-call continuations used by the approval workflow."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as OrmSession

from whitenight.storage.models import Approval, PendingToolCall


def canonical_params(params: dict[str, Any]) -> str:
    return json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def params_digest(params: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_params(params).encode("utf-8")).hexdigest()


class PendingToolRecord(BaseModel):
    id: str
    approval_id: str
    approval_code: str
    session_id: str
    channel: str
    channel_target: str | None
    tool_call_id: str
    tool_name: str
    params: dict[str, Any]
    params_digest: str
    assistant_content: str
    status: str


class PendingToolStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(
        self,
        *,
        approval_id: str,
        session_id: str,
        channel: str,
        channel_target: str | None,
        tool_call_id: str,
        tool_name: str,
        params: dict[str, Any],
        assistant_content: str,
    ) -> PendingToolRecord:
        with OrmSession(self._engine, expire_on_commit=False) as orm:
            row = PendingToolCall(
                approval_id=approval_id,
                session_id=session_id,
                channel=channel,
                channel_target=channel_target,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                params_json=canonical_params(params),
                params_digest=params_digest(params),
                assistant_content=assistant_content,
            )
            orm.add(row)
            orm.commit()
            approval = orm.get(Approval, approval_id)
            assert approval is not None
            return self._record(row, approval.code)

    def get_by_code(self, code: str) -> PendingToolRecord | None:
        with OrmSession(self._engine, expire_on_commit=False) as orm:
            pair = orm.execute(
                select(PendingToolCall, Approval)
                .join(Approval, Approval.id == PendingToolCall.approval_id)
                .where(Approval.code == code)
            ).one_or_none()
            return self._record(*pair) if pair else None

    def update(
        self,
        record_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with OrmSession(self._engine) as orm:
            row = orm.get(PendingToolCall, record_id)
            if row is None:
                raise KeyError(record_id)
            row.status = status
            row.result_json = json.dumps(result, ensure_ascii=False) if result is not None else None
            row.error = error
            row.updated_at = datetime.now(UTC)
            orm.commit()

    @staticmethod
    def _record(row: PendingToolCall, approval: Approval | str) -> PendingToolRecord:
        code = approval if isinstance(approval, str) else approval.code
        params = json.loads(row.params_json)
        return PendingToolRecord(
            id=row.id,
            approval_id=row.approval_id,
            approval_code=code,
            session_id=row.session_id,
            channel=row.channel,
            channel_target=row.channel_target,
            tool_call_id=row.tool_call_id,
            tool_name=row.tool_name,
            params=params if isinstance(params, dict) else {},
            params_digest=row.params_digest,
            assistant_content=row.assistant_content,
            status=row.status,
        )
