#!/bin/bash
# Start script for Obsidian sensor

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load environment variables from root .env if it exists
if [ -f "../../.env" ]; then
    export $(grep -v '^#' ../../.env | xargs)
fi

# Activate virtual environment
source venv/bin/activate

# Default vault path
VAULT_PATH="${OBSIDIAN_VAULT_PATH:-$HOME/Documents/Notes}"
VAULT_NAME="${OBSIDIAN_VAULT_NAME:-personal}"
COORDINATOR_URL="${KOI_COORDINATOR_URL:-http://localhost:8005}"

echo "Starting Obsidian sensor..."
echo "  Vault: $VAULT_PATH"
echo "  Name: $VAULT_NAME"
echo "  Coordinator: $COORDINATOR_URL"

python obsidian_sensor.py \
    --vault "$VAULT_PATH" \
    --vault-name "$VAULT_NAME" \
    --coordinator "$COORDINATOR_URL" \
    "$@"
