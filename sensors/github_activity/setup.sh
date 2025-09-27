#!/bin/bash

echo "=== Setting up GitHub Activity Sensor ==="

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Install koi_protocol from parent
echo "Installing koi_protocol..."
pip install -e ../../

echo "✅ GitHub Activity Sensor setup complete!"
echo "To start: ./start.sh"