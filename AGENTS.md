# Working in the Creation repo

House rules for any coding agent (or human) making changes here. Keep them short;
follow them every time.

## Environment

- Python **3.10+**. Use the repo venv: `pip install -e .` (editable). Don't add a new venv.
- This repo IS the `creation` package. The same code powers the CLI, the local server,
  and the build/agent loop.

## Before you commit

- Run the tests: `pytest -q`. Keep them green — don't commit a red suite.
- Lint the files you touched (the editor's diagnostics / `ReadLints`); fix what you introduced.
- Only commit when the change is complete. Use clear, descriptive messages
  (`area: what changed and why`). Don't bundle unrelated changes.

## Don't

- **Never start long-running dev servers** (`creation serve`, `uvicorn …`) inside a task.
  To verify the server boots, use `fastapi.testclient.TestClient(app)` instead.
- **Never commit secrets.** `~/.creation/config.json`, `.env`, tokens, and API keys stay
  out of git. Settings live in `~/.creation`, never in the repo.
- Never `git push --force` to `main`.

## UI assets

- When you edit `creation/app/**` JS or CSS, **bump the `?v=` query string** on the
  corresponding `<script>`/`<link>` in the HTML so browsers don't serve stale assets.
- Keep styling consistent with the existing design tokens in
  `creation/app/assets/css/app-shell.css` and `board.css`. Reuse components; don't reinvent.

## Honesty rule (this is a product principle, not just a convention)

Creation's value is trustworthy, verifiable output. So in code and in any agent run:

- Never fabricate board tickets, agents, missions, metrics, or context stats.
- The Ship Receipt and integration ledger must report **only outcomes that actually
  happened** — mark something "live"/"sent"/"deployed" only when the action truly
  succeeded. Prefer "configured"/"partial" over a hopeful "live".

## When behavior changes

- Update `README.md` (and `apps`/docs if present) when you change user-facing behavior,
  commands, or installation.
- Add or update tests for new behavior in `tests/`.

## Shipping the product itself

- The site auto-deploys from `main` via `.github/workflows/deploy.yml` (Vercel).
- `creation update` upgrades an install in place (git pull + editable reinstall for source
  checkouts; pip-from-git for managed venvs). No manual reinstall needed.
