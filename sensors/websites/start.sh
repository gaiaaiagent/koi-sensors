#!/bin/bash

# Website Sensor Start Script
# Runs the website sensor using its virtual environment

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found!"
    echo "Please run ./setup.sh first"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Add parent directories to Python path
export PYTHONPATH="$SCRIPT_DIR/../..:$PYTHONPATH"

# Source .env file if it exists
if [ -f "$SCRIPT_DIR/../../.env" ]; then
    source "$SCRIPT_DIR/../../.env"
fi

# Check if running in background
if [ "$1" == "--background" ] || [ "$1" == "-b" ]; then
    echo "Starting Website sensor in background..."
    nohup python3 website_sensor.py > website_sensor.log 2>&1 &
    PID=$!
    echo "✅ Website sensor started (PID: $PID)"
    echo "   Log: $SCRIPT_DIR/website_sensor.log"
    echo "   Stop: kill $PID"
else
    echo "================================"
    echo "Starting Website Sensor"
    echo "================================"
    python3 website_sensor.py
fi