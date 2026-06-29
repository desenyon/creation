"""Work-graph store: tickets, agents, triggers, evidence, missions + scope defaults."""

import pytest

from creation.store import create_project, create_run, get_run, init_db, update_run
from creation.work import AgentDef, EvidencePack, Mission, Ticket, Trigger
from creation.work import store as wstore
from creation.work.models import LOCAL_ORG, LOCAL_USER


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    init_db()
    wstore.init_work_db()
    return tmp_path


# ── scope defaults: personal/local-first ──────────────────────────────


def test_ticket_defaults_to_personal_scope(isolated_store):
    t = wstore.create_ticket(Ticket(title="fix flaky test"))
    assert t.org_id == LOCAL_ORG
    assert t.user_id == LOCAL_USER
    assert t.visibility == "private"
    assert t.scope.is_personal is True


def test_mission_defaults_to_team_visibility(isolated_store):
    m = wstore.create_mission(Mission(title="Migrate to React 19"))
    assert m.visibility == "team"
    assert m.scope.is_personal is False


# ── ticket CRUD + lifecycle ───────────────────────────────────────────


def test_ticket_roundtrip_preserves_json_fields(isolated_store):
    t = wstore.create_ticket(
        Ticket(title="add OAuth", labels=["auth", "backend"], repo="acme/api")
    )
    got = wstore.get_ticket(t.id)
    assert got is not None
    assert got.labels == ["auth", "backend"]
    assert got.repo == "acme/api"


def test_assign_ticket_to_agent_and_filter(isolated_store):
    agent = wstore.create_agent(AgentDef(name="Migration Bot", kind="migration"))
    t = wstore.create_ticket(Ticket(title="bump deps"))
    wstore.assign_ticket(t.id, assignee_type="agent", assignee_id=agent.id)

    agent_tickets = wstore.list_tickets(assignee_type="agent", assignee_id=agent.id)
    assert [x.id for x in agent_tickets] == [t.id]
    assert agent_tickets[0].assigned_to_agent() is True


def test_set_status_and_filter_by_status(isolated_store):
    t = wstore.create_ticket(Ticket(title="thing"))
    wstore.set_ticket_status(t.id, "in_progress")
    assert wstore.get_ticket(t.id).status == "in_progress"
    assert len(wstore.list_tickets(status="in_progress")) == 1
    assert len(wstore.list_tickets(status="done")) == 0


def test_link_run_to_ticket_appends_unique(isolated_store):
    t = wstore.create_ticket(Ticket(title="thing"))
    wstore.link_run_to_ticket(t.id, "run-1")
    wstore.link_run_to_ticket(t.id, "run-1")
    wstore.link_run_to_ticket(t.id, "run-2")
    assert wstore.get_ticket(t.id).run_ids == ["run-1", "run-2"]


# ── agents ─────────────────────────────────────────────────────────────


def test_agent_bench_filter(isolated_store):
    wstore.create_agent(AgentDef(name="Personal Reviewer", bench_type="personal"))
    wstore.create_agent(AgentDef(name="Org Security", bench_type="org"))
    assert len(wstore.list_agents(bench_type="personal")) == 1
    assert len(wstore.list_agents(bench_type="org")) == 1


def test_agent_policy_repo_scoping(isolated_store):
    a = wstore.create_agent(AgentDef(name="Scoped", allowed_repos=["acme/api"]))
    assert a.can_touch_repo("acme/api") is True
    assert a.can_touch_repo("acme/web") is False
    open_agent = AgentDef(name="Open")
    assert open_agent.can_touch_repo("anything") is True


def test_agent_require_approval_bool_roundtrip(isolated_store):
    a = wstore.create_agent(AgentDef(name="X", require_approval=False))
    got = wstore.get_agent(a.id)
    assert got.require_approval is False


# ── triggers ───────────────────────────────────────────────────────────


def test_trigger_config_roundtrip_and_enabled_filter(isolated_store):
    agent = wstore.create_agent(AgentDef(name="Cron Bot"))
    wstore.create_trigger(
        Trigger(agent_id=agent.id, kind="cron", config={"cron": "0 2 * * *"})
    )
    wstore.create_trigger(Trigger(agent_id=agent.id, kind="ticket_assigned", enabled=False))

    enabled = wstore.list_triggers(agent_id=agent.id, enabled_only=True)
    assert len(enabled) == 1
    assert enabled[0].config == {"cron": "0 2 * * *"}


def test_mark_trigger_fired(isolated_store):
    agent = wstore.create_agent(AgentDef(name="Bot"))
    trg = wstore.create_trigger(Trigger(agent_id=agent.id))
    assert trg.last_fired_at == ""
    wstore.mark_trigger_fired(trg.id)
    assert wstore.get_trigger(trg.id).last_fired_at != ""


# ── evidence packs ─────────────────────────────────────────────────────


def test_evidence_pack_roundtrip(isolated_store):
    t = wstore.create_ticket(Ticket(title="thing"))
    pack = wstore.create_evidence(
        EvidencePack(
            ticket_id=t.id,
            run_id="run-1",
            goal="fix bug",
            files_modified=["a.py", "b.py"],
            risks=["touches auth"],
            confidence=0.8,
        )
    )
    listed = wstore.list_evidence_for_ticket(t.id)
    assert len(listed) == 1
    assert listed[0].id == pack.id
    assert listed[0].files_modified == ["a.py", "b.py"]
    assert listed[0].confidence == 0.8


# ── missions ───────────────────────────────────────────────────────────


def test_mission_tickets_link(isolated_store):
    m = wstore.create_mission(Mission(title="Big Migration", team_id="team-1"))
    wstore.create_ticket(Ticket(title="repo a", mission_id=m.id))
    wstore.create_ticket(Ticket(title="repo b", mission_id=m.id))
    wstore.create_ticket(Ticket(title="unrelated"))
    assert len(wstore.mission_tickets(m.id)) == 2
    assert len(wstore.list_missions(team_id="team-1")) == 1


# ── legacy runs carry non-breaking scope/ticket columns ────────────────


def test_run_has_scope_and_ticket_columns(isolated_store):
    p = create_project(name="p", idea="x")
    r = create_run(p.id)
    assert r.org_id == "local"
    assert r.user_id == "me"
    assert r.ticket_id is None


def test_run_can_link_to_ticket(isolated_store):
    p = create_project(name="p", idea="x")
    t = wstore.create_ticket(Ticket(title="thing"))
    r = create_run(p.id)
    update_run(r.id, ticket_id=t.id, agent_def_id="agt_x")
    got = get_run(r.id)
    assert got.ticket_id == t.id
    assert got.agent_def_id == "agt_x"
