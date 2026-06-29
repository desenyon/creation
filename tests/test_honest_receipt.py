"""Honest ship receipt — outcome-driven integration status + token stats."""

from creation.config import UserSecrets
from creation.ship_receipt import build_ship_receipt
from creation.sponsors import build_sponsor_integrations


def _composio_row(rows):
    return next(r for r in rows if r["sponsor"] == "Composio")


def test_composio_live_only_when_action_succeeded():
    secrets = UserSecrets(composio_api_key="ck")
    # No outcomes → configured (key present) not live.
    rows = build_sponsor_integrations(secrets, outcomes={})
    assert _composio_row(rows)["status"] == "configured"

    # A real push/email → live.
    rows = build_sponsor_integrations(
        secrets, outcomes={"github_pushed": True, "gmail_ok": True, "linear_ok": True}
    )
    composio = _composio_row(rows)
    assert composio["status"] == "live"
    assert "✓" in composio["integration"]


def test_composio_pending_without_key():
    rows = build_sponsor_integrations(UserSecrets(composio_api_key=""), outcomes={})
    assert _composio_row(rows)["status"] == "pending"


def test_vercel_is_not_a_user_ship_receipt_integration():
    rows = build_sponsor_integrations(UserSecrets(), outcomes={"deploy_ok": True})
    assert all(row["sponsor"] != "Vercel" for row in rows)


def test_token_preservation_in_receipt():
    receipt = build_ship_receipt(
        idea="An app",
        product_name="App",
        tagline="Tagline",
        turns=5,
        build_complete=True,
        tracking={"github_url": "https://github.com/x/y"},
        completion={"final_gmail": {"success": True}},
        memory_totals={
            "original_tokens": 2_400_000,
            "kept_tokens": 900_000,
            "tokens_saved": 1_500_000,
            "overall_savings_pct": 62.5,
            "mem0_recalled": 148,
            "turns_compressed": 5,
        },
    )
    tp = receipt["token_preservation"]
    assert tp["savings_pct"] == 62.5
    assert tp["original_tokens"] == 2_400_000
    assert tp["kept_tokens"] == 900_000
    assert tp["mem0_recalled"] == 148
    assert "62%" in tp["summary"]
    assert "memories recalled" in tp["summary"]


def test_token_preservation_handles_empty():
    receipt = build_ship_receipt(
        idea="An app",
        product_name="App",
        tagline="Tagline",
        turns=0,
        build_complete=False,
        tracking={},
        completion={},
    )
    tp = receipt["token_preservation"]
    assert tp["original_tokens"] == 0
    assert tp["savings_pct"] == 0.0
    assert "No compression" in tp["summary"]
