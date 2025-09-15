#!/bin/bash

# Notion Sensor Setup Helper
echo "========================================"
echo "📝 Notion Sensor Setup Instructions"
echo "========================================"
echo ""
echo "To use the Notion sensor, you need a Notion Integration:"
echo ""
echo "1. Go to https://www.notion.so/my-integrations"
echo "2. Click '+ New integration'"
echo "3. Give it a name (e.g., 'KOI Sensor')"
echo "4. Select the workspace to monitor"
echo "5. Copy the 'Internal Integration Token'"
echo ""
echo "6. Set the environment variable:"
echo "   export NOTION_API_KEY='secret_YOUR_TOKEN_HERE'"
echo ""
echo "7. Share pages/databases with the integration:"
echo "   - Open any Notion page/database you want to monitor"
echo "   - Click '...' menu → 'Add connections'"
echo "   - Select your integration"
echo ""
echo "========================================"
echo ""

# Check if API key is set
if [ -n "$NOTION_API_KEY" ]; then
    echo "✅ NOTION_API_KEY is set"
    echo ""
    echo "Starting Notion sensor..."
    cd "$(dirname "$0")"
    ./setup.sh && ./start.sh
else
    echo "❌ NOTION_API_KEY not set"
    echo ""
    echo "Once you have your API key, run:"
    echo "  export NOTION_API_KEY='your_key_here'"
    echo "  cd $(pwd)"
    echo "  ./setup_notion.sh"
fi