"""审批与按会话授权。

审批编号：短期、一次性、不可重放（secrets.token_urlsafe 生成）。
scope=once 用一次即失效；scope=session 批准后建立会话授权，编号本身同样不可复用。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as OrmSession

from whitenight.storage.models import Approval, SessionGrant

ONCE_TTL = timedelta(minutes=10)
SESSION_GRANT_TTL = timedelta(hours=24)


def _now() -> datetime:
    """SQLite 返回 naive datetime；统一比较用 naive UTC。"""
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class ApprovalRequest:
    id: str
    code: str
    tool_name: str
    risk: str
    scope: str
    params_summary: str
    session_id: str | None
    channel: str | None
    created_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True)
class SessionGrantRecord:
    id: str
    session_id: str
    tool_name: str
    created_at: datetime
    expires_at: datetime | None


@dataclass(frozen=True)
class Resolution:
    ok: bool
    scope: str
    reason: str
    approval_id: str | None = None


class ApprovalError(RuntimeError):
    """审批状态不合法。"""


class ApprovalService:
    def __init__(self, engine: Engine, once_ttl: timedelta = ONCE_TTL) -> None:
        self._engine = engine
        self._once_ttl = once_ttl

    def _orm(self) -> OrmSession:
        return OrmSession(self._engine, expire_on_commit=False)

    def request(
        self,
        tool_name: str,
        risk: str,
        scope: str,
        params_summary: str,
        session_id: str | None = None,
        channel: str | None = None,
    ) -> ApprovalRequest:
        """创建待审批请求并返回短期编号。"""
        now = _now()
        with self._orm() as orm:
            approval = Approval(
                code=secrets.token_urlsafe(6)[:8],
                tool_name=tool_name,
                risk=risk,
                scope=scope,
                status="pending",
                session_id=session_id,
                channel=channel,
                params_summary=params_summary,
                expires_at=now + self._once_ttl,
            )
            orm.add(approval)
            orm.commit()
            return ApprovalRequest(
                id=approval.id,
                code=approval.code,
                tool_name=approval.tool_name,
                risk=approval.risk,
                scope=approval.scope,
                params_summary=approval.params_summary,
                session_id=approval.session_id,
                channel=approval.channel,
                created_at=approval.created_at,
                expires_at=approval.expires_at,
            )

    def resolve_once(
        self,
        code: str,
        session_id: str | None = None,
        expected_scope: str = "once",
    ) -> Resolution:
        """按编号批准/消费一次。

        编号不可重放；过期、session 不匹配、scope 与要求不一致均拒绝。
        scope=session 的批准会同时建立会话授权，但编号本身同样只消费一次。
        """
        approved = self.approve(code, session_id=session_id, expected_scope=expected_scope)
        if not approved.ok or approved.approval_id is None:
            return approved
        return self.consume_approved(
            approved.approval_id,
            session_id=session_id,
            expected_scope=expected_scope,
        )

    def approve(
        self,
        code: str,
        session_id: str | None = None,
        expected_scope: str = "once",
    ) -> Resolution:
        """Approve without consuming; a bound executor consumes it later."""
        now = _now()
        with self._orm() as orm:
            approval = orm.scalar(select(Approval).where(Approval.code == code))
            if approval is None:
                return Resolution(False, "once", "审批编号不存在")
            if approval.scope != expected_scope:
                return Resolution(
                    False,
                    "once",
                    f"审批范围不匹配：要求 {expected_scope}，实际 {approval.scope}",
                )
            if approval.status != "pending":
                return Resolution(False, "once", f"审批已处理或不可用（{approval.status}）")
            if approval.expires_at and approval.expires_at < now:
                approval.status = "revoked"
                orm.commit()
                return Resolution(False, "once", "审批编号已过期")
            if approval.session_id and approval.session_id != session_id:
                return Resolution(False, "once", "审批编号不属于当前会话")
            approval.status = "approved"
            approval.used_count = 0
            approval.decided_at = now
            if approval.scope == "session":
                orm.add(
                    SessionGrant(
                        session_id=session_id or approval.session_id or "",
                        tool_name=approval.tool_name,
                        expires_at=now + SESSION_GRANT_TTL,
                    )
                )
            orm.commit()
            return Resolution(True, approval.scope, "已批准", approval.id)

    def consume_approved(
        self,
        approval_id: str,
        *,
        session_id: str | None,
        expected_scope: str,
    ) -> Resolution:
        """Atomically consume a previously approved authorization once."""
        with self._orm() as orm:
            approval = orm.get(Approval, approval_id)
            if approval is None:
                return Resolution(False, expected_scope, "审批记录不存在")
            if approval.scope != expected_scope:
                return Resolution(False, expected_scope, "审批范围不匹配")
            if approval.session_id and approval.session_id != session_id:
                return Resolution(False, expected_scope, "审批编号不属于当前会话")
            if approval.status != "approved" or approval.used_count != 0:
                return Resolution(False, expected_scope, "审批已处理或不可用")
            approval.status = "consumed"
            approval.used_count = 1
            orm.commit()
            return Resolution(True, approval.scope, "已消费", approval.id)

    def has_session_grant(self, session_id: str, tool_name: str) -> bool:
        now = _now()
        with self._orm() as orm:
            row = orm.scalar(
                select(SessionGrant)
                .where(
                    SessionGrant.session_id == session_id,
                    SessionGrant.tool_name == tool_name,
                )
                .order_by(SessionGrant.created_at.desc())
                .limit(1)
            )
            if row is None:
                return False
            return not (row.expires_at and row.expires_at < now)

    def list_pending(self, limit: int = 20) -> list[ApprovalRequest]:
        with self._orm() as orm:
            rows = orm.scalars(
                select(Approval)
                .where(Approval.status == "pending")
                .order_by(Approval.created_at.desc())
                .limit(limit)
            ).all()
            return [
                ApprovalRequest(
                    id=row.id,
                    code=row.code,
                    tool_name=row.tool_name,
                    risk=row.risk,
                    scope=row.scope,
                    params_summary=row.params_summary,
                    session_id=row.session_id,
                    channel=row.channel,
                    created_at=row.created_at,
                    expires_at=row.expires_at,
                )
                for row in rows
            ]

    def reject(self, code: str) -> Resolution:
        """拒绝审批：拒绝只消费编号，不产生任何授权。"""
        now = _now()
        with self._orm() as orm:
            approval = orm.scalar(select(Approval).where(Approval.code == code))
            if approval is None:
                return Resolution(False, "once", "审批编号不存在")
            if approval.status != "pending":
                return Resolution(False, "once", f"审批已处理或不可用（{approval.status}）")
            approval.status = "rejected"
            approval.decided_at = now
            approval.used_count = 1
            orm.commit()
            return Resolution(True, approval.scope, "已拒绝", approval.id)

    def list_session_grants(self, limit: int = 100) -> list[SessionGrantRecord]:
        with self._orm() as orm:
            rows = orm.scalars(
                select(SessionGrant).order_by(SessionGrant.created_at.desc()).limit(limit)
            ).all()
            return [
                SessionGrantRecord(
                    id=row.id,
                    session_id=row.session_id,
                    tool_name=row.tool_name,
                    created_at=row.created_at,
                    expires_at=row.expires_at,
                )
                for row in rows
            ]

    def revoke_session_grant(self, grant_id: str) -> None:
        with self._orm() as orm:
            grant = orm.get(SessionGrant, grant_id)
            if grant is not None:
                orm.delete(grant)
                orm.commit()
