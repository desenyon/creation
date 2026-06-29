"""Approval gate — the human-in-the-loop step for governed agent work.

Agent runs that require approval stop at ``in_review``. A reviewer then approves
(optionally shipping a PR) or rejects with feedback that is fed back to the agent for
another attempt. Every decision is audited.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from creation.work import audit
from creation.work import store as wstore
from creation.work.models import LOCAL_USER, Ticket


@dataclass
class ReviewResult:
    ticket_id: str
    status: str
    pr_url: str = ""
    message: str = ""


def _latest_run_workdir(ticket: Ticket) -> Optional[Path]:
    if ticket.repo:
        p = Path(ticket.repo).expanduser()
        if p.exists():
            return p
    return None


def approve_ticket(
    ticket_id: str,
    *,
    reviewer: str = LOCAL_USER,
    ship: bool = False,
    github_url: str = "",
) -> ReviewResult:
    """Approve an in-review ticket → done. Optionally open a PR with the change."""
    ticket = wstore.get_ticket(ticket_id)
    if ticket is None:
        raise ValueError(f"ticket {ticket_id} not found")
    if ticket.status != "in_review":
        raise ValueError(f"ticket {ticket_id} is '{ticket.status}', not 'in_review'")

    pr_url = ""
    message = "approved"
    if ship:
        pr_url, message = _ship(ticket, github_url)

    wstore.set_ticket_status(ticket_id, "done")
    audit.record(
        "ticket.approved",
        "ticket",
        ticket_id,
        actor=reviewer,
        actor_type="user",
        detail={"ship": ship, "pr_url": pr_url, "message": message},
        org_id=ticket.org_id,
        team_id=ticket.team_id,
        user_id=ticket.user_id,
    )
    return ReviewResult(ticket_id=ticket_id, status="done", pr_url=pr_url, message=message)


def reject_ticket(
    ticket_id: str,
    feedback: str,
    *,
    reviewer: str = LOCAL_USER,
    requeue: bool = True,
) -> ReviewResult:
    """Reject an in-review ticket. Feedback is appended so the next run sees it.

    ``requeue=True`` sends it back to ``todo`` (agent retries with feedback);
    otherwise it is ``blocked`` for a human.
    """
    ticket = wstore.get_ticket(ticket_id)
    if ticket is None:
        raise ValueError(f"ticket {ticket_id} not found")

    ticket.description = (ticket.description or "") + f"\n\n## Reviewer feedback\n{feedback}"
    wstore.update_ticket(ticket)
    new_status = "todo" if requeue else "blocked"
    wstore.set_ticket_status(ticket_id, new_status)
    audit.record(
        "ticket.rejected",
        "ticket",
        ticket_id,
        actor=reviewer,
        actor_type="user",
        detail={"feedback": feedback[:500], "requeue": requeue},
        org_id=ticket.org_id,
        team_id=ticket.team_id,
        user_id=ticket.user_id,
    )
    return ReviewResult(ticket_id=ticket_id, status=new_status, message="rejected")


def _ship(ticket: Ticket, github_url: str) -> tuple[str, str]:
    """Best-effort PR: push a feature branch and open a PR via gh. Never raises."""
    workdir = _latest_run_workdir(ticket)
    if not workdir:
        return "", "no local workdir to ship"
    try:
        from creation.integrations.git_sync import (
            create_pull_request,
            push_feature_branch,
            resolve_github_from_workdir,
        )

        owner, repo, html = resolve_github_from_workdir(workdir)
        remote = github_url or html
        if not remote:
            return "", "no github remote configured"
        branch = f"creation/{ticket.id}"
        if not push_feature_branch(workdir, remote, branch, f"creation[{ticket.id}]: {ticket.title}"):
            return "", "push failed"
        if owner and repo:
            ok, url = create_pull_request(owner, repo, branch, ticket.title, ticket.description or ticket.title)
            if ok:
                return url, "pr opened"
        return "", "branch pushed (no PR)"
    except Exception as e:  # pragma: no cover - defensive
        return "", f"ship error: {e}"
