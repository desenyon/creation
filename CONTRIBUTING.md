# Contributing to Creation

Thank you for helping build Creation — the local-first agent operating system with first-party **Forge**, **Lens**, **Prism**, **Relay**, **Pulse**, and **Account**.

## Getting started

1. Fork and clone the repository
2. Run `./bootstrap.sh` and `source .venv/bin/activate`
3. Run `pytest tests -q` — all tests should pass
4. Run `creation doctor` to verify your environment

## What to work on

| Area | Path | Ideas |
|------|------|-------|
| Forge | `creation/services/forge/` | Better heuristics, routing prompts |
| Lens | `creation/services/lens/` | Extractors, research quality |
| Prism | `creation/services/prism/` | Memory ranking, compression |
| Relay | `creation/services/relay/` | GitLab, Jira, more ship targets |
| Pulse | `creation/services/pulse/` | Webhooks, richer templates |
| Studio | `creation/app/` | UX, accessibility |
| Agents | `creation/agents/` | New CLI adapters |

## Code style

- Python 3.10+ with type hints where practical
- Match existing patterns in the module you're editing
- Run `pytest tests -q` before opening a PR
- Keep commits focused — one logical change per commit when possible

## Pull requests

1. Describe what changed and why
2. Link related issues
3. Confirm tests pass
4. Update README if you add user-facing features or CLI commands

## First-party services only

Creation ships with a complete first-party stack. Extend **Forge**, **Lens**, **Prism**, **Relay**, or **Pulse** in `creation/services/` — do not add third-party agent-platform bundles as hard dependencies.

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
