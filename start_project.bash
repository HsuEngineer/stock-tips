#!/bin/bash
set -euo pipefail

# Start the Stock Tips Discord bot (long-running).
# On GCP Compute Engine, keep it alive with tmux or systemd, e.g.:
#   tmux new -s stocktips './start_project.bash'
# or a systemd unit ExecStart=/path/to/.venv/bin/python /path/to/main.py

echo "Starting Stock Tips..."
# shellcheck disable=SC1091
source .venv/bin/activate
python main.py
