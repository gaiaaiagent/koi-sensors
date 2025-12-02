#!/bin/bash
# Start the Notion sensor for Regen Tokenomics workspace (regentokenomics.org)
# This replaces the website sensor for regentokenomics.org content

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
    set -a  # Mark all new variables for export
    source "$SCRIPT_DIR/../../.env"
    set +a  # Turn off auto-export

    # Verify required API key
    if [ -n "$REGENTOKENOMICS_NOTION_API_KEY" ]; then
        echo "✓ REGENTOKENOMICS_NOTION_API_KEY loaded from .env"
    else
        echo "❌ REGENTOKENOMICS_NOTION_API_KEY not found in .env"
        exit 1
    fi
fi

if [ "$1" == "--background" ] || [ "$1" == "-b" ]; then
    # Use unbuffered Python output (-u flag) for real-time logging
    PYTHONUNBUFFERED=1 nohup python3 -u run_regentokenomics.py >> regentokenomics_sensor.log 2>&1 &
    echo "✅ Regentokenomics Notion sensor started (PID: $!)"
    echo "   Log: $SCRIPT_DIR/regentokenomics_sensor.log"
else
    echo "Starting Regentokenomics Notion Sensor..."
    echo "   (use -b or --background to run as daemon)"
    python3 run_regentokenomics.py
fi
