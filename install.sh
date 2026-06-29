#!/usr/bin/env bash
# Creation one-line installer — installs the `creation` CLI, no repo checkout left behind.
#
#   curl -fsSL creation.dev/install | bash
#
# pip fetches and builds Creation from the repo into a throwaway temp dir, so you get
# the tool (UI bundled inside the package) without cloning the source. Override the
# source with CREATION_REPO / CREATION_REF if you need a fork or branch.
set -euo pipefail

REPO_URL="${CREATION_REPO:-https://github.com/arjunkshah/creation.git}"
REF="${CREATION_REF:-main}"
SPEC="git+${REPO_URL}@${REF}"
CREATION_HOME="${CREATION_HOME:-$HOME/.creation}"

say()  { printf '\033[36m→\033[0m %s\n' "$1"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '\033[33m!\033[0m %s\n' "$1"; }
die()  { printf '\033[31m✗\033[0m %s\n' "$1" >&2; exit 1; }

PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || die "Python 3.10+ is required but was not found. Install it from https://python.org and re-run."
"$PY" - <<'EOF' || die "Creation needs Python 3.10 or newer."
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
EOF

CREATION_BIN=""

if command -v pipx >/dev/null 2>&1; then
  # Best path: pipx keeps Creation in its own isolated env and puts it on PATH.
  say "Installing Creation with pipx…"
  pipx install --force "$SPEC"
  pipx ensurepath >/dev/null 2>&1 || true
  CREATION_BIN="$(command -v creation || echo "$HOME/.local/bin/creation")"
else
  # Fallback: a dedicated venv + a symlink on PATH. Works even on "externally
  # managed" Pythons (Homebrew/Debian PEP 668) where `pip install --user` is blocked.
  say "pipx not found — installing into an isolated environment at $CREATION_HOME/venv…"
  "$PY" -m venv "$CREATION_HOME/venv"
  "$CREATION_HOME/venv/bin/python" -m pip install --quiet --upgrade pip
  "$CREATION_HOME/venv/bin/python" -m pip install --upgrade "$SPEC"
  mkdir -p "$HOME/.local/bin"
  ln -sf "$CREATION_HOME/venv/bin/creation" "$HOME/.local/bin/creation"
  CREATION_BIN="$HOME/.local/bin/creation"
  # Pre-fetch the Chromium used by real browser-QA (non-fatal; auto-installs later).
  "$CREATION_HOME/venv/bin/python" -m playwright install chromium >/dev/null 2>&1 \
    || warn "Chromium will auto-install on the first browser-QA run."
fi

ok "Creation installed."
echo ""

# Make sure ~/.local/bin is reachable for this shell + future ones.
case ":$PATH:" in
  *":$HOME/.local/bin:"*) : ;;
  *)
    if ! command -v creation >/dev/null 2>&1; then
      warn "Add ~/.local/bin to your PATH to use the 'creation' command:"
      echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
      echo ""
    fi
    ;;
esac

echo "  creation serve          # → http://127.0.0.1:8787  (dashboard + agent board)"
echo "  creation run --demo     # try a build without API keys"
echo "  creation doctor         # verify setup (agents, Composio, keys)"
echo "  creation update         # update in place later — no reinstall needed"
echo ""
echo "First run? Open http://127.0.0.1:8787 and the setup wizard walks you through keys."
