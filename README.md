<p align="center">
  <img src="creation/app/assets/img/logo.svg" alt="Creation" width="96" height="96" />
</p>

<h1 align="center">Creation</h1>

<p align="center">
  <strong>Turn an idea into shipped software — on your machine, with your agents.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-orange?style=flat-square" alt="MIT License" /></a>
  <a href="https://github.com/desenyon/creation/actions/workflows/ci.yml"><img src="https://github.com/desenyon/creation/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square" alt="Python 3.10+" /></a>
  <img src="https://img.shields.io/badge/tests-245%20passing-brightgreen?style=flat-square" alt="245 tests passing" />
  <img src="https://img.shields.io/badge/agents-43%20CLIs-blueviolet?style=flat-square" alt="43 coding CLIs" />
</p>

---

**Creation** is a local-first agent operating system. You describe what you want built — a new product, a feature in an existing repo, a fix, a launch — and Creation runs a full autonomous loop: research the problem, plan the work, write code with the terminal agent you already use, test it, sync to GitHub and Linear, and notify you when it ships.

Everything runs on your hardware for builds. Your Codex, Claude Code, Cursor, or Gemini CLI stays on your PATH. **Creation Cloud** ([creation.dev](https://creation.dev)) hosts your account, API key, credits, and Forge planning — so you sign in once and the CLI syncs automatically.

Open **Creation Studio** locally, or drive everything from the terminal UI.

---

## What you get

| Capability | What Creation does |
|------------|-------------------|
| **Autonomous builds** | Multi-turn loop — research once, then code → test → ship → repeat until done |
| **Existing repos** | Point at a workdir; Creation edits in place and respects your stack |
| **43 coding agents** | Orchestrates whatever CLIs you have installed — Codex, Claude, Cursor, Gemini, Copilot, and more |
| **Honest ship receipts** | Proof bundles that only claim what actually happened (commits, issues, tests) |
| **Studio + TUI** | Dark terminal aesthetic in the browser; full control from `creation` in the shell |
| **Demo mode** | `creation build --demo` exercises the entire loop without live credentials |

---

## How it works

```
  Your idea
      │
      ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Research   │ ──▶ │ Plan & brand │ ──▶ │ Agent loop  │
│  (once)     │     │              │     │ code·QA·ship│
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                │
                    ┌───────────────────────────┘
                    ▼
            GitHub · Linear · notify
```

1. **Kickoff** — Creation researches your idea and drafts a build plan and product name.
2. **Loop** — Each turn: recall memory, compress context, invoke your coding agent, run pytest and browser QA, sync through Relay.
3. **Ship** — Progress lands on GitHub and Linear; Pulse can queue launch comms when you're ready.

The loop is built for long runs (up to 200 turns) with token-aware context compression so agents stay within budget without losing critical detail.

---

## Quick start

### One-command install

```bash
curl -fsSL https://creation.dev/install | bash
```

This installs Creation, points the CLI at **Creation Cloud** (`CREATION_CLOUD_URL`), and launches the setup wizard.

Or create an account at [creation.dev/account](https://creation.dev/account) first, then install.

### Manual install

```bash
pip install git+https://github.com/desenyon/creation.git
export CREATION_CLOUD_URL=https://creation.dev
creation setup
```

Use `creation setup --yes` for non-interactive defaults, or `creation setup --reinstall` to run the wizard again.

### Sign in and open Studio

```bash
creation login
creation serve
```

Open **http://127.0.0.1:8787/dashboard** — Creation Studio.

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
| `creation setup` | Interactive install + configuration shell |
| `creation` | Open terminal UI (runs setup on first launch) |
| `creation serve` | Start Creation Studio |
| `creation login` | Sign in / create account |
| `creation build "…"` | Run full autonomous build loop |
| `creation status` | List local projects |
| `creation doctor` | Check account, agents, and integrations |
| `creation tui` | Terminal UI (requires `serve`) |

---

## Built-in stack

Creation ships with a complete first-party stack — no external SaaS bundles required. One login, one credit balance, one design language.

| Service | Role |
|---------|------|
| **Account** | Sign-in, API key (`crt_live_…`), credits, credential storage |
| **Forge** | Planning brain — build plans, branding, turn routing |
| **Lens** | Web research and page extraction — works without API keys |
| **Prism** | Episodic memory + context compression before each agent turn |
| **Relay** | Native GitHub and Linear — repos, issues, kanban, PRs |
| **Pulse** | Local notification inbox + optional SMTP on ship |

These are selling points, not dependencies you wire up yourself. They are maintained as part of Creation and exposed through Studio, the CLI, and `/api/*`.

---

## Creation Cloud (Vercel)

The marketing site and hosted APIs live at **[creation.dev](https://creation.dev)** — deployed from the `website/` Next.js app.

| Hosted on Cloud | Runs locally |
|-----------------|--------------|
| Account register / login / API keys | Build orchestrator & agents |
| Credits & Forge `/api/forge/v1` | Prism memory, Lens research |
| Web dashboard at `/account` | Studio UI (`creation serve`) |
| Tester feedback API | Relay, git, Playwright QA |

**Cloud API endpoints**

| Endpoint | Purpose |
|----------|---------|
| `POST /api/account/register` | Create account + `crt_live_…` key |
| `POST /api/account/login` | Sign in |
| `GET /api/account/me` | Profile (Bearer API key) |
| `PUT /api/account/credentials` | Relay tokens |
| `POST /api/forge/v1/chat/completions` | Forge planning |
| `GET /api/health` | Service status |

**Deploy the website**

```bash
cd website && npm install && npm run build
vercel --prod   # link repo root; uses vercel.json
```

Link **Vercel KV** in the project dashboard for persistent accounts. Set `OPENAI_API_KEY` on Vercel for stronger Forge responses.

---

## Configuration

All state lives under `~/.creation/`:

| Path | Purpose |
|------|---------|
| `config.json` | Agent defaults, Relay tokens, Forge settings |
| `account.db` | Users, credits, usage |
| `prism.db` | Episodic memory |
| `pulse/` | Notification inbox |
| `projects/` | Managed project workdirs |
| `creation.db` | Build history |

| Variable | Purpose |
|----------|---------|
| `CREATION_CLOUD_URL` | Cloud API base (default in install: `https://creation.dev`) |
| `CREATION_DEMO=1` | Demo mode — no live Relay calls |
| `OPENAI_API_KEY` | Optional Forge backend (cloud or local) |
| `CREATION_FORGE_URL` | Override Forge endpoint |

---

## Relay setup (optional)

For live ships, connect in Studio → **Relay**:

- **GitHub** — personal access token with `repo` scope
- **Linear** — API key from Linear settings
- **Notify email** — where Pulse sends progress

Demo mode skips live Relay and still exercises the full loop.

---

## Coding agents

Run `creation doctor` to see what's on your PATH. Set default in Studio or `config.json`:

```json
{ "default_agent": "codex" }
```

See `creation/agents/registry.py` for the full list of supported CLIs.

---

## Development

```bash
git clone https://github.com/desenyon/creation.git
cd creation
./bootstrap.sh
source .venv/bin/activate
pytest tests -q
creation doctor
creation serve
```

```
creation/
├── website/           # Next.js site + Vercel API routes
├── cloud/             # Python client for Creation Cloud
├── account/           # Auth, credits (local fallback)
├── services/          # Forge, Lens, Prism, Relay, Pulse
├── agents/            # Coding CLI adapters
├── orchestrator.py    # Multi-turn build loop
├── server.py          # FastAPI + Studio (local)
└── app/               # Studio static assets
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome — especially Studio UX, agent adapters, Relay targets, and Prism policies.

---

## Security

See [SECURITY.md](SECURITY.md). Report vulnerabilities privately via GitHub Security Advisories.

---

## License

MIT — see [LICENSE](LICENSE).

---

<p align="center">
  <sub>Creation · Cloud account · Local builds · Your agents</sub>
</p>
