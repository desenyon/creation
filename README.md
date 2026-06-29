<p align="center">
  <img src="creation/app/assets/img/logo.svg" alt="Creation" width="96" height="96" />
</p>

<h1 align="center">Creation</h1>

<p align="center">
  <strong>The local-first agent operating system.</strong><br/>
  One account. Five first-party services. Forty-three coding agents on your machine.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-orange?style=flat-square" alt="MIT License" /></a>
  <a href="https://github.com/desenyon/creation/actions/workflows/ci.yml"><img src="https://github.com/desenyon/creation/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square" alt="Python 3.10+" /></a>
  <img src="https://img.shields.io/badge/tests-241%20passing-brightgreen?style=flat-square" alt="241 tests passing" />
  <img src="https://img.shields.io/badge/agents-43%20CLIs-blueviolet?style=flat-square" alt="43 coding CLIs" />
</p>

---

Creation is a **local-first agent operating system** for builders who want autonomous software delivery without stitching together a dozen third-party APIs. You sign in once, get a single API key and credit balance, and run an entire stack — research, planning, memory, shipping, and notifications — built and maintained by Creation.

Give Creation an idea. It researches with **Lens**, plans with **Forge**, compresses context with **Prism**, codes with your agent of choice (Codex, Claude Code, Cursor, Gemini, …), tests in a loop, and ships through **Relay** to GitHub and Linear. **Pulse** handles notifications. Everything runs on your machine. Your coding agents stay on your PATH. Your ship credentials stay in your account.

<p align="center">
  <img src="creation/app/assets/img/logo.svg" alt="Creation mark" width="48" height="48" />
</p>

## Why Creation exists

Most “agent OS” products are thin wrappers around Composio, Tavily, Nebius, Mem0, and a hosted dashboard. Creation takes the opposite approach: **every pillar is first-party**. One login. One bill. One design language. No vendor patchwork.

| Problem | Creation's answer |
|--------|-------------------|
| Scattered API keys | **Account** — `creation login`, `crt_live_…` key, credits |
| Weak research deps | **Lens** — DuckDuckGo search + local scrape, no API key |
| Expensive planning APIs | **Forge** — OpenAI-compatible brain on your account credits |
| Memory vendor lock-in | **Prism** — SQLite episodic memory + neural compression |
| Composio for GitHub/Linear | **Relay** — native REST + GraphQL |
| Resend/Ayrshare/Gmail glue | **Pulse** — local inbox + optional SMTP |

---

## The Creation stack

```
┌─────────────────────────────────────────────────────────────┐
│                     Creation Account                        │
│          login · API key · credits · Relay creds            │
└──────────────────────────┬──────────────────────────────────┘
                           │
     ┌─────────────────────┼─────────────────────┐
     ▼                     ▼                     ▼
  ┌──────┐   ┌──────┐   ┌──────┐   ┌──────┐   ┌──────┐
  │ Forge│   │ Lens │   │ Prism│   │ Relay│   │ Pulse│
  │ plan │   │search│   │memory│   │ ship │   │notify│
  └──┬───┘   └──┬───┘   └──┬───┘   └──┬───┘   └──┬───┘
     │          │          │          │          │
     └──────────┴──────────┴────┬─────┴──────────┘
                                ▼
                    ┌───────────────────────┐
                    │   Coding agent CLIs   │
                    │ Codex · Claude · Cursor│
                    │ Gemini · Copilot · …  │
                    └───────────────────────┘
```

### Forge — planning brain

Forge is Creation's orchestration LLM. It writes build plans, brands products, routes turns, syncs Linear boards, and drafts progress updates. Calls go through `/api/forge/v1` and deduct **Account credits**. Optional: set `OPENAI_API_KEY` for stronger completions while still metering through Creation.

### Lens — research

Lens replaces external search and scrape APIs. It uses DuckDuckGo for ideation research and HTTP extraction for competitor pages. No API keys. Works offline in `--demo` mode.

### Prism — memory and compression

Prism stores episodic facts in local SQLite (`~/.creation/prism.db`) and runs a learned **context compression policy** before each agent turn — keeping answer-critical lines, evicting noise. Typical savings: ~35–65% tokens per turn depending on budget.

### Relay — ship integrations

Relay talks directly to GitHub (REST) and Linear (GraphQL). Connect tokens once in Account settings. Supports repo creation, file sync, issue tracking, kanban updates, and PR bodies — no middleware.

### Pulse — notifications

Pulse writes notifications to `~/.creation/pulse/` and can send via SMTP when configured. Launch marketing queues email + social drafts on ship — no Resend or Ayrshare required.

### Account — single sign-on

