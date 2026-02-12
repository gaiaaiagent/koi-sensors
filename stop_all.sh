#!/bin/bash

# Unified Stop Script for All Sensors
# This script stops all running sensors gracefully

echo "========================================="
echo "     KOI Sensors - Master Stop           "
echo "========================================="

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# PID file location
PID_FILE="$SCRIPT_DIR/.sensor_pids"

# Function to stop a process
stop_process() {
    local name=$1
    local pid=$2

    if ps -p "$pid" > /dev/null 2>&1; then
        echo -e "${CYAN}Stopping $name (PID: $pid)...${NC}"
        kill "$pid" 2>/dev/null

        # Wait for graceful shutdown (max 5 seconds)
        local count=0
        while ps -p "$pid" > /dev/null 2>&1 && [ $count -lt 5 ]; do
            sleep 1
            count=$((count + 1))
        done

        # Force kill if still running
        if ps -p "$pid" > /dev/null 2>&1; then
            echo -e "${YELLOW}Force stopping $name...${NC}"
            kill -9 "$pid" 2>/dev/null
        fi

        echo -e "${GREEN}✅ $name stopped${NC}"
    else
        echo -e "${YELLOW}⚠ $name (PID: $pid) not running${NC}"
    fi
}

# Stop sensors from PID file
if [ -f "$PID_FILE" ]; then
    echo -e "${CYAN}Stopping sensors from PID file...${NC}"
    echo ""

    while IFS=':' read -r name pid; do
        stop_process "$name" "$pid"
    done < "$PID_FILE"

    # Clear PID file
    > "$PID_FILE"
else
    echo -e "${YELLOW}No PID file found, searching for running sensors...${NC}"
fi

# Additional cleanup - find any remaining sensor processes
echo ""
echo -e "${CYAN}Checking for remaining sensor processes...${NC}"

# Kill any remaining sensor processes
sensor_patterns=(
    "website_sensor"
    "github_sensor"
    "gitlab_sensor"
    "medium_sensor"
    "discourse_sensor"
    "notion_sensor"
    "telegram_sensor"
    "twitter_sensor"
    "podcast_sensor"
    "email_sensor"
    "claude_session_sensor"
)

for pattern in "${sensor_patterns[@]}"; do
    pids=$(pgrep -f "$pattern" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo -e "${YELLOW}Found $pattern processes: $pids${NC}"
        for pid in $pids; do
            kill "$pid" 2>/dev/null
        done
    fi
done

# Stop KOI Coordinator if requested
echo ""
read -p "Stop KOI Coordinator too? [y/N]: " stop_coordinator
if [[ $stop_coordinator =~ ^[Yy]$ ]]; then
    coordinator_pid=$(pgrep -f "run_coordinator.py" 2>/dev/null)
    if [ -n "$coordinator_pid" ]; then
        echo -e "${CYAN}Stopping KOI Coordinator (PID: $coordinator_pid)...${NC}"
        kill "$coordinator_pid" 2>/dev/null
        echo -e "${GREEN}✅ KOI Coordinator stopped${NC}"
    else
        echo -e "${YELLOW}KOI Coordinator not running${NC}"
    fi
fi

# Final check
echo ""
echo "========================================="
echo -e "${GREEN}✅ Shutdown complete!${NC}"
echo "========================================="
echo ""

# Show any remaining processes
remaining=$(pgrep -f "_sensor|run_coordinator" 2>/dev/null)
if [ -n "$remaining" ]; then
    echo -e "${YELLOW}Warning: Some processes may still be running:${NC}"
    ps aux | grep -E "_sensor|run_coordinator" | grep -v grep
else
    echo "All sensor processes stopped successfully."
fi

echo ""
echo "Commands:"
echo "  Start all:        ./start_all.sh"
echo "  Setup sensors:    ./setup_all.sh"
echo "  Check status:     ./status.sh"
echo ""
