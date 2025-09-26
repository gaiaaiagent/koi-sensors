#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "❌ Run ./setup.sh first"
    exit 1
fi

source venv/bin/activate
export PYTHONPATH="$SCRIPT_DIR/../..:$PYTHONPATH"

# Source .env file if it exists and export all variables
if [ -f "$SCRIPT_DIR/../../.env" ]; then
    # Use export with source to ensure variables are available to Python
    set -a  # Mark all new variables for export
    source "$SCRIPT_DIR/../../.env"
    set +a  # Turn off auto-export

    # Debug: Verify NOTION_API_KEY is set
    if [ -n "$NOTION_API_KEY" ]; then
        echo "✓ NOTION_API_KEY loaded from .env"
    else
        echo "⚠️ NOTION_API_KEY not found in .env"
    fi
fi

if [ "$1" == "--background" ] || [ "$1" == "-b" ]; then
    nohup python3 notion_sensor.py >> notion_sensor.log 2>&1 &
    echo "✅ Notion sensor started (PID: $!)"
else
    echo "Starting Notion Sensor..."
    python3 notion_sensor.py
fi
