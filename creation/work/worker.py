"""Worker — execute a single ticket through a coding agent, then learn from it.

This is the heart of the loop's Work + Learn phases:

    1. claim the ticket (status -> in_progress, link a Run)
    2. build a prompt and invoke the coding agent in the repo workdir
    3. measure what actually changed (git), parse the agent's EVIDENCE block
    4. persist an EvidencePack and move the ticket to review/done/blocked per policy

It deliberately reuses the legacy ``creation.store`` Run table (now carrying ticket
linkage columns) so every ticket run shows up in the same execution history.
"""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from creation.config import UserSecrets
from creation.store import create_run, update_run
from creation.work import store as wstore
from creation.work.models import AgentDef, EvidencePack, Ticket
from creation.work.prompt import build_ticket_prompt

LineCallback = Callable[[str], None]


class _Runner(Protocol):
    """Minimal surface of CodingAgentRunner so workers are easy to test/mock."""

    def run(self, prompt: str, workdir: Path, on_line: Optional[LineCallback] = ...): ...


@dataclass
class TicketRunResult:
    ticket_id: str
    run_id: str
    success: bool
    status: str
    evidence: EvidencePack
    output: str


# ── git helpers (best-effort, never raise) ────────────────────────────────────
def _git(args: List[str], cwd: Path, timeout: int = 60) -> tuple[bool, str]:
    if not shutil.which("git"):
        return False, ""
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:  # pragma: no cover - defensive
        return False, str(e)


# Identity flags so commits succeed even on a runner/machine with no global
# git config (CI), and never get blocked on GPG signing.
_GIT_IDENT = [
    "-c", "user.email=agent@creation.dev",
    "-c", "user.name=Creation Agent",
    "-c", "commit.gpgsign=false",
]


def _ensure_repo(workdir: Path) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    if not (workdir / ".git").exists():
        _git(["init"], workdir)
        _git(["add", "-A"], workdir)
        _git([*_GIT_IDENT, "commit", "-m", "creation: baseline"], workdir)


def _changed_files(workdir: Path) -> List[str]:
    ok, out = _git(["status", "--porcelain"], workdir)
    if not ok or not out:
        return []
    files = []
    for line in out.splitlines():
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if "->" in path:  # renames: "old -> new"
            path = path.split("->")[-1].strip()
        if path:
            files.append(path)
    return files


def _diff_stat(workdir: Path) -> str:
    ok, out = _git(["diff", "--stat"], workdir)
    return out if ok else ""


def _commit(workdir: Path, message: str) -> bool:
    _git(["add", "-A"], workdir)
    ok, out = _git([*_GIT_IDENT, "commit", "-m", message], workdir)
    return ok or "nothing to commit" in out.lower()


# ── cost estimation ───────────────────────────────────────────────────────────
# No coding-agent CLI reliably reports token usage, so we estimate from the bytes
# that crossed the wire (~4 chars/token) priced at a cheap pooled rate. This is a
# transparent local estimate — good enough to power per-PR cost SLOs and budgets.
_CHARS_PER_TOKEN = 4
_USD_PER_MTOK = 0.60


def estimate_cost(prompt: str, output: str) -> tuple[int, float]:
    tokens = (len(prompt or "") + len(output or "")) // _CHARS_PER_TOKEN
    return tokens, round(tokens / 1_000_000 * _USD_PER_MTOK, 4)


# ── evidence parsing ──────────────────────────────────────────────────────────
_EVIDENCE_RE = re.compile(r"EVIDENCE_BEGIN(.*?)EVIDENCE_END", re.DOTALL)


def parse_evidence_block(output: str) -> dict:
    """Extract the structured EVIDENCE block the prompt asks the agent to emit."""
    m = _EVIDENCE_RE.search(output or "")
    fields: dict = {}
    if not m:
        return fields
    body = m.group(1)
    for key in ("PLAN", "READ", "CHANGED", "TESTS", "RESULT", "RISKS", "CONFIDENCE"):
        km = re.search(rf"{key}:\s*(.*)", body)
        if km:
            fields[key.lower()] = km.group(1).strip()
    return fields


def _matches_any(path: str, globs: List[str]) -> bool:
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(path, f"*{g}*") for g in globs)


def evaluate_policy(agent: AgentDef, ticket: Ticket, changed: List[str]) -> List[Dict[str, Any]]:
    """Turn the agent's inline policy into pass/fail checks against what it did.

    These are real gates (not just prompt text): a violation forces human review.
    """
    checks: List[Dict[str, Any]] = []

    # Repo allow-list.
    if ticket.repo:
        ok = agent.can_touch_repo(ticket.repo)
        checks.append({
            "name": "repo_allowlist",
            "ok": ok,
            "detail": ("within scope" if ok else f"{ticket.repo} not in allowed repos"),
        })

    # Sensitive paths the agent must never modify.
    if agent.denied_paths:
        violations = sorted({f for f in changed if _matches_any(f, agent.denied_paths)})
        checks.append({
            "name": "denied_paths",
            "ok": not violations,
            "detail": ("no sensitive files touched" if not violations
                       else "touched protected paths: " + ", ".join(violations)),
        })

    # Risk tier / approval posture (informational — enforced in _final_status).
    checks.append({
        "name": "approval",
        "ok": True,
        "detail": ("human approval required before ship" if agent.require_approval
                   else "auto-ship eligible"),
    })
    return checks


