#!/usr/bin/env bash
# Creation one-line installer — installs the CLI and launches the setup wizard.
#
#   curl -fsSL https://raw.githubusercontent.com/desenyon/creation/main/install.sh | bash
#
set -euo pipefail

REPO_URL="${CREATION_REPO:-https://github.com/desenyon/creation.git}"
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

if command -v pipx >/dev/null 2>&1; then
  say "Installing Creation with pipx…"
  pipx install --force "$SPEC"
  pipx ensurepath >/dev/null 2>&1 || true
else
  say "pipx not found — installing into $CREATION_HOME/venv…"
  "$PY" -m venv "$CREATION_HOME/venv"
  "$CREATION_HOME/venv/bin/python" -m pip install --quiet --upgrade pip
  "$CREATION_HOME/venv/bin/python" -m pip install --upgrade "$SPEC"
  mkdir -p "$HOME/.local/bin"
  ln -sf "$CREATION_HOME/venv/bin/creation" "$HOME/.local/bin/creation"
  "$CREATION_HOME/venv/bin/python" -m playwright install chromium >/dev/null 2>&1 \
    || warn "Chromium will auto-install on the first browser-QA run."
fi

ok "Creation installed."

case ":$PATH:" in
  *":$HOME/.local/bin:"*) : ;;
  *)
    if ! command -v creation >/dev/null 2>&1; then
      warn "Add ~/.local/bin to your PATH:"
      echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
      echo ""
    fi
    ;;
esac

CREATION_BIN="$(command -v creation || echo "$HOME/.local/bin/creation")"
if [ ! -x "$CREATION_BIN" ] && [ -x "$CREATION_HOME/venv/bin/creation" ]; then
  CREATION_BIN="$CREATION_HOME/venv/bin/creation"
fi

if [ "${CREATION_SKIP_SETUP:-}" = "1" ]; then
  warn "Skipping setup wizard (CREATION_SKIP_SETUP=1)."
  echo "  creation setup    # run the setup shell later"
else
  say "Launching setup wizard…"
  "$CREATION_BIN" setup || warn "Run 'creation setup' to finish configuration."
fi

echo ""
echo "  creation            # terminal UI"
echo "  creation serve      # Creation Studio"
echo "  creation build --demo \"your idea\""
echo "  creation doctor"
