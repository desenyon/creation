"""Pluggable persistent-memory backend interface.

Creation supports more than one memory stack so users who already run mem0 or
Supermemory keep their own setup. Every backend implements the same small
surface the orchestrator needs: ``recall`` before a turn, ``store_*`` after a
turn, an ``enabled`` flag, and an ``available()`` probe used by ``creation doctor``
and the ``auto`` provider selector.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from creation.config import UserSecrets

logger = logging.getLogger(__name__)

AGENT_ID = "creation-orchestrator"

# Used by every backend in demo mode so the dashboard shows recall working
# without live keys.
DEMO_MEMORIES = [
    "Prefer pytest for Python projects; run tests before shipping.",
    "Push all source files each turn — not just markdown logs.",
    "When tests fail, fix the named failure before adding features.",
    "Small shippable increments map cleanly to Linear plan steps.",
]

# Human labels per provider id, reused for context headings and doctor output.
PROVIDER_LABELS = {
    "prism": "Prism",
    "off": "Off",
}


def provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider.title() or "Memory")


def extract_memory_text(item: Any) -> str:
    """Pull a memory string out of the varied shapes backends return."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("memory", "text", "content", "summary", "data", "title"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        # Supermemory-style chunked results.
        chunks = item.get("chunks")
        if isinstance(chunks, list):
            joined = " ".join(
                c.get("content", "") for c in chunks if isinstance(c, dict)
            ).strip()
            if joined:
                return joined
    return ""


@dataclass
class MemoryRecall:
    """Result of a recall — provider-agnostic."""

    query: str
    memories: List[str] = field(default_factory=list)
    enabled: bool = False
    demo: bool = False
    provider: str = "mem0"

    @property
    def count(self) -> int:
        return len(self.memories)


class MemoryBridge:
    """Base class for memory backends.

    Subclasses override ``available``, ``enabled``, ``recall`` and
    ``store_messages``. ``store_turn``/``store_setup`` and ``to_context_block``
    are shared because they only format text and delegate.
    """

    #: provider id, matches the keys in ``config.memory_provider``.
    name = "memory"

    def __init__(self, secrets: UserSecrets, *, demo: bool = False):
        self.secrets = secrets
        self.demo = demo

    # ── probing / state (override) ────────────────────────────────────
    def available(self) -> bool:
        """True when this backend is configured/installed (ignores demo)."""
        return False

    @property
    def enabled(self) -> bool:
        """True when this backend will actually recall/store this run."""
        return False

    # ── core ops (override) ───────────────────────────────────────────
    def recall(
        self, query: str, *, project_id: str = "", run_id: str = "", limit: int = 8
    ) -> MemoryRecall:
        return MemoryRecall(query=query, enabled=False, provider=self.name)

    def store_messages(
        self,
        messages: List[Dict[str, str]],
        *,
        project_id: str = "",
        run_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return False

    # ── shared helpers ────────────────────────────────────────────────
    def _user_id(self) -> str:
        return (self.secrets.composio_user_id or "creation-user").strip()

    def store_turn(
        self,
        *,
        project_id: str,
        run_id: str,
        turn: int,
        idea: str,
        reason: str,
        follow_up: str = "",
        qa_summary: str = "",
        agent_excerpt: str = "",
    ) -> bool:
        parts = [f"Turn {turn} on project {idea[:120]}:", f"Route: {reason[:300]}"]
        if follow_up:
            parts.append(f"Next task: {follow_up[:400]}")
        if qa_summary:
            parts.append(f"QA: {qa_summary[:400]}")
        if agent_excerpt:
            parts.append(f"Agent: {agent_excerpt[:500]}")
        content = "\n".join(parts)
        return self.store_messages(
            [
                {"role": "user", "content": f"What happened on turn {turn}?"},
                {"role": "assistant", "content": content},
            ],
            project_id=project_id,
            run_id=run_id,
            metadata={"turn": turn, "kind": "turn_lesson"},
        )

    def store_setup(
        self,
        *,
        project_id: str,
        run_id: str,
        idea: str,
        plan: str,
        product_name: str = "",
    ) -> bool:
        snippet = plan.strip()[:1200]
        content = f"Project kickoff — {idea}\nProduct: {product_name or idea}\nPlan:\n{snippet}"
        return self.store_messages(
            [
                {"role": "user", "content": f"Remember setup for {idea[:120]}"},
                {"role": "assistant", "content": content},
            ],
            project_id=project_id,
            run_id=run_id,
            metadata={"kind": "setup"},
        )

    @staticmethod
    def to_context_block(recall: MemoryRecall) -> str:
        if not recall.memories:
            return ""
        label = provider_label(recall.provider)
        lines = [f"## {label} recall (Prism memory — before compression)"]
        for mem in recall.memories:
            lines.append(f"- {mem}")
        return "\n".join(lines)


class DisabledBridge(MemoryBridge):
    """Used when ``memory_provider`` is ``off`` — no recall, no store."""

    name = "off"

    def available(self) -> bool:
        return False

    @property
    def enabled(self) -> bool:
        return False
