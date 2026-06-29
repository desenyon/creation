"""Playbook memory — agents learn from every run so they stop repeating mistakes.

After a run, the worker distills a lesson from its EvidencePack (especially risks and
blocks) into a scoped, queryable store. Before the next run, relevant lessons are
injected into the prompt. This is the local-first seed of future.md's Company Memory
Graph: flat today, graph-shaped later, but already closing the learning loop.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from creation.store import _conn
from creation.work.models import LOCAL_ORG, LOCAL_USER, EvidencePack, Ticket, new_id, now_iso


@dataclass
class Lesson:
    id: str = field(default_factory=lambda: new_id("lsn_"))
    kind: str = "code"  # agent kind this lesson is most relevant to
    repo: str = ""
    title: str = ""
    lesson: str = ""
    outcome: str = ""  # done | blocked | in_review
    source_ticket: str = ""
    source_run: str = ""
    org_id: str = LOCAL_ORG
    team_id: Optional[str] = None
    user_id: Optional[str] = LOCAL_USER
    created_at: str = field(default_factory=now_iso)


def init_playbook_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS playbook_lessons (
                id TEXT PRIMARY KEY,
                kind TEXT, repo TEXT, title TEXT, lesson TEXT, outcome TEXT,
                source_ticket TEXT, source_run TEXT,
                org_id TEXT, team_id TEXT, user_id TEXT,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_playbook_kind ON playbook_lessons(kind);
            CREATE INDEX IF NOT EXISTS idx_playbook_repo ON playbook_lessons(repo);
            """
        )


def add_lesson(lesson: Lesson) -> Lesson:
    init_playbook_db()
    with _conn() as c:
        c.execute(
            "INSERT INTO playbook_lessons (id,kind,repo,title,lesson,outcome,source_ticket,source_run,org_id,team_id,user_id,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                lesson.id, lesson.kind, lesson.repo, lesson.title, lesson.lesson, lesson.outcome,
                lesson.source_ticket, lesson.source_run, lesson.org_id, lesson.team_id,
                lesson.user_id, lesson.created_at,
            ),
        )
    return lesson


def _row(r: sqlite3.Row) -> Lesson:
    return Lesson(**{k: v for k, v in dict(r).items() if k in Lesson.__dataclass_fields__})


def delete_lesson(lid: str) -> bool:
    """Remove a lesson from memory. Returns True if one was deleted."""
    init_playbook_db()
    with _conn() as c:
        cur = c.execute("DELETE FROM playbook_lessons WHERE id=?", (lid,))
        return cur.rowcount > 0


def add_manual_lesson(
    *, lesson: str, kind: str = "code", repo: str = "", title: str = ""
) -> Lesson:
    """Let a human teach Creation directly — a memory the agents will read on future runs."""
    return add_lesson(
        Lesson(
            kind=kind or "code",
            repo=repo,
            title=(title or lesson[:120]),
            lesson=lesson.strip()[:1000],
            outcome="human",
        )
    )


def record_from_evidence(
    evidence: EvidencePack, ticket: Ticket, agent_kind: str, outcome: str
) -> Optional[Lesson]:
    """Distill a lesson from a run. Only records when there is real signal.

    Captures explicit risks, and any blocked outcome (the highest-value lessons are
    the failures an agent should not repeat).
    """
    notes: List[str] = []
    if evidence.risks:
        notes.append("Risks flagged: " + "; ".join(evidence.risks))
    if outcome == "blocked":
        tail = (evidence.reasoning_summary or "").strip().splitlines()[-3:]
        notes.append("Run was blocked. Tail: " + " ".join(tail) if tail else "Run was blocked.")
    if not notes:
        return None

    lesson = Lesson(
        kind=agent_kind,
        repo=ticket.repo,
        title=ticket.title[:120],
        lesson=" ".join(notes)[:1000],
        outcome=outcome,
        source_ticket=ticket.id,
        source_run=evidence.run_id,
        org_id=ticket.org_id,
        team_id=ticket.team_id,
        user_id=ticket.user_id,
    )
    return add_lesson(lesson)


def relevant_lessons(ticket: Ticket, agent_kind: str, *, limit: int = 5) -> List[Lesson]:
    """Lessons most relevant to this ticket: same repo or same agent kind, in scope."""
    init_playbook_db()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT * FROM playbook_lessons
            WHERE (repo = ? AND repo != '') OR kind = ?
            ORDER BY
              CASE WHEN repo = ? AND repo != '' THEN 0 ELSE 1 END,
              CASE WHEN outcome = 'blocked' THEN 0 ELSE 1 END,
              created_at DESC
            LIMIT ?
            """,
            (ticket.repo, agent_kind, ticket.repo, limit),
        ).fetchall()
    return [_row(r) for r in rows]


def lessons_block(lessons: List[Lesson]) -> str:
    """Render lessons as a prompt section. Empty string when there are none."""
    if not lessons:
        return ""
    lines = ["## Playbook — lessons from past runs (avoid repeating these)"]
    for ls in lessons:
        prefix = "⚠ " if ls.outcome == "blocked" else "• "
        lines.append(f"{prefix}{ls.lesson}")
    return "\n".join(lines)


def list_lessons(*, kind: Optional[str] = None, repo: Optional[str] = None, limit: int = 100) -> List[Lesson]:
    init_playbook_db()
    clauses, args = [], []
    if kind is not None:
        clauses.append("kind=?")
        args.append(kind)
    if repo is not None:
        clauses.append("repo=?")
        args.append(repo)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM playbook_lessons {where} ORDER BY created_at DESC LIMIT ?", (*args, limit)
        ).fetchall()
    return [_row(r) for r in rows]


def lesson_dicts(**kwargs: Any) -> List[Dict[str, Any]]:
    return [asdict(ls) for ls in list_lessons(**kwargs)]
