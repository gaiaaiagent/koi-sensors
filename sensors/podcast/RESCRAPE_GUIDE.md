# Re-Scrape and Transcribe All Episodes - Quick Guide

## ✅ Ready to Go!

Your podcast sensor can now:
1. ✅ **Automatically get audio files** from SoundCloud (uses yt-dlp)
2. ✅ **Transcribe with word-level timestamps** (Whisper)
3. ✅ **Extract speaker diarization** (PyAnnote)
4. ✅ **Re-scrape ALL episodes** on demand

## Quick Start: Re-Scrape All Episodes

```bash
cd /Users/darrenzal/projects/RegenAI/koi-sensors/sensors/podcast
source venv/bin/activate

# Re-scrape and transcribe ALL episodes
python3 rescrape_and_transcribe_all.py
```

This will:
1. Clear the sensor's persistent state
2. Re-scrape all 70+ episodes from SoundCloud
3. Download audio files automatically (via yt-dlp)
4. Transcribe each episode with word-level timestamps
5. Extract speaker diarization
6. Save transcripts to `transcripts/` directory
7. Emit KOI events for each episode

## Re-Scrape Specific Episodes

```bash
# By SoundCloud track ID
python3 rescrape_and_transcribe_all.py 1234567890 9876543210

# This re-processes only the specified episodes
```

## How Audio Download Works

### SoundCloud URLs (Automatic)
The sensor uses **yt-dlp** to handle SoundCloud authentication:

```python
# Sensor gets episodes from SoundCloud API
episodes = await sensor.collect_soundcloud_episodes(url)

# For each episode, use permalink_url
audio_url = episode['permalink_url']
# Example: https://soundcloud.com/planetaryregeneration/episode-1

# yt-dlp handles:
# - Authentication
# - Best audio quality selection
# - Conversion to MP3
# - All automatically!
```

### Direct URLs (Also Supported)
For non-SoundCloud URLs, uses direct download:
```python
audio_url = "https://example.com/podcast.mp3"
# Downloads directly via aiohttp
```

## Performance Expectations

Based on YonEarth's 172-episode success:

### Single Episode
- Download: ~30-60 seconds (via yt-dlp)
- Transcription: ~2-5 minutes (CPU), ~20-60s (GPU)
- Total per episode: ~3-6 minutes

### All 70+ Episodes
- Estimated time: **3-7 hours** (CPU)
- With GPU: **1-2 hours**
- Network dependent (SoundCloud download speed)

## What Gets Saved

### Transcript Files
Location: `/Users/darrenzal/projects/RegenAI/koi-sensors/sensors/podcast/transcripts/`

Each file: `episode_{soundcloud_id}.json`

Contains:
```json
{
  "segments": [
    {
      "start": 0.5,
      "end": 5.2,
      "text": "Welcome to the show.",
      "speaker": "SPEAKER_00",
      "words": [
        {"word": "Welcome", "start": 0.5, "end": 1.0},
        {"word": "to", "start": 1.0, "end": 1.1}
      ]
    }
  ],
  "full_transcript": "[0.5s - 5.2s] SPEAKER_00: Welcome to the show...",
  "audio_transcription_metadata": {
    "whisper_model": "base",
    "language": "en",
    "duration": 3241.5,
    "speakers_detected": 2,
    "segments_count": 485,
    "word_timestamps": true
  }
}
```

### KOI Events
- NEW event for each episode
- Contains full transcript
- Emitted to coordinator at `localhost:8005`

## Monitoring Progress

The script shows real-time progress:

```
[1/72] Processing: Regenerative Agriculture Basics...
  🎵 Audio URL: https://soundcloud.com/planetaryregeneration/...
  ✓ Downloaded via yt-dlp: episode_12345.mp3 (42.3 MB)
  Transcribing with Whisper...
  ✓ Transcription complete (485 segments)
  Running speaker diarization...
  ✓ Diarization complete (2 speakers detected)
  ✓ Transcript saved: transcripts/episode_12345.json
  Duration: 54.1 minutes
  Segments: 485
  Speakers: 2
  ✓ Transcription complete and event emitted

[2/72] Processing: Soil Health Deep Dive...
```

## Troubleshooting

### If yt-dlp fails
```bash
# Update yt-dlp
pip install --upgrade yt-dlp

# Test manually
yt-dlp "https://soundcloud.com/planetaryregeneration/episode-name"
```

### If transcription is slow
- Normal on CPU (~3-5 min/episode)
- Check GPU availability: `python3 -c "import torch; print(torch.cuda.is_available())"`
- Consider using `whisper_model="tiny"` for faster (but less accurate) results

### If out of disk space
- Audio files: ~40MB each (temporary)
- Transcripts: ~500KB each (permanent)
- Estimate: 70 episodes = ~3GB temp + ~35MB transcripts

### If sensor crashes
- Check logs in console output
- Episodes are processed one at a time
- Can resume by re-running (already transcribed episodes are skipped)

## Configuration Options

Edit `enhanced_podcast_sensor_with_transcription.py`:

```python
sensor = EnhancedPodcastKOISensor(
    whisper_model="base",      # tiny, base, small, medium, large
    enable_diarization=True,   # Speaker labels (requires HUGGINGFACE_TOKEN)
    enable_transcription=True  # Master switch
)
```

## After Transcription

### View Transcripts
```bash
# List all transcripts
ls transcripts/

# View a transcript
cat transcripts/episode_12345.json | jq .
```

### Extract Knowledge Graph
Once transcribed, use YonEarth v3.2.2 system:

```bash
cd /Users/darrenzal/projects/RegenAI/yonearth-gaia-chatbot
python3 scripts/extract_kg_v3_2_2.py
```

Features:
- 95% high confidence relationships
- Evidence tracking with SHA256
- ~$6 cost for 172 episodes
- ~3 hours processing time

## Architecture Flow

```
1. Re-scrape Script
   ↓
2. SoundCloud API (get episode list)
   ↓
3. For each episode:
   a. Get permalink_url
   b. Download audio (yt-dlp)
   c. Transcribe (Whisper)
   d. Diarize (PyAnnote)
   e. Save transcript (JSON)
   f. Emit KOI event
```

## Safety Features

- ✅ **Cached downloads**: Already downloaded audio is reused
- ✅ **Resume capability**: Can restart without losing progress
- ✅ **Error handling**: Failures logged, script continues
- ✅ **Disk cleanup**: Audio files deleted after transcription (configurable)

## Cost

- **Transcription**: FREE (local Whisper)
- **Speaker diarization**: FREE (local PyAnnote)
- **Audio download**: FREE (SoundCloud)
- **Storage**: ~35MB for 70 transcripts

## Next Steps

1. **Test on one episode first**:
   ```bash
   # Get a SoundCloud track ID from the API
   python3 rescrape_and_transcribe_all.py 1234567890
   ```

2. **If successful, run on all**:
   ```bash
   python3 rescrape_and_transcribe_all.py
   ```

3. **Monitor progress** (takes 3-7 hours for all episodes)

4. **Extract knowledge graph** when complete

---

**Ready to start?** Run: `python3 rescrape_and_transcribe_all.py`

The system will confirm before starting and show estimated time!
