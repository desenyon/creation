"""Manual takeover — user messages queued during an active build run."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from creation.store import DB_PATH, ensure_dirs

_lock = threading.Lock()
_table_ready = False


def _conn() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_messages_table() -> None:
    global _table_ready
    if _table_ready:
        return
    with _lock:
        if _table_ready:
            return
        with _conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS run_messages (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    consumed_turn INTEGER
                );
                """
            )
        _table_ready = True


def add_message(run_id: str, text: str) -> Dict[str, Any]:
    """Queue a user steering message for the next agent turn."""
    ensure_messages_table()
    body = text.strip()
    if not body:
        raise ValueError("Message cannot be empty")
    msg_id = uuid.uuid4().hex[:12]
    created = _ts()
    with _lock:
        with _conn() as c:
            c.execute(
                """
                INSERT INTO run_messages (id, run_id, text, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (msg_id, run_id, body, created),
            )
    return {
        "id": msg_id,
        "run_id": run_id,
        "text": body,
        "status": "pending",
        "created_at": created,
    }


def drain_for_turn(run_id: str, turn: int) -> List[Dict[str, Any]]:
    """Return pending messages and mark them consumed for this turn."""
    ensure_messages_table()
    with _lock:
        with _conn() as c:
            rows = c.execute(
                """
                SELECT id, run_id, text, status, created_at, consumed_turn
                FROM run_messages
                WHERE run_id = ? AND status = 'pending'
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
            if not rows:
                return []
            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" * len(ids))
            c.execute(
                f"""
                UPDATE run_messages
                SET status = 'consumed', consumed_turn = ?
                WHERE id IN ({placeholders})
                """,
                [turn, *ids],
            )
    return [
        {
            "id": r["id"],
            "run_id": r["run_id"],
            "text": r["text"],
            "status": "consumed",
            "created_at": r["created_at"],
            "consumed_turn": turn,
        }
        for r in rows
    ]


def list_messages(run_id: str) -> List[Dict[str, Any]]:
    ensure_messages_table()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT id, run_id, text, status, created_at, consumed_turn
            FROM run_messages
            WHERE run_id = ?
            ORDER BY created_at ASC
            """,
            (run_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "run_id": r["run_id"],
            "text": r["text"],
            "status": r["status"],
            "created_at": r["created_at"],
            "consumed_turn": r["consumed_turn"],
        }
        for r in rows
    ]


def to_context_block(messages: List[Dict[str, Any]]) -> str:
    if not messages:
        return ""
    lines = ["## Manual takeover (user steering — prioritize when reasonable)"]
    for msg in messages:
        lines.append(f"- {msg['text']}")
    lines.append("Incorporate the user guidance above in this turn alongside the routed plan.")
    return "\n".join(lines)


def steering_summary(messages: List[Dict[str, Any]]) -> str:
    if not messages:
        return ""
    parts = [m["text"] for m in messages]
    return "User steering (manual takeover): " + " | ".join(parts)
