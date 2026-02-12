#!/bin/bash
#
# Start script for Claude Sessions Sensor
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load environment variables from koi-sensors root
if [ -f "../../.env" ]; then
    set -a
    source "../../.env"
    set +a
fi

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
    export PYTHONPATH="$SCRIPT_DIR/../..:$PYTHONPATH"
else
    echo "Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

BACKGROUND=false
MODE=""
PASSTHROUGH=()

for arg in "$@"; do
    case "$arg" in
        --background|-b)
            BACKGROUND=true
            ;;
        daemon|scan|session|backfill|refresh)
            MODE="$arg"
            ;;
        *)
            PASSTHROUGH+=("$arg")
            ;;
    esac
done

# Default mode:
# - foreground: scan once
# - background: daemon loop
if [ -z "$MODE" ]; then
    if [ "$BACKGROUND" = true ]; then
        MODE="daemon"
    else
        MODE="scan"
    fi
fi

if [ "$BACKGROUND" = true ]; then
    nohup python claude_session_sensor.py --mode "$MODE" "${PASSTHROUGH[@]}" >> claude_sessions_sensor.log 2>&1 &
    echo "✅ Claude Sessions sensor started (PID: $!, mode: $MODE)"
else
    echo "Starting Claude Sessions Sensor (mode: $MODE)..."
    python claude_session_sensor.py --mode "$MODE" "${PASSTHROUGH[@]}"
fi
