#!/bin/bash
#
# Setup script for Claude Sessions Sensor
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Setting up Claude Sessions Sensor..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate and install dependencies
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Setup complete!"
echo ""
echo "To run the sensor:"
echo "  ./start.sh"
echo ""
echo "To install the SessionEnd hook, add to ~/.claude/settings.json:"
echo '  {
    "hooks": {
      "SessionEnd": [
        {
          "hooks": [
            {
              "type": "command",
              "command": "'$SCRIPT_DIR'/notify_session_end.sh"
            }
          ]
        }
      ]
    }
  }'
echo ""
