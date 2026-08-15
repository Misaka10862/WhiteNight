"""长期记忆 API 测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_fact_crud_and_old_value_invalidated(client: TestClient) -> None:
    created = client.post(
        "/api/v1/memory/facts", json={"key": "称呼", "value": "主人", "confidence": 0.8}
    )
    assert created.status_code == 200
    fact = created.json()

    updated = client.put(f"/api/v1/memory/facts/{fact['id']}", json={"value": "亲爱的"})
    assert updated.status_code == 200
    facts = client.get("/api/v1/memory/facts").json()
    assert [item["value"] for item in facts] == ["亲爱的"]

    new_id = updated.json()["id"]
    response = client.delete(f"/api/v1/memory/facts/{new_id}")
    assert response.status_code == 204
    assert client.get("/api/v1/memory/facts").json() == []


def test_conflict_resolution_api(client: TestClient) -> None:
    first = client.post("/api/v1/memory/facts", json={"key": "喜好", "value": "晴天"}).json()
    second = client.post("/api/v1/memory/facts", json={"key": "喜好", "value": "雨天"}).json()
    facts = client.get("/api/v1/memory/facts").json()
    assert len(facts) == 2
    assert all(item["conflict_state"] == "conflicted" for item in facts)

    winner = client.post(f"/api/v1/memory/facts/{second['id']}/resolve", json={"keep": True})
    assert winner.status_code == 200
    facts = client.get("/api/v1/memory/facts").json()
    assert [item["value"] for item in facts] == ["雨天"]
    assert facts[0]["conflict_state"] == "resolved"
    assert first["id"] != facts[0]["id"]


def test_episodes_and_retrieve(client: TestClient) -> None:
    client.post("/api/v1/memory/episodes", json={"content": "第一次一起看烟花", "importance": 0.9})
    client.post("/api/v1/memory/facts", json={"key": "喜好", "value": "抹茶冰淇淋"})
    hits = client.get("/api/v1/memory/retrieve", params={"query": "抹茶"}).json()
    assert hits
    assert hits[0]["item_type"] == "fact"
    hits = client.get("/api/v1/memory/retrieve", params={"query": "烟花"}).json()
    assert hits
    assert hits[0]["item_type"] == "episode"


def test_export_endpoints(client: TestClient) -> None:
    client.post("/api/v1/memory/facts", json={"key": "称呼", "value": "主人"})
    jsonl = client.get("/api/v1/memory/export", params={"fmt": "jsonl"})
    assert jsonl.status_code == 200
    assert '"value": "主人"' in jsonl.text
    markdown = client.get("/api/v1/memory/export", params={"fmt": "markdown"})
    assert "## 结构化档案" in markdown.text


def test_extract_endpoint_with_rules(client: TestClient) -> None:
    from whitenight.agent.service import DummyProvider
    from whitenight.api.app import create_app
    from whitenight.memory.extraction import RuleBasedMemoryExtractor

    base_settings = client.app.state.settings
    with TestClient(
        create_app(
            base_settings,
            model_provider=DummyProvider(),
            memory_extractor=RuleBasedMemoryExtractor(),
        )
    ) as app_client:
        session = app_client.post("/api/v1/sessions", json={}).json()
        store = app_client.app.state.store
        store.add_message(session["id"], "user", "我喜欢抹茶冰淇淋")
        response = app_client.post("/api/v1/memory/extract", json={"session_id": session["id"]})
        assert response.status_code == 200
        facts = app_client.get("/api/v1/memory/facts").json()
        assert any(item["value"] == "抹茶冰淇淋" for item in facts)
