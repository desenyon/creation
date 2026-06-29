#!/usr/bin/env bash
# Safe wrappers for zsh (inline # comments are NOT ignored unless interactivecomments is on)
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi
case "${1:-serve}" in
  serve)  exec creation serve "${@:2}" ;;
  doctor) exec creation doctor "${@:2}" ;;
  demo)   exec creation run --demo "${@:2}" ;;
  *)      exec creation "$@" ;;
esac
