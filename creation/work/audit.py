"""Audit log — append-only record of who/what did what.

Every governance-relevant action (assignment, run, approval, rejection, trigger
fired, policy block) lands here. This is the spine of enterprise trust: a complete,
queryable history scoped per tenant. Reuses the shared ``creation.db``.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from creation.store import _conn
from creation.work.models import LOCAL_ORG, LOCAL_USER, new_id, now_iso


@dataclass
class AuditEvent:
    id: str = field(default_factory=lambda: new_id("aud_"))
    actor: str = LOCAL_USER  # user id or agent id
    actor_type: str = "user"  # user | agent | system
    action: str = ""  # e.g. ticket.assigned, run.completed, ticket.approved
    entity_type: str = ""  # ticket | agent | mission | trigger | run
    entity_id: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)
    org_id: str = LOCAL_ORG
    team_id: Optional[str] = None
    user_id: Optional[str] = LOCAL_USER
    created_at: str = field(default_factory=now_iso)


def init_audit_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                actor TEXT, actor_type TEXT,
                action TEXT, entity_type TEXT, entity_id TEXT,
                detail TEXT,
                org_id TEXT, team_id TEXT, user_id TEXT,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(entity_type, entity_id);
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action);
            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at);
            """
        )


def record(
    action: str,
    entity_type: str,
    entity_id: str,
    *,
    actor: str = LOCAL_USER,
    actor_type: str = "user",
    detail: Optional[Dict[str, Any]] = None,
    org_id: str = LOCAL_ORG,
    team_id: Optional[str] = None,
    user_id: Optional[str] = LOCAL_USER,
) -> AuditEvent:
    init_audit_db()
    ev = AuditEvent(
        actor=actor,
        actor_type=actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail or {},
        org_id=org_id,
        team_id=team_id,
        user_id=user_id,
    )
    with _conn() as c:
        c.execute(
            "INSERT INTO audit_events (id,actor,actor_type,action,entity_type,entity_id,detail,org_id,team_id,user_id,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                ev.id, ev.actor, ev.actor_type, ev.action, ev.entity_type, ev.entity_id,
                json.dumps(ev.detail), ev.org_id, ev.team_id, ev.user_id, ev.created_at,
            ),
        )
    return ev


def _row(r: sqlite3.Row) -> AuditEvent:
    d = dict(r)
    d["detail"] = json.loads(d.get("detail") or "{}")
    return AuditEvent(**{k: v for k, v in d.items() if k in AuditEvent.__dataclass_fields__})


def list_events(
    *,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 100,
) -> List[AuditEvent]:
    init_audit_db()
    clauses, args = [], []
    for col, val in [("entity_type", entity_type), ("entity_id", entity_id), ("action", action)]:
        if val is not None:
            clauses.append(f"{col}=?")
            args.append(val)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM audit_events {where} ORDER BY created_at DESC LIMIT ?",
            (*args, limit),
        ).fetchall()
    return [_row(r) for r in rows]


def event_dicts(**kwargs: Any) -> List[Dict[str, Any]]:
    return [asdict(e) for e in list_events(**kwargs)]
