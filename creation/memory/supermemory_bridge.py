"""Supermemory backend — hosted memory API (https://api.supermemory.ai).

Uses the documented v3 REST endpoints over httpx so no extra SDK dependency is
required. Every network call fails closed: on any error recall returns an
enabled-but-empty result and store returns False, so a memory outage never
breaks a build turn.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from creation.config import UserSecrets
from creation.memory.base import (
    DEMO_MEMORIES,
    MemoryBridge,
    MemoryRecall,
    extract_memory_text,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.supermemory.ai/v3"
TIMEOUT = 20.0


class SupermemoryBridge(MemoryBridge):
    """Supermemory client with demo fallback when no API key is configured."""

    name = "supermemory"

    def __init__(self, secrets: UserSecrets, *, demo: bool = False):
        super().__init__(secrets, demo=demo or not secrets.supermemory_api_key.strip())

    def available(self) -> bool:
        return bool(self.secrets.supermemory_api_key.strip())

    @property
    def enabled(self) -> bool:
        return self.demo or self.available()

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.secrets.supermemory_api_key.strip()}",
            "Content-Type": "application/json",
        }

    def _container(self, project_id: str = "") -> str:
        """Container tag scopes memories — per project, falling back to user."""
        return f"creation-{project_id}" if project_id else self._user_id()

    def recall(
        self, query: str, *, project_id: str = "", run_id: str = "", limit: int = 8
    ) -> MemoryRecall:
        if not self.enabled:
            return MemoryRecall(query=query, enabled=False, provider=self.name)
        if self.demo:
            hits = DEMO_MEMORIES[: min(limit, len(DEMO_MEMORIES))]
            return MemoryRecall(
                query=query, memories=hits, enabled=True, demo=True, provider=self.name
            )

        try:
            resp = httpx.post(
                f"{BASE_URL}/search",
                headers=self._headers(),
                json={
                    "q": query,
                    "containerTags": [self._container(project_id)],
                    "limit": limit,
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("Supermemory search failed: %s", exc)
            return MemoryRecall(query=query, enabled=True, provider=self.name)

        results = data.get("results") or data.get("memories") or []
        memories: List[str] = []
        for item in results:
            text = extract_memory_text(item)
            if text:
                memories.append(text)
        return MemoryRecall(
            query=query, memories=memories[:limit], enabled=True, provider=self.name
        )

    def store_messages(
        self,
        messages: List[Dict[str, str]],
        *,
        project_id: str = "",
        run_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.enabled or not messages:
            return False
        if self.demo:
            return True

        content = "\n".join(
            f"{m.get('role', '')}: {m.get('content', '')}".strip() for m in messages
        ).strip()
        if not content:
            return False

        meta = {**(metadata or {})}
        if run_id:
            meta["creation_run_id"] = run_id
        try:
            resp = httpx.post(
                f"{BASE_URL}/documents",
                headers=self._headers(),
                json={
                    "content": content,
                    "containerTag": self._container(project_id),
                    "metadata": meta,
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Supermemory add failed: %s", exc)
            return False
