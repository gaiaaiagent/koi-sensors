#!/bin/bash
# KOI Event Reconciliation Script
# Detects content that was scraped by sensors but not stored in the database
# Run manually or via cron to find and re-process missed events

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SENSORS_DIR="/opt/projects/koi-sensors/sensors"
LOG_FILE="/opt/projects/koi-sensors/logs/reconciliation.log"
ALERT_CONFIG="/opt/projects/koi-sensors/.alert-config"

# Load alert config
if [ -f "$ALERT_CONFIG" ]; then
    source "$ALERT_CONFIG"
fi

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S UTC')
echo "[$TIMESTAMP] Starting reconciliation check..." >> "$LOG_FILE"

# Database connection
DB_URL="postgresql://postgres:postgres@localhost:5433/eliza"

# Function to check a sensor
check_sensor() {
    local sensor=$1
    local state_file="$SENSORS_DIR/$sensor/${sensor}_sensor_state.json"
    
    # Try alternate naming
    if [ ! -f "$state_file" ]; then
        state_file="$SENSORS_DIR/$sensor/discourse_sensor_state.json"
    fi
    
    if [ ! -f "$state_file" ]; then
        return 0
    fi
    
    echo "Checking $sensor..."
    
    # Extract processed items from state file
    local processed_count=$(python3 -c "
import json
try:
    with open('$state_file', 'r') as f:
        state = json.load(f)
    processed = state.get('processed', [])
    print(len(processed))
except:
    print(0)
" 2>/dev/null)
    
    echo "  State file shows $processed_count processed items"
}

# Function to find missing discourse topics
check_discourse_gaps() {
    echo ""
    echo "=== Checking Discourse Sensor Gaps ==="
    
    local state_file="$SENSORS_DIR/discourse/discourse_sensor_state.json"
    
    if [ ! -f "$state_file" ]; then
        echo "No discourse state file found"
        return 0
    fi
    
    # Get topics from state file
    local state_topics=$(python3 -c "
import json
with open('$state_file', 'r') as f:
    state = json.load(f)
processed = state.get('processed', [])
# Extract topic numbers from entries like 'forum.regen.network:topic:565'
topics = set()
for p in processed:
    if 'forum.regen.network:topic:' in p:
        try:
            topic_num = p.split(':')[-1]
            topics.add(int(topic_num))
        except:
            pass
    elif 'forum.regen.network:' in p and ':post_' in p:
        try:
            parts = p.split(':')
            topic_num = parts[1]
            topics.add(int(topic_num))
        except:
            pass
for t in sorted(topics):
    print(t)
" 2>/dev/null)
    
    local state_count=$(echo "$state_topics" | wc -l)
    echo "  State file has $state_count unique topics"
    
    # Get topics from database
    local db_topics=$(psql "$DB_URL" -t -c "
        SELECT DISTINCT 
            CASE 
                WHEN url ~ '/t/[^/]+/([0-9]+)' THEN (regexp_match(url, '/t/[^/]+/([0-9]+)'))[1]::int
                ELSE NULL
            END as topic_num
        FROM koi_content 
        WHERE url LIKE '%forum.regen.network%'
        AND url ~ '/t/[^/]+/[0-9]+'
        ORDER BY topic_num;
    " 2>/dev/null | grep -v '^$' | tr -d ' ')
    
    local db_count=$(echo "$db_topics" | grep -c '[0-9]' 2>/dev/null || echo 0)
    echo "  Database has $db_count unique topics"
    
    # Find gaps
    local missing=""
    for topic in $state_topics; do
        if ! echo "$db_topics" | grep -q "^$topic$"; then
            missing="$missing $topic"
        fi
    done
    
    if [ -n "$missing" ]; then
        echo ""
        echo "  ⚠️  MISSING TOPICS (in state but not in DB):$missing"
        echo "[$TIMESTAMP] Discourse missing topics:$missing" >> "$LOG_FILE"
        return 1
    else
        echo "  ✓ No gaps detected"
        return 0
    fi
}

# Function to reset a topic for re-scraping
reset_topic() {
    local sensor=$1
    local topic=$2
    
    echo "Resetting $sensor topic $topic for re-scraping..."
    
    local state_file="$SENSORS_DIR/$sensor/${sensor}_sensor_state.json"
    if [ "$sensor" = "discourse" ]; then
        state_file="$SENSORS_DIR/discourse/discourse_sensor_state.json"
    fi
    
    python3 -c "
import json
with open('$state_file', 'r') as f:
    state = json.load(f)
state['processed'] = [p for p in state.get('processed', []) if '$topic' not in p]
with open('$state_file', 'w') as f:
    json.dump(state, f, indent=2)
print('Removed topic $topic from processed state')
"
}

# Main execution
echo ""
echo "========================================"
echo "   KOI Event Reconciliation Check"
echo "========================================"
echo "Timestamp: $TIMESTAMP"
echo ""

# Check each sensor
for sensor_dir in "$SENSORS_DIR"/*/; do
    sensor=$(basename "$sensor_dir")
    if [ -d "$sensor_dir" ] && [ "$sensor" != "experimental" ]; then
        check_sensor "$sensor"
    fi
done

# Detailed discourse check
GAPS_FOUND=0
if ! check_discourse_gaps; then
    GAPS_FOUND=1
fi

echo ""
echo "========================================"

if [ $GAPS_FOUND -eq 1 ]; then
    echo "⚠️  Gaps detected! Run with --fix to reset missing items for re-scraping"
    echo "   Example: $0 --fix discourse 565"
    
    # Send alert if email configured
    if [ -n "$ALERT_EMAIL" ] && command -v msmtp &> /dev/null; then
        echo "Sending alert email..."
        cat << EOF | msmtp "$ALERT_EMAIL"
Subject: [KOI WARNING] Event Reconciliation Found Gaps
From: zaldarren@gmail.com
To: $ALERT_EMAIL

========================================
   KOI EVENT RECONCILIATION ALERT
========================================

Time: $TIMESTAMP

Gaps were detected between sensor state and database.
Some content was scraped but not stored in the database.

Check the reconciliation log for details:
  /opt/projects/koi-sensors/logs/reconciliation.log

To fix, SSH to server and run:
  /opt/projects/koi-sensors/scripts/reconcile-events.sh --fix discourse <topic_number>

Or restart the sensor after resetting its state.

========================================
EOF
        echo "[$TIMESTAMP] Alert email sent" >> "$LOG_FILE"
    fi
else
    echo "✓ No gaps detected - all scraped content is in database"
fi

# Handle --fix argument
if [ "$1" = "--fix" ] && [ -n "$2" ] && [ -n "$3" ]; then
    reset_topic "$2" "$3"
    echo ""
    echo "Now restart the sensor to re-scrape:"
    echo "  sudo systemctl restart koi-sensor@$2"
fi

echo "[$TIMESTAMP] Reconciliation check complete" >> "$LOG_FILE"
