"""SQLite store for the work graph (tickets, agents, triggers, evidence, missions).

Reuses the same ``creation.db`` file as the legacy store but owns separate tables, so it
is fully non-breaking. Generic dataclass<->row mapping keeps CRUD compact.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import fields as dc_fields
from typing import Any, Dict, List, Optional, Type, TypeVar

from creation.store import _conn  # reuse connection + db file
from creation.work.models import (
    AgentDef,
    EvidencePack,
    Mission,
    Ticket,
    Trigger,
    now_iso,
)

T = TypeVar("T")

# Fields that must be JSON-encoded in their text column, per dataclass.
_JSON_FIELDS: Dict[type, set] = {
    Ticket: {"labels", "run_ids"},
    AgentDef: {"allowed_repos", "allowed_tools", "allowed_models", "denied_paths", "skills"},
    Trigger: {"config"},
    EvidencePack: {
        "files_read",
        "files_modified",
        "commands",
        "risks",
        "policy_checks",
        "linked_tickets",
        "open_questions",
    },
    Mission: set(),
}
# Fields stored as INTEGER booleans.
_BOOL_FIELDS: Dict[type, set] = {
    AgentDef: {"require_approval"},
    Trigger: {"enabled"},
}

_TABLE: Dict[type, str] = {
    Ticket: "tickets",
    AgentDef: "agents",
    Trigger: "triggers",
    EvidencePack: "evidence_packs",
    Mission: "missions",
}


def init_work_db() -> None:
    """Create work-graph tables. Idempotent; safe to call on every startup."""
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY,
                title TEXT, description TEXT,
                source TEXT, status TEXT, priority TEXT, risk_tier TEXT,
                assignee_type TEXT, assignee_id TEXT,
                repo TEXT, service TEXT, labels TEXT,
                mission_id TEXT, run_ids TEXT,
                external_id TEXT, external_url TEXT,
                org_id TEXT, team_id TEXT, user_id TEXT, visibility TEXT,
                created_at TEXT, updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                name TEXT, kind TEXT, bench_type TEXT, coding_agent TEXT,
                risk_tier TEXT, allowed_repos TEXT, allowed_tools TEXT,
                allowed_models TEXT, denied_paths TEXT, require_approval INTEGER,
                max_turn_budget INTEGER, skills TEXT, status TEXT,
                org_id TEXT, team_id TEXT, user_id TEXT, visibility TEXT,
                created_at TEXT, updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS triggers (
                id TEXT PRIMARY KEY,
                agent_id TEXT, kind TEXT, config TEXT, enabled INTEGER,
                org_id TEXT, team_id TEXT, user_id TEXT, visibility TEXT,
                created_at TEXT, last_fired_at TEXT
            );
            CREATE TABLE IF NOT EXISTS evidence_packs (
                id TEXT PRIMARY KEY,
                ticket_id TEXT, run_id TEXT,
                goal TEXT, plan TEXT, files_read TEXT, files_modified TEXT,
                reasoning_summary TEXT, commands TEXT, tests_run TEXT, test_results TEXT,
                risks TEXT, policy_checks TEXT, reviewer_suggestions TEXT,
                linked_tickets TEXT, open_questions TEXT, cost_usd REAL, confidence REAL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS missions (
                id TEXT PRIMARY KEY,
                title TEXT, description TEXT, goal TEXT, status TEXT, plan TEXT,
                org_id TEXT, team_id TEXT, user_id TEXT, visibility TEXT,
                created_at TEXT, updated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tickets_assignee ON tickets(assignee_type, assignee_id);
            CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
            CREATE INDEX IF NOT EXISTS idx_tickets_scope ON tickets(org_id, team_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_triggers_agent ON triggers(agent_id);
            CREATE INDEX IF NOT EXISTS idx_evidence_ticket ON evidence_packs(ticket_id);
            """
        )


# ── generic dataclass <-> row mapping ─────────────────────────────────────────
def _encode(obj: Any) -> Dict[str, Any]:
    cls = type(obj)
    json_fields = _JSON_FIELDS.get(cls, set())
    bool_fields = _BOOL_FIELDS.get(cls, set())
    out: Dict[str, Any] = {}
    for f in dc_fields(obj):
        val = getattr(obj, f.name)
        if f.name in json_fields:
            out[f.name] = json.dumps(val)
        elif f.name in bool_fields:
            out[f.name] = 1 if val else 0
        else:
            out[f.name] = val
    return out


