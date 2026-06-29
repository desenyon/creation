"""FastAPI router for the work graph — tickets, agent bench, dispatch.

Mounted by ``creation.server``. Mutating routes require ``work_graph_enabled`` so the
pivot ships dark until a user opts in. Read routes are always safe.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from creation.config import load_secrets
from creation.work import store as wstore
from creation.work.bench import agent_by_kind, seed_personal_bench
from creation.work.models import AgentDef, Ticket

router = APIRouter(prefix="/api/work", tags=["work"])


def _require_enabled() -> None:
    if not load_secrets().work_graph_enabled:
        raise HTTPException(403, "work graph disabled — enable work_graph_enabled in settings")


class TicketCreate(BaseModel):
    title: str
    description: str = ""
    repo: str = ""
    kind: str = "code"  # used only to auto-pick an agent when assign_kind is set
    priority: str = "medium"
    risk_tier: str = "low"
    assign_agent_id: str = ""
    assign_kind: str = ""
    ready: bool = False
    auto_route: bool = False  # let Creation pick a loop to append to, or spawn an agent


class AgentCreate(BaseModel):
    name: str
    kind: str = "code"
    bench_type: str = "personal"
    coding_agent: str = "codex"
    risk_tier: str = "low"
    require_approval: bool = True
    allowed_repos: List[str] = []
    skills: List[str] = []


class AssignBody(BaseModel):
    agent: str  # agent id or kind


class StatusBody(BaseModel):
    status: str


class CronTriggerCreate(BaseModel):
    agent: str  # id or kind
    every_seconds: int = 86400
    ticket: Dict[str, Any] = {}


class WebhookTriggerCreate(BaseModel):
    agent: str
    source: str
    ticket: Dict[str, Any] = {}


class MissionCreate(BaseModel):
    title: str
    goal: str = ""
    description: str = ""
    team_id: str = ""


class FanoutBody(BaseModel):
    repos: List[str]
    agent: str
    title: str
    description: str = ""
    risk_tier: str = "low"


class WebhookEvent(BaseModel):
    payload: Dict[str, Any] = {}


class ApproveBody(BaseModel):
    ship: bool = False
    github_url: str = ""


class RejectBody(BaseModel):
    feedback: str
    block: bool = False


class EnableBody(BaseModel):
    enabled: bool = True


class ArchaeologyRun(BaseModel):
    repo: str = ""  # path to a local checkout (defaults to cwd)
    create_tickets: bool = False  # turn starter tasks into assigned tickets


@router.get("/status")
def work_status(repo: Optional[str] = None) -> Dict[str, Any]:
    sec = load_secrets()
    wstore.init_work_db()
    tickets = wstore.list_tickets(repo=repo)
    by_status: Dict[str, int] = {}
    for t in tickets:
        by_status[t.status] = by_status.get(t.status, 0) + 1
    from creation.work.loop import is_pass_running

    return {
        "enabled": sec.work_graph_enabled,
        "tickets": len(tickets),
        "agents": len(wstore.list_agents()),
        "by_status": by_status,
        "repos": wstore.list_repos(),
        "repo": repo or "",
        "auto_dispatch": sec.work_auto_dispatch,
        "auto_interval": sec.work_dispatch_interval_secs,
        "dispatch_running": is_pass_running(),
    }


@router.get("/stream")
async def api_stream() -> StreamingResponse:
    """Live SSE feed of every work-graph mutation, for the board."""
    from creation.work.events import subscribe

    async def gen():
        async for msg in subscribe():
            yield f"data: {msg}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/enable")
def api_enable(body: EnableBody) -> Dict[str, Any]:
    """Flip the work-graph feature flag from the UI."""
    from creation.config import save_secrets

    sec = load_secrets()
    sec.work_graph_enabled = body.enabled
    save_secrets(sec)
    wstore.init_work_db()
    return {"enabled": sec.work_graph_enabled}


@router.post("/auto")
def api_auto_dispatch(body: EnableBody) -> Dict[str, Any]:
    """Toggle the always-on board loop (auto-run assigned tickets)."""
    _require_enabled()
    from creation.config import save_secrets

    sec = load_secrets()
    sec.work_auto_dispatch = body.enabled
    save_secrets(sec)
    return {"auto_dispatch": sec.work_auto_dispatch, "interval": sec.work_dispatch_interval_secs}


@router.post("/bench/seed")
def api_seed_bench(coding_agent: str = "codex", force: bool = False) -> List[Dict[str, Any]]:
    _require_enabled()
    return [asdict(a) for a in seed_personal_bench(coding_agent=coding_agent, force=force)]


@router.get("/agents")
def api_list_agents(bench_type: Optional[str] = None) -> List[Dict[str, Any]]:
    return [asdict(a) for a in wstore.list_agents(bench_type=bench_type)]


@router.post("/agents")
def api_create_agent(body: AgentCreate) -> Dict[str, Any]:
    _require_enabled()
    agent = AgentDef(
        name=body.name,
        kind=body.kind,  # type: ignore[arg-type]
        bench_type=body.bench_type,  # type: ignore[arg-type]
        coding_agent=body.coding_agent,
        risk_tier=body.risk_tier,  # type: ignore[arg-type]
        require_approval=body.require_approval,
        allowed_repos=body.allowed_repos,
        skills=body.skills,
    )
    return asdict(wstore.create_agent(agent))


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    coding_agent: Optional[str] = None
    risk_tier: Optional[str] = None
    require_approval: Optional[bool] = None
    allowed_repos: Optional[List[str]] = None
    status: Optional[str] = None


@router.patch("/agents/{aid}")
def api_update_agent(aid: str, body: AgentUpdate) -> Dict[str, Any]:
    _require_enabled()
    agent = wstore.get_agent(aid)
    if not agent:
        raise HTTPException(404, "agent not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(agent, field, value)
    return asdict(wstore.update_agent(agent))


@router.post("/agents/{aid}/pause")
def api_pause_agent(aid: str) -> Dict[str, Any]:
    """Pause an agent so the dispatcher skips it (work piles up but never runs)."""
    _require_enabled()
    agent = wstore.get_agent(aid)
    if not agent:
        raise HTTPException(404, "agent not found")
    agent.status = "paused"  # type: ignore[assignment]
    return asdict(wstore.update_agent(agent))


@router.post("/agents/{aid}/resume")
def api_resume_agent(aid: str) -> Dict[str, Any]:
    _require_enabled()
    agent = wstore.get_agent(aid)
    if not agent:
        raise HTTPException(404, "agent not found")
    agent.status = "active"  # type: ignore[assignment]
    return asdict(wstore.update_agent(agent))


@router.delete("/agents/{aid}")
def api_delete_agent(aid: str) -> Dict[str, Any]:
    """Delete an agent and its triggers. Its tickets are left unassigned-in-place."""
    _require_enabled()
    if not wstore.delete_agent(aid):
        raise HTTPException(404, "agent not found")
    return {"deleted": aid}


class LoopAgentCreate(BaseModel):
    template: str
    repo: str = ""
    coding_agent: str = "codex"
    with_cron: bool = True


@router.post("/agents/loop")
def api_create_loop_agent(body: LoopAgentCreate) -> Dict[str, Any]:
    """Instantiate a maintenance-loop agent (+ its cron trigger) from a template."""
    _require_enabled()
    from creation.work.bench import LOOP_TEMPLATES, create_loop_agent

    if body.template not in LOOP_TEMPLATES:
        raise HTTPException(400, f"unknown template; options: {', '.join(LOOP_TEMPLATES)}")
    agent, trigger = create_loop_agent(
        body.template, repo=body.repo, coding_agent=body.coding_agent, with_cron=body.with_cron
    )
    return {"agent": asdict(agent), "trigger": asdict(trigger) if trigger else None}


@router.get("/tickets")
def api_list_tickets(status: Optional[str] = None, repo: Optional[str] = None) -> List[Dict[str, Any]]:
    return [asdict(t) for t in wstore.list_tickets(status=status, repo=repo)]


@router.post("/tickets")
def api_create_ticket(body: TicketCreate) -> Dict[str, Any]:
    _require_enabled()
    assigned = bool(body.assign_agent_id or body.assign_kind)
    t = Ticket(
        title=body.title,
        description=body.description,
        repo=body.repo,
        priority=body.priority,  # type: ignore[arg-type]
        risk_tier=body.risk_tier,  # type: ignore[arg-type]
        status="todo" if (assigned or body.ready) else "backlog",
    )
    wstore.create_ticket(t)
    routing: Optional[Dict[str, Any]] = None
    if assigned:
        agent = (
            wstore.get_agent(body.assign_agent_id)
            if body.assign_agent_id
            else agent_by_kind(body.assign_kind)
        )
        if not agent:
            raise HTTPException(404, "assignee agent not found")
        wstore.assign_ticket(t.id, assignee_type="agent", assignee_id=agent.id)
    elif body.auto_route:
        from creation.work.routing import auto_route

        # Only force a kind when the caller set a non-default one; otherwise infer it.
        forced = body.kind if body.kind and body.kind != "code" else None
        routing = auto_route(t, kind=forced).to_dict()
    out = asdict(wstore.get_ticket(t.id))
    if routing is not None:
        out["routing"] = routing
    return out


@router.delete("/tickets/{tid}")
def api_delete_ticket(tid: str) -> Dict[str, Any]:
    _require_enabled()
    if not wstore.delete_ticket(tid):
        raise HTTPException(404, "ticket not found")
    return {"deleted": tid}


class RouteBody(BaseModel):
    kind: str = ""


@router.post("/tickets/{tid}/route")
def api_route_ticket(tid: str, body: RouteBody) -> Dict[str, Any]:
    """Decide + apply: append this ticket to a running loop, or trigger a new agent."""
    _require_enabled()
    t = wstore.get_ticket(tid)
    if not t:
        raise HTTPException(404, "ticket not found")
    from creation.work.routing import auto_route

    decision = auto_route(t, kind=body.kind or None)
    return {"ticket": asdict(wstore.get_ticket(tid)), "routing": decision.to_dict()}


@router.get("/tickets/{tid}")
def api_get_ticket(tid: str) -> Dict[str, Any]:
    t = wstore.get_ticket(tid)
    if not t:
        raise HTTPException(404, "ticket not found")
    return {
        **asdict(t),
        "evidence": [asdict(e) for e in wstore.list_evidence_for_ticket(tid)],
    }


@router.post("/tickets/{tid}/assign")
def api_assign_ticket(tid: str, body: AssignBody) -> Dict[str, Any]:
    _require_enabled()
    if not wstore.get_ticket(tid):
        raise HTTPException(404, "ticket not found")
    agent = wstore.get_agent(body.agent) or agent_by_kind(body.agent)
    if not agent:
        raise HTTPException(404, "agent not found")
    wstore.assign_ticket(tid, assignee_type="agent", assignee_id=agent.id)
    wstore.set_ticket_status(tid, "todo")
    return asdict(wstore.get_ticket(tid))


@router.post("/tickets/{tid}/status")
def api_set_status(tid: str, body: StatusBody) -> Dict[str, Any]:
    _require_enabled()
    t = wstore.set_ticket_status(tid, body.status)
    if not t:
        raise HTTPException(404, "ticket not found")
    return asdict(t)


@router.get("/tickets/{tid}/evidence")
def api_ticket_evidence(tid: str) -> List[Dict[str, Any]]:
    return [asdict(e) for e in wstore.list_evidence_for_ticket(tid)]


# ── triggers ───────────────────────────────────────────────────────────────--
@router.get("/triggers")
def api_list_triggers() -> List[Dict[str, Any]]:
    return [asdict(t) for t in wstore.list_triggers()]


@router.post("/triggers/cron")
def api_create_cron_trigger(body: CronTriggerCreate) -> Dict[str, Any]:
    _require_enabled()
    agent = wstore.get_agent(body.agent) or agent_by_kind(body.agent)
    if not agent:
        raise HTTPException(404, "agent not found")
    from creation.work.triggers import create_cron_trigger

    trg = create_cron_trigger(agent.id, every_seconds=body.every_seconds, ticket=body.ticket)
    return asdict(trg)


@router.post("/triggers/webhook")
def api_create_webhook_trigger(body: WebhookTriggerCreate) -> Dict[str, Any]:
    _require_enabled()
    agent = wstore.get_agent(body.agent) or agent_by_kind(body.agent)
    if not agent:
        raise HTTPException(404, "agent not found")
    from creation.work.triggers import create_webhook_trigger

    trg = create_webhook_trigger(agent.id, source=body.source, ticket=body.ticket)
    return asdict(trg)


@router.post("/tick")
def api_tick() -> Dict[str, Any]:
    _require_enabled()
    from creation.work.triggers import tick

    created = tick()
    return {"created": [asdict(t) for t in created], "count": len(created)}


@router.post("/webhook/{source}")
def api_inbound_webhook(source: str, body: WebhookEvent) -> Dict[str, Any]:
    """Inbound event (CI failed, incident opened, …) → spawn subscribed tickets."""
    _require_enabled()
    from creation.work.triggers import handle_webhook_event

    created = handle_webhook_event(source, body.payload)
    return {"source": source, "created": [asdict(t) for t in created], "count": len(created)}


# ── missions ───────────────────────────────────────────────────────────────--
@router.get("/missions")
def api_list_missions() -> List[Dict[str, Any]]:
    return [asdict(m) for m in wstore.list_missions()]


@router.post("/missions")
def api_create_mission(body: MissionCreate) -> Dict[str, Any]:
    _require_enabled()
    from creation.work.models import Mission

    m = Mission(title=body.title, goal=body.goal, description=body.description, team_id=body.team_id or None)
    return asdict(wstore.create_mission(m))


@router.post("/missions/{mid}/fanout")
def api_mission_fanout(mid: str, body: FanoutBody) -> Dict[str, Any]:
    _require_enabled()
    from creation.work.missions import fan_out_across_repos

    try:
        created = fan_out_across_repos(
            mid, body.repos, agent=body.agent, title=body.title,
            description=body.description, risk_tier=body.risk_tier,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"mission_id": mid, "created": [asdict(t) for t in created], "count": len(created)}


@router.get("/missions/{mid}")
def api_get_mission(mid: str) -> Dict[str, Any]:
    from creation.work.missions import mission_progress, sync_mission_status

    m = wstore.get_mission(mid)
    if not m:
        raise HTTPException(404, "mission not found")
    sync_mission_status(mid)
    return {**asdict(wstore.get_mission(mid)), "progress": mission_progress(mid)}


@router.get("/metrics")
def api_metrics() -> List[Dict[str, Any]]:
    from creation.work.evals import bench_metrics

    return bench_metrics()


# ── repo archaeologist ────────────────────────────────────────────────────────
@router.post("/archaeology")
def api_archaeology(body: ArchaeologyRun) -> Dict[str, Any]:
    """Analyze a local repo and return an onboarding brief.

    Read-only by default. With ``create_tickets`` it also files the starter tasks
    as backlog tickets under a new mission, assigned to the Repo Archaeologist —
    which requires the work graph to be enabled.
    """
    import os

    from creation.archaeology import explore_repo

    repo = (body.repo or "").strip() or os.getcwd()
    brief = explore_repo(load_secrets(), repo)
    out: Dict[str, Any] = {"brief": brief.to_dict()}

    if body.create_tickets and brief.is_repo and brief.starter_tasks:
        _require_enabled()
        from creation.work.models import Mission, Ticket

        wstore.init_work_db()
        seed_personal_bench()
        agent = agent_by_kind("archaeologist")
        mission = wstore.create_mission(
            Mission(
                title=f"Onboarding: {brief.repo_name}",
                goal=f"Safe starter tasks surfaced by the Repo Archaeologist for {brief.repo_name}.",
                description=brief.summary,
                status="active",
            )
        )
        _RISK = {"low": "low", "medium": "medium", "high": "high"}
        created: List[Dict[str, Any]] = []
        for task in brief.starter_tasks:
            t = Ticket(
                title=task["title"],
                description=task.get("why", ""),
                source="mission",
                status="todo" if agent else "backlog",
                priority="low",
                risk_tier=_RISK.get(task.get("risk", "low"), "low"),  # type: ignore[arg-type]
                repo=brief.github_url or brief.repo_path,
                labels=["onboarding", "archaeologist"],
                mission_id=mission.id,
                assignee_type="agent" if agent else "none",
                assignee_id=agent.id if agent else None,
            )
            created.append(asdict(wstore.create_ticket(t)))
        out["mission"] = asdict(mission)
        out["created"] = created

    return out


# ── review / approval gate ───────────────────────────────────────────────────
@router.post("/tickets/{tid}/approve")
def api_approve(tid: str, body: ApproveBody) -> Dict[str, Any]:
    _require_enabled()
    from dataclasses import asdict as _asdict

    from creation.work.review import approve_ticket

    try:
        res = approve_ticket(tid, ship=body.ship, github_url=body.github_url)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _asdict(res)


@router.post("/tickets/{tid}/reject")
def api_reject(tid: str, body: RejectBody) -> Dict[str, Any]:
    _require_enabled()
    from dataclasses import asdict as _asdict

    from creation.work.review import reject_ticket

    try:
        res = reject_ticket(tid, body.feedback, requeue=not body.block)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _asdict(res)


# ── governance + memory reads ─────────────────────────────────────────────────
@router.get("/audit")
def api_audit(entity_id: Optional[str] = None, action: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    from creation.work.audit import event_dicts

    return event_dicts(entity_id=entity_id, action=action, limit=limit)


@router.get("/playbook")
def api_playbook(kind: Optional[str] = None, repo: Optional[str] = None) -> List[Dict[str, Any]]:
    from creation.work.playbook import lesson_dicts

    return lesson_dicts(kind=kind, repo=repo)


class LessonCreate(BaseModel):
    lesson: str
    kind: str = "code"
    repo: str = ""
    title: str = ""


@router.post("/playbook")
def api_add_lesson(body: LessonCreate) -> Dict[str, Any]:
    """Teach Creation a memory by hand — injected into relevant future runs."""
    _require_enabled()
    from dataclasses import asdict as _asdict

    from creation.work.playbook import add_manual_lesson

    if not body.lesson.strip():
        raise HTTPException(400, "lesson text required")
    return _asdict(add_manual_lesson(lesson=body.lesson, kind=body.kind, repo=body.repo, title=body.title))


@router.delete("/playbook/{lid}")
def api_delete_lesson(lid: str) -> Dict[str, Any]:
    _require_enabled()
    from creation.work.playbook import delete_lesson

    if not delete_lesson(lid):
        raise HTTPException(404, "lesson not found")
    return {"deleted": lid}


@router.get("/runs/{rid}")
def api_get_run(rid: str) -> Dict[str, Any]:
    """Run status + agent log for a ticket's run (reads the legacy run store)."""
    from creation.store import get_run

    run = get_run(rid)
    if not run:
        raise HTTPException(404, "run not found")
    return {
        "id": run.id,
        "status": run.status,
        "agent_def_id": run.agent_def_id or "",
        "current_phase": run.current_phase or "",
        "created_at": run.created_at or "",
        "finished_at": run.finished_at or "",
        "error": run.error or "",
        "agent_log": (run.agent_log or "")[-20000:],
    }


@router.post("/dispatch")
def api_dispatch(bg: BackgroundTasks, limit: Optional[int] = None) -> Dict[str, Any]:
    _require_enabled()
    secrets = load_secrets()
    pending = wstore.list_tickets(status="todo", assignee_type="agent")
    count = len(pending) if limit is None else min(limit, len(pending))

    def _job() -> None:
        from creation.work.dispatcher import dispatch_once

        dispatch_once(secrets=secrets, limit=limit)

    bg.add_task(_job)
    return {"status": "dispatching", "queued": count}
