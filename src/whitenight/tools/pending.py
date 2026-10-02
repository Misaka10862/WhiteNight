"""Durable tool-call continuations used by the approval workflow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine, select, text, update
from sqlalchemy.orm import Session as OrmSession

from whitenight.policy.approvals import params_digest as params_digest
from whitenight.storage.models import Approval, AuditEvent, PendingToolCall


def canonical_params(params: dict[str, Any]) -> str:
    return json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
    result: dict[str, Any] | None = None
    error: str | None = None


class PendingToolStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def recover(self) -> None:
        """Called only at startup under the service's exclusive database lifetime lock."""
        with OrmSession(self._engine) as orm:
            rows = orm.scalars(
                select(PendingToolCall).where(PendingToolCall.status == "running")
            ).all()
            for row in rows:
                audit = orm.scalar(
                    select(AuditEvent)
                    .where(AuditEvent.approval_id == row.approval_id)
                    .order_by(AuditEvent.ts.desc())
                    .limit(1)
                )
                if audit and audit.action == "tool.ok":
                    row.status = "succeeded"
                    row.result_json = json.dumps({"ok": True, "summary": audit.result_summary})
                else:
                    row.status = "awaiting_review"
                    details = "执行被中断，结果待核验，不会自动重试。"
                    if row.tool_name == "file.move":
                        params = json.loads(row.params_json)
                        observations = []
                        for name in ("source", "destination"):
                            try:
                                Path(params[name]).stat()
                                observations.append(f"{name} 存在")
                            except FileNotFoundError:
                                observations.append(f"{name} 不存在")
                            except OSError:
                                observations.append(f"{name} 无法访问")
                        details += "；".join(observations)
                    row.error = details
                approval = orm.get(Approval, row.approval_id)
                if approval:
                    # Do not free the active key: an uncertain action cannot be resubmitted.
                    approval.status = (
                        "awaiting_review" if row.status == "awaiting_review" else "consumed"
                    )
                row.updated_at = datetime.now(UTC)
            orm.commit()

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
            orm.execute(text("BEGIN IMMEDIATE"))
            existing = orm.scalar(
                select(PendingToolCall).where(PendingToolCall.approval_id == approval_id)
            )
            approval = orm.get(Approval, approval_id)
            assert approval is not None
            if existing is not None:
                return self._record(existing, approval.code)
            row = PendingToolCall(
                approval_id=approval_id,
                status="pending" if approval.status == "pending" else "superseded",
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

    def claim(self, record_id: str) -> bool:
        with OrmSession(self._engine) as orm:
            changed = orm.scalar(
                update(PendingToolCall)
                .where(PendingToolCall.id == record_id, PendingToolCall.status == "pending")
                .values(status="running", updated_at=datetime.now(UTC))
                .returning(PendingToolCall.id)
            )
            orm.commit()
            return changed is not None

    def for_context(
        self, session_id: str, channel: str, target: str | None
    ) -> list[PendingToolRecord]:
        with OrmSession(self._engine) as orm:
            pairs = orm.execute(
                select(PendingToolCall, Approval)
                .join(Approval, Approval.id == PendingToolCall.approval_id)
                .where(
                    PendingToolCall.session_id == session_id,
                    PendingToolCall.channel == channel,
                    PendingToolCall.channel_target == target,
                )
                .order_by(PendingToolCall.created_at.desc())
            ).all()
            records = []
            for row, approval in pairs:
                record = self._record(row, approval)
                if (
                    record.status == "pending"
                    and approval.expires_at
                    and approval.expires_at < datetime.now(UTC).replace(tzinfo=None)
                ):
                    record.status = "expired"
                records.append(record)
            return records

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
            result=json.loads(row.result_json) if row.result_json else None,
            error=row.error,
        )
