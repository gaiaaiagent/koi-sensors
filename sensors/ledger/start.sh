#!/bin/bash

# Start script for Ledger sensor

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Source .env file if it exists
if [ -f "$SCRIPT_DIR/../../.env" ]; then
    source "$SCRIPT_DIR/../../.env"
fi

# Activate virtual environment
source venv/bin/activate

# Parse command line arguments
BACKGROUND=false
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -b|--background) BACKGROUND=true ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

echo "🚀 Starting Ledger sensor..."

if [ "$BACKGROUND" = true ]; then
    nohup python3 ledger_sensor.py > ledger_sensor.log 2>&1 &
    echo "✅ Ledger sensor started in background (PID: $!)"
    echo "📝 Logs: tail -f ledger_sensor.log"
else
    python3 ledger_sensor.py
fi