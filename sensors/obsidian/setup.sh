#!/bin/bash
# Setup script for Obsidian sensor

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Setting up Obsidian sensor..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Install shared dependencies from koi-sensors root
pip install -r ../../requirements.txt 2>/dev/null || true

echo ""
echo "Setup complete!"
echo ""
echo "To start the sensor:"
echo "  ./start.sh"
echo ""
echo "Or manually:"
echo "  source venv/bin/activate"
echo "  python obsidian_sensor.py --vault ~/Documents/Notes"
