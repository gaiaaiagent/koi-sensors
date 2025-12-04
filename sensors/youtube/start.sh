#!/bin/bash

# YouTube Sensor Start Script
# Starts the YouTube sensor in foreground or background mode

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Run ./setup.sh first"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Add parent directories to PYTHONPATH for KOI imports
export PYTHONPATH="$SCRIPT_DIR/../..:$PYTHONPATH"

# Load environment variables from root .env
if [ -f "$SCRIPT_DIR/../../.env" ]; then
    source "$SCRIPT_DIR/../../.env"
    echo "✓ Loaded environment variables from .env"
fi

# Check for background mode flag
if [ "$1" == "--background" ] || [ "$1" == "-b" ]; then
    echo "🎥 Starting YouTube Sensor in background mode..."

    # Start in background with output to log file
    nohup python3 youtube_sensor.py --continuous >> youtube_sensor.log 2>&1 &
    PID=$!

    echo "✅ YouTube sensor started (PID: $PID)"
    echo "   Log: tail -f youtube_sensor.log"
    echo "   Stop: kill $PID"

    # Save PID to file for easy stopping
    echo $PID > youtube_sensor.pid
else
    echo "🎥 Starting YouTube Sensor in foreground mode..."
    echo "   Press Ctrl+C to stop"
    echo ""

    # Start in foreground with continuous mode
    python3 youtube_sensor.py --continuous
fi
