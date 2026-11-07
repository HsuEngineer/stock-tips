#!/bin/bash
set -euo pipefail

# Foreground start (tmux / debug). Production on GCP should use systemd:
#   sudo systemctl status stocktips
#   sudo journalctl -u stocktips -f
#
# Full auto-install:
#   sudo ./deploy/install.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT}"

if [[ ! -d .venv ]]; then
  echo "Error: .venv missing. Run ./create_env.bash or sudo ./deploy/install.sh first."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if [[ ! -f config.ini ]]; then
  echo "Error: config.ini missing. Copy config.ini.example and set DISCORD.* values."
  exit 1
fi

if command -v python >/dev/null 2>&1; then
  PYTHON=python
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  echo "Error: Python not found in venv."
  exit 1
fi

echo "Starting Stock Tips (foreground). Ctrl+C to stop."
echo "Tip: for GCP production use systemd — see deploy/README.md"
"$PYTHON" main.py
