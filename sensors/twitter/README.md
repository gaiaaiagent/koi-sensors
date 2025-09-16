# Twitter Sensor for KOI Network

Twitter/X monitoring sensor using Playwright browser automation (no authentication required) with KOI protocol integration.

## Current Implementation

**Active File**: `twitter_sensor_koi.py` - KOI-compliant sensor using Playwright for scraping without API authentication

## Features

- ✅ **No Authentication Required** - Uses Playwright browser automation instead of API
- ✅ **KOI Protocol Compliance** - Full event emission with RID support
- ✅ **Smart Health Monitoring** - 30-minute heartbeats with ping response capability
- ✅ **Multiple Collection Modes**:
  - Search queries (e.g., "regenerative agriculture")
  - Hashtag monitoring
  - User timeline monitoring
- ✅ **Automatic Registration** - Registers with coordinator on startup
- ✅ **Date Extraction** - Extracts tweet timestamps for temporal filtering
- ✅ **No Rate Limits** - Browser automation bypasses API rate limiting

## Prerequisites

- Python 3.8+
- Playwright browser drivers (installed automatically by setup.sh)
- No API keys or authentication required

## Installation

```bash
# Navigate to sensor directory
cd sensors/twitter

# Run setup script (installs Playwright browsers)
./setup.sh

# No API tokens needed!
```

## Configuration

The sensor monitors these by default:
- **Search Queries**: "regenerative agriculture", "carbon credits", "regen network", "ecological credits"
- **Hashtags**: #regen, #regenag, #carboncredits, #climatetech
- **User Handles**: @regen_network

Configure via environment variables:
```bash
KOI_COORDINATOR_URL=http://localhost:8005
# No Twitter API token needed
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

Emits KOI events with Twitter-specific RIDs and includes publication dates:
```json
{
  "rid": "orn:twitter.tweet.{user_id}.{tweet_id}",
  "metadata": {
    "published_at": "2025-09-15T12:00:00Z",
    "published_confidence": 0.95
  }
}
```

## Advantages over API approach

- **No Authentication** - Works without Twitter API keys
- **No Rate Limits** - Browser automation isn't subject to API quotas
- **Always Available** - Continues working even if API access is restricted
- **Real-time Dates** - Extracts exact timestamps from tweet elements

## Files

- `twitter_sensor_koi.py` - Main Playwright-based sensor implementation
- `twitter_sensor_v2.py` - Alternative API-based implementation (requires auth)
- `twitter_scraper_playwright.py` - Standalone Playwright scraper library
- `start.sh` - Startup script (launches twitter_sensor_koi.py)
- `setup.sh` - Environment setup including Playwright browser installation
- `requirements.txt` - Python dependencies

## Troubleshooting

If tweets aren't being collected:
1. Check Playwright browsers are installed: `playwright install chromium`
2. Verify the sensor is running: `ps aux | grep twitter_sensor_koi`
3. Check logs for errors: `tail -f twitter_sensor.log`
4. Ensure network connectivity to twitter.com

## Support

Part of the KOI Sensor Network - see main README for architecture details.