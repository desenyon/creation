"""SuperCompress memory layer — compress agent context before Nebius inference."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set, Dict, Any

import torch

from creation.memory.checkpoint import load_policy
from creation.memory.local import build_inference_records
from creation.memory.policies import EvictionPolicy, FIFO, H2OPolicy, LearnedPolicy


@dataclass
class CompressResult:
    original_text: str
    compressed_text: str
    original_tokens: int
    kept_tokens: int
    budget_ratio: float
    question: str
    kept_line_ratio: float
    policy_name: str

    @property
    def compression_ratio(self) -> float:
        if self.kept_tokens == 0:
            return 0.0
        return self.original_tokens / self.kept_tokens

    @property
    def kv_savings_pct(self) -> float:
        return (1.0 - self.kept_tokens / max(self.original_tokens, 1)) * 100


def _lines_from_kept_tokens(
    lines: List[str],
    line_for_token: List[int],
    kept_positions: Set[int],
    sink_lines: int = 2,
    recent_lines: int = 8,
) -> List[str]:
    kept_lines: Set[int] = set()
    for tok_idx, line_idx in enumerate(line_for_token):
        if tok_idx in kept_positions:
            kept_lines.add(line_idx)

    n_lines = len(lines)
    for i in range(min(sink_lines, n_lines)):
        kept_lines.add(i)
    for i in range(max(0, n_lines - recent_lines), n_lines):
        kept_lines.add(i)

    return [lines[i] for i in sorted(kept_lines)]


def compress_context(
    text: str,
    question: str,
    budget_ratio: float = 0.35,
    policy: Optional[EvictionPolicy] = None,
    checkpoint: Optional[str] = None,
) -> CompressResult:
    """Trim agent context before each LLM call — smaller KV, same workflow."""
    if not text.strip():
        return CompressResult(
            original_text=text,
            compressed_text=text,
            original_tokens=0,
            kept_tokens=0,
            budget_ratio=budget_ratio,
            question=question,
            kept_line_ratio=1.0,
            policy_name="noop",
        )
    if budget_ratio <= 0 or budget_ratio > 1:
        raise ValueError("budget_ratio must be in (0, 1]")

    lines = text.splitlines() or [text]
    records, line_for_token = build_inference_records(lines, question)
    n = len(records)
    budget = max(16, int(n * budget_ratio))

    if policy is None:
        try:
            _, policy_obj, _ = load_policy(checkpoint)
            policy_name = "Prism"
        except FileNotFoundError:
            policy_obj = H2OPolicy()
            policy_name = "H2O-fallback"
        policy = policy_obj
    else:
        policy_name = getattr(policy, "name", policy.__class__.__name__)

    kept_positions = set(policy.select(records, budget))
    out_lines = _lines_from_kept_tokens(lines, line_for_token, kept_positions)
    compressed = "\n".join(out_lines)

    return CompressResult(
        original_text=text,
        compressed_text=compressed,
        original_tokens=n,
        kept_tokens=len(kept_positions),
        budget_ratio=budget_ratio,
        question=question,
        kept_line_ratio=len(out_lines) / max(len(lines), 1),
        policy_name=policy_name,
    )


def compare_policies(
    text: str,
    question: str,
    budget_ratio: float = 0.35,
    checkpoint: Optional[str] = None,
) -> dict[str, CompressResult]:
    try:
        _, learned, _ = load_policy(checkpoint)
    except FileNotFoundError:
        learned = H2OPolicy()
    return {
        "FIFO": compress_context(text, question, budget_ratio, FIFO()),
        "Prism": compress_context(text, question, budget_ratio, learned),
    }


def compress_for_turn(
    context_blocks: List[str],
    user_query: str,
    budget_ratio: float = 0.35,
    *,
    mem0_block: str = "",
) -> tuple[str, CompressResult]:
    """Merge context blocks then SuperCompress.

    When ``mem0_block`` is provided, Mem0 recall is prepended so SuperCompress
    trims the combined window — persistent facts survive via Mem0, noise via eviction.
    """
    ordered: List[str] = []
    if mem0_block.strip():
        ordered.append(mem0_block.strip())
    ordered.extend(b for b in context_blocks if b.strip())
    merged = "\n\n---\n\n".join(ordered)
    result = compress_context(merged, user_query, budget_ratio=budget_ratio)
    return result.compressed_text, result


def compress_with_memory_stack(
    context_blocks: List[str],
    user_query: str,
    budget_ratio: float,
    mem0_recall_block: str,
    *,
    mem0_count: int = 0,
) -> tuple[str, CompressResult, Dict[str, Any]]:
    """Two-layer memory: Mem0 recall → SuperCompress token eviction."""
    text, result = compress_for_turn(
        context_blocks,
        user_query,
        budget_ratio,
        mem0_block=mem0_recall_block,
    )
    stats: Dict[str, Any] = {
        "mem0_recalled": mem0_count,
        "mem0_enabled": bool(mem0_recall_block.strip()),
        "prism_policy": result.policy_name,
        "original_tokens": result.original_tokens,
        "kept_tokens": result.kept_tokens,
        "kv_savings_pct": result.kv_savings_pct,
    }
    return text, result, stats
