"""Prism compression + memory tests."""

from creation.memory import compress_for_turn, compress_with_memory_stack
from creation.memory.base import MemoryBridge
from creation.services.prism.memory import PrismMemory


def test_compress_for_turn():
    blocks = ["## Lens\nAI agents need memory.", "## Relay\nPR #1 open"]
    text, mem = compress_for_turn(blocks, "What to ship?", budget_ratio=0.35)
    assert mem.original_tokens > 0
    assert mem.kept_tokens > 0
    assert mem.policy_name in ("Prism", "H2O-fallback")
    assert text


def test_compress_with_prism_block():
    blocks = ["line one", "line two", "line three"]
    mem_block = "## Prism memory\n- keep tests green"
    text, result, stats = compress_with_memory_stack(
        blocks, "query", 0.35, mem_block, mem0_count=1
    )
    assert stats["mem0_recalled"] == 1
    assert stats["prism_policy"] in ("Prism", "H2O-fallback")
    assert "Prism" in mem_block or text


def test_prism_recall_block_format():
    from creation.memory.base import MemoryRecall

    recall = MemoryRecall(query="q", memories=["fact"], enabled=True, provider="prism")
    block = MemoryBridge.to_context_block(recall)
    assert "Prism" in block
