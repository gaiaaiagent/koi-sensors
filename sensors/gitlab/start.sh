#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "❌ Run ./setup.sh first"
    exit 1
fi

source venv/bin/activate
export PYTHONPATH="$SCRIPT_DIR/../..:$PYTHONPATH"

# Source .env file if it exists
if [ -f "$SCRIPT_DIR/../../.env" ]; then
    source "$SCRIPT_DIR/../../.env"
fi

if [ "$1" == "--background" ] || [ "$1" == "-b" ]; then
    nohup python3 gitlab_sensor_fixed.py >> gitlab_sensor.log 2>&1 &
    echo "✅ GitLab sensor started (PID: $!)"
else
    echo "Starting GitLab Sensor..."
    python3 gitlab_sensor_fixed.py
fi
