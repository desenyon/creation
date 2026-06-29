from types import SimpleNamespace

import pytest

from creation.config import UserSecrets
from creation.integrations.composio_connections import ComposioConnectionManager


def secrets(**updates):
    values = {
        "composio_api_key": "comp_test",
        "composio_user_id": "user-123",
        "composio_github_auth_config_id": "ac_github",
        "composio_linear_auth_config_id": "ac_linear",
        "composio_gmail_auth_config_id": "ac_gmail",
        "composio_firecrawl_auth_config_id": "ac_firecrawl",
    }
    values.update(updates)
    return UserSecrets(**values)


class FakeSession:
    def __init__(self, connected=True):
        self.connected = connected
        self.authorized = []

    def toolkits(self):
        items = []
        for slug in ("github", "linear", "gmail", "firecrawl"):
            account = SimpleNamespace(id=f"ca_{slug}", status="ACTIVE" if self.connected else "INITIATED")
            connection = SimpleNamespace(is_active=self.connected, connected_account=account)
            items.append(SimpleNamespace(slug=slug, connection=connection))
        return SimpleNamespace(items=items)

    def authorize(self, toolkit, callback_url):
        self.authorized.append((toolkit, callback_url))
        return SimpleNamespace(redirect_url=f"https://connect.composio.dev/{toolkit}")


class RejectingSession(FakeSession):
    def authorize(self, toolkit, callback_url):
        raise RuntimeError("Error code: 401 - Invalid API key; code 10401 HTTP_Unauthorized")


class FakeComposio:
    def __init__(self, session):
        self.session = session
        self.create_args = None

    def create(self, **kwargs):
        self.create_args = kwargs
        return self.session


def test_status_requires_all_four_active_connections():
    manager = ComposioConnectionManager(secrets())
    manager._composio = FakeComposio(FakeSession(connected=True))

    state = manager.status()

    assert state["ready"] is True
    core = ("github", "linear", "gmail", "firecrawl")
    assert all(state["connections"][s]["connected"] for s in core)
    assert manager._composio.create_args["auth_configs"]["github"] == "ac_github"


def test_missing_auth_config_is_not_ready():
    manager = ComposioConnectionManager(secrets(composio_gmail_auth_config_id=""))
    manager._composio = FakeComposio(FakeSession(connected=True))

    state = manager.status()

    assert state["ready"] is False
    assert state["connections"]["gmail"]["configured"] is False


def test_connect_link_uses_auth_config_session():
    session = FakeSession()
    manager = ComposioConnectionManager(secrets())
    manager._composio = FakeComposio(session)

    result = manager.connect_link("github", "http://127.0.0.1:8787/onboarding")

    assert result["redirect_url"].endswith("/github")
    assert session.authorized == [("github", "http://127.0.0.1:8787/onboarding")]


def test_connect_link_rejects_invalid_auth_config_id():
    manager = ComposioConnectionManager(secrets(composio_github_auth_config_id="github-config"))
    with pytest.raises(ValueError, match="must start with ac_"):
        manager.connect_link("github", "http://127.0.0.1:8787/onboarding")


def test_connect_link_explains_rejected_api_key():
    manager = ComposioConnectionManager(secrets())
    manager._composio = FakeComposio(RejectingSession())

    with pytest.raises(ValueError, match="same Composio project"):
        manager.connect_link("gmail", "http://127.0.0.1:8787/onboarding")


def test_onboarding_status_is_incomplete_without_core_keys(monkeypatch):
    from creation import composio_api

    monkeypatch.setattr(composio_api, "load_secrets", lambda: UserSecrets())

    state = composio_api.onboarding_status()

    assert state["complete"] is False
    assert state["core"]["tavily"] is False
    assert state["connections"] == {}


def test_onboarding_status_requires_live_connections(monkeypatch):
    from creation import composio_api

    configured = secrets(tavily_api_key="tvly", nebius_api_key="neb")

    class ReadyManager(ComposioConnectionManager):
        def status(self):
            return {
                "ready": True,
                "connections": {
                    slug: {"configured": True, "connected": True, "status": "ACTIVE"}
                    for slug in ("github", "linear", "gmail", "firecrawl")
                },
            }

    monkeypatch.setattr(composio_api, "load_secrets", lambda: configured)
    monkeypatch.setattr(composio_api, "ComposioConnectionManager", ReadyManager)

    state = composio_api.onboarding_status()

    assert state["complete"] is True
    assert all(state["auth_configs"].values())
