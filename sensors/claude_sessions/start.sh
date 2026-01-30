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
else
    echo "Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

# Default to scan mode (one-shot)
MODE="${1:-scan}"

echo "Starting Claude Sessions Sensor (mode: $MODE)..."

python claude_session_sensor.py --mode "$MODE"
