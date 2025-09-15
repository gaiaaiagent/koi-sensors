#!/bin/bash

# Start script for Discord sensor

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Source .env file if it exists
if [ -f "$SCRIPT_DIR/../../.env" ]; then
    source "$SCRIPT_DIR/../../.env"
fi

# Check if Discord token is set
if [ -z "$DISCORD_BOT_TOKEN" ]; then
    echo "❌ Error: DISCORD_BOT_TOKEN not set in environment"
    echo "Please add your Discord bot token to the .env file"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Parse command line arguments
BACKGROUND=false
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -b|--background) BACKGROUND=true ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

echo "🚀 Starting Discord sensor..."

if [ "$BACKGROUND" = true ]; then
    nohup python3 discord_sensor.py > discord_sensor.log 2>&1 &
    echo "✅ Discord sensor started in background (PID: $!)"
    echo "📝 Logs: tail -f discord_sensor.log"
else
    python3 discord_sensor.py
fi