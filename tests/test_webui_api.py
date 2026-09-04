"""阶段 6 WebUI 支撑 API 测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from whitenight.policy.approvals import ApprovalService


def test_session_rename_export_delete(client: TestClient) -> None:
    session = client.post("/api/v1/sessions", json={"title": "旧标题"}).json()
    store = client.app.state.store
    store.add_message(session["id"], "user", "你好")
    store.add_message(session["id"], "assistant", "在的")

    renamed = client.patch(f"/api/v1/sessions/{session['id']}", json={"title": "新标题"})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "新标题"

    exported = client.get(f"/api/v1/sessions/{session['id']}/export?fmt=markdown")
    assert "你好" in exported.text
    jsonl = client.get(f"/api/v1/sessions/{session['id']}/export?fmt=jsonl")
    assert '"role": "user"' in jsonl.text

    assert client.delete(f"/api/v1/sessions/{session['id']}").status_code == 204
    assert client.get(f"/api/v1/sessions/{session['id']}").status_code == 404
    audits = client.app.state.audit.recent()
    assert audits[0].action == "session.deleted"


def test_approvals_list_approve_reject(client: TestClient) -> None:
    service: ApprovalService = client.app.state.approvals
    one = service.request(
        "file.write", "medium", "once", '{"path":"/a"}', session_id="s1", channel="web"
    )
    two = service.request(
        "file.create", "low_write", "session", '{"path":"/b"}', session_id="s1", channel="web"
    )

    pending = client.get("/api/v1/approvals/pending").json()
    assert {item["code"] for item in pending} == {one.code, two.code}

    approved = client.post(f"/api/v1/approvals/{one.code}/approve", json={"session_id": "s1"})
    assert approved.json()["ok"] is True
    replay = client.post(f"/api/v1/approvals/{one.code}/approve", json={"session_id": "s1"})
    assert replay.json()["ok"] is False

    rejected = client.post(f"/api/v1/approvals/{two.code}/reject")
    assert rejected.json()["ok"] is True
    assert client.get("/api/v1/approvals/pending").json() == []


def test_policy_rules_and_grants_revoke(client: TestClient) -> None:
    rules = client.get("/api/v1/policy/rules").json()
    assert any(rule["tool"] == "file.delete" and rule["risk"] == "delete" for rule in rules)

    service: ApprovalService = client.app.state.approvals
    request = service.request(
        "file.create", "low_write", "session", '{"path":"/x"}', session_id="s1", channel="web"
    )
    assert service.resolve_once(
        request.code,
        session_id="s1",
        expected_scope="session",
        grant_scope="session",
        channel="web",
    ).ok
    grants = client.get("/api/v1/policy/grants").json()
    assert grants and grants[0]["tool_name"] == "file.create"

    assert client.delete(f"/api/v1/policy/grants/{grants[0]['id']}").status_code == 204
    assert not service.has_session_grant("s1", "file.create", channel="web")


def test_constraints_file_api_removed(client: TestClient) -> None:
    assert client.get("/api/v1/rules/SOUL").status_code == 404
    assert client.put("/api/v1/rules/SOUL", json={"content": "# 测试人格\n"}).status_code == 404


def test_system_health(client: TestClient) -> None:
    health = client.get("/api/v1/system/health").json()
    assert health["database"]["reachable"] is True
    assert "model" in health
    assert set(health["delegates"]) == {"codex", "hermes"}
    assert health["delegates"]["hermes"]["status"] == "disabled"
    assert "hermes" not in client.app.state.delegate_manager.providers()
    assert health["onebot"]["health"]["reason"] in {
        "ok",
        "connection_refused",
        "not_logged_in",
        "probe_failed",
        "timeout",
        "http_error",
        "invalid_json",
    }


def test_logs_endpoint(client: TestClient, settings) -> None:
    response = client.get("/api/v1/logs")
    assert response.status_code == 200
    assert (settings.data_dir / "logs" / "whitenight.log").exists()
