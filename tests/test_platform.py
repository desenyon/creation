"""Platform features — templates, queue, webhooks, portfolio, git PR helpers."""

import sys
import types
from types import SimpleNamespace

from pathlib import Path

if "torch" not in sys.modules:
    torch_stub = types.ModuleType("torch")
    nn_stub = types.ModuleType("torch.nn")

    class _TorchModule:
        def __init__(self, *args, **kwargs):
            pass

    class _TorchSequential(_TorchModule):
        pass

    nn_stub.Module = _TorchModule
    nn_stub.Sequential = _TorchSequential
    nn_stub.Linear = _TorchModule
    nn_stub.LayerNorm = _TorchModule
    nn_stub.GELU = _TorchModule
    torch_stub.nn = nn_stub
    torch_stub.Tensor = object
    torch_stub.sigmoid = lambda value: value
    sys.modules["torch"] = torch_stub
    sys.modules["torch.nn"] = nn_stub

from creation.config import UserSecrets
from creation.integrations.marketing import MarketingResult
from creation.integrations.git_sync import workdir_diff
from creation.store import create_project, enqueue_project, init_db, list_queue, portfolio_summary
from creation.templates import apply_template, list_templates
from creation.webhooks import sign_payload


def test_list_templates():
    t = list_templates()
    assert any(x["id"] == "cli" for x in t)


def test_apply_cli_template(tmp_path):
    wd = tmp_path / "p"
    hint = apply_template(wd, "cli", "sync tool")
    assert "CLI" in hint
    assert (wd / "app" / "main.py").exists()
    assert (wd / "api" / "index.py").exists()
    assert (wd / "vercel.json").exists()


def test_python_templates_are_vercel_ready(tmp_path):
    for template_id in ("python-api", "stripe-saas", "qdrant-rag", "motherduck-analytics"):
        wd = tmp_path / template_id
        apply_template(wd, template_id, "ship it")
        assert (wd / "api" / "index.py").exists()
        assert (wd / "vercel.json").exists()


def test_workdir_diff_empty(tmp_path):
    assert workdir_diff(tmp_path) == ""


def test_webhook_sign():
    sig = sign_payload("secret", b'{"a":1}')
    assert len(sig) == 64


def test_queue_and_portfolio(tmp_path, monkeypatch):
    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    init_db()
    p = create_project("Q", template_id="cli")
    qid = enqueue_project(p.id, "seed idea")
    assert qid
    assert len(list_queue()) == 1
    pf = portfolio_summary()
    assert pf and pf[0]["name"] == "Q"


def test_templates_api():
    from fastapi.testclient import TestClient

    from creation.server import app

    client = TestClient(app)
    r = client.get("/api/templates")
    assert r.status_code == 200
    assert len(r.json()) >= 3


def test_portfolio_api():
    from fastapi.testclient import TestClient

    from creation.server import app

    client = TestClient(app)
    assert client.get("/api/portfolio").status_code == 200


def test_board_route_removed():
    from fastapi.testclient import TestClient

    from creation.server import app

    client = TestClient(app)
    assert client.get("/board").status_code == 404


def test_testers_page_route():
    from fastapi.testclient import TestClient

    from creation.server import app

    client = TestClient(app)
    r = client.get("/testers")
    assert r.status_code == 200
    assert "Feedback portal" in r.text
    assert "Send feedback" in r.text


def test_tester_feedback_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    import creation.server as server

    client = TestClient(server.app)
    monkeypatch.setattr(
        server,
        "load_secrets",
        lambda: UserSecrets(
            resend_api_key="re-test",
            resend_from="Creation <hello@creation.dev>",
            marketing_to="arjun@example.com",
        ),
    )
    monkeypatch.setattr(server, "get_settings", lambda: SimpleNamespace(creation_demo=False))
    monkeypatch.setattr(
        server,
        "_send_tester_feedback_email",
        lambda sec, body, demo=False: MarketingResult(True, provider="resend", message="sent", channels=["email"]),
    )
    r = client.post(
        "/api/testers/feedback",
        json={
            "name": "Arjun",
            "email": "arjun@example.com",
            "project": "Creation",
            "feedback": "Works.",
        },
    )
    assert r.status_code == 200
    assert r.json()["provider"] == "resend"
