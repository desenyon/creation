"""Live progress rendering for synchronous CLI runs."""

from __future__ import annotations

from typing import Any, Callable, Dict

from rich.console import Console


def console_event_handler(console: Console, *, verbose: bool = False) -> Callable[[Dict[str, Any]], None]:
    """Return a sync callback suitable for ``run_factory(..., on_event=...)``."""

    def handle(event: Dict[str, Any]) -> None:
        typ = event.get("type")
        if typ == "phase":
            tool = event.get("tool") or event.get("phase") or "phase"
            detail = event.get("detail") or ""
            status = event.get("status")
            if status == "running":
                console.print(f"[dim]→[/] [bold]{tool}[/] {detail}")
            elif status == "done":
                console.print(f"[green]✓[/] [bold]{tool}[/] {detail}")
        elif typ == "turn_started":
            console.print(
                f"\n[bold cyan]Turn {event.get('turn')}/{event.get('max_turns')}[/]"
            )
        elif typ == "play_by_play":
            message = event.get("message") or ""
            if message:
                console.print(f"  [dim]·[/] {message}")
        elif typ == "tracking":
            linear = event.get("linear_url") or ""
            github = event.get("github_url") or ""
            if linear:
                console.print(f"  [blue]Linear[/] {linear}")
            if github:
                console.print(f"  [blue]GitHub[/] {github}")
        elif typ == "setup_complete":
            linear = event.get("linear_url") or ""
            if linear:
                console.print(f"[green]Setup complete[/] · [blue]{linear}[/]")
            else:
                console.print("[green]Setup complete[/] · entering build loop")
        elif typ == "agent_failover":
            console.print(
                f"[yellow]⚠[/] {event.get('from_agent')} → {event.get('to_agent')} "
                f"({event.get('reason') or 'usage limit'})"
            )
        elif typ == "agent_line":
            line = (event.get("line") or "").strip()
            if not line:
                return
            if verbose or line.startswith("$") or line.startswith("───") or line.startswith("⚠"):
                console.print(f"  [dim]{line[:240]}[/]")
        elif typ == "error":
            console.print(f"[bold red]Error:[/] {event.get('message') or 'run failed'}")

    return handle
