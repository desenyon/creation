#!/usr/bin/env python3
"""Creation CLI — simplified commands."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from creation.agents.runner import available_agents
from creation.cli_progress import console_event_handler
from creation.config import ensure_dirs, load_secrets, save_secrets
from creation.orchestrator import run_factory
from creation.store import create_project, create_run, init_db, list_projects, list_runs
from creation.validate import RunValidationError

app = typer.Typer(name="creation", help="Creation — local agent OS", no_args_is_help=False)
console = Console()

from creation.work.cli import app as work_app  # noqa: E402

app.add_typer(work_app, name="work", hidden=True)


def _main_tui() -> None:
    from creation.tui import run_tui

    run_tui()


def _run_setup_wizard(*, force: bool = False) -> Optional[str]:
    """Run setup TUI when needed. Returns finish action if wizard ran."""
    import os

    from creation.setup_wizard import needs_setup
    from creation.setup_tui import run_setup_tui

    if os.environ.get("CREATION_SKIP_SETUP") == "1" and not force:
        return None
    if not force and not needs_setup():
        return None
    return run_setup_tui()


def _handle_setup_finish(action: Optional[str]) -> None:
    if action == "serve":
        serve()
        raise typer.Exit()
    if action == "demo":
        build("A minimal todo CLI in Python", demo=True)
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Default: setup on first run, then open terminal UI."""
    if ctx.invoked_subcommand is None:
        _handle_setup_finish(_run_setup_wizard())
        _main_tui()
        raise typer.Exit()


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    """Start Creation Studio (web UI)."""
    ensure_dirs()
    init_db()
    uvicorn.run("creation.server:app", host=host, port=port, reload=False)


@app.command()
def tui(host: str = "127.0.0.1", port: int = 8787) -> None:
    """Terminal UI (requires `creation serve`)."""
    from creation.tui import run_tui

    run_tui(base_url=f"http://{host}:{port}")


@app.command()
def setup(
    yes: bool = typer.Option(False, "--yes", help="Non-interactive setup with local defaults"),
    reinstall: bool = typer.Option(False, "--reinstall", help="Run the setup wizard again"),
) -> None:
    """Interactive install + configuration shell."""
    from creation.setup_wizard import mark_setup_complete, needs_setup, run_quick_setup

    if yes:
        bootstrap = run_quick_setup()
        for line in bootstrap.lines():
            console.print(f"  {line}")
        console.print("[green]Setup complete[/] — run [cyan]creation[/] to open the terminal UI")
        return

    if reinstall or needs_setup():
        if reinstall:
            sec = load_secrets()
            sec.setup_complete = False
            save_secrets(sec)
        action = _run_setup_wizard(force=True)
        _handle_setup_finish(action)
        if action is None:
            mark_setup_complete()
        console.print("[green]Setup complete[/]")
        return

    console.print("[dim]Setup already finished. Use --reinstall to run the wizard again.[/]")


@app.command()
def login(email: str = typer.Option(..., prompt=True), password: str = typer.Option(..., prompt=True, hide_input=True)) -> None:
    """Sign in to your Creation account."""
    from creation.setup_wizard import sign_in

    try:
        user = sign_in(email, password)
    except Exception as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(f"[green]Signed in[/] as {user.email}")
    console.print(f"API key: [dim]{user.api_key}[/]")
    console.print(f"Credits: [cyan]{user.credits}[/]")


@app.command()
def build(
    idea: str = typer.Argument(..., help="What to build"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a"),
    workdir: Optional[Path] = typer.Option(None, "--workdir", "-C"),
    demo: bool = typer.Option(False, "--demo"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run a full build loop from the terminal."""
    ensure_dirs()
    init_db()
    sec = load_secrets()
    chosen = agent or sec.default_agent
    if not demo:
        try:
            from creation.validate import validate_live_run

            validate_live_run(sec, chosen)
        except RunValidationError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1)
    project = create_project(idea[:80], idea=idea, agent=chosen, workdir=str(workdir) if workdir else None)
    run = create_run(project.id)
    handler = console_event_handler(console, verbose=verbose)
    run_factory(project.id, run.id, demo=demo, on_event=handler)


@app.command()
def status() -> None:
    """Show projects and active runs."""
    ensure_dirs()
    init_db()
    sec = load_secrets()
    table = Table(title="Creation projects")
    table.add_column("ID")
    table.add_column("Idea")
    table.add_column("Status")
    for p in list_projects():
        table.add_row(p.id[:8], (p.idea or "")[:40], p.status or "idle")
    console.print(table)
    if sec.account_email:
        console.print(f"Account: [cyan]{sec.account_email}[/]")


@app.command()
def doctor() -> None:
    """Check account, agents, and first-party services."""
    from creation.account.store import AccountStore
    from creation.memory.factory import memory_status

    sec = load_secrets()
    console.print("[bold]Creation doctor[/]\n")
    acct = AccountStore().get_by_api_key(sec.account_token) if sec.account_token else AccountStore().ensure_local_account()
    console.print(f"Account: {acct.email} · credits {acct.credits}")
    mem = memory_status(sec)
    console.print(f"Prism memory: {mem.get('label')} ({mem.get('resolved')})")
    agents = available_agents()
    avail = [a["id"] for a in agents if a.get("available")]
    console.print(f"Agents on PATH: {', '.join(avail[:8]) or 'none'}")
    console.print(f"Relay GitHub: {'yes' if sec.github_token or acct.github_token else 'optional'}")
    console.print(f"Relay Linear: {'yes' if sec.linear_api_key or acct.linear_api_key else 'optional'}")


@app.command(hidden=True)
def run(*args, **kwargs):  # type: ignore
    """Alias for build."""
    return build(*args, **kwargs)


@app.command(hidden=True)
def update(ref: str = "main", with_deps: bool = False) -> None:
    """Update Creation package."""
    pkg_root = Path(__file__).resolve().parent.parent
    if (pkg_root / ".git").exists():
        subprocess.run(["git", "-C", str(pkg_root), "pull", "--ff-only", "origin", ref], check=False)
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(pkg_root), "--no-deps"], check=False)
    console.print("[green]Updated[/]")


@app.command(hidden=True)
def projects() -> None:
    status()


if __name__ == "__main__":
    app()


def main() -> None:
    app()
