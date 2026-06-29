"""Basic tests for Creation."""

from creation.memory import compress_for_turn
from creation.store import create_project, init_db, list_projects
from creation.agents.runner import available_agents


def test_compress_for_turn():
    blocks = ["## Tavily\nAI agents need memory.", "## GitHub\nPR #1 open"]
    text, mem = compress_for_turn(blocks, "What to ship?", budget_ratio=0.35)
    assert mem.original_tokens > 0
    assert mem.kept_tokens > 0
    assert mem.kept_tokens < mem.original_tokens
    assert mem.policy_name in ("Prism", "H2O-fallback")
    assert text


def test_store_project(tmp_path, monkeypatch):
    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    init_db()
    p = create_project("Test", idea="CLI tool", agent="codex")
    assert p.id
    assert list_projects()


def test_product_brand_slug():
    from creation.nebius_client import ProductBrand, _fallback_slug

    b = ProductBrand.from_idea("CLI that connects to the Creation frontend dashboard")
    assert len(b.repo_slug) <= 18
    assert _fallback_slug("My Cool App!!", 18) == "my-cool-app"


def test_parse_pytest_failures():
    from creation.review.qa import _parse_pytest_failures

    out = "FAILED tests/test_api.py::test_x - AssertionError: boom\n1 failed, 2 passed"
    fails = _parse_pytest_failures(out)
    assert fails and "test_x" in fails[0].test_id


def test_collect_sync_files(tmp_path):
    from creation.integrations.project_tracker import ProjectTracker
    from creation.integrations.composio_ops import ComposioOps
    from creation.config import UserSecrets

    wd = tmp_path / "proj"
    (wd / "src").mkdir(parents=True)
    (wd / "src" / "main.py").write_text("print('hi')")
    (wd / "README.md").write_text("# hi")
    (wd / ".venv" / "x").mkdir(parents=True)
    (wd / ".venv" / "x" / "y.py").write_text("skip")
    tracker = ProjectTracker(ComposioOps(UserSecrets(), demo=True), UserSecrets())
    files = tracker._collect_sync_files(wd)
    assert files[0] == "src/main.py"
    assert "src/main.py" in files
    assert "README.md" in files
    assert not any(".venv" in f for f in files)


def test_sync_skips_composio_when_git_pushed(tmp_path):
    from creation.integrations.project_tracker import ProjectTracker, TrackState
    from creation.integrations.composio_ops import ComposioOps
    from creation.config import UserSecrets

    calls = []

    class FakeOps(ComposioOps):
        def github_upsert_file(self, owner, repo, path, content, message):
            calls.append(path)
            return super().github_upsert_file(owner, repo, path, content, message)

    wd = tmp_path / "proj"
    wd.mkdir()
    (wd / "main.py").write_text("x = 1")
    tracker = ProjectTracker(FakeOps(UserSecrets(), demo=True), UserSecrets())
    tracker.state = TrackState(github_owner="o", github_repo="r", github_url="https://github.com/o/r")
    tracker.sync_workdir_to_github(wd, 1, "idea", composio_fallback=False)
    assert calls == []


def test_iteration_note_includes_agent_and_tests(tmp_path):
    from creation.integrations.project_tracker import ProjectTracker
    from creation.integrations.composio_ops import ComposioOps
    from creation.config import UserSecrets
    from creation.review.qa import QABundle, TestReport, TestFailure

    tracker = ProjectTracker(ComposioOps(UserSecrets(), demo=True), UserSecrets())
    qa = QABundle(
        tests=TestReport(ran=True, passed=2, failed=1, failures=[TestFailure("test_x", "boom")]),
    )
    note = tracker._iteration_note(
        turn=3,
        agent_ok=True,
        agent_excerpt="Created src/todo.py with CLI entrypoint",
        qa=qa,
        board_summary="Step 2 in progress",
        diff_stat=" src/todo.py | 42 +++++",
        git_pushed=True,
    )
    assert "src/todo.py" in note
    assert "2 passed, 1 failed" in note
    assert "git push" in note.lower()


def test_delete_project(tmp_path, monkeypatch):
    from creation.store import create_run, delete_project, enqueue_project, get_project, update_run

    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    init_db()
    p = create_project("Gone", idea="x", agent="cursor")
    run = create_run(p.id)
    update_run(run.id, status="running")
    enqueue_project(p.id)
    assert delete_project(p.id)
    assert get_project(p.id) is None


def test_delete_project_api():
    from fastapi.testclient import TestClient

    from creation.server import app

    client = TestClient(app)
    created = client.post("/api/projects", json={"name": "Del", "agent": "cursor"}).json()
    r = client.post(f"/api/projects/{created['id']}/delete")
    assert r.status_code == 200
    assert client.get(f"/api/projects/{created['id']}").status_code == 404


def test_available_agents():
    agents = available_agents()
    ids = {a["id"] for a in agents}
    assert len(agents) >= 40
    assert {"codex", "claude", "openclaw", "opencode", "cursor"}.issubset(ids)
    assert {"copilot", "gemini", "freebuff", "backboard", "cto"}.issubset(ids)
    for a in agents:
        assert {"id", "label", "available", "bins", "local_auth", "auth"}.issubset(a.keys())


def test_openclaw_agent_command(monkeypatch):
    from creation.agents.registry import build_command, resolve_spec

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npx" if name == "npx" else None)
    cmd = build_command(resolve_spec("openclaw"), "Build the feature")
    assert cmd[:5] == ["npx", "-y", "openclaw", "agent", "--local"]
    assert "--message" in cmd
    assert "Build the feature" in cmd[cmd.index("--message") + 1]


def test_parse_plan_steps():
    from creation.integrations.project_tracker import parse_plan_steps

    plan = "1. Scaffold app\n2. Add tests\n3. Ship"
    steps = parse_plan_steps(plan)
    assert len(steps) == 3
    assert "Scaffold" in steps[0]


def test_track_state_context():
    from creation.integrations.project_tracker import LinearIssueRef, TrackState

    s = TrackState(
        linear_project_url="https://linear.app/p/x",
        github_url="https://github.com/o/r",
        linear_issues=[LinearIssueRef(id="1", title="Step 1", state="done")],
    )
    block = s.to_context_block()
    assert "Linear" in block and "GitHub" in block


def test_firecrawl_via_composio_demo():
    from creation.config import UserSecrets
    from creation.integrations.composio_ops import ComposioOps
    from creation.research.firecrawl import FirecrawlResearch

    secrets = UserSecrets()
    ops = ComposioOps(secrets, demo=True)
    bundle = FirecrawlResearch(secrets, composio=ops, demo=True).scrape_urls(
        ["https://example.com/a", "https://example.com/b"]
    )
    assert len(bundle.pages) >= 1
    assert "Lens" in bundle.to_context_block()


def test_validate_live_run_missing_keys(monkeypatch):
    from creation.config import UserSecrets
    from creation.validate import RunValidationError, validate_live_run

    monkeypatch.setattr(
        "creation.validate.AccountStore",
        type(
            "X",
            (),
            {"ensure_local_account": staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("no account")))},
        ),
    )
    monkeypatch.setattr(
        "creation.validate.available_agents",
        lambda: [{"id": "codex", "available": False}],
    )
    secrets = UserSecrets(account_token="", forge_offline=False)
    try:
        validate_live_run(secrets, "codex")
        assert False, "expected validation error"
    except RunValidationError as e:
        assert "Missing" in str(e)
