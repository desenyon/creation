"""`creation work` — the agent-OS command surface (tickets, bench, dispatch).

Mounted onto the main CLI as a sub-app so the pivot lives alongside the legacy
build factory. Gated by the ``work_graph_enabled`` flag for mutating actions.
"""

from __future__ import annotations

import time
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from creation.config import load_secrets
from creation.work import store as wstore
from creation.work.bench import agent_by_kind, seed_personal_bench
from creation.work.models import Ticket

app = typer.Typer(name="work", help="Agent OS — tickets, agent bench, and the always-on loop")
console = Console()

_STATUS_STYLE = {
    "backlog": "dim",
    "todo": "cyan",
    "in_progress": "yellow",
    "in_review": "magenta",
    "blocked": "red",
    "done": "green",
    "cancelled": "dim",
}


def _ensure_enabled() -> None:
    if not load_secrets().work_graph_enabled:
        console.print(
            "[yellow]Work graph is off.[/] Enable it with: [bold]creation work enable[/]"
        )
        raise typer.Exit(code=1)


@app.command()
def enable(off: bool = typer.Option(False, "--off", help="Disable the work graph")) -> None:
    """Turn the work graph (tickets + agent bench) on or off."""
    from creation.config import load_secrets as _load, save_secrets

    sec = _load()
    sec.work_graph_enabled = not off
    save_secrets(sec)
    wstore.init_work_db()
    console.print(f"Work graph [bold]{'disabled' if off else 'enabled'}[/].")


@app.command()
def bench(
    reseed: bool = typer.Option(False, "--reseed", help="Recreate the default bench"),
    coding_agent: str = typer.Option("codex", help="Default coding-agent CLI for seeded agents"),
) -> None:
    """Seed (if empty) and list your personal agent bench."""
    _ensure_enabled()
    agents = seed_personal_bench(coding_agent=coding_agent, force=reseed)
    table = Table(title="Personal bench")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Kind")
    table.add_column("Agent")
    table.add_column("Risk")
    table.add_column("Approval")
    table.add_column("Status")
    for a in agents:
        table.add_row(
            a.id, a.name, a.kind, a.coding_agent, a.risk_tier,
            "required" if a.require_approval else "auto", a.status,
        )
    console.print(table)


@app.command("ticket-new")
def ticket_new(
    title: str = typer.Argument(..., help="Ticket title"),
    desc: str = typer.Option("", "--desc", "-d", help="Description / change request"),
    repo: str = typer.Option("", "--repo", help="Repo slug or local path"),
    kind: str = typer.Option("code", "--kind", help="code|migration|test|review|debug|docs|security|performance"),
    priority: str = typer.Option("medium", "--priority", help="low|medium|high|urgent"),
    risk: str = typer.Option("low", "--risk", help="low|medium|high"),
    assign: str = typer.Option("", "--assign", help="Agent id, or a kind (e.g. 'migration') to auto-pick from bench"),
    ready: bool = typer.Option(False, "--ready", help="Mark todo (ready for dispatch) immediately"),
) -> None:
    """Create a ticket and optionally assign it to an agent."""
    _ensure_enabled()
    t = Ticket(
        title=title, description=desc, repo=repo,
        priority=priority, risk_tier=risk,  # type: ignore[arg-type]
        status="todo" if (ready or assign) else "backlog",
    )
    wstore.create_ticket(t)

    if assign:
        agent = wstore.get_agent(assign) or agent_by_kind(assign)
        if not agent:
            console.print(f"[red]No agent found for '{assign}'.[/] Run [bold]creation work bench[/] first.")
            raise typer.Exit(code=1)
        wstore.assign_ticket(t.id, assignee_type="agent", assignee_id=agent.id)
        console.print(f"[green]Created[/] {t.id} → assigned to {agent.name} ({agent.kind})")
    else:
        console.print(f"[green]Created[/] {t.id}  [{t.status}]  {t.title}")


