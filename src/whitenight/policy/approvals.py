"""审批与按会话授权。

审批编号：短期、一次性、不可重放（secrets.token_urlsafe 生成）。
scope=once 用一次即失效；scope=session 批准后建立会话授权，编号本身同样不可复用。
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Engine, or_, select, text, update
from sqlalchemy.orm import Session as OrmSession

from whitenight.storage.models import Approval, PendingToolCall, SessionGrant

ONCE_TTL = timedelta(minutes=10)
SESSION_GRANT_TTL = timedelta(hours=24)
GrantScope = Literal["once", "session"]


def params_digest(params: dict[str, Any]) -> str:
    canonical = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _binding(value: str) -> dict[str, Any]:
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("binding_version") == 1 else {}


def _display_summary(value: str) -> str:
    return str(_binding(value).get("summary", value))


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
    channel_target: str | None = None
    presented_at: datetime | None = None
    status: str = "pending"


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
        *,
        channel_target: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """创建待审批请求并返回短期编号。"""
        if scope not in {"once", "session"} or (scope == "session" and risk != "low_write"):
            raise ValueError("只有低风险写入允许选择会话授权")
        if risk == "batch_delete":
            raise ValueError("批量删除不能通过审批授权给 Agent")
        now = _now()
        digest = params_digest(params) if params is not None else None
        key = (
            params_digest(
                {
                    "tool": tool_name,
                    "params": digest,
                    "session": session_id,
                    "channel": channel,
                    "target": channel_target,
                    "scope": scope,
                }
            )
            if digest and not tool_name.startswith("delegate.")
            else None
        )
        with self._orm() as orm:
            # SQLite/SQLCipher writer reservation serializes concurrent request/upsert.
            orm.execute(text("BEGIN IMMEDIATE"))
            active = orm.execute(
                select(PendingToolCall, Approval)
                .join(Approval, Approval.id == PendingToolCall.approval_id)
                .where(
                    PendingToolCall.session_id == session_id,
                    PendingToolCall.channel == channel,
                    PendingToolCall.channel_target == channel_target,
                    PendingToolCall.tool_name == tool_name,
                    PendingToolCall.status.in_(["running", "awaiting_review"]),
                )
            ).all()
            for operation, row in active:
                saved = json.loads(operation.params_json)
                if operation.params_digest == digest or (
                    tool_name == "file.move"
                    and params
                    and saved.get("source") == params.get("source")
                ):
                    record = self._record(row)
                    from dataclasses import replace

                    return replace(record, status=operation.status)
            candidates = orm.scalars(
                select(Approval).where(
                    Approval.tool_name == tool_name,
                    Approval.session_id == session_id,
                    Approval.channel == channel,
                    Approval.status.in_(["pending", "approved", "awaiting_review"]),
                )
            ).all()
            for row in candidates:
                binding = _binding(row.params_summary)
                if binding.get("channel_target") != channel_target:
                    continue
                if row.status in {"approved", "awaiting_review"}:
                    if (key is not None and row.active_key == key) or (
                        tool_name == "file.move"
                        and params
                        and binding.get("source") == params.get("source")
                    ):
                        return self._record(row)
                    continue
                if row.expires_at and row.expires_at < now:
                    row.status, row.active_key = "revoked", None
                    orm.execute(
                        update(PendingToolCall)
                        .where(
                            PendingToolCall.approval_id == row.id,
                            PendingToolCall.status == "pending",
                        )
                        .values(status="expired")
                    )
                    continue
                if key and binding.get("params_digest") == digest and row.scope == scope:
                    row.active_key = key
                    orm.commit()
                    return self._record(row)
                if (
                    tool_name == "file.move"
                    and params
                    and row.status == "pending"
                    and binding.get("source") == params.get("source")
                ):
                    row.status, row.active_key = "revoked", None
                    orm.execute(
                        update(PendingToolCall)
                        .where(
                            PendingToolCall.approval_id == row.id,
                            PendingToolCall.status == "pending",
                        )
                        .values(status="superseded")
                    )
            approval = Approval(
                code=secrets.token_urlsafe(6)[:8],
                tool_name=tool_name,
                risk=risk,
                scope=scope,
                status="pending",
                session_id=session_id,
                channel=channel,
                active_key=key,
                params_summary=json.dumps(
                    {
                        "binding_version": 1,
                        "summary": params_summary,
                        "params_digest": digest,
                        "channel_target": channel_target,
                        "source": params.get("source")
                        if params and tool_name == "file.move"
                        else None,
                    },
                    ensure_ascii=False,
                ),
                expires_at=now + self._once_ttl,
            )
            orm.add(approval)
            orm.commit()
            return self._record(approval)

    @staticmethod
    def _record(row: Approval) -> ApprovalRequest:
        return ApprovalRequest(
            id=row.id,
            code=row.code,
            tool_name=row.tool_name,
            risk=row.risk,
            scope=row.scope,
            params_summary=_display_summary(row.params_summary),
            session_id=row.session_id,
            channel=row.channel,
            created_at=row.created_at,
            expires_at=row.expires_at,
            channel_target=_binding(row.params_summary).get("channel_target"),
            presented_at=row.presented_at,
            status=row.status,
        )

    def mark_presented(self, codes: list[str]) -> None:
        with self._orm() as orm:
            orm.execute(
                update(Approval)
                .where(Approval.code.in_(codes), Approval.status == "pending")
                .values(presented_at=_now())
            )
            orm.commit()

    def for_context(
        self, session_id: str, channel: str, target: str | None, *, presented_only: bool = False
    ) -> list[ApprovalRequest]:
        return [
            item
            for item in self.list_pending(limit=None)
            if item.session_id == session_id
            and item.channel == channel
            and item.channel_target == target
            and (not presented_only or item.presented_at is not None)
        ]

    def resolve_once(
        self,
        code: str,
        session_id: str | None = None,
        expected_scope: str = "once",
        *,
        grant_scope: GrantScope = "once",
        tool_name: str | None = None,
        params: dict[str, Any] | None = None,
        channel: str | None = None,
        channel_target: str | None = None,
    ) -> Resolution:
        """按编号批准/消费一次。

        编号不可重放；过期、session 不匹配、scope 与要求不一致均拒绝。
        scope=session 的批准会同时建立会话授权，但编号本身同样只消费一次。
        """
        # Validate the action before changing pending -> approved, so a mismatched
        # tool cannot make another operation's code unusable.
        if tool_name is not None:
            with self._orm() as orm:
                row = orm.scalar(select(Approval).where(Approval.code == code))
                if row is not None and row.status != "pending":
                    return Resolution(False, expected_scope, "审批已处理或不可用")
                binding = _binding(row.params_summary) if row is not None else {}
                if (
                    row is None
                    or row.tool_name != tool_name
                    or params is None
                    or not binding.get("params_digest")
                    or binding["params_digest"] != params_digest(params)
                ):
                    return Resolution(False, expected_scope, "审批工具或参数不匹配")
        approved = self.approve(
            code,
            session_id=session_id,
            expected_scope=expected_scope,
            grant_scope=grant_scope,
            channel=channel,
            channel_target=channel_target,
        )
        if not approved.ok or approved.approval_id is None:
            return approved
        return self.consume_approved(
            approved.approval_id,
            session_id=session_id,
            expected_scope=expected_scope,
            tool_name=tool_name,
            params=params,
            channel=channel,
            channel_target=channel_target,
        )

    def approve(
        self,
        code: str,
        session_id: str | None = None,
        expected_scope: str = "once",
        *,
        grant_scope: GrantScope = "once",
        channel: str | None = None,
        channel_target: str | None = None,
    ) -> Resolution:
        """Choose an explicit grant scope; ``expected_scope`` is the policy ceiling."""
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
            if grant_scope not in {"once", "session"} or (
                grant_scope == "session" and (approval.scope != "session" or not session_id)
            ):
                return Resolution(False, "once", "该操作不允许会话授权")
            if approval.status != "pending":
                return Resolution(False, "once", f"审批已处理或不可用（{approval.status}）")
            if approval.expires_at and approval.expires_at < now:
                approval.status = "revoked"
                approval.active_key = None
                orm.commit()
                return Resolution(False, "once", "审批编号已过期")
            if approval.session_id != session_id:
                return Resolution(False, "once", "审批编号不属于当前会话")
            if (
                approval.channel != channel
                or _binding(approval.params_summary).get("channel_target") != channel_target
            ):
                return Resolution(False, "once", "审批编号不属于当前渠道或接收人")
            changed = orm.scalar(
                update(Approval)
                .where(
                    Approval.id == approval.id,
                    Approval.status == "pending",
                    or_(Approval.expires_at.is_(None), Approval.expires_at >= now),
                )
                .values(status="approved", scope=grant_scope, used_count=0, decided_at=now)
                .returning(Approval.id)
            )
            if changed is None:
                return Resolution(False, "once", "审批已处理或不可用")
            orm.commit()
            return Resolution(True, grant_scope, "已批准", approval.id)

    def consume_approved(
        self,
        approval_id: str,
        *,
        session_id: str | None,
        expected_scope: str,
        tool_name: str | None = None,
        params: dict[str, Any] | None = None,
        channel: str | None = None,
        channel_target: str | None = None,
    ) -> Resolution:
        """Atomically consume a previously approved authorization once."""
        now = _now()
        with self._orm() as orm:
            approval = orm.get(Approval, approval_id)
            if approval is None:
                return Resolution(False, expected_scope, "审批记录不存在")
            if approval.scope not in (
                {"once", "session"} if expected_scope == "session" else {"once"}
            ):
                return Resolution(False, expected_scope, "审批范围不匹配")
            if approval.session_id != session_id:
                return Resolution(False, expected_scope, "审批编号不属于当前会话")
            binding = _binding(approval.params_summary)
            if approval.channel != channel or binding.get("channel_target") != channel_target:
                return Resolution(False, expected_scope, "审批编号不属于当前渠道或接收人")
            if tool_name is not None and (
                tool_name != approval.tool_name
                or params is None
                or not binding.get("params_digest")
                or params_digest(params) != binding["params_digest"]
            ):
                return Resolution(False, expected_scope, "审批工具或参数不匹配")
            if binding.get("params_digest") and (tool_name is None or params is None):
                return Resolution(False, expected_scope, "执行时必须提供审批绑定的工具与参数")
            if approval.expires_at and approval.expires_at < now:
                return Resolution(False, expected_scope, "审批编号已过期")
            if approval.status != "approved" or approval.used_count != 0:
                return Resolution(False, expected_scope, "审批已处理或不可用")
            changed = orm.scalar(
                update(Approval)
                .where(
                    Approval.id == approval.id,
                    Approval.status == "approved",
                    Approval.used_count == 0,
                    or_(Approval.expires_at.is_(None), Approval.expires_at >= now),
                )
                .values(status="consumed", used_count=1, active_key=None)
                .returning(Approval.id)
            )
            if changed is None:
                return Resolution(False, expected_scope, "审批已处理或不可用")
            if approval.scope == "session":
                orm.add(
                    SessionGrant(
                        id=approval.id,
                        session_id=session_id or "",
                        tool_name=approval.tool_name,
                        expires_at=now + SESSION_GRANT_TTL,
                    )
                )
            orm.commit()
            return Resolution(True, approval.scope, "已消费", approval.id)

    def has_session_grant(
        self,
        session_id: str,
        tool_name: str,
        *,
        channel: str | None = None,
        channel_target: str | None = None,
    ) -> bool:
        now = _now()
        with self._orm() as orm:
            rows = orm.execute(
                select(SessionGrant, Approval)
                .join(Approval, Approval.id == SessionGrant.id)
                .where(
                    SessionGrant.session_id == session_id,
                    SessionGrant.tool_name == tool_name,
                )
                .order_by(SessionGrant.created_at.desc())
            ).all()
            return any(
                not (row.expires_at and row.expires_at < now)
                and approval.status == "consumed"
                and approval.channel == channel
                and _binding(approval.params_summary).get("channel_target") == channel_target
                for row, approval in rows
            )

    def list_pending(self, limit: int | None = 1000) -> list[ApprovalRequest]:
        now = _now()
        with self._orm() as orm:
            rows = orm.scalars(
                select(Approval)
                .where(
                    Approval.status == "pending",
                    or_(Approval.expires_at.is_(None), Approval.expires_at >= now),
                )
                .order_by(Approval.created_at.desc())
                .limit(limit)
            ).all()
            return [self._record(row) for row in rows]

    def invalidate(self, code: str) -> None:
        """Close a failed validation without manufacturing user consent or rejection."""
        with self._orm() as orm:
            orm.execute(
                update(Approval)
                .where(Approval.code == code, Approval.status.in_(["pending", "approved"]))
                .values(status="revoked", active_key=None, decided_at=_now())
            )
            orm.commit()

    def reject(self, code: str) -> Resolution:
        """拒绝审批：拒绝只消费编号，不产生任何授权。"""
        now = _now()
        with self._orm() as orm:
            approval = orm.scalar(select(Approval).where(Approval.code == code))
            if approval is None:
                return Resolution(False, "once", "审批编号不存在")
            if approval.status != "pending":
                return Resolution(False, "once", f"审批已处理或不可用（{approval.status}）")
            changed = orm.scalar(
                update(Approval)
                .where(
                    Approval.id == approval.id,
                    Approval.status == "pending",
                )
                .values(status="rejected", decided_at=now, used_count=1, active_key=None)
                .returning(Approval.id)
            )
            if changed is None:
                return Resolution(False, "once", "审批已处理或不可用")
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
