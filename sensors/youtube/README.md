# YouTube Sensor

Monitors YouTube channels and transcribes videos using OpenAI Whisper.

## Features

- Channel monitoring via yt-dlp
- Audio extraction from videos
- High-accuracy transcription with Whisper large model
- KOI protocol integration
- Persistent state management (avoids re-processing videos)
- Configurable check intervals

## Setup

### 1. Install Dependencies

```bash
./setup.sh
```

This will:
- Create a virtual environment
- Install Python dependencies (Whisper, yt-dlp, etc.)
- Check for ffmpeg (required for audio extraction)

If ffmpeg is not installed:
- **macOS**: `brew install ffmpeg`
- **Ubuntu/Debian**: `sudo apt-get install ffmpeg`
- **Other**: https://ffmpeg.org/download.html

### 2. Configuration

Add to `../../.env`:

```bash
# YouTube Sensor Configuration
YOUTUBE_CHANNEL_URL=https://www.youtube.com/@RegenNetwork
WHISPER_MODEL=large                    # base, small, medium, or large
YOUTUBE_MAX_VIDEOS_FIRST_RUN=5         # Number of recent videos to process initially
YOUTUBE_CHECK_INTERVAL=86400           # Check interval in seconds (86400 = 24 hours)
```

### 3. Test the Sensor

Run the test suite to verify everything works:

```bash
source venv/bin/activate
export PYTHONPATH="../../:$PYTHONPATH"
python3 test_youtube.py
```

This will:
- Fetch recent videos from the channel
- Download audio from one video
- Optionally test transcription (slow, ~5-10 min with large model)

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
# Find PID
cat youtube_sensor.pid

# Kill process
kill $(cat youtube_sensor.pid)
```

### How It Works

1. **Initial Run**: Processes the last N videos (configured by `YOUTUBE_MAX_VIDEOS_FIRST_RUN`)
2. **Continuous Mode**: Checks for new videos every N seconds (configured by `YOUTUBE_CHECK_INTERVAL`)
3. **For Each Video**:
   - Download audio track
   - Transcribe with Whisper
   - Send to KOI coordinator
   - Clean up audio file (unless `KEEP_AUDIO_FILES=1`)
4. **State Management**: Tracks processed videos to avoid duplicates

## Files

- `youtube_sensor.py` - Main sensor implementation
- `test_youtube.py` - Test suite
- `setup.sh` - Setup script
- `start.sh` - Start script
- `requirements.txt` - Python dependencies
- `videos/` - Temporary audio storage (auto-cleaned)
- `youtube_sensor_state.json` - Persistent state
- `youtube_sensor.log` - Log file (background mode)

## Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `YOUTUBE_CHANNEL_URL` | `https://www.youtube.com/@RegenNetwork` | Channel to monitor |
| `WHISPER_MODEL` | `large` | Whisper model size (base, small, medium, large) |
| `YOUTUBE_MAX_VIDEOS_FIRST_RUN` | `5` | Videos to process on first run |
| `YOUTUBE_CHECK_INTERVAL` | `86400` | Check interval in seconds |
| `KEEP_AUDIO_FILES` | `0` | Set to `1` to keep audio files after processing |

## Whisper Models

| Model | Size | Accuracy | Speed | Recommended For |
|-------|------|----------|-------|-----------------|
| base | ~140MB | Good | Fast | Quick testing |
| small | ~460MB | Better | Moderate | Balanced |
| medium | ~1.5GB | Very Good | Slow | High accuracy |
| large | ~3GB | Excellent | Very Slow | Production (current) |

## Performance

- **Video Fetching**: ~1 second per batch
- **Audio Download**: Depends on video length and connection speed
  - Example: ~1 minute for a 1-hour video
- **Transcription**: Depends on model and hardware
  - **large model + CPU**: ~10-15 minutes for a 1-hour video
  - **large model + GPU**: ~2-3 minutes for a 1-hour video
  - Hardware acceleration: Automatically uses CUDA if available

## KOI Integration

The sensor integrates with the KOI protocol:

- **RID Format**: `orn:youtube.video:CHANNEL_ID/VIDEO_ID`
- **Events**: NEW (first time), UPDATE (changes detected)
- **Heartbeats**: Every 30 minutes to coordinator
- **Metadata**: Includes video stats, transcription info, timestamps

## Troubleshooting

### No videos found
- Check the channel URL is correct
- Try adding `/videos` to the URL manually
- Check yt-dlp is up to date: `pip install --upgrade yt-dlp`

### Audio download fails
- Ensure ffmpeg is installed: `which ffmpeg`
- Check internet connection
- Some videos may be region-locked or unavailable

### Transcription is slow
- Consider using a smaller Whisper model (medium or small)
- Use GPU acceleration if available (install CUDA)
- Increase check interval to reduce frequency

### Out of disk space
- Audio files are auto-cleaned after processing
- Check `videos/` directory for stuck files
- Reduce `YOUTUBE_MAX_VIDEOS_FIRST_RUN` for initial run

## Example Output

```
🎥 YOUTUBE SENSOR STARTING
Channel: https://www.youtube.com/@RegenNetwork
Continuous mode: True

================================================================================
ITERATION 1
================================================================================

Fetching videos from: https://www.youtube.com/@RegenNetwork/videos
✓ Found 5 videos

[1/5] Processing video...
================================================================================
Processing: From Soil Data to Revenue: Inside the Havona Carbon Modeling Engine
Video ID: 7L48I4gih0M
================================================================================
Downloading audio from: https://www.youtube.com/watch?v=7L48I4gih0M
✓ Downloaded audio: 7L48I4gih0M.mp3 (106.3 MB)
Loading Whisper model: large
✓ Whisper model loaded on cpu
Transcribing: 7L48I4gih0M.mp3
✓ Transcription complete: 487 segments, 4644.0s
✅ Sent to KOI: From Soil Data to Revenue: Inside the Havona Carbon Modeling Engine
Cleaned up audio file: 7L48I4gih0M.mp3

✅ Processed 5/5 videos

💤 Sleeping for 86400s (24.0h)
```

## Development

To modify the sensor:

1. Edit `youtube_sensor.py`
2. Test changes: `python3 test_youtube.py`
3. Restart the sensor: `./start.sh`

## License

Part of the KOI Sensors project.
