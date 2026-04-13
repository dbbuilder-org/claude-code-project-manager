#!/usr/bin/env bash
# daily-brief.sh — Send pm brief via iMessage at 8am
# Installed as a launchd job: com.pm.daily-brief

set -euo pipefail

PM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$PM_DIR/venv/bin/activate"

if [ ! -f "$VENV" ]; then
    echo "Error: venv not found at $VENV" >&2
    exit 1
fi

source "$VENV"

# Send brief via iMessage — suppress if nothing urgent
exec pm brief --imessage --only-if-urgent
