"""Creation terminal UI — simplified."""

from __future__ import annotations

import json
from typing import Optional

import httpx
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, RichLog, Static, TextArea

DEFAULT_BASE = "http://127.0.0.1:8787"


class CreationApp(App):
    CSS = """
    Screen { background: #09090b; }
  #sidebar { width: 28; background: #121214; border-right: solid #2a2a32; padding: 1; }
  #log { height: 1fr; background: #000; border: solid #2a2a32; }
  Button.primary { background: #f97316; color: #111; }
  .title { color: #f97316; text-style: bold; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("b", "focus_build", "Build"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, base_url: str = DEFAULT_BASE) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("CREATION", classes="title")
                yield Button("Refresh", id="refresh")
                yield Button("Doctor", id="doctor")
            with Vertical():
                yield Static("Idea")
                yield TextArea(id="idea")
                yield Input(placeholder="Workdir (optional)", id="workdir")
                yield Button("Build", id="build", variant="primary")
                yield RichLog(id="log", highlight=True, markup=True)
        yield Footer()

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=60.0)

    @on(Button.Pressed, "#build")
    def on_build(self) -> None:
        idea = self.query_one("#idea", TextArea).text.strip()
        workdir = self.query_one("#workdir", Input).value.strip()
        if not idea:
            self.query_one("#log", RichLog).write("[red]Enter an idea[/]")
            return
        self._start_build(idea, workdir)

    @on(Button.Pressed, "#refresh")
    def on_refresh(self) -> None:
        self.action_refresh()

    @on(Button.Pressed, "#doctor")
    def on_doctor(self) -> None:
        import subprocess
        import sys

        subprocess.Popen([sys.executable, "-m", "creation.completion_cli", "doctor"])

    @work(thread=True)
    def _start_build(self, idea: str, workdir: str) -> None:
        log = self.query_one("#log", RichLog)
        try:
            with self._client() as c:
                body = {"idea": idea}
                if workdir:
                    body["workdir"] = workdir
                p = c.post("/api/projects", json=body).json()
                run = c.post(f"/api/projects/{p['id']}/run", json={}).json()
                run_id = run.get("run_id")
                self.call_from_thread(log.write, f"[green]Run {str(run_id)[:8]} started[/]")
                with c.stream("GET", f"/api/runs/{run_id}/stream") as stream:
                    for line in stream.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            ev = json.loads(payload)
                            msg = ev.get("line") or ev.get("message") or json.dumps(ev)[:120]
                        except json.JSONDecodeError:
                            msg = payload
                        self.call_from_thread(log.write, str(msg))
        except Exception as exc:
            self.call_from_thread(log.write, f"[red]{exc}[/]")

    def action_refresh(self) -> None:
        self.query_one("#log", RichLog).write("Refreshed")

    def action_focus_build(self) -> None:
        self.query_one("#idea", TextArea).focus()


def run_tui(base_url: str = DEFAULT_BASE) -> None:
    CreationApp(base_url=base_url).run()
