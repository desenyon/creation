"""Creation work graph — the multi-tenant ticketing + agent-bench core (the pivot).

This package introduces tickets, agents, triggers, evidence packs, and missions as
first-class durable objects. It runs alongside the legacy Project/Run build factory
and is gated by the `work_graph_enabled` feature flag during the pivot.

Scope model: every entity carries (org_id, team_id, user_id, visibility). "Personal"
work is user-scoped/private; "company-wide" work is team/org-scoped. One system, two
scopes — never two apps.
"""

from creation.work.models import (
    AgentDef,
    EvidencePack,
    Mission,
    Scope,
    Ticket,
    Trigger,
    LOCAL_ORG,
    LOCAL_USER,
)

__all__ = [
    "AgentDef",
    "EvidencePack",
    "Mission",
    "Scope",
    "Ticket",
    "Trigger",
    "LOCAL_ORG",
    "LOCAL_USER",
    "seed_personal_bench",
    "agent_by_kind",
    "create_loop_agent",
    "run_ticket",
    "dispatch_once",
    "build_ticket_prompt",
    "tick",
    "handle_webhook_event",
    "fan_out_mission",
    "fan_out_across_repos",
    "mission_progress",
    "agent_metrics",
    "bench_metrics",
    "approve_ticket",
    "reject_ticket",
]


def __getattr__(name: str):  # lazy to avoid importing the runner stack eagerly
    if name in ("seed_personal_bench", "agent_by_kind", "create_loop_agent"):
        from creation.work import bench

        return getattr(bench, name)
    if name in ("run_ticket", "TicketRunResult"):
        from creation.work import worker

        return getattr(worker, name)
    if name == "dispatch_once":
        from creation.work.dispatcher import dispatch_once

        return dispatch_once
    if name == "build_ticket_prompt":
        from creation.work.prompt import build_ticket_prompt

        return build_ticket_prompt
    if name in ("tick", "handle_webhook_event"):
        from creation.work import triggers

        return getattr(triggers, name)
    if name in ("fan_out_mission", "fan_out_across_repos", "mission_progress"):
        from creation.work import missions

        return getattr(missions, name)
    if name in ("agent_metrics", "bench_metrics"):
        from creation.work import evals

        return getattr(evals, name)
    if name in ("approve_ticket", "reject_ticket"):
        from creation.work import review

        return getattr(review, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
