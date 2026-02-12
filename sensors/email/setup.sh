#!/bin/bash
# Setup script for Email Sensor

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🔧 Setting up Email Sensor..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
echo "📥 Installing dependencies..."
pip install -r requirements.txt

# Install shared dependencies from parent
if [ -f "../../requirements.txt" ]; then
    pip install -r ../../requirements.txt
fi

echo "✅ Email Sensor setup complete!"
echo ""
echo "To run the sensor:"
echo "  source venv/bin/activate"
echo "  python email_sensor.py [--limit N] [--daemon]"
echo ""
echo "To watch for new emails:"
echo "  python file_watcher.py"
