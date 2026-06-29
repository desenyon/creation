"""Tests for the Repo Archaeologist — analysis, heuristic brief, and API route."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from creation.archaeology import OnboardingBrief, analyze_repo, explore_repo
from creation.config import UserSecrets

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "branch", "-M", "main")
    _git(path, "config", "user.email", "dev@example.com")
    _git(path, "config", "user.name", "Dev One")

    (path / "app.py").write_text("print('hello')\n")
    (path / "README.md").write_text("# Demo\n")
    (path / "tests").mkdir()
    (path / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")

    # a second commit that churns app.py so it shows up as a hot file
    (path / "app.py").write_text("print('hello world')\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "tweak app")
    return path


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    return _make_repo(tmp_path / "demo")


def test_analyze_repo_basic_signals(repo: Path):
    sig = analyze_repo(str(repo))
    assert sig.is_repo is True
    assert sig.repo_name == "demo"
    assert sig.total_commits == 2
    assert sig.contributors == 1
    assert sig.primary_language == "Python"
    assert sig.has_tests is True
    assert sig.has_readme is True
    assert sig.has_codeowners is False
    paths = {rf.path for rf in sig.risky_files}
    assert "app.py" in paths


def test_non_repo_returns_empty(tmp_path: Path):
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    sig = analyze_repo(str(plain))
    assert sig.is_repo is False
    brief = OnboardingBrief.from_signals(sig)
    assert brief.is_repo is False
    assert "git" in brief.summary.lower()


def test_heuristic_brief_no_nebius_key(repo: Path):
    brief = explore_repo(UserSecrets(nebius_api_key=""), str(repo))
    assert brief.generated_by == "heuristic"
    assert brief.repo_name == "demo"
    assert brief.summary
    assert brief.starter_tasks  # always proposes safe first tasks
    # no CODEOWNERS in the repo → a CODEOWNERS task should be suggested
    titles = " ".join(t["title"] for t in brief.starter_tasks).lower()
    assert "codeowners" in titles
    assert brief.stats["total_commits"] == 2


# ── API route ─────────────────────────────────────────────────────────────────
@pytest.fixture()
def client(tmp_path, monkeypatch):
    from creation.store import init_db
    from creation.work import store as wstore

    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    init_db()
    wstore.init_work_db()

    enabled = {"on": True}

    def fake_secrets():
        return UserSecrets(work_graph_enabled=enabled["on"], nebius_api_key="")

    monkeypatch.setattr("creation.work.api.load_secrets", fake_secrets)

    from creation.work.api import router

    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    c._enabled = enabled  # type: ignore[attr-defined]
    return c


def test_api_archaeology_readonly(client, repo: Path):
    r = client.post("/api/work/archaeology", json={"repo": str(repo)})
    assert r.status_code == 200
    data = r.json()
    assert data["brief"]["is_repo"] is True
    assert data["brief"]["repo_name"] == "demo"
    assert "created" not in data  # read-only by default


def test_api_archaeology_creates_tickets(client, repo: Path):
    r = client.post("/api/work/archaeology", json={"repo": str(repo), "create_tickets": True})
    assert r.status_code == 200
    data = r.json()
    assert data["mission"]["title"].startswith("Onboarding:")
    assert len(data["created"]) >= 1
    # tickets are routed to the archaeologist agent and tagged
    t0 = data["created"][0]
    assert "onboarding" in t0["labels"]
    assert t0["mission_id"] == data["mission"]["id"]


def test_api_archaeology_tickets_blocked_when_disabled(client, repo: Path):
    client._enabled["on"] = False
    r = client.post("/api/work/archaeology", json={"repo": str(repo), "create_tickets": True})
    assert r.status_code == 403
