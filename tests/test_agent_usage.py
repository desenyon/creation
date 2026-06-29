"""Tests for agent usage tracking and concurrent runs."""

from __future__ import annotations

import json

import pytest

from creation.agents.usage import (
    detect_rate_limit,
    mark_exhausted,
    probe_agent,
    record_turn,
    resolve_agent_for_turn,
)
from creation.config import UserSecrets
from creation.store import (
    count_running_runs,
    create_project,
    create_run,
    init_db,
    list_running_runs,
    update_run,
)


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr("creation.store.DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr("creation.store.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("creation.agents.usage.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("creation.agents.usage.USAGE_FILE", tmp_path / "agent_usage.json")
    monkeypatch.setattr("creation.agents.usage.LIMITS_FILE", tmp_path / "agent_turn_limits.json")
    init_db()
    return tmp_path


def test_detect_rate_limit():
    assert detect_rate_limit("Error: rate limit exceeded, try again later")
    assert not detect_rate_limit("Build completed successfully")


def test_record_turn_and_probe(isolated_store, monkeypatch):
    (isolated_store / "agent_turn_limits.json").write_text(json.dumps({"cursor": 10}))
    for _ in range(9):
        record_turn("cursor")
    snap = probe_agent("cursor", UserSecrets())
    assert snap.used == 9
    assert snap.pct == 90.0
    assert snap.status == "critical"


def test_failover_when_high_usage(isolated_store, monkeypatch):
    (isolated_store / "agent_turn_limits.json").write_text(json.dumps({"cursor": 10, "codex": 100}))
    for _ in range(9):
        record_turn("cursor")

    secrets = UserSecrets(
        agent_failover_enabled=True,
        agent_usage_failover_pct=90.0,
        agent_fallback="codex",
    )

    monkeypatch.setattr(
        "creation.agents.usage.available_agents",
        lambda: [
            {"id": "cursor", "available": True},
            {"id": "codex", "available": True},
        ],
    )
    monkeypatch.setattr("creation.agents.usage._probe_cursor_cli", lambda: True)

    agent, failover_from, snap = resolve_agent_for_turn("cursor", secrets)
    assert failover_from == "cursor"
    assert agent == "codex"
    assert snap.pct < 90


def test_mark_exhausted_forces_failover(isolated_store, monkeypatch):
    mark_exhausted("cursor")
    secrets = UserSecrets(agent_failover_enabled=True, agent_usage_failover_pct=90.0, agent_fallback="codex")
    monkeypatch.setattr(
        "creation.agents.usage.available_agents",
        lambda: [
            {"id": "cursor", "available": True},
            {"id": "codex", "available": True},
        ],
    )
    monkeypatch.setattr("creation.agents.usage._probe_cursor_cli", lambda: True)
    agent, failover_from, _ = resolve_agent_for_turn("cursor", secrets)
    assert failover_from == "cursor"
    assert agent == "codex"


def test_concurrent_running_runs(isolated_store):
    p1 = create_project("A", agent="codex")
    p2 = create_project("B", agent="codex")
    r1 = create_run(p1.id)
    r2 = create_run(p2.id)
    update_run(r1.id, status="running")
    update_run(r2.id, status="running")
    assert count_running_runs() == 2
    runs = list_running_runs()
    assert len(runs) == 2
    ids = {r["project_id"] for r in runs}
    assert p1.id in ids and p2.id in ids
