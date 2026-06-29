"""Validate Creation account + agent before a live run."""

from __future__ import annotations

from creation.account.store import AccountStore
from creation.agents.runner import available_agents
from creation.config import UserSecrets


class RunValidationError(Exception):
    pass


def validate_live_run(secrets: UserSecrets, agent: str) -> None:
    missing: list[str] = []

    has_account = bool(secrets.account_token.strip())
    if not has_account:
        try:
            AccountStore().ensure_local_account()
            has_account = True
        except Exception:
            has_account = False
    if not has_account and not secrets.forge_offline:
        missing.append("Creation account (run `creation login`)")

    agents = {a["id"]: a for a in available_agents()}
    info = agents.get(agent)
    if info and not info.get("available"):
        missing.append(f"{agent} CLI not on PATH")

    if missing:
        raise RunValidationError(
            "Live run needs a Creation account and a coding agent on PATH. Missing: "
            + "; ".join(missing)
        )
