#!/bin/bash
# Start Email Sensor

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "❌ Run ./setup.sh first"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate
export PYTHONPATH="$SCRIPT_DIR/../..:$PYTHONPATH"

# Load environment variables if .env exists
if [ -f "$SCRIPT_DIR/../../.env" ]; then
    set -a
    source "$SCRIPT_DIR/../../.env"
    set +a
fi

BACKGROUND=false
ARGS=()

for arg in "$@"; do
    case "$arg" in
        --background|-b)
            BACKGROUND=true
            ;;
        *)
            ARGS+=("$arg")
            ;;
    esac
done

if [ "$BACKGROUND" = true ]; then
    # Background mode always runs daemon scan loop unless caller explicitly passes --file.
    if [[ " ${ARGS[*]} " != *" --daemon "* ]] && [[ " ${ARGS[*]} " != *" --file "* ]]; then
        ARGS+=("--daemon")
    fi
    nohup python email_sensor.py "${ARGS[@]}" >> email_sensor.log 2>&1 &
    echo "✅ Email sensor started (PID: $!)"
else
    echo "🚀 Starting Email Sensor..."
    python email_sensor.py "${ARGS[@]}"
fi
