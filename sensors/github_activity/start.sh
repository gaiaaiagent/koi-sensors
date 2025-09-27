#!/bin/bash

# Parse arguments
BACKGROUND=false
if [ "$1" = "--background" ] || [ "$1" = "-b" ]; then
    BACKGROUND=true
fi

# Source the .env file from project root if it exists
if [ -f "../../.env" ]; then
    source ../../.env
fi

# Activate virtual environment
source venv/bin/activate

# Start the sensor
if [ "$BACKGROUND" = true ]; then
    echo "Starting GitHub Activity Sensor in background..."
    nohup python3 github_activity_sensor.py > github_activity.log 2>&1 &
    echo $! > github_activity.pid
    echo "GitHub Activity Sensor started (PID: $(cat github_activity.pid))"
    echo "Logs: tail -f github_activity.log"
else
    echo "Starting GitHub Activity Sensor..."
    python3 github_activity_sensor.py
fi