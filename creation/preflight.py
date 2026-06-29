"""Preflight gate — finish onboarding + ask clarifying questions before building.

Before a real build starts, Creation verifies the integrations it needs to ship
(GitHub, Linear, Gmail via Composio) are actually connected, and surfaces any
clarifying questions. When something is missing or ambiguous the run pauses,
emails the user, and waits for a reply (by email/Linear or the dashboard).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from creation.config import UserSecrets
from creation.integrations.composio_connections import ComposioConnectionManager

logger = logging.getLogger(__name__)

# Toolkits a live build needs to ship end-to-end. Firecrawl is research-only and
# degrades gracefully, so it never blocks the build.
REQUIRED_TOOLKITS = ("github", "linear", "gmail")

_CONNECT_HINT = "Open the Creation dashboard → Settings → Connect integrations."


def missing_integrations(secrets: UserSecrets) -> List[Dict[str, str]]:
    """Required Composio toolkits that are not connected yet.

    Returns a list of ``{toolkit, status, hint}`` dicts (empty when everything
    required is connected). Never raises — on lookup failure it returns [] so a
    transient Composio error doesn't wedge the build.
    """
    if not secrets.composio_api_key.strip():
        return [
            {"toolkit": t, "status": "NO_COMPOSIO_KEY", "hint": _CONNECT_HINT}
            for t in REQUIRED_TOOLKITS
        ]
    try:
        state = ComposioConnectionManager(secrets).status()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("preflight integration check failed: %s", exc)
        return []
    conns = state.get("connections", {}) if isinstance(state, dict) else {}
    missing: List[Dict[str, str]] = []
    for toolkit in REQUIRED_TOOLKITS:
        item = conns.get(toolkit) or {}
        if not item.get("connected"):
            missing.append(
                {
                    "toolkit": toolkit,
                    "status": str(item.get("status") or "NOT_CONNECTED"),
                    "hint": _CONNECT_HINT,
                }
            )
    return missing


def clarifying_questions(idea: str, *, secrets: UserSecrets, existing_repo: bool, demo: bool = False) -> List[str]:
    """Deterministic clarifying questions for an ambiguous or risky build.

    Kept simple and side-effect free: catches the common cases where Creation would
    otherwise guess (an extremely thin brief). The build can
    still proceed with safe defaults if these go unanswered.
    """
    questions: List[str] = []
    text = (idea or "").strip()

    if len(text) < 12:
        questions.append(
            "Your brief is very short — what should this project actually do, and who is it for?"
        )

    if existing_repo:
        questions.append(
            "I detected an existing repo. Should I extend it in place on a safety branch, or treat this as a fresh build?"
        )

    return questions


def build_needs_input_email(
    *,
    product: str,
    idea: str,
    missing: List[Dict[str, str]],
    questions: List[str],
    run_id: str,
) -> str:
    """Plain-text email body asking the user to finish setup / answer questions."""
    lines = [
        f"Creation paused the build for: {product or idea[:60]}",
        "",
        "Before I start, I need a couple of things from you. Just reply to this",
        "email (or comment on the Linear project) and I'll pick it up automatically.",
        "",
    ]
    if missing:
        lines.append("Missing integrations (please connect these):")
        for m in missing:
            lines.append(f"  • {m['toolkit'].title()} — {m['status']}. {m['hint']}")
        lines.append("")
    if questions:
        lines.append("Questions:")
        for i, q in enumerate(questions, 1):
            lines.append(f"  {i}. {q}")
        lines.append("")
    lines.append(f"(Run reference: {run_id})")
    return "\n".join(lines)


def needs_input(missing: List[Dict[str, str]], questions: List[str]) -> bool:
    return bool(missing or questions)
