#!/bin/bash
# KOI Sensor Health Check Script
# Run via cron to detect stale sensors (defense in depth)
# Sends alerts via Telegram

STALE_THRESHOLD_MINUTES=120  # Alert if no log activity in 2 hours
LOG_DIR="/opt/projects/koi-sensors/logs"
ALERT_LOG="$LOG_DIR/alerts.log"

# Sensors to monitor
SENSORS=(discourse github github_activity telegram twitter websites notion youtube)  # gitlab, medium, podcast DISABLED

# Telegram configuration
TELEGRAM_ALERT_BOT_TOKEN="${TELEGRAM_ALERT_BOT_TOKEN:-}"
TELEGRAM_ALERT_CHAT_ID="${TELEGRAM_ALERT_CHAT_ID:-}"

# Load from config file
if [ -z "$TELEGRAM_ALERT_BOT_TOKEN" ] || [ -z "$TELEGRAM_ALERT_CHAT_ID" ]; then
    if [ -f /opt/projects/koi-sensors/.alert-config ]; then
        source /opt/projects/koi-sensors/.alert-config
    fi
fi

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S UTC')
HOSTNAME=$(hostname)
STALE_SENSORS=()

for sensor in "${SENSORS[@]}"; do
    SENSOR_DIR="/opt/projects/koi-sensors/sensors/$sensor"

    # Skip if sensor directory doesn't exist
    [ ! -d "$SENSOR_DIR" ] && continue

    # Find the main log file
    LOG_FILE="$SENSOR_DIR/${sensor}_sensor.log"
    [ ! -f "$LOG_FILE" ] && LOG_FILE="$SENSOR_DIR/${sensor}.log"

    if [ -f "$LOG_FILE" ]; then
        # Check if log was modified recently
        MINS_OLD=$(( ($(date +%s) - $(stat -c %Y "$LOG_FILE")) / 60 ))

        if [ $MINS_OLD -gt $STALE_THRESHOLD_MINUTES ]; then
            STALE_SENSORS+=("$sensor (stale for ${MINS_OLD}m)")
        fi
    else
        # Check if systemd service is running
        if ! systemctl is-active --quiet koi-sensor@$sensor 2>/dev/null; then
            # Also check for background process
            if ! pgrep -f "${sensor}_sensor" > /dev/null 2>&1; then
                STALE_SENSORS+=("$sensor (not running)")
            fi
        fi
    fi
done

# If there are stale sensors, alert
if [ ${#STALE_SENSORS[@]} -gt 0 ]; then
    echo "[$TIMESTAMP] HEALTH CHECK: Found ${#STALE_SENSORS[@]} stale sensors: ${STALE_SENSORS[*]}" >> "$ALERT_LOG"

    if [ -n "$TELEGRAM_ALERT_BOT_TOKEN" ] && [ -n "$TELEGRAM_ALERT_CHAT_ID" ]; then
        # Build sensor list
        SENSOR_LIST=""
        for s in "${STALE_SENSORS[@]}"; do
            SENSOR_LIST="${SENSOR_LIST}  - ${s}
"
        done

        MESSAGE="⚠️ *KOI SENSOR HEALTH WARNING*

*Host:* \`$HOSTNAME\`
*Time:* $TIMESTAMP

The following sensors appear stale or stopped:

\`\`\`
${SENSOR_LIST}\`\`\`

*Recommended Action:*
\`\`\`
ssh darren@$HOSTNAME
cd /opt/projects/koi-sensors && ./status.sh
./start_all.sh
\`\`\`"

        RESPONSE=$(curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_ALERT_BOT_TOKEN}/sendMessage" \
            -d chat_id="$TELEGRAM_ALERT_CHAT_ID" \
            -d parse_mode="Markdown" \
            --data-urlencode "text=$MESSAGE" 2>&1)

        if echo "$RESPONSE" | grep -q '"ok":true'; then
            echo "[$TIMESTAMP] Sent health warning via Telegram" >> "$ALERT_LOG"
        else
            echo "[$TIMESTAMP] Failed to send Telegram health warning: $RESPONSE" >> "$ALERT_LOG"
        fi
    fi
else
    echo "[$TIMESTAMP] HEALTH CHECK: All monitored sensors are healthy" >> "$ALERT_LOG"
fi