def _decode(cls: Type[T], row: sqlite3.Row) -> T:
    json_fields = _JSON_FIELDS.get(cls, set())
    bool_fields = _BOOL_FIELDS.get(cls, set())
    valid = {f.name for f in dc_fields(cls)}
    d: Dict[str, Any] = {}
    for k, v in dict(row).items():
        if k not in valid:
            continue
        if k in json_fields:
            d[k] = json.loads(v) if v else ([] if k != "config" else {})
        elif k in bool_fields:
            d[k] = bool(v)
        else:
            d[k] = v
    return cls(**d)  # type: ignore[arg-type]


def _broadcast(table: str, obj: Any, op: str) -> None:
    """Stream a mutation to connected boards (best-effort, never raises)."""
    try:
        from creation.work import events

        fields = {"entity": table, "id": getattr(obj, "id", ""), "op": op}
        if hasattr(obj, "status"):
            fields["status"] = obj.status
        events.emit("work.update", **fields)
    except Exception:
        pass


def _insert(obj: Any) -> Any:
    init_work_db()
    table = _TABLE[type(obj)]
    data = _encode(obj)
    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    with _conn() as c:
        c.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", tuple(data.values()))
    _broadcast(table, obj, "insert")
    return obj


def _update(obj: Any) -> Any:
    init_work_db()
    table = _TABLE[type(obj)]
    if hasattr(obj, "updated_at"):
        obj.updated_at = now_iso()
    data = _encode(obj)
    oid = data.pop("id")
    sets = ", ".join(f"{k}=?" for k in data)
    with _conn() as c:
        c.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*data.values(), oid))
    _broadcast(table, obj, "update")
    return obj


def _get(cls: Type[T], oid: str) -> Optional[T]:
    init_work_db()
    table = _TABLE[cls]
    with _conn() as c:
        r = c.execute(f"SELECT * FROM {table} WHERE id=?", (oid,)).fetchone()
    return _decode(cls, r) if r else None


# ── Tickets ───────────────────────────────────────────────────────────────────
def create_ticket(ticket: Ticket) -> Ticket:
    return _insert(ticket)


def get_ticket(tid: str) -> Optional[Ticket]:
    return _get(Ticket, tid)


def update_ticket(ticket: Ticket) -> Ticket:
    return _update(ticket)


def list_tickets(
    *,
    status: Optional[str] = None,
    assignee_id: Optional[str] = None,
    assignee_type: Optional[str] = None,
    mission_id: Optional[str] = None,
    user_id: Optional[str] = None,
    team_id: Optional[str] = None,
    repo: Optional[str] = None,
) -> List[Ticket]:
    init_work_db()
    clauses, args = [], []
    for col, val in [
        ("status", status),
        ("assignee_id", assignee_id),
        ("assignee_type", assignee_type),
        ("mission_id", mission_id),
        ("user_id", user_id),
        ("team_id", team_id),
        ("repo", repo),
    ]:
        if val is not None:
            clauses.append(f"{col}=?")
            args.append(val)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _conn() as c:
        rows = c.execute(f"SELECT * FROM tickets {where} ORDER BY created_at DESC", tuple(args)).fetchall()
    return [_decode(Ticket, r) for r in rows]


def list_repos(*, user_id: Optional[str] = None, team_id: Optional[str] = None) -> List[str]:
    """Distinct non-empty project repos across tickets — drives the board's project filter."""
    init_work_db()
    clauses, args = ["repo IS NOT NULL", "repo != ''"], []
    for col, val in [("user_id", user_id), ("team_id", team_id)]:
        if val is not None:
            clauses.append(f"{col}=?")
            args.append(val)
    where = f"WHERE {' AND '.join(clauses)}"
    with _conn() as c:
        rows = c.execute(f"SELECT DISTINCT repo FROM tickets {where} ORDER BY repo ASC", tuple(args)).fetchall()
    return [r["repo"] for r in rows]


def delete_ticket(tid: str) -> bool:
    """Remove a ticket and its evidence. Returns True if a ticket was deleted."""
    init_work_db()
    existing = get_ticket(tid)
    with _conn() as c:
        c.execute("DELETE FROM evidence_packs WHERE ticket_id=?", (tid,))
        cur = c.execute("DELETE FROM tickets WHERE id=?", (tid,))
        deleted = cur.rowcount > 0
    if deleted and existing is not None:
        _broadcast("tickets", existing, "delete")
    return deleted


def assign_ticket(tid: str, *, assignee_type: str, assignee_id: str) -> Optional[Ticket]:
    t = get_ticket(tid)
    if not t:
        return None
    t.assignee_type = assignee_type  # type: ignore[assignment]
    t.assignee_id = assignee_id
    return _update(t)


