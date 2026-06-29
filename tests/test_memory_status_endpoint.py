"""API test for Prism memory status endpoint."""

from fastapi.testclient import TestClient

from creation.config import UserSecrets
from creation.server import app


def test_memory_status_endpoint_returns_expected_keys(monkeypatch):
    monkeypatch.setattr("creation.server.load_secrets", lambda: UserSecrets())

    client = TestClient(app)
    resp = client.get("/api/memory/status")
    assert resp.status_code == 200

    data = resp.json()
    assert data["resolved"] == "prism"
    assert data["available"]["prism"] is True


def test_memory_status_endpoint_reflects_pinned_provider(monkeypatch):
    monkeypatch.setattr(
        "creation.server.load_secrets",
        lambda: UserSecrets(memory_provider="off"),
    )

    client = TestClient(app)
    data = client.get("/api/memory/status").json()
    assert data["setting"] == "off"
    assert data["resolved"] == "off"
