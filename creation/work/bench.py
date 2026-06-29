"""Default agent bench — the starting roster of personal agents.

Seeding a sensible bench is what makes the product feel alive on first run: a user
opens Creation and already has a Migration agent, a Code agent, a Reviewer, and a Test
agent ready to be assigned tickets. Org benches (Phase 3) reuse the same shape with
team scope and stricter policy.
"""

from __future__ import annotations

from typing import List

from creation.work import store as wstore
from creation.work.models import LOCAL_ORG, LOCAL_USER, AgentDef

# name -> (kind, risk_tier, require_approval, skills)
# The full specialist roster from the product vision — every engineer's bench.
_DEFAULT_BENCH = [
    ("Code Agent", "code", "low", True, ["feature-work", "bug-fix", "refactor"]),
    ("Test Agent", "test", "low", False, ["unit-tests", "regression", "flaky-test-repair"]),
    ("Reviewer", "review", "low", False, ["code-review", "risk-analysis"]),
    ("Debug Agent", "debug", "low", True, ["repro", "root-cause", "hotfix"]),
    ("Docs Agent", "docs", "low", False, ["docs-sync", "readme", "changelog"]),
    ("Migration Agent", "migration", "medium", True, ["dependency-upgrades", "codemods", "framework-migration"]),
    ("Incident Agent", "incident", "medium", True, ["postmortem-followup", "hardening", "runbooks"]),
    ("Infra Agent", "infra", "high", True, ["ci", "iac", "config", "deploy"]),
    ("Security Agent", "security", "high", True, ["vuln-fix", "secret-scan", "authz-review"]),
    ("Performance Agent", "performance", "medium", True, ["profiling", "hot-path", "regression-budget"]),
    ("Repo Archaeologist", "archaeologist", "low", False, ["code-history", "ownership", "onboarding"]),
]


def seed_personal_bench(
    *, user_id: str = LOCAL_USER, coding_agent: str = "codex", force: bool = False
) -> List[AgentDef]:
    """Create the default personal bench if the user has no agents yet.

    Idempotent: returns the existing bench unless ``force`` is set.
    """
    existing = wstore.list_agents(bench_type="personal", user_id=user_id)
    if existing and not force:
        return existing

    created: List[AgentDef] = []
    for name, kind, risk, approval, skills in _DEFAULT_BENCH:
        agent = AgentDef(
            name=name,
            kind=kind,  # type: ignore[arg-type]
            bench_type="personal",
            coding_agent=coding_agent,
            risk_tier=risk,  # type: ignore[arg-type]
            require_approval=approval,
            skills=skills,
            org_id=LOCAL_ORG,
            user_id=user_id,
            visibility="private",
        )
        created.append(wstore.create_agent(agent))
    return created


def agent_by_kind(kind: str, *, user_id: str = LOCAL_USER) -> AgentDef | None:
    for a in wstore.list_agents(bench_type="personal", user_id=user_id):
        if a.kind == kind:
            return a
    return None


# ── Loop templates — reusable maintenance agents + their cron triggers ─────────
# Each template is a long-running maintenance loop (future.md's "Maintenance OS").
# slug -> spec for the agent + an optional default cron loop (every_seconds + ticket).
LOOP_TEMPLATES: dict[str, dict] = {
    "flaky-test-killer": {
        "name": "Flaky-Test Killer",
        "kind": "test",
        "risk_tier": "low",
        "require_approval": False,
        "skills": ["flaky-test-repair", "test-stability"],
        "cron": {
            "every_seconds": 86400,
            "ticket": {
                "title": "Scan for and repair flaky tests",
                "priority": "medium",
                "risk_tier": "low",
            },
        },
    },
    "dependency-upgrade": {
        "name": "Dependency Upgrade",
        "kind": "migration",
        "risk_tier": "medium",
        "require_approval": True,
        "skills": ["dependency-upgrades", "lockfile-maintenance"],
        "cron": {
            "every_seconds": 604800,
            "ticket": {
                "title": "Upgrade outdated dependencies (safe bumps)",
                "priority": "low",
                "risk_tier": "medium",
            },
        },
    },
    "docs-drift": {
        "name": "Docs Drift",
        "kind": "docs",
        "risk_tier": "low",
        "require_approval": False,
        "skills": ["docs-sync", "readme-maintenance"],
        "cron": {
            "every_seconds": 604800,
            "ticket": {"title": "Reconcile docs with current behavior", "priority": "low"},
        },
    },
    "bug-backlog": {
        "name": "Small-Bug Backlog",
        "kind": "debug",
        "risk_tier": "low",
        "require_approval": True,
        "skills": ["bug-fix", "triage"],
        "cron": None,
    },
}


def create_loop_agent(
    template: str,
    *,
    repo: str = "",
    bench_type: str = "personal",
    user_id: str = LOCAL_USER,
    team_id: str | None = None,
    coding_agent: str = "codex",
    with_cron: bool = True,
):
    """Instantiate a maintenance-loop agent (+ its cron trigger) from a template.

    Returns ``(agent, trigger_or_None)``. The cron trigger makes it self-sustaining:
    on each dispatcher tick it spawns its scan/maintenance ticket.
    """
    spec = LOOP_TEMPLATES.get(template)
    if spec is None:
        raise ValueError(f"unknown loop template '{template}'")

    agent = wstore.create_agent(
        AgentDef(
            name=spec["name"],
            kind=spec["kind"],
            bench_type=bench_type,  # type: ignore[arg-type]
            coding_agent=coding_agent,
            risk_tier=spec["risk_tier"],
            require_approval=spec["require_approval"],
            skills=list(spec.get("skills", [])),
            allowed_repos=[repo] if repo else [],
            org_id=LOCAL_ORG,
            user_id=user_id,
            team_id=team_id,
            visibility="team" if bench_type == "org" else "private",
        )
    )

    trigger = None
    cron = spec.get("cron")
    if with_cron and cron:
        from creation.work.triggers import create_cron_trigger

        ticket = dict(cron["ticket"])
        if repo:
            ticket.setdefault("repo", repo)
        trigger = create_cron_trigger(agent.id, every_seconds=cron["every_seconds"], ticket=ticket)
    return agent, trigger
