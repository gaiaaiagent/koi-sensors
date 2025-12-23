#!/bin/bash
# KOI Sensor Health Check Script
# Run via cron to detect stale sensors (defense in depth)

STALE_THRESHOLD_MINUTES=120  # Alert if no log activity in 2 hours
LOG_DIR="/opt/projects/koi-sensors/logs"
ALERT_LOG="$LOG_DIR/alerts.log"

# Sensors to monitor
SENSORS=(discourse github telegram twitter websites notion youtube)  # gitlab, medium, podcast DISABLED  # gitlab and medium DISABLED

# Check if msmtp is available
HAS_MSMTP=false
if command -v msmtp &> /dev/null && [ -f /etc/msmtprc -o -f ~/.msmtprc ]; then
    HAS_MSMTP=true
fi

# Get alert email
ALERT_EMAIL=""
if [ -f /opt/projects/koi-sensors/.alert-config ]; then
    source /opt/projects/koi-sensors/.alert-config
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
    
    if [ "$HAS_MSMTP" = true ] && [ -n "$ALERT_EMAIL" ]; then
        cat << EOF | msmtp "$ALERT_EMAIL"
Subject: [KOI WARNING] Stale Sensors Detected on $HOSTNAME
From: zaldarren@gmail.com
To: $ALERT_EMAIL

========================================
   KOI SENSOR HEALTH WARNING
========================================

Time:       $TIMESTAMP
Host:       $HOSTNAME

The following sensors appear stale or stopped:

$(printf '  - %s\n' "${STALE_SENSORS[@]}")

----------------------------------------
RECOMMENDED ACTION:
----------------------------------------
SSH to server and check sensor status:
  ssh darren@$HOSTNAME
  cd /opt/projects/koi-sensors && ./status.sh

Restart all sensors:
  ./start_all.sh

Or restart specific sensor:
  sudo systemctl restart koi-sensor@SENSOR_NAME

----------------------------------------
This is an automated health check from the KOI sensor monitoring system.
EOF
        echo "[$TIMESTAMP] Sent health warning email to $ALERT_EMAIL" >> "$ALERT_LOG"
    fi
else
    echo "[$TIMESTAMP] HEALTH CHECK: All monitored sensors are healthy" >> "$ALERT_LOG"
fi
