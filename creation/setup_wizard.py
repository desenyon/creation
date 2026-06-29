"""Creation setup wizard — shared logic for CLI and TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from creation.account.auth import login as account_login
from creation.account.auth import register as account_register
from creation.account.store import AccountStore, AccountUser
from creation.agents.runner import available_agents
from creation.config import UserSecrets, ensure_dirs, load_secrets, save_secrets
from creation.memory.factory import memory_status
from creation.store import init_db

SETUP_VERSION = 1


def needs_setup(secrets: Optional[UserSecrets] = None) -> bool:
    """True when the interactive setup wizard has not been completed."""
    sec = secrets or load_secrets()
    return not sec.setup_complete


def mark_setup_complete(secrets: Optional[UserSecrets] = None) -> UserSecrets:
    sec = secrets or load_secrets()
    sec.setup_complete = True
    sec.setup_version = SETUP_VERSION
    save_secrets(sec)
    return sec


def bootstrap_environment() -> None:
    """Create ~/.creation layout and SQLite stores."""
    import os

    ensure_dirs()
    init_db()
    AccountStore()
    url = os.environ.get("CREATION_CLOUD_URL", "").strip()
    if url:
        sec = load_secrets()
        sec.cloud_api_url = url
        if not sec.forge_base_url.strip():
            sec.forge_base_url = url
        save_secrets(sec)


def sync_account_to_secrets(user: AccountUser) -> UserSecrets:
    sec = load_secrets()
    sec.account_email = user.email
    sec.account_token = user.api_key
    if user.github_token:
        sec.github_token = user.github_token
    if user.linear_api_key:
        sec.linear_api_key = user.linear_api_key
    if user.linear_team_id:
        sec.linear_team_id = user.linear_team_id
    if user.notify_email:
        sec.notify_email = user.notify_email
    save_secrets(sec)
    return sec


def create_account(email: str, password: str) -> AccountUser:
    from creation.cloud.client import cloud_enabled, cloud_register

    if cloud_enabled() and email.strip() and password:
        profile = cloud_register(email, password)
        user = AccountUser(
            id="cloud",
            email=profile["email"],
            api_key=profile["api_key"],
            credits=int(profile.get("credits", 0)),
        )
        sync_account_to_secrets(user)
        return user
    user = account_register(email.strip(), password)
    sync_account_to_secrets(user)
    return user


def sign_in(email: str, password: str) -> AccountUser:
    from creation.cloud.client import cloud_enabled, cloud_login

    if cloud_enabled() and email.strip() and password:
        profile = cloud_login(email, password)
        user = AccountUser(
            id="cloud",
            email=profile["email"],
            api_key=profile["api_key"],
            credits=int(profile.get("credits", 0)),
        )
        sync_account_to_secrets(user)
        return user
    user, _session = account_login(email.strip(), password)
    sync_account_to_secrets(user)
    return user


def save_relay_credentials(
    *,
    github_token: str = "",
    linear_api_key: str = "",
    linear_team_id: str = "",
    notify_email: str = "",
) -> UserSecrets:
    sec = load_secrets()
    if github_token.strip():
        sec.github_token = github_token.strip()
    if linear_api_key.strip():
        sec.linear_api_key = linear_api_key.strip()
    if linear_team_id.strip():
        sec.linear_team_id = linear_team_id.strip()
    if notify_email.strip():
        sec.notify_email = notify_email.strip()
    save_secrets(sec)
    user = AccountStore().get_by_api_key(sec.account_token)
    if user:
        AccountStore().update_credentials(
            user.id,
            github_token=sec.github_token or None,
            linear_api_key=sec.linear_api_key or None,
            linear_team_id=sec.linear_team_id or None,
            notify_email=sec.notify_email or None,
        )
    return sec


def save_default_agent(agent_id: str) -> UserSecrets:
    sec = load_secrets()
    sec.default_agent = agent_id
    save_secrets(sec)
    return sec


def list_agent_choices() -> List[Tuple[str, str, bool]]:
    """Return (id, label, available) for agent picker."""
    return [(a["id"], str(a.get("label") or a["id"]), bool(a.get("available"))) for a in available_agents()]


def pick_default_agent() -> str:
    choices = list_agent_choices()
    for agent_id, _label, ok in choices:
        if ok:
            return agent_id
    return load_secrets().default_agent or "codex"


@dataclass
class DoctorReport:
    account_email: str
    credits: int
    memory_label: str
    agents_available: List[str]
    relay_github: bool
    relay_linear: bool

    def lines(self) -> List[str]:
        agents = ", ".join(self.agents_available[:6]) or "none detected"
        if len(self.agents_available) > 6:
            agents += f" (+{len(self.agents_available) - 6} more)"
        return [
            f"Account: {self.account_email} · {self.credits:,} credits",
            f"Prism: {self.memory_label}",
            f"Agents: {agents}",
            f"Relay GitHub: {'connected' if self.relay_github else 'optional'}",
            f"Relay Linear: {'connected' if self.relay_linear else 'optional'}",
        ]


def doctor_report() -> DoctorReport:
    sec = load_secrets()
    store = AccountStore()
    user = store.get_by_api_key(sec.account_token) if sec.account_token else store.ensure_local_account()
    mem = memory_status(sec)
    avail = [a["id"] for a in available_agents() if a.get("available")]
    return DoctorReport(
        account_email=user.email,
        credits=user.credits,
        memory_label=str(mem.get("label") or "Prism"),
        agents_available=avail,
        relay_github=bool(sec.github_token or user.github_token),
        relay_linear=bool(sec.linear_api_key or user.linear_api_key),
    )


def run_quick_setup(*, email: str = "", password: str = "", skip_relay: bool = True) -> DoctorReport:
    """Non-interactive setup for tests and install --yes."""
    bootstrap_environment()
    sec = load_secrets()
    if email and password:
        try:
            create_account(email, password)
        except ValueError:
            sign_in(email, password)
    elif not sec.account_token:
        user = AccountStore().ensure_local_account()
        sync_account_to_secrets(user)
    save_default_agent(pick_default_agent())
    if not skip_relay:
        save_relay_credentials()
    mark_setup_complete()
    return doctor_report()
