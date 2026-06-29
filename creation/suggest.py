"""Autosuggest — ranked product ideas before running the factory loop."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List

from creation.config import UserSecrets
from creation.research.tavily import TavilyBundle, TavilyResearch

logger = logging.getLogger(__name__)

SUGGEST_SYSTEM = """You propose shippable software products for an autonomous factory.
Given Tavily market research, output JSON only — an array of exactly 3 ideas:
[
  {
    "title": "short product name",
    "idea": "one-sentence build scope",
    "pitch": "2 sentences: why now + who it's for",
    "score": 0.0-1.0,
    "signals": ["market signal 1", "signal 2"]
  }
]

Prefer CLI tools, dev tools, and micro-SaaS a solo builder can ship in <30 turns.
Score higher when research cites clear demand and feasible scope."""


@dataclass
class IdeaSuggestion:
    title: str
    idea: str
    pitch: str = ""
    score: float = 0.5
    signals: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "idea": self.idea,
            "pitch": self.pitch,
            "score": round(self.score, 2),
            "signals": self.signals,
        }


def _parse_suggestions(raw: str) -> List[IdeaSuggestion]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            return []
        data = json.loads(m.group())
    if not isinstance(data, list):
        return []
    out: List[IdeaSuggestion] = []
    for item in data[:5]:
        if not isinstance(item, dict):
            continue
        out.append(
            IdeaSuggestion(
                title=str(item.get("title") or "Untitled")[:80],
                idea=str(item.get("idea") or "")[:500],
                pitch=str(item.get("pitch") or "")[:600],
                score=min(1.0, max(0.0, float(item.get("score") or 0.5))),
                signals=[str(s)[:120] for s in (item.get("signals") or [])[:4] if s],
            )
        )
    return out


def _demo_suggestions(seed: str) -> List[IdeaSuggestion]:
    base = seed.strip() or "developer automation"
    return [
        IdeaSuggestion(
            title="ShipCLI",
            idea=f"A CLI that automates repetitive workflows around {base}",
            pitch="Developers waste hours on glue scripts. A focused CLI with Composio hooks ships fast and has clear distribution on GitHub.",
            score=0.88,
            signals=["Dev tooling TAM", "CLI distribution"],
        ),
        IdeaSuggestion(
            title="LocalSync",
            idea=f"Offline-first sync layer for teams working on {base}",
            pitch="Remote teams need local-first tools that sync when online. SQLite + markdown export is buildable in one factory run.",
            score=0.79,
            signals=["Local-first trend", "Low infra cost"],
        ),
        IdeaSuggestion(
            title="AuditKit",
            idea=f"Automated audit reports and dashboards for {base} metrics",
            pitch="Compliance and observability budgets are growing. A read-only audit CLI with HTML export fits the factory QA loop.",
            score=0.72,
            signals=["Observability spend", "Report automation"],
        ),
    ]


def suggest_products(
    secrets: UserSecrets,
    seed: str = "",
    *,
    demo: bool = False,
    count: int = 3,
) -> tuple[List[IdeaSuggestion], TavilyBundle]:
    bundle = TavilyResearch(secrets, demo=demo).search_ideas(seed)
    if demo or not secrets.nebius_api_key.strip():
        return _demo_suggestions(seed)[:count], bundle

    from creation.nebius_client import _client

    merged = bundle.to_context_block()[:12000]
    client = _client(secrets)
    try:
        resp = client.chat.completions.create(
            model=secrets.nebius_model,
            messages=[
                {"role": "system", "content": SUGGEST_SYSTEM},
                {
                    "role": "user",
                    "content": f"Seed topic: {seed or '(open — pick from research)'}\n\nResearch:\n{merged}",
                },
            ],
            max_tokens=900,
        )
        raw = (resp.choices[0].message.content or "").strip()
        ideas = _parse_suggestions(raw)
    except Exception:
        logger.exception("suggest_products failed")
        ideas = []

    if not ideas:
        ideas = _demo_suggestions(seed)
    return ideas[:count], bundle
