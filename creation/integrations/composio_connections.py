"""Composio Auth Config connection lifecycle for onboarding and preflight."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from creation.config import UserSecrets

CORE_TOOLKITS = ("github", "linear", "gmail", "firecrawl")
OPTIONAL_TOOLKITS: tuple[str, ...] = ()
TOOLKITS = CORE_TOOLKITS  # back-compat: callers that mean "required" toolkits


@dataclass(frozen=True)
class ConnectionSpec:
    toolkit: str
    auth_config_id: str


class ComposioConnectionManager:
    def __init__(self, secrets: UserSecrets):
        self.secrets = secrets
        self._composio = None

    @property
    def composio(self):
        if self._composio is None:
            from composio import Composio

            self._composio = Composio(api_key=self.secrets.composio_api_key.strip())
        return self._composio

    def specs(self) -> Dict[str, ConnectionSpec]:
        """Core (required) toolkit specs — used for onboarding readiness."""
        return {
            "github": ConnectionSpec("github", self.secrets.composio_github_auth_config_id.strip()),
            "linear": ConnectionSpec("linear", self.secrets.composio_linear_auth_config_id.strip()),
            "gmail": ConnectionSpec("gmail", self.secrets.composio_gmail_auth_config_id.strip()),
            "firecrawl": ConnectionSpec("firecrawl", self.secrets.composio_firecrawl_auth_config_id.strip()),
        }

    def optional_specs(self) -> Dict[str, ConnectionSpec]:
        return {}

    def all_specs(self) -> Dict[str, ConnectionSpec]:
        return {**self.specs(), **self.optional_specs()}

    def _session(self):
        toolkits = list(CORE_TOOLKITS) + [
            slug for slug, spec in self.optional_specs().items() if spec.auth_config_id
        ]
        configured = {slug: spec.auth_config_id for slug, spec in self.all_specs().items() if spec.auth_config_id}
        return self.composio.create(
            user_id=self.secrets.composio_user_id.strip(),
            toolkits=toolkits,
            auth_configs=configured,
            manage_connections=False,
        )

    @staticmethod
    def _value(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        detail = str(exc)
        lowered = detail.lower()
        if "invalid api key" in lowered or "10401" in lowered or "http_unauthorized" in lowered:
            return (
                "Composio rejected the saved API key. Re-enter the Project API key from "
                "the same Composio project that owns these Auth Config IDs, then save again."
            )
        return detail[:240]

    def status(self) -> Dict[str, Any]:
        specs = self.all_specs()
        result: Dict[str, Any] = {
            slug: {
                "toolkit": slug,
                "configured": bool(spec.auth_config_id),
                "connected": False,
                "optional": slug in OPTIONAL_TOOLKITS,
                "status": "MISSING_AUTH_CONFIG" if not spec.auth_config_id else "NOT_CONNECTED",
                "connected_account_id": "",
            }
            for slug, spec in specs.items()
        }

        def _ready() -> bool:
            # Readiness depends only on core toolkits; optional ones never block.
            return all(result[s]["configured"] and result[s]["connected"] for s in CORE_TOOLKITS)

        if not self.secrets.composio_api_key.strip() or not self.secrets.composio_user_id.strip():
            return {"ready": False, "connections": result}

        try:
            toolkits = self._session().toolkits()
            for item in self._value(toolkits, "items", []) or []:
                slug = str(self._value(item, "slug", self._value(item, "name", ""))).lower()
                if slug not in result:
                    continue
                connection = self._value(item, "connection")
                account = self._value(connection, "connected_account") if connection else None
                active = bool(self._value(connection, "is_active", False))
                account_id = str(self._value(account, "id", "") or "")
                account_status = str(self._value(account, "status", "") or "")
                result[slug].update(
                    connected=active or account_status.upper() == "ACTIVE",
                    status=account_status.upper() or ("ACTIVE" if active else "NOT_CONNECTED"),
                    connected_account_id=account_id,
                )
        except Exception as exc:
            error = self._friendly_error(exc)
            for connection in result.values():
                if connection["configured"]:
                    connection["status"] = "ERROR"
                    connection["error"] = error

        return {
            "ready": _ready(),
            "connections": result,
        }

    def connect_link(self, toolkit: str, callback_url: str) -> Dict[str, str]:
        slug = toolkit.lower().strip()
        if slug not in CORE_TOOLKITS and slug not in OPTIONAL_TOOLKITS:
            raise ValueError(f"Unsupported Composio toolkit: {toolkit}")
        spec = self.all_specs()[slug]
        if not self.secrets.composio_api_key.strip():
            raise ValueError("Composio API key is required")
        if not self.secrets.composio_user_id.strip():
            raise ValueError("Composio user ID is required")
        if not spec.auth_config_id:
            raise ValueError(f"{slug.title()} Auth Config ID is required")
        if not spec.auth_config_id.startswith("ac_"):
            raise ValueError(f"{slug.title()} Auth Config ID must start with ac_")

        try:
            request = self._session().authorize(slug, callback_url=callback_url)
        except Exception as exc:
            raise ValueError(self._friendly_error(exc)) from exc
        redirect_url = str(self._value(request, "redirect_url", "") or "")
        if not redirect_url:
            raise RuntimeError("Composio did not return a Connect Link")
        return {"toolkit": slug, "redirect_url": redirect_url}
