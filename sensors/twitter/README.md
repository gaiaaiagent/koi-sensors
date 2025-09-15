# Twitter Sensor for KOI Network

Twitter/X monitoring sensor using the Twitter API v2 with KOI protocol integration.

## Current Implementation

**Active File**: `twitter_sensor_v2.py` - KOI-compliant sensor with heartbeat support

## Features

- ✅ **Twitter API v2 Integration** - Uses official API with bearer token authentication
- ✅ **KOI Protocol Compliance** - Full event emission with RID support
- ✅ **Smart Health Monitoring** - 30-minute heartbeats with ping response capability
- ✅ **Multiple Collection Modes**:
  - Search queries (e.g., "regenerative agriculture")
  - Hashtag monitoring
  - User timeline monitoring
- ✅ **Automatic Registration** - Registers with coordinator on startup
- ✅ **Passive Mode Support** - Runs without API token for heartbeat/ping only

## Prerequisites

- Python 3.8+
- Twitter API Bearer Token (optional, but required for data collection)

## Installation

```bash
# Navigate to sensor directory
cd sensors/twitter

# Run setup script
./setup.sh

# Configure environment variables
export TWITTER_BEARER_TOKEN="your-bearer-token-here"
```

## Configuration

The sensor monitors these by default:
- **Search Queries**: "regenerative agriculture", "carbon credits", "regen network", "ecological credits"
- **Hashtags**: #regen, #regenag, #carboncredits, #climatetech
- **User Handles**: @regen_network

Configure via environment variables:
```bash
TWITTER_BEARER_TOKEN=your-token-here
KOI_COORDINATOR_URL=http://localhost:8005
```

## Usage

```bash
# Start in foreground
./start.sh

# Start in background
./start.sh --background

# Check logs
tail -f twitter_sensor.log
```

## Health Monitoring

The sensor implements the Smart Hybrid health monitoring system:
- Sends heartbeat events every 30 minutes
- Responds to ping requests from coordinator
- Registers automatically on startup
- Shows status in dashboard: Active/Idle/Offline

## Output Format

Emits KOI events with Twitter-specific RIDs:
```
orn:twitter.tweet.{user_id}.{tweet_id}
orn:twitter.user.{user_id}
```

## Limitations

- Requires Twitter API Bearer Token for data collection
- Subject to Twitter API rate limits
- Can only access public tweets

## Files

- `twitter_sensor_v2.py` - Main sensor implementation
- `start.sh` - Startup script
- `setup.sh` - Environment setup
- `requirements.txt` - Python dependencies

## Support

Part of the KOI Sensor Network - see main README for architecture details.