def _as_list(value: str) -> List[str]:
    if not value or value.strip().lower() in {"none", "n/a", "-"}:
        return []
    return [p.strip() for p in re.split(r"[,\n]", value) if p.strip()]


def _confidence(value: str) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _final_status(
    agent: AgentDef, ticket: Ticket, success: bool, policy_ok: bool = True
) -> str:
    if not success:
        return "blocked"
    # Policy gate: a failed policy check, high-risk work, or approval-required agents
    # all stop at review — never auto-done.
    if (
        not policy_ok
        or agent.require_approval
        or agent.risk_tier == "high"
        or ticket.risk_tier == "high"
    ):
        return "in_review"
    return "done"


def run_ticket(
    ticket: Ticket,
    agent: AgentDef,
    workdir: Path,
    secrets: UserSecrets,
    *,
    on_line: Optional[LineCallback] = None,
    runner: Optional[_Runner] = None,
    auto_commit: bool = True,
) -> TicketRunResult:
    """Run one ticket end-to-end and return its result + evidence."""
    wstore.init_work_db()
    workdir = Path(workdir)

    # 1 — claim
    run = create_run(project_id=f"ticket:{ticket.id}")
    update_run(
        run.id,
        status="running",
        ticket_id=ticket.id,
        agent_def_id=agent.id,
        org_id=ticket.org_id,
        team_id=ticket.team_id,
        user_id=ticket.user_id or "me",
        current_phase="work",
    )
    wstore.set_ticket_status(ticket.id, "in_progress")
    wstore.link_run_to_ticket(ticket.id, run.id)
    if on_line:
        on_line(f"[{ticket.id}] claimed by {agent.name} ({agent.kind}) → run {run.id}")

    _ensure_repo(workdir)

    # 2 — work (inject playbook lessons so the agent avoids past mistakes)
    if runner is None:
        from creation.agents.runner import CodingAgentRunner

        runner = CodingAgentRunner(agent.coding_agent, secrets)
    from creation.work import playbook

    lessons = playbook.lessons_block(playbook.relevant_lessons(ticket, agent.kind))
    prompt = build_ticket_prompt(ticket, agent, lessons=lessons)
    result = runner.run(prompt, workdir, on_line)
    output = getattr(result, "output", "") or ""
    success = bool(getattr(result, "success", False))
    command = getattr(result, "command", "")

    # 3 — learn: what actually changed + what the agent claims
    changed = _changed_files(workdir)
    diff_stat = _diff_stat(workdir)
    parsed = parse_evidence_block(output)
    claimed_changed = _as_list(parsed.get("changed", ""))
    files_modified = sorted(set(changed) | set(claimed_changed))

    # Real policy evaluation against what the agent actually changed.
    policy_checks = evaluate_policy(agent, ticket, files_modified)
    policy_ok = all(c["ok"] for c in policy_checks)
    risks = _as_list(parsed.get("risks", ""))
    if not policy_ok:
        for c in policy_checks:
            if not c["ok"]:
                risks.append(f"Policy: {c['detail']}")

    tokens, cost = estimate_cost(prompt, output)

    evidence = EvidencePack(
        ticket_id=ticket.id,
        run_id=run.id,
        goal=ticket.title,
        plan=parsed.get("plan", ""),
        files_read=_as_list(parsed.get("read", "")),
        files_modified=files_modified,
        reasoning_summary=output[-2000:],
        commands=[command] if command else [],
        tests_run=parsed.get("tests", ""),
        test_results=parsed.get("result", ""),
        risks=risks,
        policy_checks=policy_checks,
        reviewer_suggestions="",
        cost_usd=cost,
        confidence=_confidence(parsed.get("confidence", "")),
    )
    wstore.create_evidence(evidence)

    # A policy violation must never be silently committed.
    if auto_commit and changed and success and policy_ok:
        _commit(workdir, f"creation[{ticket.id}]: {ticket.title}"[:100])

    # 4 — transition per policy
    status = _final_status(agent, ticket, success, policy_ok=policy_ok)
    wstore.set_ticket_status(ticket.id, status)
    update_run(
        run.id,
        status="done" if success else "error",
        current_phase="learn",
        result={
            "ticket_id": ticket.id,
            "files_modified": evidence.files_modified,
            "diff_stat": diff_stat,
            "confidence": evidence.confidence,
            "cost_usd": evidence.cost_usd,
            "tokens_est": tokens,
            "policy_ok": policy_ok,
            "final_status": status,
        },
    )

    # 5 — learn for next time: distill a playbook lesson + audit the run
    from creation.work import audit, playbook

    playbook.record_from_evidence(evidence, ticket, agent.kind, status)
    audit.record(
        "run.completed",
        "ticket",
        ticket.id,
        actor=agent.id,
        actor_type="agent",
        detail={"run_id": run.id, "status": status, "files": len(evidence.files_modified)},
        org_id=ticket.org_id,
        team_id=ticket.team_id,
        user_id=ticket.user_id,
    )
    if on_line:
        on_line(f"[{ticket.id}] {'ok' if success else 'failed'} → {status} ({len(evidence.files_modified)} files)")

    return TicketRunResult(
        ticket_id=ticket.id,
        run_id=run.id,
        success=success,
        status=status,
        evidence=evidence,
        output=output,
    )
