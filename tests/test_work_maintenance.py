"""Phase 2: triggers (always-on), missions (fan-out), loop templates, evals."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import pytest

from creation.config import UserSecrets
from creation.store import init_db
from creation.work import store as wstore
from creation.work.bench import LOOP_TEMPLATES, create_loop_agent, seed_personal_bench
from creation.work.dispatcher import actionable_tickets, dispatch_once
from creation.work.evals import agent_metrics, bench_metrics
from creation.work.missions import (
    fan_out_across_repos,
    fan_out_mission,
    mission_progress,
    sync_mission_status,
)
from creation.work.models import AgentDef, Mission, Ticket
from creation.work.triggers import (
    actionable_statuses_for,
    create_cron_trigger,
    create_status_trigger,
    create_webhook_trigger,
    due_cron_triggers,
    handle_webhook_event,
    tick,
)


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    init_db()
    wstore.init_work_db()
    return tmp_path


class FakeRunner:
    def run(self, prompt: str, workdir: Path, on_line: Optional[Callable[[str], None]] = None):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        (Path(workdir) / "f.py").write_text("x = 1\n")

        class R:
            output = "EVIDENCE_BEGIN\nPLAN: p\nCHANGED: f.py\nCONFIDENCE: 0.8\nEVIDENCE_END"
            success = True
            command = "fake"

        return R()


# ── cron triggers ──────────────────────────────────────────────────────


def test_new_cron_trigger_is_due_immediately(isolated_store):
    a = wstore.create_agent(AgentDef(name="Loop", kind="test"))
    create_cron_trigger(a.id, every_seconds=3600, ticket={"title": "scan"})
    assert len(due_cron_triggers()) == 1


def test_tick_fires_due_trigger_and_creates_ticket(isolated_store):
    a = wstore.create_agent(AgentDef(name="Loop", kind="test", require_approval=False))
    create_cron_trigger(a.id, every_seconds=3600, ticket={"title": "nightly scan", "repo": "acme/api"})
    created = tick()
    assert len(created) == 1
    t = created[0]
    assert t.title == "nightly scan"
    assert t.assignee_id == a.id
    assert t.status == "todo"
    assert t.source == "agent"
    # immediately ticking again should not double-fire (interval not elapsed)
    assert tick() == []


def test_cron_not_due_until_interval_elapses(isolated_store):
    a = wstore.create_agent(AgentDef(name="Loop", kind="test"))
    trg = create_cron_trigger(a.id, every_seconds=3600, ticket={"title": "scan"})
    tick()  # fires once, sets last_fired_at
    assert due_cron_triggers() == []
    # backdate last_fired_at beyond the interval → due again
    trg = wstore.get_trigger(trg.id)
    trg.last_fired_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    wstore.update_trigger(trg)
    assert len(due_cron_triggers()) == 1


def test_paused_agent_trigger_does_not_fire(isolated_store):
    a = wstore.create_agent(AgentDef(name="Loop", kind="test", status="paused"))
    create_cron_trigger(a.id, every_seconds=3600, ticket={"title": "scan"})
    assert tick() == []


# ── webhook triggers ───────────────────────────────────────────────────


def test_webhook_event_spawns_ticket_with_interpolation(isolated_store):
    a = wstore.create_agent(AgentDef(name="CI Fixer", kind="debug"))
    create_webhook_trigger(
        a.id, source="ci_failed", ticket={"title": "Fix CI on {branch}", "repo": "acme/api"}
    )
    created = handle_webhook_event("ci_failed", {"branch": "main"})
    assert len(created) == 1
    assert created[0].title == "Fix CI on main"
    assert created[0].source == "incident"
    # non-matching source does nothing
    assert handle_webhook_event("deploy_ok", {}) == []


# ── status triggers + dispatcher integration ───────────────────────────


def test_status_trigger_makes_custom_status_actionable(isolated_store):
    a = wstore.create_agent(AgentDef(name="A", kind="code"))
    create_status_trigger(a.id, status="ready")
    assert set(actionable_statuses_for(a.id)) == {"todo", "ready"}

    t = wstore.create_ticket(Ticket(title="x", status="ready"))
    wstore.assign_ticket(t.id, assignee_type="agent", assignee_id=a.id)
    found = [x.id for x in actionable_tickets()]
    assert t.id in found


def test_dispatch_fires_triggers_then_runs(isolated_store, tmp_path):
    a = wstore.create_agent(AgentDef(name="Loop", kind="test", require_approval=False))
    create_cron_trigger(
        a.id, every_seconds=3600, ticket={"title": "scan", "repo": str(tmp_path / "r")}
    )
    results = dispatch_once(secrets=UserSecrets(), runner_factory=lambda ag: FakeRunner())
    # the cron trigger created a ticket and it was worked in the same pass
    assert len(results) == 1
    assert results[0].status == "done"


# ── loop templates ─────────────────────────────────────────────────────


def test_create_loop_agent_with_cron(isolated_store):
    agent, trigger = create_loop_agent("flaky-test-killer", repo="acme/api")
    assert agent.kind == "test"
    assert agent.require_approval is False
    assert trigger is not None
    assert trigger.config["ticket"]["repo"] == "acme/api"
    assert "flaky-test-killer" in LOOP_TEMPLATES


def test_create_loop_agent_unknown_template_raises(isolated_store):
    with pytest.raises(ValueError):
        create_loop_agent("nope")


def test_bug_backlog_template_has_no_cron(isolated_store):
    agent, trigger = create_loop_agent("bug-backlog")
    assert trigger is None


# ── missions ───────────────────────────────────────────────────────────


def test_fan_out_mission_creates_assigned_children(isolated_store):
    seed_personal_bench()
    m = wstore.create_mission(Mission(title="Migrate everything"))
    created = fan_out_mission(
        m.id,
        [
            {"title": "repo a", "repo": "acme/a", "agent": "migration"},
            {"title": "repo b", "repo": "acme/b", "agent": "migration"},
        ],
    )
    assert len(created) == 2
    assert all(t.status == "todo" and t.assignee_type == "agent" for t in created)
    # mission flipped planning → active
    assert wstore.get_mission(m.id).status == "active"


def test_fan_out_across_repos_interpolates_title(isolated_store):
    seed_personal_bench()
    m = wstore.create_mission(Mission(title="React 19"))
    created = fan_out_across_repos(
        m.id, ["acme/web", "acme/admin"], agent="migration", title="Upgrade {repo} to React 19"
    )
    titles = sorted(t.title for t in created)
    assert titles == ["Upgrade acme/admin to React 19", "Upgrade acme/web to React 19"]


def test_mission_progress_and_completion(isolated_store):
    seed_personal_bench()
    m = wstore.create_mission(Mission(title="M"))
    children = fan_out_across_repos(m.id, ["a", "b"], agent="code", title="t {repo}")
    prog = mission_progress(m.id)
    assert prog["total"] == 2
    assert prog["complete"] is False

    for c in children:
        wstore.set_ticket_status(c.id, "done")
    prog = mission_progress(m.id)
    assert prog["done"] == 2
    assert prog["done_pct"] == 100.0
    assert prog["complete"] is True
    assert sync_mission_status(m.id).status == "complete"


def test_fan_out_unknown_mission_raises(isolated_store):
    with pytest.raises(ValueError):
        fan_out_mission("missing", [{"title": "x", "agent": "code"}])


# ── evals ──────────────────────────────────────────────────────────────


def test_agent_metrics_acceptance_rate(isolated_store, tmp_path):
    a = wstore.create_agent(AgentDef(name="Code", kind="code", require_approval=False))
    from creation.work.worker import run_ticket

    # one success (→ done) assigned to the agent
    good = wstore.create_ticket(Ticket(title="good", repo=str(tmp_path / "g")))
    wstore.assign_ticket(good.id, assignee_type="agent", assignee_id=a.id)
    run_ticket(wstore.get_ticket(good.id), a, tmp_path / "g", UserSecrets(), runner=FakeRunner())

    class FailRunner:
        def run(self, prompt, workdir, on_line=None):
            class R:
                output = ""
                success = False
                command = "x"

            return R()

    # one failure (→ blocked) assigned to the agent
    bad = wstore.create_ticket(Ticket(title="bad", repo=str(tmp_path / "b")))
    wstore.assign_ticket(bad.id, assignee_type="agent", assignee_id=a.id)
    run_ticket(wstore.get_ticket(bad.id), a, tmp_path / "b", UserSecrets(), runner=FailRunner())

    m = agent_metrics(a.id)
    assert m["assigned"] == 2
    assert m["done"] == 1
    assert m["blocked"] == 1
    assert m["acceptance_rate"] == 0.5
    assert m["runs"] == 2
    assert m["avg_confidence"] > 0  # the successful run reported confidence


def test_bench_metrics_reports_all_agents(isolated_store):
    from creation.work.bench import _DEFAULT_BENCH

    seed_personal_bench()
    metrics = bench_metrics()
    assert len(metrics) == len(_DEFAULT_BENCH)
    assert all("acceptance_rate" in row for row in metrics)
