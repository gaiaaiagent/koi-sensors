#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "❌ Run ./setup.sh first"
    exit 1
fi

source venv/bin/activate
export PYTHONPATH="$SCRIPT_DIR/../..:$PYTHONPATH"

if [ "$1" == "--background" ] || [ "$1" == "-b" ]; then
    nohup python3 gitlab_sensor_v2.py > gitlab_sensor_v2.log 2>&1 &
    echo "✅ GitLab sensor started (PID: $!)"
else
    echo "Starting GitLab Sensor..."
    python3 gitlab_sensor_v2.py
fi
