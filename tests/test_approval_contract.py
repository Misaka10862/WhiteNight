"""Regression contracts for approval identity, scope and single consumption."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import update

from whitenight.policy.approvals import ApprovalService, _now
from whitenight.storage.models import Approval


def _request(service):
    return service.request(
        "file.create",
        "low_write",
        "session",
        "new file",
        session_id="session",
        channel="onebot",
        channel_target="owner",
        params={"path": "/a", "content": "hello"},
    )


def _approve(service, code, grant_scope="once"):
    return service.approve(
        code,
        session_id="session",
        expected_scope="session",
        grant_scope=grant_scope,
        channel="onebot",
        channel_target="owner",
    )


def _consume(service, approval_id, **overrides):
    args = dict(
        session_id="session",
        expected_scope="session",
        tool_name="file.create",
        params={"path": "/a", "content": "hello"},
        channel="onebot",
        channel_target="owner",
    )
    return service.consume_approved(approval_id, **(args | overrides))


def test_low_write_once_does_not_grant_session(engine):
    service = ApprovalService(engine)
    item = _request(service)
    assert _approve(service, item.code).ok
    assert _consume(service, item.id).ok
    assert not service.has_session_grant("session", "file.create")


def test_session_scope_requires_explicit_choice(engine):
    service = ApprovalService(engine)
    item = _request(service)
    assert _approve(service, item.code, "session").ok
    assert _consume(service, item.id).ok
    assert service.has_session_grant(
        "session", "file.create", channel="onebot", channel_target="owner"
    )
    assert not service.has_session_grant("session", "file.create", channel="web")


def test_binding_mismatch_does_not_consume(engine):
    service = ApprovalService(engine)
    item = _request(service)
    assert _approve(service, item.code).ok
    for changed in (
        {"tool_name": "file.write"},
        {"params": {"path": "/b", "content": "hello"}},
        {"session_id": "other"},
        {"channel": "web"},
        {"channel_target": "other"},
    ):
        assert not _consume(service, item.id, **changed).ok
    assert _consume(service, item.id).ok
    assert not _consume(service, item.id).ok


def test_approved_expiry_is_checked_at_execution(engine):
    service = ApprovalService(engine)
    item = _request(service)
    assert _approve(service, item.code).ok
    with engine.begin() as connection:
        connection.execute(
            update(Approval)
            .where(Approval.id == item.id)
            .values(expires_at=_now() - timedelta(seconds=1))
        )
    assert not _consume(service, item.id).ok


def test_concurrent_consumers_have_exactly_one_winner(engine):
    service = ApprovalService(engine)
    item = _request(service)
    assert _approve(service, item.code).ok
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _consume(service, item.id).ok, range(2)))
    assert results.count(True) == 1
