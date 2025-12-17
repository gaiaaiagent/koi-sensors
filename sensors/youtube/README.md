# YouTube Sensor

Monitors multiple YouTube channels and transcribes videos using a remote transcription API.

## Features

- **Multi-channel monitoring** via yt-dlp
- **Remote transcription** via Scribe API (no local Whisper needed)
- **Lightweight** - no GPU or large models required locally
- KOI protocol integration
- Persistent state management (avoids re-processing videos)
- Configurable check intervals

## Monitored Channels

Currently configured to monitor:
- `@RegenNetwork` - Main Regen Network channel
- `@FirstPrinciplesAI` - First Principles AI channel
- `@regenfoundation` - Regen Foundation channel

## Setup

### 1. Install Dependencies

```bash
./setup.sh
```

This will:
- Create a virtual environment
- Install Python dependencies (yt-dlp, httpx, etc.)

### 2. Configuration

Add to `../../.env`:

```bash
# YouTube Sensor Configuration
# Multiple channels supported (comma-separated)
YOUTUBE_CHANNEL_URLS=https://www.youtube.com/@RegenNetwork,https://www.youtube.com/@FirstPrinciplesAI,https://www.youtube.com/@regenfoundation
WHISPER_MODEL=large
YOUTUBE_MAX_VIDEOS_PER_CHANNEL=50
YOUTUBE_CHECK_INTERVAL=86400

# Remote Transcription API
TRANSCRIPTION_API_URL=http://37.27.48.12:8080/api
TRANSCRIPTION_API_KEY=your_api_key_here
```

### 3. Test the Sensor

Run the test suite to verify everything works:

```bash
source venv/bin/activate
export PYTHONPATH="../../:$PYTHONPATH"
python3 test_youtube.py
```

## Usage

### Start the Sensor

**Foreground mode** (see output in terminal):
```bash
./start.sh
```

**Background mode** (runs in background):
```bash
./start.sh -b
```

View logs:
```bash
tail -f youtube_sensor.log
```

Stop the sensor:
```bash
kill $(cat youtube_sensor.pid)
```

### How It Works

1. **For Each Channel**: Fetches up to N videos (configured by `YOUTUBE_MAX_VIDEOS_PER_CHANNEL`)
2. **For Each Video**:
   - Submit video URL to remote transcription API
   - Poll for transcription completion
   - Send transcribed content to KOI coordinator
3. **Continuous Mode**: Re-checks all channels every N seconds (configured by `YOUTUBE_CHECK_INTERVAL`)
4. **State Management**: Tracks processed videos to avoid duplicates

## Files

- `youtube_sensor.py` - Main sensor implementation
- `test_youtube.py` - Test suite
- `setup.sh` - Setup script
- `start.sh` - Start script
- `requirements.txt` - Python dependencies
- `videos/` - Temporary storage (usually empty with remote transcription)
- `youtube_sensor_state.json` - Persistent state (gitignored)
- `youtube_sensor.log` - Log file (gitignored)

## Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `YOUTUBE_CHANNEL_URLS` | `https://www.youtube.com/@RegenNetwork` | Comma-separated list of channels to monitor |
| `WHISPER_MODEL` | `large` | Whisper model for remote API (base, small, medium, large) |
| `YOUTUBE_MAX_VIDEOS_PER_CHANNEL` | `50` | Max videos to process per channel |
| `YOUTUBE_CHECK_INTERVAL` | `86400` | Check interval in seconds (86400 = 24 hours) |
| `TRANSCRIPTION_API_URL` | `http://37.27.48.12:8080/api` | Remote transcription API endpoint |
| `TRANSCRIPTION_API_KEY` | - | API key for transcription service |

## Architecture

```
YouTube Sensor
     |
     v
+--------------------+
| yt-dlp             |  Fetch video metadata from channels
+--------------------+
     |
     v
+--------------------+
| Remote Scribe API  |  Transcribe videos (no local GPU needed)
+--------------------+
     |
     v
+--------------------+
| KOI Coordinator    |  Broadcast transcribed content
+--------------------+
```

## KOI Integration

The sensor integrates with the KOI protocol:

- **RID Format**: `orn:youtube.video:CHANNEL_ID/VIDEO_ID`
- **Events**: NEW (first time video processed)
- **Heartbeats**: Every 30 minutes to coordinator
- **Metadata**: Includes video stats, transcription info, timestamps

## Troubleshooting

### No videos found
- Check the channel URLs are correct
- Try adding `/videos` to the URL manually
- Check yt-dlp is up to date: `pip install --upgrade yt-dlp`

### Transcription fails
- Check the transcription API is accessible
- Verify API key is correct in `.env`
- Check API logs for errors

### Sensor not starting
- Ensure KOI coordinator is running on port 8005
- Check `.env` file exists and is sourced
- Try manual start: `source venv/bin/activate && python3 youtube_sensor.py`

## Example Output

```
🎥 YOUTUBE SENSOR STARTING
Channels (3):
  - https://www.youtube.com/@RegenNetwork
  - https://www.youtube.com/@FirstPrinciplesAI
  - https://www.youtube.com/@regenfoundation
Continuous mode: True

================================================================================
ITERATION 1
================================================================================

📺 CHANNEL 1/3: https://www.youtube.com/@RegenNetwork
────────────────────────────────────────────────────────────
Fetching videos from: https://www.youtube.com/@RegenNetwork/videos
✓ Found 50 videos

[1/50] Processing video...
================================================================================
Processing: From Soil Data to Revenue: Inside the Havona Carbon Modeling Engine
Video ID: 7L48I4gih0M
================================================================================
Submitting to transcription API: https://www.youtube.com/watch?v=7L48I4gih0M
Job submitted: abc123...
✓ Transcription complete for: From Soil Data to Revenue...
✅ Sent to KOI: From Soil Data to Revenue...

📺 CHANNEL 2/3: https://www.youtube.com/@FirstPrinciplesAI
...

📊 ITERATION 1 SUMMARY: 150/150 total videos across 3 channels

💤 Sleeping for 86400s (24.0h)
```

## Adding New Channels

To add a new YouTube channel:

1. Edit `.env` and add the channel URL to `YOUTUBE_CHANNEL_URLS`:
   ```bash
   YOUTUBE_CHANNEL_URLS=...,https://www.youtube.com/@NewChannel
   ```

2. Restart the sensor:
   ```bash
   kill $(cat youtube_sensor.pid)
   ./start.sh -b
   ```

## License

Part of the KOI Sensors project.
