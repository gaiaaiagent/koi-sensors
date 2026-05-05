#!/bin/bash
# Wrapper script for running sensors under systemd
# Usage: run-sensor.sh <sensor-name>

SENSOR=$1

if [ -z "$SENSOR" ]; then
    echo "Usage: run-sensor.sh <sensor-name>"
    exit 1
fi

SENSOR_DIR="/opt/projects/koi-sensors/sensors/$SENSOR"
KOI_ROOT="/opt/projects/koi-sensors"

if [ ! -d "$SENSOR_DIR" ]; then
    echo "Error: Sensor directory not found: $SENSOR_DIR"
    exit 1
fi

cd "$SENSOR_DIR"

# Activate virtual environment (try sensor-specific first, then shared)
if [ -d "$SENSOR_DIR/venv" ]; then
    source "$SENSOR_DIR/venv/bin/activate"
elif [ -d "$KOI_ROOT/venv" ]; then
    source "$KOI_ROOT/venv/bin/activate"
fi

# Set Python path
export PYTHONPATH="$KOI_ROOT:$PYTHONPATH"

# Force unbuffered stdout so heartbeats and log lines reach journald
# immediately instead of batching with the next collection cycle flush.
export PYTHONUNBUFFERED=1

# Source environment
if [ -f "$KOI_ROOT/.env" ]; then
    set -a
    source "$KOI_ROOT/.env"
    set +a
fi

# Local sensors don't need envelope signing — the coordinator handles
# signing for external federation. Override only when broadcasting to
# localhost; remote sensor deployments should set KOI_ENVELOPE_SIGN
# explicitly in their own .env or systemd override.
if [ -z "${KOI_SENSOR_REMOTE:-}" ]; then
    export KOI_ENVELOPE_SIGN=false
fi

# Determine which Python script to run based on sensor
case $SENSOR in
    discourse)
        SCRIPT="discourse_sensor.py"
        ;;
    github)
        SCRIPT="github_sensor.py"
        ;;
    github_activity)
        SCRIPT="github_activity_sensor.py"
        ;;
    gitlab)
        SCRIPT="gitlab_sensor.py"
        ;;
    telegram)
        SCRIPT="telegram_sensor.py"
        ;;
    twitter)
        SCRIPT="twitter_sensor_koi.py"
        ;;
    websites)
        SCRIPT="website_sensor.py"
        ;;
    medium)
        SCRIPT="medium_sensor.py"
        ;;
    notion)
        SCRIPT="notion_sensor.py"
        ;;
    youtube)
        SCRIPT="youtube_sensor.py"
        ;;
    podcast)
        SCRIPT="podcast_sensor.py"
        ;;
    rss)
        SCRIPT="rss_sensor.py"
        ;;
    newsletters)
        SCRIPT="newsletters_sensor.py"
        ;;
    discord)
        SCRIPT="discord_sensor.py"
        ;;
    ledger)
        SCRIPT="ledger_sensor.py"
        ;;
    *)
        # Try common naming patterns
        if [ -f "${SENSOR}_sensor.py" ]; then
            SCRIPT="${SENSOR}_sensor.py"
        elif [ -f "${SENSOR}.py" ]; then
            SCRIPT="${SENSOR}.py"
        else
            echo "Error: Cannot determine script for sensor: $SENSOR"
            echo "Available .py files:"
            ls -1 *.py 2>/dev/null
            exit 1
        fi
        ;;
esac

if [ ! -f "$SCRIPT" ]; then
    echo "Error: Script not found: $SENSOR_DIR/$SCRIPT"
    exit 1
fi

# Preflight: verify critical shared dependencies are importable
# Catches venv drift before systemd burns through restart limits
PREFLIGHT_DEPS="rid_lib cryptography"
for dep in $PREFLIGHT_DEPS; do
    if ! python3 -c "import $dep" 2>/dev/null; then
        echo "PREFLIGHT FAILED: $SENSOR venv is missing '$dep'"
        echo "Fix: $(which pip) install -r $KOI_ROOT/requirements.txt"
        exit 1
    fi
done

echo "Starting $SENSOR sensor: python3 $SCRIPT"
exec python3 "$SCRIPT"
