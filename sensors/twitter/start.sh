#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "❌ Run ./setup.sh first"
    exit 1
fi

source venv/bin/activate
export PYTHONPATH="$SCRIPT_DIR/../..:$PYTHONPATH"

# Source .env file if it exists and export variables
if [ -f "$SCRIPT_DIR/../../.env" ]; then
    set -a  # automatically export all variables
    source "$SCRIPT_DIR/../../.env"
    set +a
fi

if [ "$1" == "--background" ] || [ "$1" == "-b" ]; then
    # Use -u for unbuffered output so logs appear immediately
    nohup python3 -u twitter_sensor_koi.py >> twitter_sensor.log 2>&1 &
    echo "✅ Twitter sensor (Playwright KOI - no auth required) started (PID: $!)"
else
    echo "Starting Twitter Sensor (Playwright KOI - no auth required)..."
    python3 -u twitter_sensor_koi.py
fi