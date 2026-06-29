#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
# Browser QA drives your app in a real Chromium and screenshots it. Fetch the
# browser now so the first QA run isn't delayed; non-fatal if it can't.
python -m playwright install chromium || echo "  (playwright chromium will auto-install on first QA run)"
echo ""
echo "Creation installed."
echo ""
echo "  source .venv/bin/activate"
echo "  creation serve"
echo "  creation doctor"
echo "  creation run --demo"
echo ""
echo "Or: ./scripts/creation.sh serve"
