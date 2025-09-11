#!/bin/bash

# Twitter Sensor Setup Script
# This script installs all dependencies needed for the Twitter scraper

echo "========================================"
echo "Twitter Sensor Setup"
echo "========================================"

# Check Python version
python_version=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
required_version="3.8"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "❌ Python 3.8+ is required. Current version: $python_version"
    exit 1
fi

echo "✅ Python version: $python_version"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Install Playwright browsers
echo "Installing Playwright browsers..."
playwright install chromium
playwright install-deps  # Install system dependencies

# Create necessary directories
echo "Creating directories..."
mkdir -p cache
mkdir -p output
mkdir -p logs

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    cat > .env << EOF
# Twitter Sensor Configuration
HEADLESS=true
CACHE_DIR=./cache
OUTPUT_DIR=./output
LOG_LEVEL=INFO
MAX_TWEETS=100
RATE_LIMIT_DELAY=3
EOF
    echo "✅ Created .env file with default settings"
fi

echo ""
echo "========================================"
echo "✅ Setup complete!"
echo "========================================"
echo ""
echo "To run the Twitter scraper:"
echo "  1. Activate the virtual environment: source venv/bin/activate"
echo "  2. Run the scraper: python twitter_scraper_playwright.py"
echo ""
echo "To use in your code:"
echo "  from twitter_scraper_playwright import TwitterPlaywrightScraper"
echo ""