def set_ticket_status(tid: str, status: str) -> Optional[Ticket]:
    t = get_ticket(tid)
    if not t:
        return None
    t.status = status  # type: ignore[assignment]
    return _update(t)


def link_run_to_ticket(tid: str, run_id: str) -> Optional[Ticket]:
    t = get_ticket(tid)
    if not t:
        return None
    if run_id not in t.run_ids:
        t.run_ids.append(run_id)
    return _update(t)


# ── Agents ──────────────────────────────────────────────────────────────────--
def create_agent(agent: AgentDef) -> AgentDef:
    return _insert(agent)


def get_agent(aid: str) -> Optional[AgentDef]:
    return _get(AgentDef, aid)


def update_agent(agent: AgentDef) -> AgentDef:
    return _update(agent)


def delete_agent(aid: str) -> bool:
    """Remove an agent. Returns True if one was deleted. Does not touch its tickets."""
    init_work_db()
    existing = get_agent(aid)
    with _conn() as c:
        c.execute("DELETE FROM triggers WHERE agent_id=?", (aid,))
        cur = c.execute("DELETE FROM agents WHERE id=?", (aid,))
        deleted = cur.rowcount > 0
    if deleted and existing is not None:
        _broadcast("agents", existing, "delete")
    return deleted


def list_agents(
    *, bench_type: Optional[str] = None, user_id: Optional[str] = None, team_id: Optional[str] = None
) -> List[AgentDef]:
    init_work_db()
    clauses, args = [], []
    for col, val in [("bench_type", bench_type), ("user_id", user_id), ("team_id", team_id)]:
        if val is not None:
            clauses.append(f"{col}=?")
            args.append(val)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _conn() as c:
        rows = c.execute(f"SELECT * FROM agents {where} ORDER BY created_at DESC", tuple(args)).fetchall()
    return [_decode(AgentDef, r) for r in rows]


# ── Triggers ──────────────────────────────────────────────────────────────────
def create_trigger(trigger: Trigger) -> Trigger:
    return _insert(trigger)


def get_trigger(trid: str) -> Optional[Trigger]:
    return _get(Trigger, trid)


def update_trigger(trigger: Trigger) -> Trigger:
    return _update(trigger)


def list_triggers(*, agent_id: Optional[str] = None, kind: Optional[str] = None, enabled_only: bool = False) -> List[Trigger]:
    init_work_db()
    clauses, args = [], []
    if agent_id is not None:
        clauses.append("agent_id=?")
        args.append(agent_id)
    if kind is not None:
        clauses.append("kind=?")
        args.append(kind)
    if enabled_only:
        clauses.append("enabled=1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _conn() as c:
        rows = c.execute(f"SELECT * FROM triggers {where} ORDER BY created_at ASC", tuple(args)).fetchall()
    return [_decode(Trigger, r) for r in rows]


def mark_trigger_fired(trid: str) -> None:
    init_work_db()
    with _conn() as c:
        c.execute("UPDATE triggers SET last_fired_at=? WHERE id=?", (now_iso(), trid))


# ── Evidence packs ──────────────────────────────────────────────────────────--
def create_evidence(pack: EvidencePack) -> EvidencePack:
    return _insert(pack)


def get_evidence(eid: str) -> Optional[EvidencePack]:
    return _get(EvidencePack, eid)


def list_evidence_for_ticket(ticket_id: str) -> List[EvidencePack]:
    init_work_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM evidence_packs WHERE ticket_id=? ORDER BY created_at DESC", (ticket_id,)
        ).fetchall()
    return [_decode(EvidencePack, r) for r in rows]


# ── Missions ────────────────────────────────────────────────────────────────--
def create_mission(mission: Mission) -> Mission:
    return _insert(mission)


def get_mission(mid: str) -> Optional[Mission]:
    return _get(Mission, mid)


def update_mission(mission: Mission) -> Mission:
    return _update(mission)


def list_missions(*, team_id: Optional[str] = None, status: Optional[str] = None) -> List[Mission]:
    init_work_db()
    clauses, args = [], []
    if team_id is not None:
        clauses.append("team_id=?")
        args.append(team_id)
    if status is not None:
        clauses.append("status=?")
        args.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _conn() as c:
        rows = c.execute(f"SELECT * FROM missions {where} ORDER BY created_at DESC", tuple(args)).fetchall()
    return [_decode(Mission, r) for r in rows]


def mission_tickets(mission_id: str) -> List[Ticket]:
    return list_tickets(mission_id=mission_id)
