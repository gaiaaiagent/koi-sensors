#!/bin/bash

# Website Sensor Setup Script
# Sets up virtual environment and installs dependencies

echo "================================"
echo "Website Sensor Setup"
echo "================================"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
else
    echo "Virtual environment already exists"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip --quiet

# Install requirements
echo "Installing dependencies..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt --quiet
else
    # Install core dependencies if no requirements.txt
    echo "Installing core dependencies..."
    pip install aiohttp beautifulsoup4 lxml httpx --quiet
fi

# Verify installation
echo ""
echo "Verifying installation..."
python3 -c "
import sys
sys.path.append('../../')

try:
    import aiohttp
    print('✅ aiohttp installed')
except ImportError:
    print('❌ aiohttp missing')

try:
    import bs4
    print('✅ BeautifulSoup installed')
except ImportError:
    print('❌ BeautifulSoup missing')

try:
    import httpx
    print('✅ httpx installed')
except ImportError:
    print('❌ httpx missing')

# Test sensor import
try:
    from website_sensor import WebsiteSensor
    print('✅ Website sensor imports successfully')
except ImportError as e:
    print(f'❌ Website sensor import failed: {e}')
"

echo ""
echo "================================"
echo "Setup Complete!"
echo "================================"
echo ""
echo "To run the Website sensor:"
echo "  ./start.sh"
echo ""