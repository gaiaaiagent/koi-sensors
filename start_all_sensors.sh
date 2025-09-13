#!/bin/bash

echo "================================"
echo "Starting KOI Sensors"
echo "================================"

# Configuration
LOG_DIR="/tmp"
PYTHON_CMD="python3"

# Set Python path for koi_protocol module
export PYTHONPATH="/opt/projects/koi-sensors:$PYTHONPATH"

# Kill any existing sensors
echo "Stopping existing sensors..."
pkill -f "website_sensor.py|notion_sensor.py|discourse_sensor.py|medium_sensor.py|twitter_sensor.py" 2>/dev/null || true
sleep 2

# Function to start a sensor
start_sensor() {
    local name=$1
    local script=$2
    local log_file=$3
    
    echo -n "Starting $name..."
    nohup $PYTHON_CMD $script > $LOG_DIR/$log_file 2>&1 &
    local pid=$!
    sleep 1
    
    if ps -p $pid > /dev/null; then
        echo " ✓ (PID: $pid)"
    else
        echo " ✗ (failed to start - check $LOG_DIR/$log_file)"
    fi
}

echo ""
echo "Starting sensors..."

# 1. Website Sensor (monitoring Regen Network sites)
if [ -f "sensors/websites/website_sensor.py" ]; then
    start_sensor "Website Sensor" "sensors/websites/website_sensor.py" "website_sensor.log"
fi

# 2. Notion Sensor (if configured)
if [ -f "sensors/notion/notion_sensor.py" ] && [ -n "$NOTION_API_KEY" ]; then
    start_sensor "Notion Sensor" "sensors/notion/notion_sensor.py" "notion_sensor.log"
fi

# 3. Discourse Sensor (if configured)
if [ -f "sensors/discourse/discourse_sensor.py" ] && [ -n "$DISCOURSE_API_KEY" ]; then
    start_sensor "Discourse Sensor" "sensors/discourse/discourse_sensor.py" "discourse_sensor.log"
fi

# 4. Medium Sensor (monitoring Regen Network Medium)
if [ -f "sensors/medium/medium_sensor.py" ]; then
    start_sensor "Medium Sensor" "sensors/medium/medium_sensor.py" "medium_sensor.log"
fi

# 5. Twitter Sensor (if configured)
if [ -f "sensors/twitter/twitter_sensor.py" ] && [ -n "$TWITTER_BEARER_TOKEN" ]; then
    start_sensor "Twitter Sensor" "sensors/twitter/twitter_sensor.py" "twitter_sensor.log"
fi

# Wait for sensors to stabilize
echo ""
echo "Waiting for sensors to stabilize..."
sleep 3

# Check sensor status
echo ""
echo "Checking sensor status..."
echo "================================"

# Show running sensors
echo "Running sensors:"
ps aux | grep -E "website_sensor|notion_sensor|discourse_sensor|medium_sensor|twitter_sensor" | grep -v grep | awk '{print "  -", $11, "(PID:", $2")"}'

# Show recent logs
echo ""
echo "Recent sensor activity:"
for log in website_sensor.log notion_sensor.log discourse_sensor.log medium_sensor.log twitter_sensor.log; do
    if [ -f "$LOG_DIR/$log" ]; then
        echo ""
        echo "From $log:"
        tail -3 "$LOG_DIR/$log" | head -10
    fi
done

echo ""
echo "================================"
echo "Sensors started!"
echo "Monitor logs in $LOG_DIR/"
echo ""
echo "To view sensor activity:"
echo "  tail -f $LOG_DIR/*_sensor.log"
echo ""
echo "To stop all sensors:"
echo "  pkill -f '_sensor.py'"
echo "================================"