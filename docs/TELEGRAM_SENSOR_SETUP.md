# Telegram Sensor Setup Guide

## Overview
The Telegram sensor monitors Telegram channels and groups for messages, processing them through the KOI pipeline for knowledge extraction and analysis.

## Prerequisites

1. **Telegram Bot Token**: You need a bot token from @BotFather on Telegram
2. **Python Environment**: Python 3.8+ with virtual environment support
3. **KOI Coordinator**: Must be running on port 8005

## Bot Token Configuration

### Creating a New Bot
1. Message @BotFather on Telegram
2. Send `/newbot` and follow the prompts
3. Save the bot token provided

### Important: Bot Token Conflicts
⚠️ **Each bot token can only have ONE active connection at a time**

If you're using the same bot token for other services (like Eliza agents), you'll get this error:
```
telegram.error.Conflict: Conflict: terminated by other getUpdates request
```

**Solution**: Use a dedicated bot token for the KOI sensor, or ensure no other services are using the same token.

## Installation

1. **Setup the sensor environment:**
```bash
cd sensors/telegram
./setup.sh
```

2. **Configure environment variables:**
Edit `.env` in the project root:
```bash
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_BOT_USERNAME=YourBotUsername
TELEGRAM_CHANNEL=@channel_to_monitor
```

3. **Add bot to channel/group:**
- Add your bot as an admin to the channel/group you want to monitor
- The bot needs permission to read messages

## Running the Sensor

### Using the start script:
```bash
cd sensors/telegram
./start.sh
```

### Or manually:
```bash
cd /opt/projects/koi-sensors
source .env
export PYTHONPATH=/opt/projects/koi-sensors:$PYTHONPATH
python3 sensors/telegram/telegram_sensor_v2.py
```

## Configuration Options

The sensor can be configured via `TelegramSensorConfig`:

- `bot_token`: Your Telegram bot token (from .env)
- `bot_username`: Bot's username (from .env)
- `channel_username`: Channel/group to monitor (from .env)
- `poll_interval`: How often to check for new messages (default: 60 seconds)
- `batch_size`: Number of messages to process at once (default: 10)
- `include_forwards`: Whether to track forwarded messages (default: True)
- `coordinator_url`: KOI coordinator URL (default: http://localhost:8005)

## Troubleshooting

### Bot Token Issues
- **Error**: "401: Unauthorized" - Invalid bot token
- **Solution**: Verify token from @BotFather

### Connection Conflicts
- **Error**: "Conflict: terminated by other getUpdates request"
- **Solution**: Ensure only one service uses this bot token

### RID Generation Errors
- **Error**: "Could not generate RID for document: unknown"
- **Solution**: Ensure the sensor is using telegram_sensor_v2.py with proper document fields

### Permission Issues
- **Error**: Bot can't read messages
- **Solution**: Add bot as admin to the channel/group

## Message Processing

The sensor processes messages and creates KOI events with:
- Message text content
- Author information
- Media attachments (when present)
- Forward information (when enabled)
- Timestamps and channel metadata

Each message is assigned a unique RID (Resource Identifier) for tracking through the KOI pipeline.

## Integration with KOI Pipeline

Messages flow through:
1. **Telegram Sensor** → Captures messages
2. **KOI Coordinator** → Deduplicates and routes events
3. **Event Processing** → Extracts knowledge
4. **Storage** → Persists in PostgreSQL with embeddings
5. **Agent Access** → Available for Eliza agents to query

## Monitoring

Check sensor status:
```bash
# View running sensors
curl http://localhost:8005/sensors | jq

# Check sensor logs
tail -f sensors/telegram/telegram_sensor.log

# Monitor KOI coordinator
curl http://localhost:8005/health
```

## Security Notes

- Never commit bot tokens to git
- Use environment variables for sensitive data
- Rotate bot tokens periodically
- Monitor bot activity for unusual patterns

## Support

For issues or questions:
- Check logs in `sensors/telegram/telegram_sensor.log`
- Verify coordinator connection at http://localhost:8005/health
- Ensure PostgreSQL is running and accessible