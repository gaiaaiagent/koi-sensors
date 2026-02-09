#!/bin/bash
# KOI Sensor Health Check Script
# Run via cron to detect stale sensors (defense in depth)
# Sends alerts via Telegram (deduped - only alerts on status changes or daily reminder)

STALE_THRESHOLD_MINUTES=120  # Alert if no log activity in 2 hours
LOG_DIR="/opt/projects/koi-sensors/logs"
ALERT_LOG="$LOG_DIR/alerts.log"
STATE_FILE="$LOG_DIR/.health-check-state"
DAILY_REMINDER_HOURS=24

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
            STALE_SENSORS+=("$sensor")
        fi
    else
        # Check if systemd service is running
        if ! systemctl is-active --quiet koi-sensor@$sensor 2>/dev/null; then
            # Also check for background process
            if ! pgrep -f "${sensor}_sensor" > /dev/null 2>&1; then
                STALE_SENSORS+=("$sensor")
            fi
        fi
    fi
done

# Determine if we should send an alert
SHOULD_ALERT=false
CURRENT_STATE=$(printf '%s\n' "${STALE_SENSORS[@]}" | sort | tr '\n' ',')

if [ ${#STALE_SENSORS[@]} -gt 0 ]; then
    if [ -f "$STATE_FILE" ]; then
        PREV_STATE=$(head -1 "$STATE_FILE")
        PREV_TIMESTAMP=$(tail -1 "$STATE_FILE")
        HOURS_SINCE=$(( ($(date +%s) - ${PREV_TIMESTAMP:-0}) / 3600 ))

        if [ "$CURRENT_STATE" != "$PREV_STATE" ]; then
            # Stale sensor set changed — alert immediately
            SHOULD_ALERT=true
        elif [ $HOURS_SINCE -ge $DAILY_REMINDER_HOURS ]; then
            # Same sensors still stale — daily reminder
            SHOULD_ALERT=true
        fi
    else
        # No previous state — first alert
        SHOULD_ALERT=true
    fi
fi

if [ ${#STALE_SENSORS[@]} -gt 0 ]; then
    echo "[$TIMESTAMP] HEALTH CHECK: Found ${#STALE_SENSORS[@]} stale sensors: ${STALE_SENSORS[*]}" >> "$ALERT_LOG"

    if [ "$SHOULD_ALERT" = true ] && [ -n "$TELEGRAM_ALERT_BOT_TOKEN" ] && [ -n "$TELEGRAM_ALERT_CHAT_ID" ]; then
        # Build sensor list with staleness details
        SENSOR_LIST=""
        for sensor in "${STALE_SENSORS[@]}"; do
            SENSOR_DIR="/opt/projects/koi-sensors/sensors/$sensor"
            LOG_FILE="$SENSOR_DIR/${sensor}_sensor.log"
            [ ! -f "$LOG_FILE" ] && LOG_FILE="$SENSOR_DIR/${sensor}.log"
            if [ -f "$LOG_FILE" ]; then
                MINS_OLD=$(( ($(date +%s) - $(stat -c %Y "$LOG_FILE")) / 60 ))
                SENSOR_LIST="${SENSOR_LIST}  - ${sensor} (stale for ${MINS_OLD}m)
"
            else
                SENSOR_LIST="${SENSOR_LIST}  - ${sensor} (not running)
"
            fi
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
            # Save state with current timestamp
            echo "$CURRENT_STATE" > "$STATE_FILE"
            echo "$(date +%s)" >> "$STATE_FILE"
        else
            echo "[$TIMESTAMP] Failed to send Telegram health warning: $RESPONSE" >> "$ALERT_LOG"
        fi
    else
        echo "[$TIMESTAMP] Stale sensors unchanged, suppressing duplicate alert" >> "$ALERT_LOG"
    fi
else
    echo "[$TIMESTAMP] HEALTH CHECK: All monitored sensors are healthy" >> "$ALERT_LOG"
    # Clear state file when all healthy — so next issue triggers immediately
    rm -f "$STATE_FILE"
fi
