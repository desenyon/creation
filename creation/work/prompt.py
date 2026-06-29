"""Build coding-agent prompts from a ticket.

The prompt is the contract between a ticket and the agent that executes it. It is
kind-aware: a migration ticket gets different marching orders than a bug fix or a
review. Every prompt demands an EVIDENCE section so the Learn step has structured
signal to parse back into an EvidencePack.
"""

from __future__ import annotations

from creation.work.models import AgentDef, Ticket

_EVIDENCE_CONTRACT = """\
## REQUIRED — end your run with an EVIDENCE block

Append this block (verbatim headers) as the final thing you output:

EVIDENCE_BEGIN
PLAN: <one-line summary of the approach you took>
READ: <comma-separated files you read to understand the task, or "none">
CHANGED: <comma-separated files you created or modified>
TESTS: <commands you ran to verify, or "none">
RESULT: <pass/fail summary of those tests, or "none">
RISKS: <anything risky/uncertain a reviewer must check, or "none">
CONFIDENCE: <0.0-1.0 how confident you are this is correct and complete>
EVIDENCE_END
"""

_KIND_GUIDANCE = {
    "migration": (
        "You are a MIGRATION agent. Make the smallest correct mechanical change that "
        "moves the codebase toward the target. Preserve behavior. Update imports, "
        "config, and lockfiles as needed. Do not refactor unrelated code."
    ),
    "code": (
        "You are a CODE agent. Implement the change request fully and idiomatically, "
        "matching the existing style and structure of the repo."
    ),
    "test": (
        "You are a TEST agent. Add or repair tests so the described behavior is covered. "
        "Do not weaken assertions to make tests pass; fix the root cause if needed."
    ),
    "review": (
        "You are a REVIEW agent. Inspect the change described and leave precise, "
        "actionable findings. Prefer concrete diffs over vague advice."
    ),
    "debug": (
        "You are a DEBUG agent. Reproduce the issue, isolate the root cause, and apply a "
        "minimal fix. Explain the failure mode in your evidence."
    ),
    "docs": (
        "You are a DOCS agent. Update documentation to match current behavior. Keep it "
        "concise and accurate; do not invent features."
    ),
    "security": (
        "You are a SECURITY agent. Treat secrets and auth paths as sensitive. Do not log "
        "or exfiltrate credentials. Flag every risky change in your evidence."
    ),
    "performance": (
        "You are a PERFORMANCE agent. Measure before and after where possible. Avoid "
        "premature micro-optimizations; target the described hot path."
    ),
    "incident": (
        "You are an INCIDENT agent. Read the incident context, find the related "
        "services and files, and produce the follow-through: a minimal hardening fix, "
        "a regression test, and any runbook/doc update. Be conservative and reversible."
    ),
    "infra": (
        "You are an INFRA agent. Treat config, CI, IaC, and deploy files as production. "
        "Make the smallest correct change, keep it idempotent, and call out any change "
        "that affects environments or secrets in your evidence."
    ),
    "archaeologist": (
        "You are a REPO ARCHAEOLOGIST. Do not change code unless asked. Investigate and "
        "explain: why code is the way it is, who owns it, what broke historically, and "
        "the unwritten rules. Output findings and safe next steps in your evidence."
    ),
}


def _policy_notes(agent: AgentDef) -> str:
    notes = []
    if agent.denied_paths:
        notes.append(f"Never touch these paths: {', '.join(agent.denied_paths)}.")
    if agent.allowed_repos:
        notes.append(f"Stay within these repos: {', '.join(agent.allowed_repos)}.")
    if agent.allowed_tools:
        notes.append(f"Only use these tools: {', '.join(agent.allowed_tools)}.")
    if agent.max_turn_budget:
        notes.append(
            f"Keep the work tight — aim to finish well within ~{agent.max_turn_budget} steps."
        )
    if agent.risk_tier == "high":
        notes.append("This is a HIGH-RISK change. Be conservative and over-document risks.")
    return ("\n".join(f"- {n}" for n in notes)) if notes else ""


def build_ticket_prompt(ticket: Ticket, agent: AgentDef, *, lessons: str = "") -> str:
    guidance = _KIND_GUIDANCE.get(agent.kind, _KIND_GUIDANCE["code"])
    parts = [
        f"# Ticket {ticket.id}: {ticket.title}",
        "",
        guidance,
        "",
        "## Task",
        ticket.description or ticket.title,
    ]
    if ticket.repo:
        parts += ["", f"## Repository\n{ticket.repo}"]
    if ticket.labels:
        parts += ["", f"## Labels\n{', '.join(ticket.labels)}"]

    if lessons:
        parts += ["", lessons]

    policy = _policy_notes(agent)
    if policy:
        parts += ["", "## Constraints", policy]

    parts += [
        "",
        "## Working agreement",
        "- Make the change directly in the working directory.",
        "- Keep the change scoped to this ticket only.",
        "- Leave the repo in a working state.",
        "",
        _EVIDENCE_CONTRACT,
    ]
    return "\n".join(parts)
