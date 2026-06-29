"""Memory backend — Prism local memory only."""

from __future__ import annotations

from typing import Dict

from creation.config import UserSecrets
from creation.memory.base import DisabledBridge, MemoryBridge, provider_label
from creation.services.prism.memory import (
    PrismMemory,
    available_providers,
    build_prism_bridge,
    memory_status,
    resolve_provider,
)

PROVIDERS = {"prism": PrismMemory}


def build_memory_bridge(secrets: UserSecrets, *, demo: bool = False) -> MemoryBridge:
    if resolve_provider(secrets) == "off":
        return DisabledBridge(secrets, demo=demo)
    return build_prism_bridge(secrets, demo=demo)


__all__ = [
    "build_memory_bridge",
    "memory_status",
    "resolve_provider",
    "available_providers",
    "provider_label",
    "PROVIDERS",
]
