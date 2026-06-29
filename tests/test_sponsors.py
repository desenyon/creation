"""Sponsor integration map for Ship Receipt."""

from creation.config import UserSecrets
from creation.sponsors import build_sponsor_integrations


def test_sponsor_integrations_includes_core():
    rows = build_sponsor_integrations(UserSecrets(tavily_api_key="x", nebius_api_key="y", mem0_api_key="m"))
    names = {r["sponsor"] for r in rows}
    assert "Tavily" in names
    assert "Mem0" in names
    assert "Nebius Token Factory" in names
    assert "Composio" in names
    assert "OpenClaw" in names


def test_openclaw_is_live_only_when_selected():
    inactive = build_sponsor_integrations(UserSecrets())
    active = build_sponsor_integrations(UserSecrets(), agents=["openclaw"])
    assert next(r for r in inactive if r["sponsor"] == "OpenClaw")["status"] == "available"
    assert next(r for r in active if r["sponsor"] == "OpenClaw")["status"] == "live"


def test_sdk_template_adds_stripe():
    rows = build_sponsor_integrations(UserSecrets(), template_id="stripe-saas")
    assert any(r["sponsor"] == "Stripe" for r in rows)


def test_demo_integrations_are_not_marked_live():
    rows = build_sponsor_integrations(UserSecrets(), demo=True, agents=["openclaw"])
    assert not any(r["status"] == "live" for r in rows)
    assert next(r for r in rows if r["sponsor"] == "Tavily")["status"] == "demo"
