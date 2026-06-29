"""Mem0 backend — hosted semantic memory, pairs with SuperCompress.

Mem0 stores and recalls semantic facts across runs (user, project, agent
scope). SuperCompress then trims the merged context window before each turn.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from creation.config import UserSecrets
from creation.memory.base import (
    AGENT_ID,
    DEMO_MEMORIES,
    MemoryBridge,
    MemoryRecall,
    extract_memory_text,
)

logger = logging.getLogger(__name__)

# Back-compat alias — callers and tests import Mem0Recall from here.
Mem0Recall = MemoryRecall


class Mem0Bridge(MemoryBridge):
    """Hosted Mem0 client with demo fallback when no API key is configured."""

    name = "mem0"

    def __init__(self, secrets: UserSecrets, *, demo: bool = False):
        super().__init__(secrets, demo=demo or not secrets.mem0_api_key.strip())
        self._client: Any = None

    def available(self) -> bool:
        return bool(self.secrets.mem0_api_key.strip())

    @property
    def enabled(self) -> bool:
        if not self.secrets.mem0_enabled:
            return False
        return self.demo or self.available()

    def _client_or_none(self) -> Any:
        if self.demo or not self.secrets.mem0_api_key.strip():
            return None
        if self._client is not None:
            return self._client
        try:
            from mem0 import MemoryClient
        except ImportError:
            logger.warning("mem0ai not installed — Mem0 recall disabled")
            return None
        try:
            self._client = MemoryClient(api_key=self.secrets.mem0_api_key.strip())
        except Exception as exc:
            logger.warning("Mem0 client init failed: %s", exc)
            return None
        return self._client

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

        client = self._client_or_none()
        if client is None:
            return MemoryRecall(query=query, enabled=False, provider=self.name)

        filters: Dict[str, str] = {"user_id": self._user_id()}
        if project_id:
            filters["run_id"] = project_id
        try:
            raw = client.search(query, filters=filters, top_k=limit)
        except Exception as exc:
            logger.warning("Mem0 search failed: %s", exc)
            return MemoryRecall(query=query, enabled=True, provider=self.name)

        items = raw if isinstance(raw, list) else raw.get("results", []) if isinstance(raw, dict) else []
        memories: List[str] = []
        for item in items:
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

        client = self._client_or_none()
        if client is None:
            return False

        kwargs: Dict[str, Any] = {
            "user_id": self._user_id(),
            "agent_id": AGENT_ID,
            "metadata": metadata or {},
        }
        if project_id:
            kwargs["run_id"] = project_id
        if run_id:
            kwargs["metadata"] = {**(metadata or {}), "creation_run_id": run_id}
        try:
            client.add(messages, **kwargs)
            return True
        except Exception as exc:
            logger.warning("Mem0 add failed: %s", exc)
            return False