@app.command()
def assign(ticket_id: str = typer.Argument(...), agent: str = typer.Argument(..., help="Agent id or kind")) -> None:
    """Assign a ticket to an agent and mark it ready for dispatch."""
    _ensure_enabled()
    a = wstore.get_agent(agent) or agent_by_kind(agent)
    if not a:
        console.print(f"[red]No agent found for '{agent}'.[/]")
        raise typer.Exit(code=1)
    if not wstore.get_ticket(ticket_id):
        console.print(f"[red]No ticket {ticket_id}.[/]")
        raise typer.Exit(code=1)
    wstore.assign_ticket(ticket_id, assignee_type="agent", assignee_id=a.id)
    wstore.set_ticket_status(ticket_id, "todo")
    console.print(f"[green]Assigned[/] {ticket_id} → {a.name}")


@app.command()
def tickets(status: str = typer.Option("", help="Filter by status")) -> None:
    """Show the board."""
    _ensure_enabled()
    rows = wstore.list_tickets(status=status or None)
    table = Table(title="Board")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Kind/Assignee")
    table.add_column("Title")
    table.add_column("Repo")
    for t in rows:
        assignee = ""
        if t.assignee_type == "agent" and t.assignee_id:
            a = wstore.get_agent(t.assignee_id)
            assignee = a.name if a else t.assignee_id
        st = f"[{_STATUS_STYLE.get(t.status, 'white')}]{t.status}[/]"
        table.add_row(t.id, st, assignee or t.assignee_type, t.title[:50], t.repo[:30])
    console.print(table)


@app.command()
def dispatch(
    limit: Optional[int] = typer.Option(None, help="Max tickets this pass"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Stream agent output"),
) -> None:
    """Run one dispatch pass: pick up ready agent tickets and work them."""
    _ensure_enabled()
    from creation.work.dispatcher import dispatch_once

    on_line = (lambda s: console.print(f"[dim]{s}[/]")) if verbose else None
    results = dispatch_once(secrets=load_secrets(), on_line=on_line, limit=limit)
    if not results:
        console.print("[yellow]Nothing actionable.[/] Assign tickets to agents and mark them ready.")
        return
    for r in results:
        tag = "[green]done[/]" if r.success else "[red]failed[/]"
        console.print(f"{tag} {r.ticket_id} → {r.status}  ({len(r.evidence.files_modified)} files, conf {r.evidence.confidence})")


@app.command()
def watch(
    interval: int = typer.Option(60, help="Seconds between passes"),
    max_passes: int = typer.Option(0, help="Stop after N passes (0 = forever)"),
) -> None:
    """Keep going: dispatch on an interval until interrupted (the always-on loop)."""
    _ensure_enabled()
    from creation.work.dispatcher import dispatch_once

    sec = load_secrets()
    n = 0
    console.print(f"[bold]Creation watch[/] — every {interval}s. Ctrl-C to stop.")
    try:
        while True:
            n += 1
            results = dispatch_once(secrets=sec)
            console.print(f"[dim]pass {n}: ran {len(results)} ticket(s)[/]")
            if max_passes and n >= max_passes:
                break
            time.sleep(max(interval, 1))
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/]")


@app.command("loop-new")
def loop_new(
    template: str = typer.Argument(..., help="flaky-test-killer | dependency-upgrade | docs-drift | bug-backlog"),
    repo: str = typer.Option("", "--repo", help="Scope the loop to a repo"),
    coding_agent: str = typer.Option("codex", help="Coding-agent CLI"),
    no_cron: bool = typer.Option(False, "--no-cron", help="Skip the recurring trigger"),
) -> None:
    """Create a self-sustaining maintenance-loop agent from a template."""
    _ensure_enabled()
    from creation.work.bench import LOOP_TEMPLATES, create_loop_agent

    if template not in LOOP_TEMPLATES:
        console.print(f"[red]Unknown template.[/] Options: {', '.join(LOOP_TEMPLATES)}")
        raise typer.Exit(code=1)
    agent, trigger = create_loop_agent(
        template, repo=repo, coding_agent=coding_agent, with_cron=not no_cron
    )
    console.print(f"[green]Created loop[/] {agent.name} ({agent.id})")
    if trigger:
        every = trigger.config.get("every_seconds")
        console.print(f"  cron trigger {trigger.id} · every {every}s")


