"""审计：每项现实动作记录执行者、参数摘要、审批记录、结果和时间。

参数与结果只存摘要，不存完整文件内容；日志与审计均不记录密钥。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as OrmSession

from whitenight.storage.models import AuditEvent


@dataclass(frozen=True)
class AuditRecord:
    id: str
    ts: datetime
    actor: str
    action: str
    tool_name: str | None
    risk: str | None
    decision: str
    params_summary: str
    result_summary: str
    session_id: str | None
    channel: str | None
    approval_id: str | None


class AuditService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record(
        self,
        actor: str,
        action: str,
        decision: str,
        params_summary: str = "",
        result_summary: str = "",
        tool_name: str | None = None,
        risk: str | None = None,
        session_id: str | None = None,
        channel: str | None = None,
        approval_id: str | None = None,
    ) -> AuditRecord:
        with OrmSession(self._engine, expire_on_commit=False) as orm:
            event = AuditEvent(
                actor=actor,
                action=action,
                decision=decision,
                params_summary=params_summary[:4000],
                result_summary=result_summary[:4000],
                tool_name=tool_name,
                risk=risk,
                session_id=session_id,
                channel=channel,
                approval_id=approval_id,
            )
            orm.add(event)
            orm.commit()
            return AuditRecord(
                id=event.id,
                ts=event.ts,
                actor=event.actor,
                action=event.action,
                tool_name=event.tool_name,
                risk=event.risk,
                decision=event.decision,
                params_summary=event.params_summary,
                result_summary=event.result_summary,
                session_id=event.session_id,
                channel=event.channel,
                approval_id=event.approval_id,
            )

    def recent(self, limit: int = 50) -> list[AuditRecord]:
        with OrmSession(self._engine, expire_on_commit=False) as orm:
            rows = orm.scalars(select(AuditEvent).order_by(AuditEvent.ts.desc()).limit(limit)).all()
            return [
                AuditRecord(
                    id=row.id,
                    ts=row.ts,
                    actor=row.actor,
                    action=row.action,
                    tool_name=row.tool_name,
                    risk=row.risk,
                    decision=row.decision,
                    params_summary=row.params_summary,
                    result_summary=row.result_summary,
                    session_id=row.session_id,
                    channel=row.channel,
                    approval_id=row.approval_id,
                )
                for row in rows
            ]
