"""Work-graph dataclasses for the enterprise agent OS pivot.

These are intentionally JSON-friendly (string enums, list/dict fields) so they map
cleanly onto SQLite columns today and Postgres/multitenancy later without churn.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

# ── Local-first defaults ──────────────────────────────────────────────────────
# In solo mode there is one implicit org and one implicit user. The same columns
# carry real tenant IDs once hosted multi-tenant mode lands (Phase 3).
LOCAL_ORG = "local"
LOCAL_USER = "me"

Visibility = Literal["private", "team", "org"]

TicketSource = Literal["human", "jira", "linear", "github", "agent", "incident", "mission"]
TicketStatus = Literal["backlog", "todo", "in_progress", "in_review", "blocked", "done", "cancelled"]
Priority = Literal["low", "medium", "high", "urgent"]
RiskTier = Literal["low", "medium", "high"]
AssigneeType = Literal["none", "user", "agent"]

AgentKind = Literal[
    "code",
    "test",
    "review",
    "debug",
    "docs",
    "migration",
    "incident",
    "infra",
    "security",
    "performance",
    "archaeologist",
]
BenchType = Literal["personal", "org"]
AgentStatus = Literal["active", "paused"]

TriggerKind = Literal["ticket_assigned", "ticket_status", "cron", "webhook", "mission_fanout"]
MissionStatus = Literal["planning", "active", "paused", "complete", "cancelled"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "") -> str:
    h = uuid.uuid4().hex[:12]
    return f"{prefix}{h}" if prefix else h


@dataclass
class Scope:
    """Tenancy + visibility carried by every work-graph entity."""

    org_id: str = LOCAL_ORG
    team_id: Optional[str] = None
    user_id: Optional[str] = LOCAL_USER
    visibility: Visibility = "private"

    @property
    def is_personal(self) -> bool:
        return self.visibility == "private" and self.team_id is None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Ticket:
    """A unit of work. Can be assigned to a human OR an agent. The board's atom."""

    id: str = field(default_factory=lambda: new_id("tkt_"))
    title: str = ""
    description: str = ""
    source: TicketSource = "human"
    status: TicketStatus = "backlog"
    priority: Priority = "medium"
    risk_tier: RiskTier = "low"

    assignee_type: AssigneeType = "none"
    assignee_id: Optional[str] = None  # user_id or agent_id

    repo: str = ""
    service: str = ""
    labels: List[str] = field(default_factory=list)

    mission_id: Optional[str] = None
    run_ids: List[str] = field(default_factory=list)

    # External system linkage (when synced from Jira/Linear/GitHub)
    external_id: str = ""
    external_url: str = ""

    # Tenancy
    org_id: str = LOCAL_ORG
    team_id: Optional[str] = None
    user_id: Optional[str] = LOCAL_USER
    visibility: Visibility = "private"

    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    @property
    def scope(self) -> Scope:
        return Scope(self.org_id, self.team_id, self.user_id, self.visibility)

    def assigned_to_agent(self) -> bool:
        return self.assignee_type == "agent" and bool(self.assignee_id)


@dataclass
class AgentDef:
    """A bench member: a governed, reusable agent. Personal or org-scoped."""

    id: str = field(default_factory=lambda: new_id("agt_"))
    name: str = ""
    kind: AgentKind = "code"
    bench_type: BenchType = "personal"

    # Which underlying coding-agent CLI executes this agent's work.
    coding_agent: str = "codex"

    # Lightweight inline policy (extracted to a Policy entity in Phase 3).
    risk_tier: RiskTier = "low"
    allowed_repos: List[str] = field(default_factory=list)  # empty = all in scope
    allowed_tools: List[str] = field(default_factory=list)
    allowed_models: List[str] = field(default_factory=list)
    denied_paths: List[str] = field(default_factory=list)  # sensitive files/globs
    require_approval: bool = True
    max_turn_budget: int = 50

    skills: List[str] = field(default_factory=list)
    status: AgentStatus = "active"

    # Tenancy
    org_id: str = LOCAL_ORG
    team_id: Optional[str] = None
    user_id: Optional[str] = LOCAL_USER
    visibility: Visibility = "private"

    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    @property
    def scope(self) -> Scope:
        return Scope(self.org_id, self.team_id, self.user_id, self.visibility)

    def can_touch_repo(self, repo: str) -> bool:
        return not self.allowed_repos or repo in self.allowed_repos


@dataclass
class Trigger:
    """Binds work to an agent so it 'just keeps going'. The always-on hook."""

    id: str = field(default_factory=lambda: new_id("trg_"))
    agent_id: str = ""
    kind: TriggerKind = "ticket_assigned"
    # kind-specific config: {"cron": "0 2 * * *"} | {"status": "todo"} |
    # {"source": "ci_failed"} | {"mission_id": "..."}
    config: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

    org_id: str = LOCAL_ORG
    team_id: Optional[str] = None
    user_id: Optional[str] = LOCAL_USER
    visibility: Visibility = "private"

    created_at: str = field(default_factory=now_iso)
    last_fired_at: str = ""


@dataclass
class EvidencePack:
    """The reviewable artifact every agent run produces. Reduces review burden."""

    id: str = field(default_factory=lambda: new_id("evd_"))
    ticket_id: str = ""
    run_id: str = ""

    goal: str = ""
    plan: str = ""
    files_read: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    reasoning_summary: str = ""
    commands: List[str] = field(default_factory=list)
    tests_run: str = ""
    test_results: str = ""
    risks: List[str] = field(default_factory=list)
    policy_checks: List[Dict[str, Any]] = field(default_factory=list)
    reviewer_suggestions: str = ""
    linked_tickets: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    cost_usd: float = 0.0
    confidence: float = 0.0

    created_at: str = field(default_factory=now_iso)


@dataclass
class Mission:
    """A company-wide objective that decomposes into many tickets across repos."""

    id: str = field(default_factory=lambda: new_id("msn_"))
    title: str = ""
    description: str = ""
    goal: str = ""
    status: MissionStatus = "planning"
    plan: str = ""

    # Tenancy — missions are typically team/org scoped.
    org_id: str = LOCAL_ORG
    team_id: Optional[str] = None
    user_id: Optional[str] = LOCAL_USER
    visibility: Visibility = "team"

    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    @property
    def scope(self) -> Scope:
        return Scope(self.org_id, self.team_id, self.user_id, self.visibility)
