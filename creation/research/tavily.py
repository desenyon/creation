"""Tavily shim — use Creation Lens instead."""

from __future__ import annotations

from creation.services.lens.search import LensBundle as TavilyBundle
from creation.services.lens.search import LensSearch as TavilyResearch
from creation.services.lens.search import SearchHit

__all__ = ["TavilyResearch", "TavilyBundle", "SearchHit"]
