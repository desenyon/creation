"""Routing: decide whether new work spawns an agent or joins a running loop."""

import pytest

from creation.store import init_db
from creation.work import store as wstore
from creation.work.models import AgentDef, Ticket
from creation.work.routing import auto_route, estimate_complexity, infer_kind, route_ticket
from creation.work.triggers import create_cron_trigger


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    init_db()
    wstore.init_work_db()
    return tmp_path


# ── kind inference ─────────────────────────────────────────────────────


def test_infer_kind_from_labels_wins():
    assert infer_kind(Ticket(title="anything", labels=["security"])) == "security"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Upgrade to React 19", "migration"),
        ("Fix flaky checkout test", "test"),
        ("Patch auth bypass CVE", "security"),
        ("Reduce p99 latency", "performance"),
        ("Update the README", "docs"),
        ("Build a new dashboard widget", "code"),
    ],
)
def test_infer_kind_from_keywords(title, expected):
    assert infer_kind(Ticket(title=title)) == expected


# ── spawn vs append ─────────────────────────────────────────────────────


def test_spawn_when_no_loop_exists(isolated_store):
    wstore.create_agent(AgentDef(name="Code", kind="code"))
    t = wstore.create_ticket(Ticket(title="Build a feature", repo="acme/web"))
    d = route_ticket(t)
    assert d.action == "spawn"
    assert d.agent_name == "Code"


def test_manual_when_no_eligible_agent(isolated_store):
    # only a scoped agent that can't touch this repo
    wstore.create_agent(AgentDef(name="Scoped", kind="code", allowed_repos=["acme/api"]))
    t = wstore.create_ticket(Ticket(title="x", repo="acme/web"))
    d = route_ticket(t)
    assert d.action == "manual"
    assert d.agent_id is None


def test_append_to_agent_mid_run_on_same_repo(isolated_store):
    agent = wstore.create_agent(AgentDef(name="Code", kind="code"))
    busy = wstore.create_ticket(Ticket(title="in flight", repo="acme/web", status="in_progress"))
    wstore.assign_ticket(busy.id, assignee_type="agent", assignee_id=agent.id)

    t = wstore.create_ticket(Ticket(title="another change", repo="acme/web"))
    d = route_ticket(t)
    assert d.action == "append"
    assert d.agent_id == agent.id
    assert "mid-run" in d.reason


def test_append_to_cron_maintenance_loop_scoped_to_repo(isolated_store):
    agent = wstore.create_agent(
        AgentDef(name="Dep Upgrade", kind="migration", allowed_repos=["acme/web"])
    )
    create_cron_trigger(agent.id, every_seconds=86400, ticket={"title": "weekly bumps"})

    t = wstore.create_ticket(Ticket(title="Upgrade lodash", repo="acme/web"))
    d = route_ticket(t)
    assert d.action == "append"
    assert d.agent_id == agent.id


def test_loop_does_not_capture_mismatched_kind(isolated_store):
    # a docs loop should not swallow a migration ticket; a fresh migration agent spawns
    docs = wstore.create_agent(AgentDef(name="Docs", kind="docs", allowed_repos=["acme/web"]))
    create_cron_trigger(docs.id, every_seconds=86400, ticket={"title": "docs"})
    wstore.create_agent(AgentDef(name="Mig", kind="migration"))

    t = wstore.create_ticket(Ticket(title="Upgrade to React 19", repo="acme/web"))
    d = route_ticket(t)
    assert d.action == "spawn"
    assert d.agent_name == "Mig"


def test_auto_route_assigns_and_makes_actionable(isolated_store):
    agent = wstore.create_agent(AgentDef(name="Code", kind="code"))
    t = wstore.create_ticket(Ticket(title="Build a feature", repo="acme/web"))
    d = auto_route(t)
    assert d.action == "spawn"
    updated = wstore.get_ticket(t.id)
    assert updated.assignee_type == "agent"
    assert updated.assignee_id == agent.id
    assert updated.status == "todo"


# ── complexity sizing ───────────────────────────────────────────────────


def test_estimate_complexity_small_vs_large():
    small = estimate_complexity(Ticket(title="Fix a typo in the footer"))
    assert small.size == "small"

    big = estimate_complexity(
        Ticket(
            title="Build the entire billing platform from scratch",
            description="- subscriptions\n- invoices\n- webhooks\n- dunning\n- tax\n",
            priority="high",
            risk_tier="high",
        )
    )
    assert big.size == "large"
    assert big.signals  # explainable


def test_epic_label_forces_large():
    assert estimate_complexity(Ticket(title="x", labels=["epic"])).size == "large"


# ── size-aware spawn vs append ──────────────────────────────────────────


def test_big_task_spawns_dedicated_agent_even_with_active_loop(isolated_store):
    busy_agent = wstore.create_agent(AgentDef(name="Code A", kind="code"))
    inflight = wstore.create_ticket(Ticket(title="in flight", repo="acme/web", status="in_progress"))
    wstore.assign_ticket(inflight.id, assignee_type="agent", assignee_id=busy_agent.id)
    free_agent = wstore.create_agent(AgentDef(name="Code B", kind="code"))

    big = wstore.create_ticket(
        Ticket(
            title="Build the entire billing platform from scratch",
            description="- subscriptions\n- invoices\n- webhooks\n- dunning\n",
            priority="high",
            risk_tier="high",
            repo="acme/web",
        )
    )
    d = route_ticket(big)
    assert d.action == "spawn"
    assert d.agent_id == free_agent.id  # least-loaded agent, not the busy loop
    assert d.size == "large"


def test_small_task_appends_to_active_loop(isolated_store):
    agent = wstore.create_agent(AgentDef(name="Code", kind="code"))
    inflight = wstore.create_ticket(Ticket(title="in flight", repo="acme/web", status="in_progress"))
    wstore.assign_ticket(inflight.id, assignee_type="agent", assignee_id=agent.id)

    small = wstore.create_ticket(Ticket(title="Tweak the button color", priority="low", repo="acme/web"))
    d = route_ticket(small)
    assert d.action == "append"
    assert d.agent_id == agent.id
    assert d.size == "small"


def test_overloaded_loop_spawns_to_free_agent(isolated_store):
    busy = wstore.create_agent(AgentDef(name="Busy", kind="code"))
    for i in range(4):
        tk = wstore.create_ticket(Ticket(title=f"open {i}", repo="acme/web", status="in_progress"))
        wstore.assign_ticket(tk.id, assignee_type="agent", assignee_id=busy.id)
    free = wstore.create_agent(AgentDef(name="Free", kind="code"))

    t = wstore.create_ticket(Ticket(title="Refactor the auth module", priority="high", repo="acme/web"))
    d = route_ticket(t)
    assert d.action == "spawn"
    assert d.agent_id == free.id
