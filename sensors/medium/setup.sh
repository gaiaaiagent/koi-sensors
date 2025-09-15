#!/bin/bash

echo "================================"
echo "Medium Sensor Setup"
echo "================================"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
else
    echo "Virtual environment already exists"
fi

source venv/bin/activate
pip install --upgrade pip --quiet
echo "Installing dependencies..."
pip install -r requirements.txt --quiet

echo "✅ Setup complete! Run: ./start.sh"
