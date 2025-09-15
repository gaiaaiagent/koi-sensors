#!/bin/bash

# Podcast Sensor Setup Script
# Sets up a virtual environment with all required dependencies

echo "================================"
echo "Podcast Sensor Setup"
echo "================================"

# Get the directory of this script
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
pip install --upgrade pip

# Install required packages
echo "Installing required packages..."
pip install -r requirements.txt

# Check if user wants to install optional transcription libraries
echo ""
echo "================================"
echo "Optional: Audio Transcription"
echo "================================"
echo "The Podcast sensor can transcribe audio using Whisper."
echo "This requires additional packages (~1GB download)."
echo ""
read -p "Install audio transcription libraries? (y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Installing transcription libraries..."
    pip install openai-whisper
    echo "✅ Transcription libraries installed"
else
    echo "⚠️  Skipping transcription libraries"
    echo "   The sensor will collect metadata only (no transcripts)"
fi

# Verify installation
echo ""
echo "================================"
echo "Verifying Installation"
echo "================================"

python3 -c "
import sys
sys.path.append('../../')

# Check required libraries
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
    import yt_dlp
    print('✅ yt-dlp installed (audio download)')
except ImportError:
    print('⚠️  yt-dlp missing (no audio download)')

try:
    import whisper
    print('✅ Whisper installed (transcription enabled)')
except ImportError:
    print('⚠️  Whisper missing (no transcription)')

# Test sensor import
try:
    from podcast_sensor import PodcastKOISensor
    print('✅ Podcast sensor imports successfully')
except ImportError as e:
    print(f'❌ Podcast sensor import failed: {e}')
"

echo ""
echo "================================"
echo "Setup Complete!"
echo "================================"
echo ""
echo "To run the Podcast sensor:"
echo "  1. Activate the virtual environment:"
echo "     source $SCRIPT_DIR/venv/bin/activate"
echo ""
echo "  2. Run the sensor:"
echo "     python3 run_podcast_sensor.py"
echo ""
echo "Or use the convenience script:"
echo "     ./start_podcast_sensor.sh"
echo ""