@app.command("trigger-cron")
def trigger_cron(
    agent: str = typer.Argument(..., help="Agent id or kind"),
    every: int = typer.Option(86400, "--every", help="Interval in seconds"),
    title: str = typer.Option(..., "--title", help="Ticket title to spawn"),
    repo: str = typer.Option("", "--repo"),
    priority: str = typer.Option("medium", "--priority"),
) -> None:
    """Add a recurring trigger that spawns a ticket on an interval."""
    _ensure_enabled()
    from creation.work.triggers import create_cron_trigger

    a = wstore.get_agent(agent) or agent_by_kind(agent)
    if not a:
        console.print(f"[red]No agent for '{agent}'.[/]")
        raise typer.Exit(code=1)
    trg = create_cron_trigger(
        a.id, every_seconds=every, ticket={"title": title, "repo": repo, "priority": priority}
    )
    console.print(f"[green]Cron trigger[/] {trg.id} → {a.name} every {every}s")


@app.command()
def triggers() -> None:
    """List triggers."""
    _ensure_enabled()
    table = Table(title="Triggers")
    table.add_column("ID")
    table.add_column("Kind")
    table.add_column("Agent")
    table.add_column("Config")
    table.add_column("Enabled")
    for t in wstore.list_triggers():
        a = wstore.get_agent(t.agent_id)
        table.add_row(t.id, t.kind, (a.name if a else t.agent_id), str(t.config)[:50], "✓" if t.enabled else "—")
    console.print(table)


@app.command()
def tick() -> None:
    """Fire any due cron triggers now (without running a full dispatch)."""
    _ensure_enabled()
    from creation.work.triggers import tick as _tick

    created = _tick()
    console.print(f"Fired triggers → [green]{len(created)}[/] new ticket(s)")
    for t in created:
        console.print(f"  {t.id}  {t.title}")


@app.command("mission-new")
def mission_new(
    title: str = typer.Argument(...),
    goal: str = typer.Option("", "--goal"),
    team: str = typer.Option("", "--team", help="Team id (company-wide scope)"),
) -> None:
    """Create a company-wide mission."""
    _ensure_enabled()
    from creation.work.models import Mission

    m = Mission(title=title, goal=goal, team_id=team or None, visibility="team" if team else "private")
    wstore.create_mission(m)
    console.print(f"[green]Mission[/] {m.id}  {m.title}")


@app.command("mission-fanout")
def mission_fanout(
    mission_id: str = typer.Argument(...),
    repos: str = typer.Option(..., "--repos", help="Comma-separated repos"),
    agent: str = typer.Option(..., "--agent", help="Agent id or kind"),
    title: str = typer.Option(..., "--title", help="Ticket title ('{repo}' interpolated)"),
    risk: str = typer.Option("low", "--risk"),
) -> None:
    """Fan a mission out into one child ticket per repo."""
    _ensure_enabled()
    from creation.work.missions import fan_out_across_repos

    repo_list = [r.strip() for r in repos.split(",") if r.strip()]
    created = fan_out_across_repos(mission_id, repo_list, agent=agent, title=title, risk_tier=risk)
    console.print(f"[green]Fanned out[/] {len(created)} ticket(s) for mission {mission_id}")
    for t in created:
        console.print(f"  {t.id}  {t.repo}  [{t.status}]")


@app.command()
def mission(mission_id: str = typer.Argument(...)) -> None:
    """Show mission progress."""
    _ensure_enabled()
    from creation.work.missions import mission_progress, sync_mission_status

    sync_mission_status(mission_id)
    prog = mission_progress(mission_id)
    m = wstore.get_mission(mission_id)
    console.print(f"[bold]{m.title if m else mission_id}[/] — {m.status if m else '?'}")
    console.print(f"  {prog['done']}/{prog['total']} done ({prog['done_pct']}%)  {prog['by_status']}")


