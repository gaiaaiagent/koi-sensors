#!/bin/bash

# KOI Notion Sensor Startup Script
# This script starts the Notion sensor with proper environment configuration

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo -e "${GREEN}🚀 Starting KOI Notion Sensor${NC}"
echo "========================================="

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${RED}❌ Error: .env file not found${NC}"
    echo "Please create a .env file with your Notion API key:"
    echo "  NOTION_API_KEY=your_notion_integration_secret"
    exit 1
fi

# Load environment variables
export $(grep -v '^#' .env | xargs)

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not found. Creating...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Check if running in screen
if [ -z "$STY" ]; then
    # Not in screen, create a new screen session
    echo -e "${GREEN}📺 Starting in screen session 'notion_sensor'${NC}"
    screen -dmS notion_sensor bash -c "cd $SCRIPT_DIR && source venv/bin/activate && python sensors/notion/run_notion_sensor.py 2>&1 | tee logs/notion_sensor.log"
    
    # Wait a moment for startup
    sleep 3
    
    # Check if screen session is running
    if screen -list | grep -q "notion_sensor"; then
        echo -e "${GREEN}✅ Notion sensor started successfully${NC}"
        echo -e "${GREEN}📋 To view logs: screen -r notion_sensor${NC}"
        echo -e "${GREEN}📋 To detach: Ctrl+A, then D${NC}"
        
        # Show last few lines of log
        if [ -f logs/notion_sensor.log ]; then
            echo ""
            echo "Recent log output:"
            echo "-------------------"
            tail -10 logs/notion_sensor.log
        fi
    else
        echo -e "${RED}❌ Failed to start Notion sensor${NC}"
        exit 1
    fi
else
    # Already in screen, run directly
    echo -e "${GREEN}🔄 Running Notion sensor...${NC}"
    python sensors/notion/run_notion_sensor.py
fi