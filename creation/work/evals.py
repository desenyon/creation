"""Evals — manage agents like services with measurable outcomes.

Derives basic quality signal from the work graph: how many tickets an agent handled,
its acceptance rate (done vs. blocked), average self-reported confidence, and review
load. These are the seeds of the Agent SLOs in future.md (Phase 5).
"""

from __future__ import annotations

from typing import Any, Dict, List

from creation.work import store as wstore


def agent_metrics(agent_id: str) -> Dict[str, Any]:
    agent = wstore.get_agent(agent_id)
    tickets = wstore.list_tickets(assignee_type="agent", assignee_id=agent_id)

    counts: Dict[str, int] = {}
    confidences: List[float] = []
    files_changed = 0
    runs = 0
    total_cost = 0.0
    policy_violations = 0
    for t in tickets:
        counts[t.status] = counts.get(t.status, 0) + 1
        for pack in wstore.list_evidence_for_ticket(t.id):
            runs += 1
            files_changed += len(pack.files_modified)
            total_cost += pack.cost_usd or 0.0
            if any(not c.get("ok", True) for c in (pack.policy_checks or [])):
                policy_violations += 1
            if pack.confidence:
                confidences.append(pack.confidence)

    done = counts.get("done", 0)
    in_review = counts.get("in_review", 0)
    blocked = counts.get("blocked", 0)
    # Acceptance = completed work vs. work that needed human rescue (blocked).
    decided = done + blocked
    acceptance_rate = round(done / decided, 3) if decided else 0.0
    avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    # Cost per shipped unit of work — the headline enterprise SLO.
    cost_per_done = round(total_cost / done, 4) if done else 0.0

    return {
        "agent_id": agent_id,
        "name": agent.name if agent else agent_id,
        "kind": agent.kind if agent else "",
        "assigned": len(tickets),
        "runs": runs,
        "done": done,
        "in_review": in_review,
        "blocked": blocked,
        "acceptance_rate": acceptance_rate,
        "avg_confidence": avg_conf,
        "files_changed": files_changed,
        "total_cost": round(total_cost, 4),
        "cost_per_done": cost_per_done,
        "policy_violations": policy_violations,
        "by_status": counts,
    }


def bench_metrics(*, bench_type: str | None = None) -> List[Dict[str, Any]]:
    return [agent_metrics(a.id) for a in wstore.list_agents(bench_type=bench_type)]
