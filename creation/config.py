"""Local configuration — Creation account + first-party services."""

from __future__ import annotations

import json
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from creation.agents.registry import normalize_agent

CONFIG_DIR = Path.home() / ".creation"
CONFIG_FILE = CONFIG_DIR / "config.json"
PROJECTS_DIR = CONFIG_DIR / "projects"

AgentKind = str


class UserSecrets(BaseModel):
    """Creation runs on one account and first-party services."""

    account_email: str = ""
    account_token: str = ""

    forge_api_key: str = ""
    forge_base_url: str = ""
    forge_model: str = "creation-forge-v1"
    forge_offline: bool = False

    github_token: str = ""
    linear_api_key: str = ""
    linear_team_id: str = ""
    github_owner: str = ""
    github_repo: str = ""
    notify_email: str = ""
    gmail_notify_to: str = "me"

    memory_provider: Literal["prism", "off"] = "prism"
    memory_budget: float = 0.35

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    default_agent: AgentKind = "codex"

    ship_mode: Literal["push", "pr"] = "pr"
    max_turn_budget: int = 200
    auto_branch: bool = True
    parallel_agents: bool = False
    secondary_agent: str = "claude"
    subagents_enabled: bool = False
    max_subagents: int = 3
    max_concurrent_runs: int = 3

    work_graph_enabled: bool = False
    work_auto_dispatch: bool = False
    work_dispatch_interval_secs: int = 20

    preflight_enabled: bool = True
    preflight_timeout_secs: int = 1800
    inbound_hitl_enabled: bool = True
    inbound_poll_secs: int = 30

    schedule_enabled: bool = False
    schedule_interval_hours: int = 24

    linear_project_mode: Literal["create", "existing"] = "create"
    linear_project_id: str = ""
    linear_project_url: str = ""
    linear_project_name: str = ""

    marketing_enabled: bool = False
    marketing_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True

    agent_usage_warn_pct: float = 75.0
    agent_usage_critical_pct: float = 90.0
    agent_usage_failover_pct: float = 90.0
    agent_failover_enabled: bool = True
    agent_fallback: str = "codex"

    webhook_url: str = ""
    webhook_secret: str = ""

    composio_api_key: str = ""
    composio_user_id: str = ""
    composio_github_auth_config_id: str = ""
    composio_linear_auth_config_id: str = ""
    composio_gmail_auth_config_id: str = ""
    composio_firecrawl_auth_config_id: str = ""
    composio_firecrawl_user_id: str = ""
    tavily_api_key: str = ""
    nebius_api_key: str = ""
    nebius_base_url: str = ""
    nebius_model: str = ""
    mem0_api_key: str = ""
    mem0_enabled: bool = True
    supermemory_api_key: str = ""
    resend_api_key: str = ""
    resend_from: str = ""
    resend_segment_id: str = ""
    ayrshare_api_key: str = ""
    marketing_platforms: str = "twitter,linkedin"
    marketing_media_url: str = ""

    model_config = ConfigDict(extra="ignore")

    @field_validator("default_agent")
    @classmethod
    def _validate_default_agent(cls, v: str) -> str:
        try:
            return normalize_agent(v)
        except ValueError:
            return "codex"

    @field_validator("memory_provider", mode="before")
    @classmethod
    def _validate_memory_provider(cls, value: object) -> object:
        if isinstance(value, str):
            v = value.strip().lower()
            if v == "off":
                return "off"
            return "prism"
        return "prism"

    def schedule_state_file(self) -> Path:
        return CONFIG_DIR / "schedule_state.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    creation_host: str = "127.0.0.1"
    creation_port: int = 8787
    creation_demo: bool = Field(default=False, validation_alias="CREATION_DEMO")


def _migrate_legacy_data() -> None:
    legacy_factory = Path.home() / ".software-factory"
    if not legacy_factory.exists():
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    legacy_cfg = legacy_factory / "config.json"
    if legacy_cfg.exists():
        try:
            current: dict = {}
            if CONFIG_FILE.exists():
                current = json.loads(CONFIG_FILE.read_text())
            legacy_data = json.loads(legacy_cfg.read_text())
            merged = _migrate_service_keys(_merge_config_dicts(current, legacy_data))
            if merged != current or not CONFIG_FILE.exists():
                CONFIG_FILE.write_text(json.dumps(merged, indent=2))
        except json.JSONDecodeError:
            pass


def _merge_config_dicts(primary: dict, fallback: dict) -> dict:
    out = dict(primary)
    for key, value in fallback.items():
        if key not in out or out[key] in (None, "") or (isinstance(out[key], str) and not str(out[key]).strip()):
            out[key] = value
    return out


def _migrate_service_keys(data: dict) -> dict:
    out = dict(data)
    if not out.get("forge_api_key") and out.get("nebius_api_key"):
        out["forge_api_key"] = out["nebius_api_key"]
    if not out.get("forge_base_url") and out.get("nebius_base_url"):
        out["forge_base_url"] = out["nebius_base_url"]
    if not out.get("forge_model") and out.get("nebius_model"):
        out["forge_model"] = out["nebius_model"]
    if not out.get("notify_email") and out.get("gmail_notify_to") and out["gmail_notify_to"] != "me":
        out["notify_email"] = out["gmail_notify_to"]
    if (out.get("memory_provider") or "prism").lower() in {"auto", "mem0", "supermemory"}:
        out["memory_provider"] = "prism"
    return out


def _read_config_raw() -> dict:
    ensure_dirs()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except json.JSONDecodeError:
            data = {}
    return _migrate_service_keys(data)


def load_secrets() -> UserSecrets:
    ensure_dirs()
    data = _read_config_raw()
    if data:
        return UserSecrets.model_validate(data)
    secrets = UserSecrets()
    try:
        from creation.account.store import AccountStore

        acct = AccountStore().ensure_local_account()
        secrets.account_email = acct.email
        secrets.account_token = acct.api_key
    except Exception:
        pass
    return secrets


def save_secrets(secrets: UserSecrets) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if CONFIG_FILE.exists():
        try:
            existing = json.loads(CONFIG_FILE.read_text())
        except json.JSONDecodeError:
            existing = {}
    CONFIG_FILE.write_text(json.dumps({**existing, **secrets.model_dump()}, indent=2))


def ensure_dirs() -> None:
    _migrate_legacy_data()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    import os

    if os.environ.get("FACTORY_DEMO") == "1" or os.environ.get("CREATION_DEMO") == "1":
        return s.model_copy(update={"creation_demo": True})
    return s
