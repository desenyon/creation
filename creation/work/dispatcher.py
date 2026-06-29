"""Dispatcher — the Watch phase that keeps agents going.

Scans the board for tickets that are assigned to an *active* agent and ready to
run, then hands each to the worker. This is what makes Creation feel "always on": you
assign a ticket to an agent and the dispatcher picks it up on its next pass.

In local-first mode a pass is driven by the CLI/scheduler. Hosted mode (Phase 3)
swaps this polling loop for a durable job queue without changing the worker.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, List, Optional

from creation.config import CONFIG_DIR, UserSecrets, load_secrets
from creation.work import store as wstore
from creation.work.models import Ticket
from creation.work.worker import TicketRunResult, run_ticket

LineCallback = Callable[[str], None]

# Statuses a dispatcher will actively pick up. "todo" = queued for an agent.
ACTIONABLE_STATUSES = ("todo",)

REPOS_DIR = CONFIG_DIR / "repos"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", (text or "").lower()).strip("-")
    return s or "repo"


def default_workdir(ticket: Ticket) -> Path:
    """Resolve a local working directory for a ticket.

    If the ticket points at an existing local path, use it. Otherwise fall back to
    a managed per-repo directory under ~/.creation/repos.
    """
    if ticket.repo:
        p = Path(ticket.repo).expanduser()
        if p.exists():
            return p
        return REPOS_DIR / _slug(ticket.repo)
    return REPOS_DIR / _slug(ticket.id)


def actionable_tickets(*, user_id: Optional[str] = None, team_id: Optional[str] = None) -> List[Ticket]:
    """Agent-assigned tickets that are ready to run.

    A ticket is actionable when its status is in the dispatcher's base set (``todo``)
    or in any extra status its assignee agent subscribes to via a ``ticket_status``
    trigger (e.g. a custom "ready-for-agent" column).
    """
    from creation.work.triggers import actionable_statuses_for

    out: List[Ticket] = []
    seen: set[str] = set()
    candidate_statuses = set(ACTIONABLE_STATUSES)
    # Gather any custom actionable statuses configured across agents.
    for trg in wstore.list_triggers(kind="ticket_status", enabled_only=True):
        s = trg.config.get("status")
        if s:
            candidate_statuses.add(str(s))

    for status in candidate_statuses:
        for t in wstore.list_tickets(
            status=status, assignee_type="agent", user_id=user_id, team_id=team_id
        ):
            if not t.assignee_id or t.id in seen:
                continue
            if status in ACTIONABLE_STATUSES or status in actionable_statuses_for(t.assignee_id):
                seen.add(t.id)
                out.append(t)
    return out


def dispatch_once(
    *,
    secrets: Optional[UserSecrets] = None,
    workdir_resolver: Callable[[Ticket], Path] = default_workdir,
    runner_factory: Optional[Callable[[object], object]] = None,
    on_line: Optional[LineCallback] = None,
    limit: Optional[int] = None,
    user_id: Optional[str] = None,
    team_id: Optional[str] = None,
    fire_triggers: bool = True,
) -> List[TicketRunResult]:
    """Run one dispatch pass: fire due triggers, then work all actionable tickets."""
    secrets = secrets or load_secrets()
    if fire_triggers:
        from creation.work.triggers import tick

        created = tick()
        if created and on_line:
            on_line(f"triggers fired → {len(created)} new ticket(s)")
    tickets = actionable_tickets(user_id=user_id, team_id=team_id)
    if limit is not None:
        tickets = tickets[:limit]

    # An agent runs one task per pass: anything it's already mid-run on, or a second
    # ticket for the same agent this pass, is appended to that loop (left ``todo``)
    # rather than spawning a parallel run. This is the "add to the current loop" path.
    busy_agents = {
        t.assignee_id
        for t in wstore.list_tickets(status="in_progress", assignee_type="agent")
        if t.assignee_id
    }

    results: List[TicketRunResult] = []
    for ticket in tickets:
        agent = wstore.get_agent(ticket.assignee_id or "")
        if agent is None:
            if on_line:
                on_line(f"[{ticket.id}] skipped — assignee agent not found")
            continue
        if agent.status != "active":
            if on_line:
                on_line(f"[{ticket.id}] skipped — agent {agent.name} is paused")
            continue
        if agent.id in busy_agents:
            if on_line:
                on_line(f"[{ticket.id}] queued — appended to {agent.name}'s running loop")
            continue
        if ticket.repo and not agent.can_touch_repo(ticket.repo):
            wstore.set_ticket_status(ticket.id, "blocked")
            if on_line:
                on_line(f"[{ticket.id}] blocked — {agent.name} not allowed on {ticket.repo}")
            continue

        runner = runner_factory(agent) if runner_factory else None
        results.append(
            run_ticket(
                ticket,
                agent,
                workdir_resolver(ticket),
                secrets,
                on_line=on_line,
                runner=runner,
            )
        )
        busy_agents.add(agent.id)  # further tickets this pass append to this loop
    return results
