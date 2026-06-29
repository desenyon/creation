"""Trigger engine — the reason agents 'just keep going'.

A trigger is a durable subscription that turns events into tickets:

  - ``cron``          → on an interval, spawn a ticket (e.g. nightly flaky-test scan)
  - ``webhook``       → an inbound event (CI failed, incident opened) spawns a ticket
  - ``ticket_status`` → makes a status (beyond "todo") actionable for the bound agent
  - ``ticket_assigned`` / ``mission_fanout`` → handled by the worker/missions modules

Firing a trigger creates a ticket pre-assigned to the trigger's agent and marked
``todo`` so the dispatcher's next pass picks it up. Scope is inherited from the agent
so personal agents make personal tickets and org agents make org/team tickets.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from creation.work import store as wstore
from creation.work.models import AgentDef, Ticket, Trigger


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _parse(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _safe_format(text: str, payload: Dict[str, Any]) -> str:
    class _Default(dict):
        def __missing__(self, key: str) -> str:  # leave unknown {fields} intact
            return "{" + key + "}"

    try:
        return text.format_map(_Default(payload))
    except (ValueError, IndexError):
        return text


def _ticket_from_spec(spec: Dict[str, Any], agent: AgentDef, source: str) -> Ticket:
    return Ticket(
        title=spec.get("title") or "Untitled",
        description=spec.get("description", ""),
        repo=spec.get("repo", ""),
        priority=spec.get("priority", "medium"),
        risk_tier=spec.get("risk_tier", agent.risk_tier),
        labels=list(spec.get("labels", [])),
        source=source,  # type: ignore[arg-type]
        status="todo",
        assignee_type="agent",
        assignee_id=agent.id,
        mission_id=spec.get("mission_id"),
        org_id=agent.org_id,
        team_id=agent.team_id,
        user_id=agent.user_id,
        visibility=agent.visibility,
    )


# ── creation helpers ──────────────────────────────────────────────────────────
def create_cron_trigger(agent_id: str, *, every_seconds: int, ticket: Dict[str, Any]) -> Trigger:
    agent = wstore.get_agent(agent_id)
    trg = Trigger(
        agent_id=agent_id,
        kind="cron",
        config={"every_seconds": int(every_seconds), "ticket": ticket},
        org_id=agent.org_id if agent else "local",
        team_id=agent.team_id if agent else None,
        user_id=agent.user_id if agent else "me",
        visibility=agent.visibility if agent else "private",
    )
    return wstore.create_trigger(trg)


def create_webhook_trigger(agent_id: str, *, source: str, ticket: Dict[str, Any]) -> Trigger:
    agent = wstore.get_agent(agent_id)
    trg = Trigger(
        agent_id=agent_id,
        kind="webhook",
        config={"source": source, "ticket": ticket},
        org_id=agent.org_id if agent else "local",
        team_id=agent.team_id if agent else None,
        user_id=agent.user_id if agent else "me",
        visibility=agent.visibility if agent else "private",
    )
    return wstore.create_trigger(trg)


def create_status_trigger(agent_id: str, *, status: str) -> Trigger:
    """Make ``status`` actionable for this agent (e.g. a 'ready-for-agent' column)."""
    return wstore.create_trigger(
        Trigger(agent_id=agent_id, kind="ticket_status", config={"status": status})
    )


# ── cron ──────────────────────────────────────────────────────────────────────
def _is_due(trigger: Trigger, now: datetime) -> bool:
    if not trigger.enabled:
        return False
    every = int(trigger.config.get("every_seconds", 0) or 0)
    last = _parse(trigger.last_fired_at)
    if last is None:
        return True  # never fired → fire on first tick
    if every <= 0:
        return False
    return (now - last).total_seconds() >= every


def due_cron_triggers(now: Optional[datetime] = None) -> List[Trigger]:
    now = _now(now)
    return [t for t in wstore.list_triggers(kind="cron", enabled_only=True) if _is_due(t, now)]


def fire_trigger(trigger: Trigger) -> Optional[Ticket]:
    """Create the ticket a trigger describes (if its agent is active)."""
    agent = wstore.get_agent(trigger.agent_id)
    if agent is None or agent.status != "active":
        return None
    spec = dict(trigger.config.get("ticket") or {})
    source = "incident" if trigger.kind == "webhook" else "agent"
    ticket = _ticket_from_spec(spec, agent, source)
    wstore.create_ticket(ticket)
    wstore.mark_trigger_fired(trigger.id)
    from creation.work import audit

    audit.record(
        "trigger.fired",
        "trigger",
        trigger.id,
        actor=agent.id,
        actor_type="system",
        detail={"ticket_id": ticket.id, "kind": trigger.kind},
        org_id=ticket.org_id,
        team_id=ticket.team_id,
        user_id=ticket.user_id,
    )
    return ticket


def tick(now: Optional[datetime] = None) -> List[Ticket]:
    """Fire every due cron trigger. Returns the tickets created this tick."""
    created: List[Ticket] = []
    for trigger in due_cron_triggers(now):
        t = fire_trigger(trigger)
        if t:
            created.append(t)
    return created


# ── webhook ─────────────────────────────────────────────────────────────────--
def handle_webhook_event(source: str, payload: Optional[Dict[str, Any]] = None) -> List[Ticket]:
    """Fan an inbound event out to every webhook trigger that subscribes to it.

    ``payload`` fields can be interpolated into the ticket's title/description via
    ``{field}`` placeholders (e.g. "Fix failing CI on {branch}").
    """
    payload = payload or {}
    created: List[Ticket] = []
    for trigger in wstore.list_triggers(kind="webhook", enabled_only=True):
        if (trigger.config.get("source") or "") != source:
            continue
        agent = wstore.get_agent(trigger.agent_id)
        if agent is None or agent.status != "active":
            continue
        spec = dict(trigger.config.get("ticket") or {})
        spec["title"] = _safe_format(spec.get("title", f"{source} event"), payload)
        spec["description"] = _safe_format(spec.get("description", ""), payload)
        ticket = _ticket_from_spec(spec, agent, "incident")
        wstore.create_ticket(ticket)
        wstore.mark_trigger_fired(trigger.id)
        created.append(ticket)
    return created


# ── status triggers (consumed by the dispatcher) ─────────────────────────────--
def actionable_statuses_for(agent_id: str) -> List[str]:
    """Statuses that make a ticket actionable for this agent: 'todo' + any configured."""
    statuses = {"todo"}
    for trg in wstore.list_triggers(agent_id=agent_id, kind="ticket_status", enabled_only=True):
        s = trg.config.get("status")
        if s:
            statuses.add(str(s))
    return sorted(statuses)
