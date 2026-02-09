#!/bin/bash
# KOI Sensor Failure Alert Script
# Called by systemd OnFailure= when a sensor exceeds restart limits
# Sends alerts via Telegram

SENSOR=$1
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S UTC')
HOSTNAME=$(hostname)

# Telegram configuration
TELEGRAM_ALERT_BOT_TOKEN="${TELEGRAM_ALERT_BOT_TOKEN:-}"
TELEGRAM_ALERT_CHAT_ID="${TELEGRAM_ALERT_CHAT_ID:-}"

# Load from config file if not in environment
if [ -z "$TELEGRAM_ALERT_BOT_TOKEN" ] || [ -z "$TELEGRAM_ALERT_CHAT_ID" ]; then
    if [ -f /opt/projects/koi-sensors/.alert-config ]; then
        source /opt/projects/koi-sensors/.alert-config
    fi
fi

if [ -z "$TELEGRAM_ALERT_BOT_TOKEN" ] || [ -z "$TELEGRAM_ALERT_CHAT_ID" ]; then
    echo "[$TIMESTAMP] ALERT: Telegram not configured for sensor $SENSOR failure" >> /opt/projects/koi-sensors/logs/alerts.log
    exit 1
fi

# Get recent logs (last 20 lines to fit Telegram message limit)
RECENT_LOGS=$(journalctl -u koi-sensor@$SENSOR -n 20 --no-pager 2>/dev/null || tail -20 /opt/projects/koi-sensors/sensors/$SENSOR/${SENSOR}_sensor.log 2>/dev/null || echo "No logs available")

# Build message
MESSAGE="🚨 *KOI SENSOR FAILURE*

*Sensor:* \`$SENSOR\`
*Host:* \`$HOSTNAME\`
*Time:* $TIMESTAMP
*Status:* FAILED (exceeded restart limit)

This sensor has crashed repeatedly and systemd has stopped attempting to restart it.

*Required Action:*
\`\`\`
ssh darren@$HOSTNAME
journalctl -u koi-sensor@$SENSOR -n 200
sudo systemctl start koi-sensor@$SENSOR
\`\`\`

*Recent Logs:*
\`\`\`
$RECENT_LOGS
\`\`\`"

# Send via Telegram
RESPONSE=$(curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_ALERT_BOT_TOKEN}/sendMessage" \
    -d chat_id="$TELEGRAM_ALERT_CHAT_ID" \
    -d parse_mode="Markdown" \
    --data-urlencode "text=$MESSAGE" 2>&1)

if echo "$RESPONSE" | grep -q '"ok":true'; then
    echo "[$TIMESTAMP] Sent failure alert for sensor $SENSOR via Telegram" >> /opt/projects/koi-sensors/logs/alerts.log
else
    echo "[$TIMESTAMP] Failed to send Telegram alert for sensor $SENSOR: $RESPONSE" >> /opt/projects/koi-sensors/logs/alerts.log
fi
