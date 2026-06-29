"""Routing — decide whether new work spawns an agent or joins a running loop.

This is the brain behind "Creation just keeps going". When a ticket arrives we ask a
single question: is an agent *already looping* on this work? If so we **append** the
ticket to that loop (no new agent, no duplicate run). If not, we **spawn**: trigger a
fresh agent of the right kind.

An agent counts as "looping on a repo" when any of these hold (strongest first):

  1. it is mid-run (`in_progress`) on that repo — append straight into its context
  2. it has queued (`todo`) work on that repo and matches the ticket's kind
  3. it owns a maintenance loop (an enabled ``cron`` trigger) covering that repo

Keeping this logic in one place means the API, the dispatcher, and the CLI all make
the same call, and it stays easy to unit-test without a coding agent in the loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple, get_args

from creation.work import store as wstore
from creation.work.models import AgentDef, AgentKind, Ticket

RouteAction = Literal["append", "spawn", "manual"]
TaskSize = Literal["small", "medium", "large"]

_KINDS = set(get_args(AgentKind))

# How many open tickets an agent's loop can hold before we stop piling on and
# spawn a fresh agent instead (when one is free).
_APPEND_LOAD_CAP = 4
# Complexity score thresholds (see ``estimate_complexity``).
_LARGE_AT = 5
_MEDIUM_AT = 2

# Phrases that signal a heavyweight task that deserves its own agent.
_BIG_SIGNALS: List[Tuple[str, Tuple[str, ...]]] = [
    ("greenfield build", ("build ", "implement ", "create ", "from scratch", "end-to-end", "end to end", "greenfield")),
    ("broad rework", ("refactor", "rewrite", "redesign", "overhaul", "re-architect", "rearchitect", "migrate the", "migration across")),
    ("system scope", ("entire", "across the", "whole ", "platform", "system", "all of", "everywhere")),
    ("multi-step", ("multiple", "several", "and then", "as well as", "phase 1", "milestone")),
]

# title/description keywords → agent kind, checked in priority order.
_KIND_KEYWORDS: List[Tuple[str, Tuple[str, ...]]] = [
    ("security", ("security", "vuln", "cve", "secret", "exploit", "auth bypass")),
    ("migration", ("migrat", "upgrade", "bump ", "codemod", "deprecat", "react 19")),
    ("performance", ("perf", "latency", "slow", "optimi", "throughput", "memory leak")),
    ("test", ("flaky", "unit test", "coverage", "regression", "add tests")),
    ("docs", ("docs", "documentation", "readme", "changelog", "docstring")),
    ("review", ("review", "code review")),
    ("debug", ("bug", "broken", "crash", "stack trace", "incident", "hotfix")),
]


@dataclass
class Complexity:
    """A cheap estimate of how big a ticket is, used to size the response."""

    size: TaskSize
    score: int
    signals: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return {"small": "Small task", "medium": "Task", "large": "Big task"}[self.size]


@dataclass
class RoutingDecision:
    """Where a ticket should go, and why — surfaced to the board so it's explainable."""

    action: RouteAction
    kind: str
    agent_id: Optional[str] = None
    agent_name: str = ""
    reason: str = ""
    size: TaskSize = "medium"
    signals: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "kind": self.kind,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "reason": self.reason,
            "size": self.size,
            "signals": self.signals,
        }


def estimate_complexity(ticket: Ticket) -> Complexity:
    """Score a ticket's heft from priority, risk, length, structure, and wording.

    This is deliberately a fast heuristic (no LLM): it runs on every routing call.
    ``large`` tickets get a dedicated agent; ``small`` ones are appended to a loop.
    """
    text = f"{ticket.title}\n{ticket.description}".lower()
    score = 0
    signals: List[str] = []

    if ticket.priority == "urgent":
        score += 2
        signals.append("urgent")
    elif ticket.priority == "high":
        score += 1
        signals.append("high priority")

    if ticket.risk_tier == "high":
        score += 2
        signals.append("high risk")
    elif ticket.risk_tier == "medium":
        score += 1

    words = len(text.split())
    if words >= 120:
        score += 2
        signals.append("detailed spec")
    elif words >= 45:
        score += 1

    items = len(re.findall(r"(?m)^\s*(?:[-*]|\d+[.)])\s+", ticket.description or ""))
    if items >= 5:
        score += 2
        signals.append(f"{items} sub-items")
    elif items >= 2:
        score += 1
        signals.append(f"{items} sub-items")

    for label, keywords in _BIG_SIGNALS:
        if any(kw in text for kw in keywords):
            score += 1
            signals.append(label)

    labels = {l.lower() for l in (ticket.labels or [])}
    if labels & {"epic", "initiative", "project"}:
        score += _LARGE_AT  # an explicitly-tagged epic is always a big task
        signals.append("epic")

    if score >= _LARGE_AT:
        size: TaskSize = "large"
    elif score >= _MEDIUM_AT:
        size = "medium"
    else:
        size = "small"
    return Complexity(size, score, signals)


def infer_kind(ticket: Ticket) -> str:
    """Best-effort agent kind for a ticket from its labels, then keyword heuristics."""
    for label in ticket.labels or []:
        if label in _KINDS:
            return label
    text = f"{ticket.title} {ticket.description}".lower()
    for kind, keywords in _KIND_KEYWORDS:
        if any(kw in text for kw in keywords):
            return kind
    return "code"


def _can_touch(agent: AgentDef, repo: str) -> bool:
    return not repo or agent.can_touch_repo(repo)


