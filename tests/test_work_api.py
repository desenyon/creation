"""HTTP surface for the work graph + CLI gating."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from creation.config import UserSecrets
from creation.store import init_db
from creation.work import store as wstore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    init_db()
    wstore.init_work_db()

    enabled = {"on": True}

    def fake_secrets():
        return UserSecrets(work_graph_enabled=enabled["on"])

    monkeypatch.setattr("creation.work.api.load_secrets", fake_secrets)

    from creation.work.api import router

    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    c._enabled = enabled  # type: ignore[attr-defined]
    return c


def test_status_reports_counts(client):
    r = client.get("/api/work/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["tickets"] == 0


def test_seed_bench_and_list(client):
    from creation.work.bench import _DEFAULT_BENCH

    n = len(_DEFAULT_BENCH)
    r = client.post("/api/work/bench/seed")
    assert r.status_code == 200
    assert len(r.json()) == n
    r2 = client.get("/api/work/agents")
    assert len(r2.json()) == n


def test_create_and_assign_ticket_flow(client):
    client.post("/api/work/bench/seed")
    r = client.post(
        "/api/work/tickets",
        json={"title": "Upgrade deps", "kind": "migration", "assign_kind": "migration"},
    )
    assert r.status_code == 200
    t = r.json()
    assert t["status"] == "todo"
    assert t["assignee_type"] == "agent"
    assert t["assignee_id"]

    detail = client.get(f"/api/work/tickets/{t['id']}").json()
    assert detail["title"] == "Upgrade deps"
    assert detail["evidence"] == []


def test_assign_then_status_transition(client):
    client.post("/api/work/bench/seed")
    tid = client.post("/api/work/tickets", json={"title": "x"}).json()["id"]
    client.post(f"/api/work/tickets/{tid}/assign", json={"agent": "code"})
    assert client.get(f"/api/work/tickets/{tid}").json()["status"] == "todo"
    client.post(f"/api/work/tickets/{tid}/status", json={"status": "done"})
    assert client.get(f"/api/work/tickets/{tid}").json()["status"] == "done"


def test_mutations_blocked_when_disabled(client):
    client._enabled["on"] = False
    assert client.post("/api/work/bench/seed").status_code == 403
    assert client.post("/api/work/tickets", json={"title": "x"}).status_code == 403
    # reads still allowed
    assert client.get("/api/work/status").status_code == 200
    assert client.get("/api/work/agents").status_code == 200


def test_assign_unknown_agent_404(client):
    tid = client.post("/api/work/tickets", json={"title": "x", "ready": True}).json()["id"]
    r = client.post(f"/api/work/tickets/{tid}/assign", json={"agent": "nope"})
    assert r.status_code == 404


# ── Live SSE event bus ─────────────────────────────────────────────────


def test_stream_endpoint_exists(client):
    from creation.work.api import router

    paths = {getattr(r, "path", None) for r in router.routes}
    assert "/api/work/stream" in paths


def test_store_mutation_publishes_event(client, monkeypatch):
    from creation.work import events

    captured = []
    monkeypatch.setattr(events, "publish", lambda e: captured.append(e))

    client.post("/api/work/bench/seed")
    client.post("/api/work/tickets", json={"title": "stream me"})

    kinds = [e.get("type") for e in captured]
    assert "work.update" in kinds
    assert any(e.get("entity") == "tickets" and e.get("op") == "insert" for e in captured)


# ── CLI gating ─────────────────────────────────────────────────────────


def test_cli_bench_requires_enabled(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    init_db()
    wstore.init_work_db()
    monkeypatch.setattr("creation.work.cli.load_secrets", lambda: UserSecrets(work_graph_enabled=False))

    from creation.work.cli import app as work_app

    res = CliRunner().invoke(work_app, ["bench"])
    assert res.exit_code == 1
    assert "off" in res.output.lower()


def test_cli_bench_lists_when_enabled(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    init_db()
    wstore.init_work_db()
    monkeypatch.setattr("creation.work.cli.load_secrets", lambda: UserSecrets(work_graph_enabled=True))

    from creation.work.cli import app as work_app

    res = CliRunner().invoke(work_app, ["bench"])
    assert res.exit_code == 0
    assert "Personal bench" in res.output
    # full default bench seeded + listed
    from creation.work.bench import _DEFAULT_BENCH

    assert len(wstore.list_agents(bench_type="personal")) == len(_DEFAULT_BENCH)
