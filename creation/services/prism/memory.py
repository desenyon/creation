"""Prism — local episodic memory."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from creation.config import UserSecrets
from creation.memory.base import DEMO_MEMORIES, MemoryBridge, MemoryRecall, provider_label

PRISM_DB = Path.home() / ".creation" / "prism.db"


class PrismMemory(MemoryBridge):
    name = "prism"

    def __init__(self, secrets: UserSecrets, *, demo: bool = False):
        super().__init__(secrets, demo=demo)
        PRISM_DB.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(PRISM_DB)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT DEFAULT '',
                    content TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def available(self) -> bool:
        return True

    @property
    def enabled(self) -> bool:
        return self.secrets.memory_provider != "off"

    def recall(
        self, query: str, *, project_id: str = "", run_id: str = "", limit: int = 8
    ) -> MemoryRecall:
        if self.demo:
            return MemoryRecall(
                query=query,
                memories=DEMO_MEMORIES[:limit],
                enabled=True,
                demo=True,
                provider=self.name,
            )
        tokens = [t for t in re.findall(r"[a-z0-9]{3,}", query.lower())][:8]
        if not tokens:
            return MemoryRecall(query=query, enabled=self.enabled, provider=self.name)
        clauses = " OR ".join("content LIKE ?" for _ in tokens)
        params: List[Any] = [f"%{t}%" for t in tokens]
        sql = f"SELECT content FROM memories WHERE project_id = ? AND ({clauses}) ORDER BY id DESC LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(sql, [project_id, *params, limit]).fetchall()
        items = [r[0] for r in rows]
        return MemoryRecall(
            query=query,
            memories=items,
            enabled=self.enabled,
            provider=self.name,
        )

    def store_messages(
        self,
        messages: List[Dict[str, str]],
        *,
        project_id: str = "",
        run_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        text = "\n".join(m.get("content", "") for m in messages if m.get("content"))
        if not text.strip():
            return False
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memories (project_id, content) VALUES (?, ?)",
                (project_id, text.strip()[:4000]),
            )
        return True

    def status(self) -> Dict[str, Any]:
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        return {"provider": "prism", "enabled": self.enabled, "stored": count}


def build_prism_bridge(secrets: UserSecrets, *, demo: bool = False) -> MemoryBridge:
    if secrets.memory_provider == "off":
        from creation.memory.base import DisabledBridge

        return DisabledBridge(secrets, demo=demo)
    return PrismMemory(secrets, demo=demo)


def memory_status(secrets: UserSecrets, *, demo: bool = False) -> Dict[str, Any]:
    bridge = build_prism_bridge(secrets, demo=demo)
    base = {
        "setting": secrets.memory_provider,
        "resolved": resolve_provider(secrets),
        "label": provider_label(resolve_provider(secrets)),
        "enabled": bridge.enabled,
        "available": {"prism": True},
    }
    if hasattr(bridge, "status"):
        base.update(bridge.status())  # type: ignore[union-attr]
    return base


def available_providers(secrets: UserSecrets) -> Dict[str, bool]:
    return {"prism": True}


def resolve_provider(secrets: UserSecrets) -> str:
    return "off" if secrets.memory_provider == "off" else "prism"
