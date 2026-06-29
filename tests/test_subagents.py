"""Named subagent fan-out: call-signs, ordering, and live lifecycle events."""

from pathlib import Path

from creation.agents.runner import AgentResult, CodingAgentRunner, subagent_names
from creation.config import UserSecrets


def test_subagent_names_distinct_and_stable():
    names = subagent_names(3)
    assert names == ["Ada", "Turing", "Hopper"]
    assert len(set(subagent_names(12))) == 12  # no collisions past the roster


def _stub_runner(monkeypatch):
    runner = CodingAgentRunner("codex", UserSecrets())
    seen_prompts = []

    def fake_run(prompt, workdir, on_line=None):
        seen_prompts.append(prompt)
        if on_line:
            on_line("did work")
        return AgentResult(agent="codex", success=True, output=f"out::{prompt[-40:]}", command="codex")

    monkeypatch.setattr(runner, "run", fake_run)
    return runner, seen_prompts


def test_run_subagents_names_events_and_order(monkeypatch, tmp_path):
    runner, _ = _stub_runner(monkeypatch)
    lines: list[str] = []
    events: list[dict] = []

    result = runner.run_subagents(
        "base",
        ["frontend work", "backend work", "tests"],
        Path(tmp_path),
        on_line=lines.append,
        on_event=events.append,
        max_workers=3,
    )

    # Every subagent announces start and done, tagged by name.
    starts = [e for e in events if e["type"] == "subagent_start"]
    dones = [e for e in events if e["type"] == "subagent_done"]
    assert {e["name"] for e in starts} == {"Ada", "Turing", "Hopper"}
    assert all(e["success"] for e in dones)

    # Output lines are tagged with the call-sign so you can follow each agent.
    assert any(line.startswith("[Ada]") for line in lines)
    assert any(line.startswith("[Hopper]") for line in lines)

    # Combined output preserves task order (Ada→Turing→Hopper) regardless of finish order.
    assert result.output.index("Ada") < result.output.index("Turing") < result.output.index("Hopper")
    assert result.success


def test_run_subagents_single_task_falls_back_to_normal_run(monkeypatch, tmp_path):
    runner, _ = _stub_runner(monkeypatch)
    events: list[dict] = []
    result = runner.run_subagents("base", ["only one"], Path(tmp_path), on_event=events.append)
    assert events == []  # no fan-out
    assert result.agent == "codex"
