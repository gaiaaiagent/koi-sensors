#!/bin/bash

# Setup script for Discord sensor

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "🔧 Setting up Discord sensor..."

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

echo "✅ Discord sensor setup complete!"
echo ""
echo "⚠️  IMPORTANT: Discord Bot Setup Required"
echo "1. Create a Discord application at https://discord.com/developers/applications"
echo "2. Create a bot user for your application"
echo "3. Copy the bot token and add to .env file: DISCORD_BOT_TOKEN=your_token_here"
echo "4. Invite the bot to your server with these permissions:"
echo "   - Read Messages/View Channels"
echo "   - Read Message History"
echo "   - Send Messages (optional)"
echo ""
echo "Optional: Add guild IDs to monitor specific servers:"
echo "   DISCORD_GUILDS=123456789,987654321"