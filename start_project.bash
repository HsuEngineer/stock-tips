#!/bin/bash
set -euo pipefail

# Start the Stock Tips Discord bot (long-running).
# On GCP Compute Engine, keep it alive with tmux or systemd, e.g.:
#   tmux new -s stocktips './start_project.bash'
# or a systemd unit ExecStart=/path/to/.venv/bin/python /path/to/main.py

echo "Starting Stock Tips..."
# shellcheck disable=SC1091
source .venv/bin/activate

if command -v python >/dev/null 2>&1; then
  PYTHON=python
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  echo "Error: Python not found in venv. Run ./create_env.bash first."
  exit 1
fi

"$PYTHON" main.py
