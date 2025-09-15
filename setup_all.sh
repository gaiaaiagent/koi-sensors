#!/bin/bash

# Unified Setup Script for All Sensors
# This script sets up all sensors in parallel for faster installation

echo "========================================="
echo "     KOI Sensors - Master Setup         "
echo "========================================="

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Array of sensors to setup
declare -a SENSORS=(
    "websites"
    "github"
    "gitlab"
    "medium"
    "discourse"
    "notion"
    "telegram"
    "twitter"
    "podcast"
)

# Function to setup a sensor
setup_sensor() {
    local sensor=$1
    local sensor_dir="$SCRIPT_DIR/sensors/$sensor"

    if [ ! -d "$sensor_dir" ]; then
        echo -e "${YELLOW}⚠ Skipping $sensor (directory not found)${NC}"
        return
    fi

    if [ ! -f "$sensor_dir/setup.sh" ]; then
        echo -e "${YELLOW}⚠ Skipping $sensor (no setup.sh found)${NC}"
        return
    fi

    echo -e "${GREEN}Setting up $sensor sensor...${NC}"
    cd "$sensor_dir"
    bash setup.sh > setup.log 2>&1
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ $sensor sensor setup complete${NC}"
    else
        echo -e "${RED}❌ $sensor sensor setup failed (check $sensor_dir/setup.log)${NC}"
    fi
}

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 is required but not installed${NC}"
    exit 1
fi

# Setup KOI protocol dependencies first
echo -e "${GREEN}Setting up KOI protocol dependencies...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# Ask if user wants sequential or parallel setup
echo ""
echo "How would you like to setup the sensors?"
echo "1) Sequential (safer, shows progress)"
echo "2) Parallel (faster, but harder to debug)"
read -p "Choice [1/2]: " choice

case $choice in
    2)
        echo -e "${GREEN}Starting parallel setup...${NC}"
        # Setup all sensors in parallel
        for sensor in "${SENSORS[@]}"; do
            setup_sensor "$sensor" &
        done
        # Wait for all background jobs to complete
        wait
        ;;
    *)
        echo -e "${GREEN}Starting sequential setup...${NC}"
        # Setup sensors one by one
        for sensor in "${SENSORS[@]}"; do
            setup_sensor "$sensor"
        done
        ;;
esac

echo ""
echo "========================================="
echo -e "${GREEN}✅ Setup complete!${NC}"
echo "========================================="
echo ""
echo "To start all sensors:"
echo "  ./start_all.sh"
echo ""
echo "To start individual sensors:"
echo "  cd sensors/<sensor_name> && ./start.sh"
echo ""
echo "To stop all sensors:"
echo "  ./stop_all.sh"
echo ""