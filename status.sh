#!/bin/bash

# Status Script for KOI Sensors
# Shows the current status of all sensors and the coordinator

echo "========================================="
echo "     KOI Sensors - System Status         "
echo "========================================="

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Check KOI Coordinator
echo ""
echo -e "${CYAN}KOI Coordinator Status:${NC}"
if curl -s http://localhost:8005/health > /dev/null 2>&1; then
    coordinator_pid=$(pgrep -f "run_coordinator.py" 2>/dev/null)
    echo -e "  ${GREEN}● Running${NC} (PID: $coordinator_pid)"
    echo "    Health check: http://localhost:8005/health"
else
    echo -e "  ${RED}● Not running${NC}"
fi

# Check individual sensors
echo ""
echo -e "${CYAN}Sensor Status:${NC}"

declare -A sensor_files=(
    ["Website"]="website_sensor.py"
    ["GitHub"]="github_sensor_v2.py"
    ["GitLab"]="gitlab_sensor_v2.py"
    ["Medium"]="medium_sensor.py"
    ["Discourse"]="discourse_sensor.py"
    ["Notion"]="notion_sensor.py"
    ["Telegram"]="telegram_sensor.py"
    ["Twitter"]="twitter_sensor.py"
    ["Podcast"]="podcast_sensor.py"
)

for sensor_name in "${!sensor_files[@]}"; do
    sensor_file="${sensor_files[$sensor_name]}"
    pid=$(pgrep -f "$sensor_file" 2>/dev/null | head -1)

    if [ -n "$pid" ]; then
        echo -e "  ${GREEN}●${NC} $sensor_name (PID: $pid)"
    else
        echo -e "  ${RED}●${NC} $sensor_name"
    fi
done

# Check for log files
echo ""
echo -e "${CYAN}Recent Log Activity:${NC}"

for sensor_dir in sensors/*/; do
    if [ -d "$sensor_dir" ]; then
        sensor_name=$(basename "$sensor_dir")
        log_file="$sensor_dir/${sensor_name}_sensor.log"

        if [ -f "$log_file" ]; then
            last_modified=$(stat -c %Y "$log_file" 2>/dev/null || stat -f %m "$log_file" 2>/dev/null)
            current_time=$(date +%s)
            age=$((current_time - last_modified))

            if [ $age -lt 60 ]; then
                echo -e "  ${GREEN}●${NC} $sensor_name: Active (updated <1 min ago)"
            elif [ $age -lt 300 ]; then
                echo -e "  ${YELLOW}●${NC} $sensor_name: Recent (updated <5 min ago)"
            else
                echo -e "  ${RED}●${NC} $sensor_name: Stale (updated >5 min ago)"
            fi

            # Show last line of log
            last_line=$(tail -1 "$log_file" 2>/dev/null | head -c 80)
            if [ -n "$last_line" ]; then
                echo "      Last: $last_line..."
            fi
        fi
    fi
done

# System resources
echo ""
echo -e "${CYAN}System Resources:${NC}"
echo -n "  Memory usage: "
free -h | grep "^Mem:" | awk '{print $3 " / " $2 " (" int($3/$2 * 100) "%)"}'

echo -n "  Python processes: "
pgrep -c python3

# PID file status
PID_FILE="$SCRIPT_DIR/.sensor_pids"
if [ -f "$PID_FILE" ] && [ -s "$PID_FILE" ]; then
    echo ""
    echo -e "${CYAN}Tracked Processes (from PID file):${NC}"
    while IFS=':' read -r name pid; do
        if ps -p "$pid" > /dev/null 2>&1; then
            echo -e "  ${GREEN}●${NC} $name (PID: $pid)"
        else
            echo -e "  ${RED}●${NC} $name (PID: $pid - not running)"
        fi
    done < "$PID_FILE"
fi

echo ""
echo "========================================="
echo "Commands:"
echo "  Start all:        ./start_all.sh"
echo "  Stop all:         ./stop_all.sh"
echo "  Setup sensors:    ./setup_all.sh"
echo "  View logs:        tail -f sensors/*/\*.log"
echo ""