#!/usr/bin/env bash
# ── Italy Visa Slot Checker — local runner ────────────────────────────────────
# Usage: ./run.sh
# Reads credentials from .env in the same directory.

set -euo pipefail
cd "$(dirname "$0")"

# Load .env if present
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
else
  echo "ERROR: .env file not found. Copy .env.example to .env and fill in your values."
  exit 1
fi

# Check Python 3 is available
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found. Install it from https://python.org"
  exit 1
fi

# Install dependencies if not already installed
if ! python3 -c "import playwright" &>/dev/null 2>&1; then
  echo "Installing Python dependencies …"
  pip3 install -r requirements.txt
  echo "Installing Playwright Chromium …"
  python3 -m playwright install chromium --with-deps
fi

echo "Starting Italy Visa Slot Checker …"
echo "Logs will appear below. Press Ctrl+C to stop."
echo ""

python3 -m bot.checker
