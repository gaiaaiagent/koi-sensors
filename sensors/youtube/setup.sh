#!/bin/bash

# YouTube Sensor Setup Script
# Creates virtual environment and installs dependencies

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "🎥 YouTube Sensor Setup"
echo "======================="

# Check if venv exists
if [ -d "venv" ]; then
    echo "⚠️  Virtual environment already exists. Remove it? (y/n)"
    read -r response
    if [ "$response" = "y" ]; then
        rm -rf venv
        echo "✓ Removed existing venv"
    else
        echo "Keeping existing venv"
    fi
fi

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
fi

# Activate venv
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Check for ffmpeg (required for yt-dlp audio extraction)
if ! command -v ffmpeg &> /dev/null; then
    echo ""
    echo "⚠️  WARNING: ffmpeg not found"
    echo "ffmpeg is required for audio extraction from YouTube videos"
    echo ""
    echo "Install with:"
    echo "  macOS: brew install ffmpeg"
    echo "  Ubuntu/Debian: sudo apt-get install ffmpeg"
    echo "  Other: https://ffmpeg.org/download.html"
    echo ""
fi

# Create output directory
mkdir -p videos

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Add YouTube configuration to ../../.env:"
echo "   YOUTUBE_CHANNEL_URL=https://www.youtube.com/@RegenNetwork"
echo "   WHISPER_MODEL=large"
echo "   YOUTUBE_MAX_VIDEOS_FIRST_RUN=5"
echo "   YOUTUBE_CHECK_INTERVAL=86400  # 24 hours"
echo ""
echo "2. Start the sensor:"
echo "   ./start.sh          # Foreground mode"
echo "   ./start.sh -b       # Background mode"
echo ""
