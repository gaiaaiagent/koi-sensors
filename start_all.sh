#!/bin/bash

# Unified Start Script for All Sensors
# This script starts all sensors using their individual start scripts

echo "========================================="
echo "     KOI Sensors - Master Start          "
echo "========================================="

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# PID file to track sensor processes
PID_FILE="$SCRIPT_DIR/.sensor_pids"
> "$PID_FILE"  # Clear previous PIDs

# Array of sensors to start (in order of priority)
declare -a SENSORS=(
    "websites"
    "github"
    "gitlab"
    "medium"
    "discourse"
    "notion"
    "telegram"
    "twitter"
    "podcast"
)

# Function to check if sensor is configured
is_sensor_configured() {
    local sensor=$1

    case $sensor in
        notion)
            [ -n "$NOTION_API_KEY" ]
            ;;
        telegram)
            [ -n "$TELEGRAM_BOT_TOKEN" ]
            ;;
        twitter)
            # Twitter uses Playwright, no API key needed
            return 0
            ;;
        *)
            # Most sensors work without configuration
            return 0
            ;;
    esac
}

# Function to start a sensor
start_sensor() {
    local sensor=$1
    local sensor_dir="$SCRIPT_DIR/sensors/$sensor"

    if [ ! -d "$sensor_dir" ]; then
        echo -e "${YELLOW}⚠ Skipping $sensor (directory not found)${NC}"
        return
    fi

    if [ ! -f "$sensor_dir/start.sh" ]; then
        echo -e "${YELLOW}⚠ Skipping $sensor (no start.sh found)${NC}"
        return
    fi

    if ! is_sensor_configured "$sensor"; then
        echo -e "${YELLOW}⚠ Skipping $sensor (not configured)${NC}"
        return
    fi

    echo -e "${CYAN}Starting $sensor sensor...${NC}"
    cd "$sensor_dir"

    # Start in background mode
    ./start.sh --background > /dev/null 2>&1

    # Get the PID of the started process
    local pid=$(pgrep -f "${sensor}_sensor" | tail -1)

    if [ -n "$pid" ]; then
        echo "$sensor:$pid" >> "$PID_FILE"
        echo -e "${GREEN}✅ $sensor sensor started (PID: $pid)${NC}"
    else
        echo -e "${RED}❌ $sensor sensor failed to start${NC}"
    fi
}

# Check if coordinator is running
echo -e "${CYAN}Checking KOI Coordinator...${NC}"
if ! curl -s http://localhost:8005/health > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠ KOI Coordinator not running. Starting it...${NC}"
    cd "$SCRIPT_DIR"
    source venv/bin/activate
    nohup python3 koi_protocol/coordinator/run_coordinator.py > coordinator.log 2>&1 &
    echo "KOI_COORDINATOR:$!" >> "$PID_FILE"
    sleep 3
fi

# Start sensors
echo ""
echo -e "${CYAN}Starting sensors...${NC}"
echo ""

for sensor in "${SENSORS[@]}"; do
    start_sensor "$sensor"
    sleep 1  # Small delay between sensors
done

# Show status
echo ""
echo "========================================="
echo -e "${GREEN}✅ Sensor startup complete!${NC}"
echo "========================================="
echo ""

# Count running sensors
running_count=$(grep -c ":" "$PID_FILE" 2>/dev/null || echo "0")
echo -e "Running sensors: ${GREEN}$running_count${NC}"
echo ""

# Show running processes
if [ -s "$PID_FILE" ]; then
    echo "Active processes:"
    while IFS=':' read -r name pid; do
        if ps -p "$pid" > /dev/null 2>&1; then
            echo -e "  ${GREEN}●${NC} $name (PID: $pid)"
        else
            echo -e "  ${RED}●${NC} $name (PID: $pid - not running)"
        fi
    done < "$PID_FILE"
fi

echo ""
echo "Commands:"
echo "  View logs:        tail -f sensors/*/\*.log"
echo "  Stop all:         ./stop_all.sh"
echo "  Check status:     ./status.sh"
echo "  Setup sensors:    ./setup_all.sh"
echo ""