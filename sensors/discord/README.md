# Discord Sensor

A KOI sensor for monitoring Discord servers and collecting messages in real-time.

## Features

- ✅ Real-time message monitoring
- ✅ Message edit tracking
- ✅ Message deletion events
- ✅ Historical message collection
- ✅ Attachment and embed support
- ✅ Reaction tracking
- ✅ Thread support
- ✅ Automatic tagging based on content
- ✅ Multi-guild support
- ✅ Continuous polling with configurable intervals

## Setup

### 1. Create Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" section
4. Click "Add Bot"
5. Copy the bot token
6. Enable these Privileged Gateway Intents:
   - MESSAGE CONTENT INTENT
   - SERVER MEMBERS INTENT

### 2. Configure Environment

Add to your `.env` file:

```bash
# Required
DISCORD_BOT_TOKEN=your_bot_token_here

# Optional - specific guild IDs to monitor (comma-separated)
DISCORD_GUILDS=123456789,987654321

# Polling interval for historical messages (seconds)
DISCORD_POLL_INTERVAL=3600
```

### 3. Invite Bot to Server

1. In Discord Developer Portal, go to OAuth2 > URL Generator
2. Select scopes:
   - `bot`
3. Select bot permissions:
   - Read Messages/View Channels
   - Read Message History
   - Send Messages (optional for commands)
4. Copy the generated URL and open it to invite the bot

### 4. Install Dependencies

```bash
./setup.sh
```

### 5. Run the Sensor

```bash
# Foreground
./start.sh

# Background
./start.sh -b
```

## How It Works

The Discord sensor operates in two modes simultaneously:

1. **Real-time Monitoring**: Listens for new messages, edits, and deletions as they happen
2. **Periodic Collection**: Every polling interval, collects recent messages from the last 24 hours

## Data Collected

For each message, the sensor collects:

- Message content and metadata
- Author information
- Guild and channel context
- Timestamps (created/edited)
- Attachments and embeds
- Reactions
- Mentions (users, roles, channels)
- Thread information if applicable

## RID Format

Discord messages are assigned RIDs in the format:
```
orn:discord.g{guild_id}.c{channel_id}.m{message_id}
```

## Event Types

- **NEW**: New messages or historical messages on first collection
- **UPDATE**: Message edits
- **FORGET**: Message deletions

## Output

Messages are saved locally to `output/discord_YYYYMMDD_HHMMSS.json` and emitted to the KOI coordinator in real-time.

## Monitoring Specific Guilds

To monitor only specific Discord servers, add their guild IDs to the `DISCORD_GUILDS` environment variable:

```bash
DISCORD_GUILDS=123456789,987654321
```

To find a guild ID:
1. Enable Developer Mode in Discord (User Settings > Advanced > Developer Mode)
2. Right-click on the server name
3. Click "Copy ID"

## Troubleshooting

### Bot Not Responding
- Check bot token is correct
- Verify bot has proper permissions in the server
- Check logs: `tail -f discord_sensor.log`

### Missing Messages
- Ensure MESSAGE CONTENT INTENT is enabled in bot settings
- Verify bot has "Read Message History" permission in channels

### Permission Errors
- Bot needs "Read Messages" and "Read Message History" permissions
- For private channels, bot needs explicit access