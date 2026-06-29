"""Preflight gate — integration checks + clarifying questions."""

from creation.config import UserSecrets
from creation.preflight import (
    clarifying_questions,
    missing_integrations,
    needs_input,
)


def test_missing_integrations_without_composio_key():
    missing = missing_integrations(UserSecrets(composio_api_key=""))
    toolkits = {m["toolkit"] for m in missing}
    assert {"github", "linear", "gmail"} <= toolkits
    assert all(m["status"] == "NO_COMPOSIO_KEY" for m in missing)


def test_clarifying_questions_flag_thin_brief():
    qs = clarifying_questions("app", secrets=UserSecrets(), existing_repo=False)
    assert any("short" in q.lower() or "what should" in q.lower() for q in qs)


def test_clarifying_questions_flag_existing_repo():
    qs = clarifying_questions(
        "Add an export-to-CSV button to the reports page",
        secrets=UserSecrets(),
        existing_repo=True,
    )
    assert any("existing repo" in q.lower() for q in qs)


def test_no_questions_for_clear_greenfield():
    qs = clarifying_questions(
        "Build a polished todo app with reminders and tags",
        secrets=UserSecrets(),
        existing_repo=False,
    )
    assert qs == []


def test_needs_input():
    assert needs_input([{"toolkit": "github"}], []) is True
    assert needs_input([], ["a question?"]) is True
    assert needs_input([], []) is False
