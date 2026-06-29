"""Forge — Creation planning brain (replaces Nebius)."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from creation.account.store import AccountStore
from creation.config import UserSecrets

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "creation-forge-v1"
DEFAULT_BASE = "http://127.0.0.1:8787/api/forge/v1"


def _resolve_key(secrets: UserSecrets) -> str:
    if secrets.forge_api_key.strip():
        return secrets.forge_api_key.strip()
    if secrets.account_token.strip():
        return secrets.account_token.strip()
    return AccountStore().ensure_local_account().api_key


def _client(secrets: UserSecrets):
    from openai import OpenAI

    base = secrets.forge_base_url.strip() or os.environ.get("CREATION_FORGE_URL", DEFAULT_BASE)
    return OpenAI(api_key=_resolve_key(secrets), base_url=base)


def _charge(secrets: UserSecrets, units: int, detail: str) -> None:
    user = AccountStore().get_by_api_key(_resolve_key(secrets))
    if user:
        AccountStore().deduct_credits(user.id, units, "forge", detail)


def _chat(secrets: UserSecrets, system: str, user: str, max_tokens: int = 600) -> str:
    if secrets.forge_offline or not _resolve_key(secrets):
        return ""
    try:
        client = _client(secrets)
        resp = client.chat.completions.create(
            model=secrets.forge_model or DEFAULT_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
        text = (resp.choices[0].message.content or "").strip()
        _charge(secrets, max(50, len(user) // 4), "completion")
        return text
    except Exception as exc:
        logger.warning("Forge completion failed: %s", exc)
        return ""


def heuristic_plan(idea: str, max_turns: int, *, edit: bool = False) -> str:
    if edit:
        return "\n".join(
            [
                "1. Read affected modules and tests",
                "2. Implement the requested change with minimal diff",
                "3. Run and fix tests for touched areas",
                "4. Update docs if user-facing behavior changed",
            ]
        )
    steps = [
        "1. Scaffold project structure and dependencies",
        "2. Implement core user-facing flow",
        "3. Add automated tests for the happy path",
        "4. Wire CLI or API entrypoint",
        "5. Polish README and error handling",
    ]
    if max_turns >= 12:
        steps.extend(["6. Add secondary features from research", "7. Browser QA and visual polish"])
    return "\n".join(steps[: min(len(steps), max(3, max_turns // 3))])


def heuristic_brand(idea: str) -> Dict[str, str]:
    from creation.services.forge.brand import ProductBrand, _fallback_slug

    b = ProductBrand.from_idea(idea)
    return {
        "product_name": b.product_name,
        "repo_slug": b.repo_slug,
        "tagline": b.tagline,
        "linear_project_name": b.linear_project_name,
    }
