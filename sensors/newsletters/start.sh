#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "❌ Run ./setup.sh first"
    exit 1
fi

source venv/bin/activate
export PYTHONPATH="$SCRIPT_DIR/../..:$PYTHONPATH"

# Source root .env so ${GMAIL_*_APP_PASSWORD} placeholders resolve
if [ -f "$SCRIPT_DIR/../../.env" ]; then
    set -a
    source "$SCRIPT_DIR/../../.env"
    set +a
fi

if [ "$1" == "--background" ] || [ "$1" == "-b" ]; then
    nohup python3 newsletters_sensor.py >> newsletters_sensor.log 2>&1 &
    echo "✅ Newsletters sensor started (PID: $!)"
else
    echo "Starting Newsletters Sensor..."
    python3 newsletters_sensor.py
fi
