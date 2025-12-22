#!/bin/bash
# KOI Sensor Failure Alert Script
# Called by systemd OnFailure= when a sensor exceeds restart limits

SENSOR=$1
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S UTC')
HOSTNAME=$(hostname)

# Check if msmtp is configured
if [ ! -f /etc/msmtprc ] && [ ! -f ~/.msmtprc ]; then
    echo "[$TIMESTAMP] ALERT: Sensor $SENSOR failed but msmtp not configured" >> /opt/projects/koi-sensors/logs/alerts.log
    exit 1
fi

# Get recipient email from environment or config
ALERT_EMAIL=${KOI_ALERT_EMAIL:-""}

if [ -z "$ALERT_EMAIL" ]; then
    # Try to read from config file
    if [ -f /opt/projects/koi-sensors/.alert-config ]; then
        source /opt/projects/koi-sensors/.alert-config
    fi
fi

if [ -z "$ALERT_EMAIL" ]; then
    echo "[$TIMESTAMP] ALERT: No alert email configured for sensor $SENSOR failure" >> /opt/projects/koi-sensors/logs/alerts.log
    exit 1
fi

# Get recent logs
RECENT_LOGS=$(journalctl -u koi-sensor@$SENSOR -n 100 --no-pager 2>/dev/null || tail -100 /opt/projects/koi-sensors/sensors/$SENSOR/${SENSOR}_sensor.log 2>/dev/null || echo "No logs available")

# Send email
cat << EOF | msmtp "$ALERT_EMAIL"
Subject: [KOI ALERT] Sensor Failure: $SENSOR on $HOSTNAME
From: koi-alerts@$HOSTNAME
To: $ALERT_EMAIL
Content-Type: text/plain; charset=utf-8

========================================
   KOI SENSOR FAILURE ALERT
========================================

Sensor:     $SENSOR
Host:       $HOSTNAME
Time:       $TIMESTAMP
Status:     FAILED (exceeded restart limit)

This sensor has crashed repeatedly and systemd has stopped
attempting to restart it automatically.

----------------------------------------
REQUIRED ACTION:
----------------------------------------
1. SSH to server: ssh darren@$HOSTNAME
2. Check logs:    journalctl -u koi-sensor@$SENSOR -n 200
3. Fix issue and restart:
   sudo systemctl start koi-sensor@$SENSOR

----------------------------------------
RECENT LOGS:
----------------------------------------
$RECENT_LOGS

----------------------------------------
This is an automated alert from the KOI sensor monitoring system.
EOF

# Log the alert
echo "[$TIMESTAMP] Sent failure alert for sensor $SENSOR to $ALERT_EMAIL" >> /opt/projects/koi-sensors/logs/alerts.log
