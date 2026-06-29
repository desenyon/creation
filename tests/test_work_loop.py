"""The ticket-driven loop: prompt → worker (Work+Learn) → dispatcher (Watch) → bench."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import pytest

from creation.config import UserSecrets
from creation.store import get_run, init_db
from creation.work import store as wstore
from creation.work.bench import agent_by_kind, seed_personal_bench
from creation.work.dispatcher import default_workdir, dispatch_once
from creation.work.models import AgentDef, Ticket
from creation.work.prompt import build_ticket_prompt
from creation.work.worker import parse_evidence_block, run_ticket


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    init_db()
    wstore.init_work_db()
    return tmp_path


@dataclass
class FakeResult:
    output: str
    success: bool = True
    command: str = "fake-agent run"


class FakeRunner:
    """Simulates a coding agent: writes a file then emits an EVIDENCE block."""

    def __init__(self, *, write: dict[str, str] | None = None, success: bool = True, evidence: str | None = None):
        self.write = write or {"feature.py": "print('hi')\n"}
        self.success = success
        self.evidence = evidence
        self.calls = 0

    def run(self, prompt: str, workdir: Path, on_line: Optional[Callable[[str], None]] = None):
        self.calls += 1
        for rel, content in self.write.items():
            p = Path(workdir) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        ev = self.evidence if self.evidence is not None else (
            "EVIDENCE_BEGIN\n"
            "PLAN: added a feature module\n"
            f"CHANGED: {', '.join(self.write)}\n"
            "TESTS: none\n"
            "RISKS: none\n"
            "CONFIDENCE: 0.9\n"
            "EVIDENCE_END\n"
        )
        return FakeResult(output=f"working...\n{ev}", success=self.success)


# ── prompt ─────────────────────────────────────────────────────────────


def test_prompt_is_kind_aware_and_demands_evidence():
    t = Ticket(title="Upgrade to React 19", description="bump react", repo="acme/web")
    a = AgentDef(name="Mig", kind="migration", denied_paths=[".env"])
    prompt = build_ticket_prompt(t, a)
    assert "MIGRATION agent" in prompt
    assert "EVIDENCE_BEGIN" in prompt
    assert "acme/web" in prompt
    assert ".env" in prompt  # policy constraint surfaced


def test_parse_evidence_block_extracts_fields():
    fields = parse_evidence_block(
        "noise\nEVIDENCE_BEGIN\nPLAN: do x\nCHANGED: a.py, b.py\nCONFIDENCE: 0.7\nEVIDENCE_END\n"
    )
    assert fields["plan"] == "do x"
    assert fields["changed"] == "a.py, b.py"
    assert fields["confidence"] == "0.7"


# ── worker: Work + Learn ───────────────────────────────────────────────


def test_run_ticket_produces_evidence_and_moves_to_review(isolated_store, tmp_path):
    repo = tmp_path / "repo"
    t = wstore.create_ticket(Ticket(title="Add feature", repo=str(repo)))
    a = wstore.create_agent(AgentDef(name="Code", kind="code", require_approval=True))
    runner = FakeRunner(write={"feature.py": "x = 1\n"})

    res = run_ticket(t, a, repo, UserSecrets(), runner=runner)

    assert res.success is True
    assert res.status == "in_review"  # approval-required → stops at review
    assert "feature.py" in res.evidence.files_modified
    assert res.evidence.confidence == 0.9
    assert wstore.get_ticket(t.id).status == "in_review"
    # run is linked + recorded
    assert res.run_id in wstore.get_ticket(t.id).run_ids
    run = get_run(res.run_id)
    assert run.ticket_id == t.id
    assert run.status == "done"


def test_run_ticket_autodone_when_no_approval(isolated_store, tmp_path):
    repo = tmp_path / "repo"
    t = wstore.create_ticket(Ticket(title="tidy", repo=str(repo)))
    a = wstore.create_agent(AgentDef(name="Test", kind="test", require_approval=False, risk_tier="low"))
    res = run_ticket(t, a, repo, UserSecrets(), runner=FakeRunner())
    assert res.status == "done"


def test_run_ticket_high_risk_forces_review(isolated_store, tmp_path):
    repo = tmp_path / "repo"
    t = wstore.create_ticket(Ticket(title="touch auth", repo=str(repo), risk_tier="high"))
    a = wstore.create_agent(AgentDef(name="Code", kind="code", require_approval=False))
    res = run_ticket(t, a, repo, UserSecrets(), runner=FakeRunner())
    assert res.status == "in_review"


def test_run_ticket_failure_blocks(isolated_store, tmp_path):
    repo = tmp_path / "repo"
    t = wstore.create_ticket(Ticket(title="broken", repo=str(repo)))
    a = wstore.create_agent(AgentDef(name="Code", kind="code"))
    res = run_ticket(t, a, repo, UserSecrets(), runner=FakeRunner(success=False))
    assert res.success is False
    assert res.status == "blocked"
    assert wstore.get_ticket(t.id).status == "blocked"
    assert get_run(res.run_id).status == "error"


def test_run_ticket_commits_changes(isolated_store, tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    t = wstore.create_ticket(Ticket(title="Add feature", repo=str(repo)))
    a = wstore.create_agent(AgentDef(name="Code", kind="code"))
    run_ticket(t, a, repo, UserSecrets(), runner=FakeRunner(write={"f.py": "y = 2\n"}))
    log = subprocess.run(["git", "log", "--oneline"], cwd=str(repo), capture_output=True, text=True)
    assert t.id in log.stdout  # ticket id is in the commit message


# ── dispatcher: Watch ──────────────────────────────────────────────────


def test_dispatch_runs_only_actionable_agent_tickets(isolated_store, tmp_path):
    agent = wstore.create_agent(AgentDef(name="Code", kind="code", require_approval=False))
    repo = tmp_path / "repo"
    ready = wstore.create_ticket(Ticket(title="ready", repo=str(repo), status="todo"))
    wstore.assign_ticket(ready.id, assignee_type="agent", assignee_id=agent.id)
    # backlog (not todo) and human-assigned should be ignored
    wstore.create_ticket(Ticket(title="backlog", status="backlog"))
    wstore.create_ticket(Ticket(title="human", status="todo", assignee_type="user", assignee_id="me"))

    results = dispatch_once(secrets=UserSecrets(), runner_factory=lambda a: FakeRunner())
    assert len(results) == 1
    assert results[0].ticket_id == ready.id


def test_dispatch_blocks_when_repo_not_allowed(isolated_store, tmp_path):
    agent = wstore.create_agent(AgentDef(name="Scoped", kind="code", allowed_repos=["acme/api"]))
    t = wstore.create_ticket(Ticket(title="x", repo="acme/web", status="todo"))
    wstore.assign_ticket(t.id, assignee_type="agent", assignee_id=agent.id)
    results = dispatch_once(secrets=UserSecrets(), runner_factory=lambda a: FakeRunner())
    assert results == []
    assert wstore.get_ticket(t.id).status == "blocked"


def test_dispatch_appends_second_ticket_to_running_loop(isolated_store, tmp_path):
    """One task per agent per pass — extra work is appended (left todo), not run twice."""
    agent = wstore.create_agent(AgentDef(name="Code", kind="code", require_approval=False))
    repo = tmp_path / "repo"
    first = wstore.create_ticket(Ticket(title="first", repo=str(repo), status="todo"))
    second = wstore.create_ticket(Ticket(title="second", repo=str(repo), status="todo"))
    for t in (first, second):
        wstore.assign_ticket(t.id, assignee_type="agent", assignee_id=agent.id)

    results = dispatch_once(secrets=UserSecrets(), runner_factory=lambda a: FakeRunner())
    assert len(results) == 1  # only one ran this pass
    statuses = {wstore.get_ticket(first.id).status, wstore.get_ticket(second.id).status}
    assert "todo" in statuses  # the other stayed queued for the loop's next pass


def test_dispatch_skips_paused_agent(isolated_store):
    agent = wstore.create_agent(AgentDef(name="Paused", kind="code", status="paused"))
    t = wstore.create_ticket(Ticket(title="x", status="todo"))
    wstore.assign_ticket(t.id, assignee_type="agent", assignee_id=agent.id)
    results = dispatch_once(secrets=UserSecrets(), runner_factory=lambda a: FakeRunner())
    assert results == []
    assert wstore.get_ticket(t.id).status == "todo"  # left for when agent resumes


def test_default_workdir_prefers_existing_local_path(isolated_store, tmp_path):
    repo = tmp_path / "live"
    repo.mkdir()
    t = Ticket(title="x", repo=str(repo))
    assert default_workdir(t) == repo


# ── bench ──────────────────────────────────────────────────────────────


def test_seed_personal_bench_is_idempotent(isolated_store):
    from creation.work.bench import _DEFAULT_BENCH

    n = len(_DEFAULT_BENCH)
    first = seed_personal_bench()
    assert len(first) == n
    again = seed_personal_bench()
    assert len(again) == n  # not duplicated
    assert {a.kind for a in again} == {kind for _, kind, *_ in _DEFAULT_BENCH}


def test_agent_by_kind_lookup(isolated_store):
    seed_personal_bench()
    mig = agent_by_kind("migration")
    assert mig is not None
    assert mig.kind == "migration"