def _loop_score(agent: AgentDef, repo: str, kind: str) -> Tuple[int, str]:
    """How strongly is ``agent`` already looping on this repo? 0 = not a loop."""
    same_repo = lambda t: (not repo) or (t.repo == repo)
    owned = wstore.list_tickets(assignee_id=agent.id)

    if any(t.status == "in_progress" and same_repo(t) for t in owned):
        return 5, f"{agent.name} is mid-run on {repo or 'this work'} — task appended to its loop"

    score, reason = 0, ""
    kind_match = agent.kind == kind
    if kind_match and any(t.status == "todo" and same_repo(t) for t in owned):
        score, reason = 3, f"{agent.name} already has queued work here — appended to its queue"

    if kind_match and wstore.list_triggers(agent_id=agent.id, kind="cron", enabled_only=True):
        scoped = bool(repo) and repo in (agent.allowed_repos or [])
        s = 4 if scoped else 2
        if s > score:
            where = f" on {repo}" if scoped else ""
            score, reason = s, f"{agent.name} runs a maintenance loop{where} — appended"
    return score, reason


def _open_load(agent_id: str, repo: str) -> int:
    """How many open (todo/in_progress) tickets an agent already holds on this repo."""
    owned = wstore.list_tickets(assignee_id=agent_id)
    same_repo = lambda t: (not repo) or (t.repo == repo)
    return sum(1 for t in owned if t.status in ("todo", "in_progress") and same_repo(t))


def _pick_spawn_target(active: List[AgentDef], kind: str, repo: str) -> Optional[AgentDef]:
    """Pick the least-loaded agent that can take a fresh run — matching kind, else a coder."""
    matches = [a for a in active if a.kind == kind] or [a for a in active if a.kind == "code"]
    if not matches:
        return None
    matches.sort(key=lambda a: (_open_load(a.id, repo), a.created_at))
    return matches[0]


def route_ticket(ticket: Ticket, *, kind: Optional[str] = None, prefer_loop: bool = True) -> RoutingDecision:
    """Decide how a ticket should be handled without mutating anything.

    Size-aware: a **big** task gets its own agent (a dedicated run) even when a loop
    is already active here, while a **small** task is handed to a running loop so we
    don't spin up a whole new agent for a trivial change. An overloaded loop also
    pushes work onto a free agent.
    """
    resolved_kind = kind or infer_kind(ticket)
    active = [a for a in wstore.list_agents() if a.status == "active" and _can_touch(a, ticket.repo)]
    cx = estimate_complexity(ticket)
    sig = f" [{', '.join(cx.signals)}]" if cx.signals else ""

    def decide(action: RouteAction, agent: Optional[AgentDef], reason: str) -> RoutingDecision:
        return RoutingDecision(
            action, resolved_kind, agent.id if agent else None, agent.name if agent else "",
            reason, cx.size, cx.signals,
        )

    # Is an agent already looping on this repo? (strongest signal first)
    append_agent: Optional[AgentDef] = None
    append_why = ""
    if prefer_loop:
        scored = [(score, a, why) for a in active for score, why in [_loop_score(a, ticket.repo, resolved_kind)] if score > 0]
        if scored:
            scored.sort(key=lambda x: (x[0], x[1].created_at), reverse=True)
            _, append_agent, append_why = scored[0]

    spawn_agent = _pick_spawn_target(active, resolved_kind, ticket.repo)

    # BIG task → dedicate a fresh agent run, even if a loop already exists here.
    if cx.size == "large" and spawn_agent is not None:
        extra = f" (instead of piling onto {append_agent.name})" if append_agent else ""
        return decide("spawn", spawn_agent, f"Big task{sig} — dedicating {spawn_agent.name} to its own run{extra}")

    # A loop is running here → hand work to it, unless it's overloaded and a free agent exists.
    if append_agent is not None:
        load = _open_load(append_agent.id, ticket.repo)
        free = spawn_agent is not None and spawn_agent.id != append_agent.id and _open_load(spawn_agent.id, ticket.repo) < load
        if load >= _APPEND_LOAD_CAP and free:
            return decide("spawn", spawn_agent, f"{append_agent.name}'s loop is busy ({load} open){sig} — spawning {spawn_agent.name} instead")
        return decide("append", append_agent, f"{cx.label}{sig} — handed to {append_agent.name}'s loop ({append_why})")

    # Nobody looping here → spawn if we can.
    if spawn_agent is not None:
        scope = ticket.repo or "this repo"
        return decide("spawn", spawn_agent, f"No active loop on {scope}{sig} — triggering {spawn_agent.name}")

    return decide("manual", None, "No eligible agent — seed a bench or assign one manually")


def apply_routing(ticket: Ticket, decision: RoutingDecision) -> Optional[Ticket]:
    """Assign the ticket per a decision and mark it actionable. No-op for ``manual``."""
    if decision.action == "manual" or not decision.agent_id:
        return wstore.get_ticket(ticket.id)
    wstore.assign_ticket(ticket.id, assignee_type="agent", assignee_id=decision.agent_id)
    updated = wstore.set_ticket_status(ticket.id, "todo")

    from creation.work import audit

    audit.record(
        "ticket.routed",
        "ticket",
        ticket.id,
        actor=decision.agent_id,
        actor_type="system",
        detail={"action": decision.action, "kind": decision.kind, "reason": decision.reason},
        org_id=ticket.org_id,
        team_id=ticket.team_id,
        user_id=ticket.user_id,
    )
    return updated


def auto_route(ticket: Ticket, *, kind: Optional[str] = None) -> RoutingDecision:
    """Route + assign in one call. Returns the decision for the caller to surface."""
    decision = route_ticket(ticket, kind=kind)
    apply_routing(ticket, decision)
    return decision
