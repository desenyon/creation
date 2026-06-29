"""BuilderShip sponsor integration map — for Ship Receipt and showcase."""

from __future__ import annotations

from typing import Any, Dict, List

from creation.config import UserSecrets

SDK_TEMPLATE_SPONSORS = {
    "stripe-saas": ("Stripe", "Checkout + webhook scaffold"),
    "qdrant-rag": ("Qdrant", "Vector RAG scaffold"),
    "motherduck-analytics": ("MotherDuck", "DuckDB analytics scaffold"),
}


def build_sponsor_integrations(
    secrets: UserSecrets,
    *,
    template_id: str = "greenfield",
    memory: Dict[str, Any] | None = None,
    agents: List[str] | None = None,
    demo: bool = False,
    outcomes: Dict[str, Any] | None = None,
) -> List[Dict[str, str]]:
    """Integration ledger for the Ship Receipt.

    Honesty rule: an integration is only "live" when an action through it
    actually succeeded this run. Composio (GitHub/Linear/Gmail) is driven by
    ``outcomes``; research/memory toolkits run unconditionally during
    setup so they stay "live" in a real run.
    """
    mem = memory or {}
    out = outcomes or {}
    selected_agents = set(agents or [])
    mem0_on = bool(secrets.mem0_enabled and (demo or secrets.mem0_api_key.strip()))
    active = "demo" if demo else "live"

    # What actually happened through Composio this run.
    composio_actions = {
        "GitHub": bool(out.get("github_pushed") or out.get("github_repo")),
        "Linear": bool(out.get("linear_ok")),
        "Gmail": bool(out.get("gmail_ok")),
    }
    composio_live = demo or any(composio_actions.values())
    if demo:
        composio_detail = "GitHub · Linear · Gmail · Firecrawl"
    else:
        done = [name for name, ok in composio_actions.items() if ok]
        composio_detail = (" · ".join(f"{n} ✓" for n in done)) if done else "No action completed yet"

    rows: List[Dict[str, str]] = [
        {
            "sponsor": "OpenClaw",
            "integration": "Local agent runtime for build turns",
            "status": active if "openclaw" in selected_agents and not demo else "available",
        },
        {"sponsor": "Tavily", "integration": "Ideation + market search", "status": active},
        {"sponsor": "Firecrawl", "integration": "Deep scrape via Composio", "status": active},
        {"sponsor": "Mem0", "integration": "Persistent recall each turn", "status": active if mem0_on else "configured"},
        {"sponsor": "SuperCompress", "integration": "In-turn token eviction", "status": active},
        {
            "sponsor": "Nebius Token Factory",
            "integration": "Plan · brand · route (Llama 3.3 70B)",
            "status": active if secrets.nebius_api_key.strip() or demo else "pending",
        },
        {
            "sponsor": "Composio",
            "integration": composio_detail,
            "status": (
                active if composio_live else ("configured" if secrets.composio_api_key.strip() else "pending")
            ),
        },
    ]
    sdk = SDK_TEMPLATE_SPONSORS.get(template_id)
    if sdk:
        rows.append({"sponsor": sdk[0], "integration": sdk[1], "status": "sdk_template"})
    if mem.get("mem0_recalled"):
        rows[3]["integration"] = f"Recalled {mem['mem0_recalled']} memories"
    if mem.get("kv_savings_pct"):
        rows[4]["integration"] = f"{int(mem['kv_savings_pct'])}% KV saved last turn"
    return rows
