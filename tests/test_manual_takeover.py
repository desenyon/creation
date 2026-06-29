"""Manual takeover message queue."""

import pytest

import creation.manual_takeover as mt


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db = tmp_path / "manual.db"
    monkeypatch.setattr(mt, "DB_PATH", db)
    mt._table_ready = False
    yield


def test_add_and_drain():
    run_id = "run-manual-1"
    msg = mt.add_message(run_id, "Use Tailwind for styling")
    assert msg["status"] == "pending"

    drained = mt.drain_for_turn(run_id, 2)
    assert len(drained) == 1
    assert drained[0]["consumed_turn"] == 2
    assert mt.drain_for_turn(run_id, 3) == []

    all_msgs = mt.list_messages(run_id)
    assert all_msgs[0]["status"] == "consumed"


def test_to_context_block():
    block = mt.to_context_block([{"text": "Add dark mode"}])
    assert "Manual takeover" in block
    assert "Add dark mode" in block


def test_steering_summary():
    s = mt.steering_summary([{"text": "SQLite only"}, {"text": "Add tests"}])
    assert "SQLite only" in s
    assert "manual takeover" in s.lower()


def test_empty_message_raises():
    with pytest.raises(ValueError):
        mt.add_message("run-x", "   ")
