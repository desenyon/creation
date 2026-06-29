"""Creation setup TUI — one-command install + configure shell."""

from __future__ import annotations

from typing import List, Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Label, RadioButton, RadioSet, Static

from creation.setup_wizard import (
    DoctorReport,
    bootstrap_environment,
    create_account,
    doctor_report,
    list_agent_choices,
    mark_setup_complete,
    pick_default_agent,
    save_default_agent,
    save_relay_credentials,
    sign_in,
)

STEPS = ["Welcome", "Account", "Agents", "Relay", "Done"]


class StepRail(Static):
    """Left rail showing setup progress."""

    def __init__(self) -> None:
        super().__init__(id="rail")
        self.current = 0
        self.done: set[int] = set()

    def set_step(self, index: int) -> None:
        self.current = index
        self.refresh_rail()

    def mark_done(self, index: int) -> None:
        self.done.add(index)
        self.refresh_rail()

    def refresh_rail(self) -> None:
        lines: List[str] = []
        for i, name in enumerate(STEPS):
            if i in self.done:
                mark = "[x]"
            elif i == self.current:
                mark = ">"
            else:
                mark = " "
            lines.append(f"{mark} {name}")
        self.update("\n".join(lines))


class SetupApp(App):
    """Interactive setup shell for Creation."""

    CSS = """
    Screen { background: #09090b; }
    #rail-wrap { width: 22; background: #121214; border-right: solid #2a2a32; padding: 1 1; }
    #main { padding: 1 2; width: 1fr; }
    .brand { color: #f97316; text-style: bold; margin-bottom: 1; }
    .lead { color: #a1a1aa; margin: 1 0; }
    .error { color: #f87171; margin-top: 1; }
    .ok { color: #4ade80; margin-top: 1; }
    .step-title { text-style: bold; margin-bottom: 1; }
    Input { margin: 0 0 1 0; }
    Label { margin-top: 1; color: #a1a1aa; }
    Button.primary { background: #f97316; color: #111; margin: 1 1 0 0; }
    Button { margin: 1 1 0 0; }
    RadioSet { margin: 1 0; height: auto; max-height: 14; }
    #summary { background: #121214; border: solid #2a2a32; padding: 1; margin-top: 1; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    def __init__(self, *, finish_action: str = "tui") -> None:
        super().__init__()
        self.step = 0
        self.finish_action = finish_action
        self._account_mode = "create"
        self._report: Optional[DoctorReport] = None
        self._error = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            with Vertical(id="rail-wrap"):
                yield Static("CREATION", classes="brand")
                yield Static("SETUP", classes="brand")
                yield StepRail()
            with VerticalScroll(id="main"):
                yield Static("", id="step-body")
        yield Footer()

    def on_mount(self) -> None:
        bootstrap_environment()
        self._show_step(0)

    def _rail(self) -> StepRail:
        return self.query_one(StepRail)

    def _body(self) -> Static:
        return self.query_one("#step-body", Static)

    def _show_step(self, index: int) -> None:
        self.step = index
        self._error = ""
        self._rail().set_step(index)
        handlers = [
            self._render_welcome,
            self._render_account,
            self._render_agents,
            self._render_relay,
            self._render_done,
        ]
        handlers[index]()

    def _render_welcome(self) -> None:
        self._body().update(
            "[b]Welcome to Creation[/b]\n\n"
            "This wizard installs your local agent OS in a few steps:\n"
            "  · Creation account (credits + API key)\n"
            "  · Coding agent on your PATH\n"
            "  · Optional GitHub / Linear for live ships\n\n"
            "Everything stays on this machine under [cyan]~/.creation/[/].\n\n"
            "[dim]Press the button or Enter to continue[/]"
        )
        self._mount_action(Button("Start setup", id="next-primary", variant="primary", classes="primary"))

    def _render_account(self) -> None:
        self._body().update(
            "[b]Your Creation account[/b]\n\n"
            "One account powers planning, research, and memory. "
            "Create a new account or sign in to an existing one.\n"
        )
        self._mount_action(Label("Email"))
        self._mount_action(Input(placeholder="you@example.com", id="email"))
        self._mount_action(Label("Password"))
        self._mount_action(Input(password=True, id="password"))
        self._mount_action(Button("Create account", id="acct-create", variant="primary", classes="primary"))
        self._mount_action(Button("Sign in", id="acct-signin"))
        self._mount_action(Button("Back", id="back"))

    def _render_agents(self) -> None:
        choices = list_agent_choices()
        avail = [(i, label) for i, label, ok in choices if ok]
        default = pick_default_agent()
        lines = ["[b]Default coding agent[/b]\n", "Creation orchestrates terminal agents already on your PATH.\n"]
        if not avail:
            lines.append("[yellow]No agents detected yet.[/] Install Codex, Claude Code, or Cursor CLI, then re-run [cyan]creation doctor[/].\n")
            lines.append(f"Default will be set to [cyan]{default}[/].\n")
        self._body().update("\n".join(lines))
        if avail:
            buttons = [
                RadioButton(f"{label} ({agent_id})", id=f"agent-{agent_id}", value=agent_id == default)
                for agent_id, label in avail[:12]
            ]
            self._mount_action(RadioSet(*buttons, id="agent-radio"))
        self._mount_action(Button("Continue", id="next-primary", variant="primary", classes="primary"))
        self._mount_action(Button("Back", id="back"))

    def _render_relay(self) -> None:
        self._body().update(
            "[b]Relay — ship to GitHub & Linear[/b]\n\n"
            "Optional. Skip to use demo mode, or add tokens now for live ships.\n"
        )
        self._mount_action(Label("GitHub token (repo scope)"))
        self._mount_action(Input(password=True, id="github-token"))
        self._mount_action(Label("Linear API key"))
        self._mount_action(Input(password=True, id="linear-key"))
        self._mount_action(Label("Linear team ID"))
        self._mount_action(Input(id="linear-team"))
        self._mount_action(Label("Notify email"))
        self._mount_action(Input(placeholder="you@example.com", id="notify-email"))
        self._mount_action(Button("Save & continue", id="relay-save", variant="primary", classes="primary"))
        self._mount_action(Button("Skip for now", id="relay-skip"))
        self._mount_action(Button("Back", id="back"))

    def _render_done(self) -> None:
        mark_setup_complete()
        self._report = doctor_report()
        summary = "\n".join(f"  {line}" for line in self._report.lines())
        self._body().update(
            "[b]Creation is ready[/b]\n\n"
            f"[green]Setup complete.[/] Your local stack:\n\n{summary}\n\n"
            "What next?"
        )
        self._mount_action(Button("Open terminal UI", id="finish-tui", variant="primary", classes="primary"))
        self._mount_action(Button("Start Studio", id="finish-serve"))
        self._mount_action(Button("Run demo build", id="finish-demo"))

    def _main_panel(self) -> VerticalScroll:
        return self.query_one("#main", VerticalScroll)

    def _clear_actions(self) -> None:
        panel = self._main_panel()
        for selector in ("Button", "Input", "Label", "RadioSet"):
            for node in list(panel.query(selector)):
                node.remove()

    def _mount_action(self, *widgets) -> None:
        panel = self._main_panel()
        for w in widgets:
            panel.mount(w)

    def _advance(self) -> None:
        self._clear_actions()
        self._rail().mark_done(self.step)
        self._show_step(min(self.step + 1, len(STEPS) - 1))

    def _back(self) -> None:
        if self.step == 0:
            return
        self._clear_actions()
        self._show_step(self.step - 1)

    def _show_error(self, message: str) -> None:
        self._error = message
        body = self._body()
        text = str(body.renderable) if body.renderable is not None else ""
        if "[red]" not in text:
            body.update(f"{text}\n\n[red]{message}[/]")

    @on(Button.Pressed, "#next-primary")
    def on_next_primary(self) -> None:
        if self.step == 2:
            selected = self._selected_agent()
            save_default_agent(selected)
        self._advance()

    @on(Button.Pressed, "#back")
    def on_back(self) -> None:
        self._back()

    @on(Button.Pressed, "#acct-create")
    def on_create(self) -> None:
        email = self.query_one("#email", Input).value.strip()
        password = self.query_one("#password", Input).value
        if not email or not password:
            self._show_error("Email and password are required.")
            return
        try:
            create_account(email, password)
            self._advance()
        except ValueError as exc:
            self._show_error(str(exc))

    @on(Button.Pressed, "#acct-signin")
    def on_signin(self) -> None:
        email = self.query_one("#email", Input).value.strip()
        password = self.query_one("#password", Input).value
        if not email or not password:
            self._show_error("Email and password are required.")
            return
        try:
            sign_in(email, password)
            self._advance()
        except ValueError as exc:
            self._show_error(str(exc))

    @on(Button.Pressed, "#relay-save")
    def on_relay_save(self) -> None:
        save_relay_credentials(
            github_token=self.query_one("#github-token", Input).value,
            linear_api_key=self.query_one("#linear-key", Input).value,
            linear_team_id=self.query_one("#linear-team", Input).value,
            notify_email=self.query_one("#notify-email", Input).value,
        )
        self._advance()

    @on(Button.Pressed, "#relay-skip")
    def on_relay_skip(self) -> None:
        self._advance()

    @on(Button.Pressed, "#finish-tui")
    def on_finish_tui(self) -> None:
        self.finish_action = "tui"
        self.exit()

    @on(Button.Pressed, "#finish-serve")
    def on_finish_serve(self) -> None:
        self.finish_action = "serve"
        self.exit()

    @on(Button.Pressed, "#finish-demo")
    def on_finish_demo(self) -> None:
        self.finish_action = "demo"
        self.exit()

    def _selected_agent(self) -> str:
        try:
            radio = self.query_one("#agent-radio", RadioSet)
        except Exception:
            return pick_default_agent()
        pressed = radio.pressed_button
        if not pressed or not pressed.id:
            return pick_default_agent()
        return pressed.id.replace("agent-", "", 1)


def run_setup_tui() -> str:
    """Run setup shell. Returns finish action: tui, serve, or demo."""
    app = SetupApp()
    app.run()
    return app.finish_action
