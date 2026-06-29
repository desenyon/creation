"""API tests for manual takeover."""

from fastapi.testclient import TestClient

from creation.server import app
from creation.store import create_project, create_run, init_db, update_run


def test_manual_message_api(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setattr("creation.store.DB_PATH", db)
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("creation.manual_takeover.DB_PATH", db)
    import creation.manual_takeover as mt

    mt._table_ready = False

    init_db()
    p = create_project("Test", idea="app", agent="codex")
    run = create_run(p.id)
    update_run(run.id, status="running")

    client = TestClient(app)
    ok = client.post(f"/api/runs/{run.id}/messages", json={"text": "Prefer pytest"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "pending"

    listed = client.get(f"/api/runs/{run.id}/messages")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    done = create_run(p.id)
    update_run(done.id, status="completed")
    bad = client.post(f"/api/runs/{done.id}/messages", json={"text": "Too late"})
    assert bad.status_code == 400