@app.command()
def metrics() -> None:
    """Bench quality metrics (acceptance rate, confidence, review load)."""
    _ensure_enabled()
    from creation.work.evals import bench_metrics

    table = Table(title="Agent SLOs")
    table.add_column("Agent")
    table.add_column("Kind")
    table.add_column("Assigned")
    table.add_column("Done")
    table.add_column("Review")
    table.add_column("Blocked")
    table.add_column("Accept%")
    table.add_column("Conf")
    for m in bench_metrics():
        table.add_row(
            m["name"], m["kind"], str(m["assigned"]), str(m["done"]),
            str(m["in_review"]), str(m["blocked"]),
            f"{m['acceptance_rate'] * 100:.0f}", f"{m['avg_confidence']:.2f}",
        )
    console.print(table)


@app.command()
def approve(
    ticket_id: str = typer.Argument(...),
    ship: bool = typer.Option(False, "--ship", help="Open a PR with the change"),
    github_url: str = typer.Option("", "--github-url"),
) -> None:
    """Approve an in-review ticket (optionally ship a PR)."""
    _ensure_enabled()
    from creation.work.review import approve_ticket

    try:
        res = approve_ticket(ticket_id, ship=ship, github_url=github_url)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=1)
    console.print(f"[green]Approved[/] {ticket_id} → {res.status}" + (f"  PR: {res.pr_url}" if res.pr_url else ""))


@app.command()
def reject(
    ticket_id: str = typer.Argument(...),
    feedback: str = typer.Option(..., "--feedback", "-m", help="What needs to change"),
    block: bool = typer.Option(False, "--block", help="Block for a human instead of requeueing"),
) -> None:
    """Reject an in-review ticket with feedback (requeues for another attempt)."""
    _ensure_enabled()
    from creation.work.review import reject_ticket

    try:
        res = reject_ticket(ticket_id, feedback, requeue=not block)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=1)
    console.print(f"[yellow]Rejected[/] {ticket_id} → {res.status}")


@app.command()
def audit(
    entity_id: str = typer.Option("", "--entity", help="Filter by entity id"),
    limit: int = typer.Option(30, "--limit"),
) -> None:
    """Show the audit log."""
    _ensure_enabled()
    from creation.work.audit import list_events

    table = Table(title="Audit log")
    table.add_column("When")
    table.add_column("Actor")
    table.add_column("Action")
    table.add_column("Entity")
    for e in list_events(entity_id=entity_id or None, limit=limit):
        table.add_row(e.created_at[:19], f"{e.actor_type}:{e.actor}"[:24], e.action, f"{e.entity_type}/{e.entity_id}"[:30])
    console.print(table)


@app.command()
def playbook(
    kind: str = typer.Option("", "--kind", help="Filter by agent kind"),
    repo: str = typer.Option("", "--repo"),
) -> None:
    """Show learned lessons (the playbook memory)."""
    _ensure_enabled()
    from creation.work.playbook import list_lessons

    rows = list_lessons(kind=kind or None, repo=repo or None)
    if not rows:
        console.print("[yellow]No lessons yet.[/] They accrue as agents run.")
        return
    for ls in rows:
        flag = "[red]⚠[/]" if ls.outcome == "blocked" else "•"
        console.print(f"{flag} [{ls.kind}] {ls.repo or '—'}: {ls.lesson[:120]}")


@app.command()
def evidence(ticket_id: str = typer.Argument(...)) -> None:
    """Show evidence packs for a ticket (what the agent did + risks)."""
    _ensure_enabled()
    packs = wstore.list_evidence_for_ticket(ticket_id)
    if not packs:
        console.print("[yellow]No evidence yet.[/]")
        return
    for p in packs:
        console.print(f"[bold]{p.id}[/]  run={p.run_id}  conf={p.confidence}")
        console.print(f"  plan: {p.plan or '—'}")
        console.print(f"  files: {', '.join(p.files_modified) or '—'}")
        console.print(f"  tests: {p.tests_run or '—'}")
        if p.risks:
            console.print(f"  [red]risks:[/] {', '.join(p.risks)}")