```bash
creation login
```

Creates a local account at `~/.creation/account.db` with email, password, `crt_live_…` API key, and 500,000 starter credits. Relay credentials and usage history live on the same profile.

---

## Quick start

### Install

```bash
pip install git+https://github.com/desenyon/creation.git
# or from a checkout:
pip install -e .
```

### Sign in and open Studio

```bash
creation login
creation serve
```

Open **http://127.0.0.1:8787/dashboard** — the Creation Studio (dark terminal UI).

### Build from the terminal

```bash
creation build "A CLI that turns Linear issues into markdown files"
creation build --demo "Todo app in Python"          # no live keys needed
creation build -C ~/code/my-app "Add OAuth login"   # edit existing repo
```

### Terminal UI

```bash
creation serve    # in one tab
creation          # or: creation tui — in another tab
```

---

## CLI reference

| Command | Description |
|---------|-------------|
| `creation` | Open terminal UI (default) |
| `creation serve` | Start Creation Studio web UI |
| `creation login` | Sign in / create account |
| `creation build "…"` | Run full autonomous build loop |
| `creation status` | List local projects |
| `creation doctor` | Check account, Prism, agents, Relay |
| `creation tui` | Terminal UI (requires `serve`) |

---

## Configuration

All state lives under `~/.creation/`:

| Path | Purpose |
|------|---------|
| `config.json` | Agent defaults, Relay tokens, Forge settings |
| `account.db` | Users, credits, usage |
| `prism.db` | Prism episodic memory |
| `pulse/` | Notification inbox |
| `projects/` | Managed project workdirs |
| `creation.db` | Build history (SQLite) |

Environment variables:

| Variable | Purpose |
|----------|---------|
| `CREATION_DEMO=1` | Demo mode — no live Relay/Forge calls |
| `OPENAI_API_KEY` | Optional Forge backend for stronger planning |
| `CREATION_FORGE_URL` | Override Forge endpoint (default: local server) |

---

## Architecture

```
creation/
├── account/           # Auth, credits, usage
├── services/
│   ├── forge/         # Planning LLM client + API
│   ├── lens/          # Search + scrape
│   ├── prism/         # Memory + compression
│   ├── relay/         # GitHub + Linear
│   └── pulse/         # Notifications
├── agents/            # 43 coding CLI adapters
├── orchestrator.py    # Multi-turn build loop
├── server.py          # FastAPI + Studio
├── tui.py             # Textual terminal UI
└── app/               # Studio static assets
```

### Build loop (simplified)

1. **Lens** — one-time web research + scrape  
2. **Relay** — verify ship targets  
3. **Forge** — plan + brand  
4. **Loop** (up to 200 turns): Prism compress → agent code → pytest + browser QA → Relay sync → Forge route  
5. **Pulse** — optional launch comms on ship  
6. **Ship receipt** — proof bundle (GitHub, Linear, stats)

---

## Coding agents

Creation orchestrates **43 terminal-native coding CLIs**. Run `creation doctor` to see what's on your PATH. Set default in Studio or `config.json`:

```json
{ "default_agent": "codex" }
```

Supported agents include Codex, Claude Code, Cursor Agent, Gemini CLI, GitHub Copilot CLI, OpenClaw, Freebuff, Kimi, OpenCode, and more — see `creation/agents/registry.py`.

---

## Relay setup (optional for live ships)

In Studio → **Relay**, or via API:

- **GitHub** — personal access token with `repo` scope  
- **Linear** — API key from Linear settings  
- **Notify email** — where Pulse sends progress  

Demo mode (`creation build --demo`) skips live Relay and still exercises the full loop.

---

## Development

```bash
git clone https://github.com/desenyon/creation.git
cd creation
./bootstrap.sh
source .venv/bin/activate
pytest tests -q          # 241 tests
creation doctor
creation serve
```

### Project layout

| Directory | Contents |
|-----------|----------|
| `tests/` | Pytest suite |
| `web/` | Marketing site |
| `creation/app/` | Bundled Studio UI |
| `.github/workflows/` | CI |

---

## Testing

```bash
pytest tests -q
```

Covers Prism compression, Relay ops, Forge client, Lens research, Account store, orchestrator paths, and API endpoints.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). We welcome issues and PRs for Forge heuristics, Lens extractors, Prism policies, Relay integrations, and Studio UX.

---

## Security

See [SECURITY.md](SECURITY.md). Report vulnerabilities privately via GitHub Security Advisories.

---

## License

MIT — see [LICENSE](LICENSE).

---

<p align="center">
  <sub>Built with Creation · Local-first · Your machine · Your agents</sub>
</p>
