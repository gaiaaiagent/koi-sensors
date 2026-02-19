#!/bin/bash
# update-sensor-venvs.sh — Sync all sensor venvs with shared requirements
#
# Run after updating requirements.txt or adding new sensors.
# Safe to re-run: pip install is idempotent.
#
# Usage:
#   ./scripts/update-sensor-venvs.sh              # update all
#   ./scripts/update-sensor-venvs.sh ledger github # update specific sensors

set -euo pipefail

KOI_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REQUIREMENTS="$KOI_ROOT/requirements.txt"

if [ ! -f "$REQUIREMENTS" ]; then
    echo "ERROR: $REQUIREMENTS not found"
    exit 1
fi

# Determine which sensors to update
if [ $# -gt 0 ]; then
    SENSORS=("$@")
else
    SENSORS=()
    for d in "$KOI_ROOT"/sensors/*/venv; do
        [ -d "$d" ] && SENSORS+=("$(basename "$(dirname "$d")")")
    done
fi

if [ ${#SENSORS[@]} -eq 0 ]; then
    echo "No sensor venvs found."
    exit 0
fi

echo "Updating ${#SENSORS[@]} sensor venv(s) from $REQUIREMENTS"
echo "Requirements: $(cat "$REQUIREMENTS" | tr '\n' ' ')"
echo "---"

FAILED=()
for sensor in "${SENSORS[@]}"; do
    pip_bin="$KOI_ROOT/sensors/$sensor/venv/bin/pip"
    if [ ! -x "$pip_bin" ]; then
        echo "$sensor: SKIP (no venv)"
        continue
    fi
    if "$pip_bin" install -q -r "$REQUIREMENTS" 2>&1; then
        echo "$sensor: OK"
    else
        echo "$sensor: FAILED"
        FAILED+=("$sensor")
    fi
done

echo "---"
if [ ${#FAILED[@]} -gt 0 ]; then
    echo "FAILED: ${FAILED[*]}"
    exit 1
else
    echo "All sensor venvs updated successfully."
fi
