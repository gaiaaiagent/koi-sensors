#!/bin/bash

# Podcast Sensor Start Script
# Runs the podcast sensor using the virtual environment

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found!"
    echo "Please run ./setup.sh first to set up the environment"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Add parent directories to Python path for KOI imports
export PYTHONPATH="$SCRIPT_DIR/../..:$PYTHONPATH"

# Check if running in background
if [ "$1" == "--background" ]; then
    echo "Starting Podcast sensor in background..."
    nohup python3 podcast_sensor.py > podcast_sensor.log 2>&1 &
    PID=$!
    echo "✅ Podcast sensor started (PID: $PID)"
    echo "   Log file: $SCRIPT_DIR/podcast_sensor.log"
    echo "   To stop: kill $PID"
else
    echo "================================"
    echo "Starting Podcast Sensor"
    echo "================================"
    python3 podcast_sensor.py
fi