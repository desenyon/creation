"""Prism memory backend tests."""

from creation.config import UserSecrets
from creation.memory import build_memory_bridge, memory_status, resolve_provider
from creation.memory.base import DisabledBridge, MemoryBridge
from creation.services.prism.memory import PrismMemory, available_providers


def test_resolve_prism_default():
    assert resolve_provider(UserSecrets()) == "prism"


def test_off_disables_memory():
    sec = UserSecrets(memory_provider="off")
    assert resolve_provider(sec) == "off"
    bridge = build_memory_bridge(sec)
    assert isinstance(bridge, DisabledBridge)


def test_prism_demo_recall():
    bridge = PrismMemory(UserSecrets(), demo=True)
    recall = bridge.recall("how to ship?")
    assert recall.enabled and recall.demo and recall.count >= 1
    assert recall.provider == "prism"


def test_available_providers():
    assert available_providers(UserSecrets()) == {"prism": True}


def test_memory_status_shape():
    status = memory_status(UserSecrets())
    assert status["resolved"] == "prism"
    assert "label" in status
    assert status["available"]["prism"] is True


def test_prism_stores_and_recalls(tmp_path, monkeypatch):
    monkeypatch.setattr("creation.services.prism.memory.PRISM_DB", tmp_path / "prism.db")
    bridge = PrismMemory(UserSecrets())
    bridge.store_messages(
        [{"role": "assistant", "content": "Always run pytest before shipping."}],
        project_id="p1",
    )
    recall = bridge.recall("pytest shipping", project_id="p1")
    assert recall.count >= 1
    block = MemoryBridge.to_context_block(recall)
    assert "Prism" in block
