#!/bin/bash
#
# Claude Code SessionEnd Hook Script
#
# This script is called by Claude Code when a session ends.
# It notifies the sensor to process the session immediately.
#
# Input (via stdin): JSON with session_id, transcript_path, etc.
# Output: Exit 0 for success (non-blocking)
#
# Install by adding to ~/.claude/settings.json:
# {
#   "hooks": {
#     "SessionEnd": [
#       {
#         "hooks": [
#           {
#             "type": "command",
#             "command": "/absolute/path/to/koi-sensors/sensors/claude_sessions/notify_session_end.sh"
#           }
#         ]
#       }
#     ]
#   }
# }

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/hook.log"
SENSOR_VENV="$SCRIPT_DIR/venv"

# Read input from stdin
INPUT=$(cat)

# Log the hook call
echo "[$(date '+%Y-%m-%d %H:%M:%S')] SessionEnd hook called" >> "$LOG_FILE"
echo "$INPUT" >> "$LOG_FILE"

# Extract session_id and transcript_path
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')

if [ -z "$SESSION_ID" ] || [ -z "$TRANSCRIPT_PATH" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Missing session_id or transcript_path" >> "$LOG_FILE"
    exit 0  # Don't block, just log
fi

# Check if transcript file exists
if [ ! -f "$TRANSCRIPT_PATH" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Transcript file not found: $TRANSCRIPT_PATH" >> "$LOG_FILE"
    exit 0
fi

# Option 1: Call the sensor directly (runs in background)
# This is the primary method - runs the sensor to process the session

if [ -d "$SENSOR_VENV" ]; then
    # Load environment from koi-sensors root
    if [ -f "$SCRIPT_DIR/../../.env" ]; then
        set -a
        source "$SCRIPT_DIR/../../.env"
        set +a
    fi

    # Run sensor in background (non-blocking)
    (
        source "$SENSOR_VENV/bin/activate"
        python "$SCRIPT_DIR/claude_session_sensor.py" \
            --mode session \
            --session-id "$SESSION_ID" \
            --transcript-path "$TRANSCRIPT_PATH" \
            >> "$LOG_FILE" 2>&1
    ) &

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sensor triggered for $SESSION_ID" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sensor venv not found. Run setup.sh first." >> "$LOG_FILE"
fi

# Option 2: Call the KOI API directly (alternative - enable if API endpoint exists)
# KOI_API_URL="${KOI_API_URL:-http://localhost:8351}"
# curl -s -X POST "$KOI_API_URL/ingest-session" \
#     -H "Content-Type: application/json" \
#     -d "{\"session_id\": \"$SESSION_ID\", \"transcript_path\": \"$TRANSCRIPT_PATH\"}" \
#     >> "$LOG_FILE" 2>&1 &

# Always exit 0 to not block Claude Code
exit 0
