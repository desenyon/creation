"""Creation CLI bootstrap with deterministic build completion guards."""

from __future__ import annotations

import re
from typing import Dict, Tuple

from creation import nebius_client

_original_generate_turn_plan = nebius_client.generate_turn_plan
_route_state: Dict[str, Tuple[str, int]] = {}


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _qa_is_clean(qa_context: str) -> bool:
    lowered = qa_context.lower()
    tests_ran = "command:" in lowered
    zero_failures = bool(re.search(r"\bfailed\s+0\b", lowered))
    browser_errors = "- [error]" in lowered
    return tests_ran and zero_failures and not browser_errors


def _linear_is_complete(linear_context: str) -> bool:
    lowered = linear_context.lower()
    has_board = "### kanban board" in lowered
    has_open_work = "**todo**" in lowered or "**in progress**" in lowered
    return has_board and not has_open_work and "**done**" in lowered


def _guarded_generate_turn_plan(*args, **kwargs):
    plan = _original_generate_turn_plan(*args, **kwargs)
    idea = str(kwargs.get("idea") or "default")
    turn = int(kwargs.get("turn") or 0)
    qa_context = str(kwargs.get("qa_context") or "")
    linear_context = str(kwargs.get("linear_context") or "")
    follow_up = _normalized(plan.follow_up)

    if turn <= 1:
        _route_state.pop(idea, None)

    previous, repeats = _route_state.get(idea, ("", 0))
    repeats = repeats + 1 if follow_up and follow_up == previous else 0
    _route_state[idea] = (follow_up, repeats)

    clean_qa = _qa_is_clean(qa_context)
    completed_board = _linear_is_complete(linear_context)
    stalled_after_clean_qa = clean_qa and repeats >= 2

    if plan.done or (clean_qa and completed_board) or stalled_after_clean_qa:
        reason = plan.reason
        if not plan.done:
            reason = "QA clean and build complete" if completed_board else "QA clean; repeated route stopped"
        return nebius_client.TurnPlan(
            done=True,
            refresh_research=False,
            run_agent=False,
            run_qa=False,
            follow_up="",
            reason=reason,
        )
    return plan


nebius_client.generate_turn_plan = _guarded_generate_turn_plan


def main() -> None:
    from creation.cli import main as cli_main

    cli_main()
