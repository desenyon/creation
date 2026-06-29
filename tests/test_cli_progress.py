import re

from creation.cli_progress import console_event_handler
from rich.console import Console


def test_console_event_handler_renders_phase_and_turn(capsys):
    console = Console(force_terminal=True, width=120)
    handle = console_event_handler(console)

    handle({"type": "phase", "tool": "Tavily", "detail": "Web research…", "status": "running"})
    handle({"type": "phase", "tool": "Tavily", "detail": "Idea ready", "status": "done"})
    handle({"type": "turn_started", "turn": 1, "max_turns": 8})

    out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    assert "Tavily" in out
    assert "Turn 1/8" in out
