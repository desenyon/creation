"""Missions — the company-wide path: one objective → many child tickets.

A Mission is how org-scale work happens: "Migrate every service to React 19" or
"Add structured logging across all repos". It decomposes into child tickets (one per
repo / unit of work), auto-assigns them to agents, and tracks aggregate progress. The
same dispatcher + worker then chews through them continuously.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from creation.work import store as wstore
from creation.work.bench import agent_by_kind
from creation.work.models import AgentDef, Mission, Ticket

# Statuses that count as "settled" for progress purposes.
_TERMINAL = {"done", "cancelled"}


def _resolve_agent(ref: str, *, user_id: Optional[str]) -> Optional[AgentDef]:
    """Resolve an agent by id, or by kind from the relevant bench."""
    agent = wstore.get_agent(ref)
    if agent:
        return agent
    return agent_by_kind(ref, user_id=user_id or "me")


def fan_out_mission(mission_id: str, specs: List[Dict[str, Any]]) -> List[Ticket]:
    """Create + assign child tickets for a mission from explicit specs.

    Each spec: ``{title, repo?, agent (id|kind), description?, priority?, risk_tier?}``.
    Tickets inherit the mission's scope and are linked back via ``mission_id``.
    """
    mission = wstore.get_mission(mission_id)
    if mission is None:
        raise ValueError(f"mission {mission_id} not found")

    created: List[Ticket] = []
    for spec in specs:
        agent = _resolve_agent(str(spec.get("agent", "")), user_id=mission.user_id)
        ticket = Ticket(
            title=spec.get("title") or mission.title,
            description=spec.get("description", ""),
            repo=spec.get("repo", ""),
            priority=spec.get("priority", "medium"),
            risk_tier=spec.get("risk_tier", "low"),
            source="mission",
            status="todo" if agent else "backlog",
            assignee_type="agent" if agent else "none",
            assignee_id=agent.id if agent else None,
            mission_id=mission.id,
            org_id=mission.org_id,
            team_id=mission.team_id,
            user_id=mission.user_id,
            visibility=mission.visibility,
        )
        wstore.create_ticket(ticket)
        created.append(ticket)

    if created and mission.status == "planning":
        mission.status = "active"
        wstore.update_mission(mission)
    return created


def fan_out_across_repos(
    mission_id: str,
    repos: List[str],
    *,
    agent: str,
    title: str,
    description: str = "",
    kind_priority: str = "medium",
    risk_tier: str = "low",
) -> List[Ticket]:
    """Common pattern: apply the same change across many repos (one ticket each).

    ``title`` may contain ``{repo}`` which is interpolated per repo.
    """
    specs = [
        {
            "title": title.format(repo=repo) if "{repo}" in title else f"{title} — {repo}",
            "description": description,
            "repo": repo,
            "agent": agent,
            "priority": kind_priority,
            "risk_tier": risk_tier,
        }
        for repo in repos
    ]
    return fan_out_mission(mission_id, specs)


def mission_progress(mission_id: str) -> Dict[str, Any]:
    """Aggregate child-ticket status for a mission."""
    tickets = wstore.list_tickets(mission_id=mission_id)
    by_status: Dict[str, int] = {}
    for t in tickets:
        by_status[t.status] = by_status.get(t.status, 0) + 1
    total = len(tickets)
    settled = sum(by_status.get(s, 0) for s in _TERMINAL)
    done = by_status.get("done", 0)
    return {
        "mission_id": mission_id,
        "total": total,
        "by_status": by_status,
        "done": done,
        "done_pct": round(100 * done / total, 1) if total else 0.0,
        "complete": total > 0 and settled == total,
    }


def sync_mission_status(mission_id: str) -> Optional[Mission]:
    """Flip a mission to ``complete`` once all its child tickets are settled."""
    mission = wstore.get_mission(mission_id)
    if mission is None:
        return None
    prog = mission_progress(mission_id)
    if prog["complete"] and mission.status not in _TERMINAL:
        mission.status = "complete"
        wstore.update_mission(mission)
    return mission
