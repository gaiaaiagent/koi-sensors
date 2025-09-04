# Planetary Regeneration Podcast Indexing

This module handles the indexing of the Planetary Regeneration Podcast, including metadata collection from SoundCloud, transcript fetching from Notion, and audio transcription using Whisper AI.

## Overview

The podcast indexing system collects and processes ~70 episodes of the Planetary Regeneration Podcast from multiple sources:
- **SoundCloud**: Episode metadata and audio URLs
- **Notion**: Professional transcripts (when accessible)
- **Whisper AI**: Audio transcription fallback

## Current Status

### ✅ Completed
- SoundCloud collector implemented and tested
- Successfully collected 70 episodes from SoundCloud
- Discovered 52 transcript URLs on Notion
- Successfully fetched 50 Notion transcripts via API v3
- Audio transcription pipeline ready with Whisper
- Transcribed 2 episodes using Whisper (episodes 20, 67)
- **74.3% complete**: 52 of 70 episodes have transcripts

### 🚧 In Progress
- 18 episodes still need transcription (episodes 21-36, 43, 70)
- Episode 70 is a stub that needs real transcript

### 📊 Statistics
- **Total Episodes**: 70 (on SoundCloud)
- **Transcripts Complete**: 52 episodes (428,113 words)
- **Notion API v3**: 50 episodes fetched
- **Whisper Transcribed**: 2 episodes
- **Missing**: 17 episodes
- **Stub**: 1 episode (needs replacement)

## Directory Structure

```
podcast/
├── collectors/
│   └── soundcloud_collector.py    # SoundCloud API collector
├── scripts/
│   ├── test_podcast_collection.py # Test SoundCloud collection
│   ├── scrape_notion_transcripts.py # Discover Notion URLs
│   ├── fetch_notion_transcripts_batch.py # Batch fetch with delays
│   ├── fetch_notion_playwright_batch.py # Browser-based fetching
│   ├── transcribe_podcast_audio.py # Audio transcription pipeline
│   ├── transcribe_direct.py       # Main transcription tool for missing episodes
│   ├── check_transcript_status.py # Check which episodes are missing
│   └── combine_transcripts.py     # Merge all sources
├── storage/
│   ├── notion_transcripts/        # Notion transcript links
│   ├── podcast_complete/          # Fetched Notion transcripts
│   ├── podcast_transcribed/       # Audio transcriptions
│   └── podcast_final/             # Combined final dataset
├── docs/
│   └── TODO_NOTION_API.md        # Notion API requirements
├── audio_transcriber.py          # Whisper transcription module
└── README.md                      # This file
```

## Usage

### 1. Collect SoundCloud Metadata
```bash
# Test with a few episodes
python indexing/podcast/scripts/test_podcast_collection.py --limit 5

# Collect all episodes
python indexing/podcast/scripts/test_podcast_collection.py
```

### 2. Fetch Notion Transcripts

#### Option A: Batch Fetching (Limited Success)
```bash
# Attempts to fetch in batches with delays
# Currently only first 5 work before Cloudflare blocks
python indexing/podcast/scripts/fetch_notion_transcripts_batch.py

# Aggressive mode (higher risk of blocking)
python indexing/podcast/scripts/fetch_notion_transcripts_batch.py --aggressive
```

#### Option B: Browser Automation (Also Gets Blocked)
```bash
# Uses Playwright for browser automation
python indexing/podcast/scripts/fetch_notion_playwright_batch.py --test
```

### 3. Transcribe Missing Episodes

#### Main Tool (Recommended)
```bash
# Check which episodes are missing
python indexing/podcast/scripts/check_transcript_status.py

# Transcribe all missing episodes automatically
source venv/bin/activate
python indexing/podcast/scripts/transcribe_direct.py
```

#### Alternative: Manual Transcription
```bash
# Test with first 3 episodes
python indexing/podcast/scripts/transcribe_podcast_audio.py --test

# Use faster model for testing
python indexing/podcast/scripts/transcribe_podcast_audio.py --test --tiny

# Full transcription (all episodes)
python indexing/podcast/scripts/transcribe_podcast_audio.py

# Higher quality transcription
python indexing/podcast/scripts/transcribe_podcast_audio.py --medium
```

### 4. Combine All Sources
```bash
# Creates final dataset using best available source for each episode
python indexing/podcast/scripts/combine_transcripts.py
```

## Cloudflare Blocking Issue

### Problem
Notion uses Cloudflare protection that blocks automated access after ~5 requests, even with:
- Rate limiting (10+ seconds between requests)
- Batch processing with long delays (5+ minutes)
- Browser automation with human-like behavior
- Various user agents and headers

### Current Workaround
1. First 5 episodes successfully fetched from Notion
2. Remaining episodes use audio transcription via Whisper
3. Metadata from SoundCloud enriches all episodes

### Permanent Solution Needed
**Notion API Access** - See `docs/TODO_NOTION_API.md` for details

## Notion API Requirements

To properly fetch all transcripts, we need:

1. **Notion Integration Token**
   - Read access to the PRP Transcripts database
   - Database ID or share access to: https://regennetwork.notion.site/PRP-Trascripts-3b97bc2cf21246e09e599b615e483b8d

2. **Benefits of API Access**
   - Reliable access to all 52 transcripts
   - Professional transcripts (likely from Otter.ai)
   - Speaker identification and formatting
   - No Cloudflare blocking issues
   - Faster than audio transcription

3. **Implementation Ready**
   Once API credentials are provided:
   ```python
   # Example implementation ready to use
   from notion_client import Client
   
   notion = Client(auth=NOTION_TOKEN)
   database_id = "YOUR_DATABASE_ID"
   
   # Fetch all transcript pages
   results = notion.databases.query(database_id=database_id)
   ```

## Audio Transcription Details

### Technology
- **Model**: OpenAI Whisper
- **Default Model**: `base` (good balance of speed/quality)
- **Available Models**: `tiny`, `base`, `small`, `medium`, `large`
- **Processing Time**: ~2-5 minutes per episode (base model)

### Features
- Automatic audio download from SoundCloud
- Smart caching to avoid re-downloading
- Timestamped segments in output
- Progress tracking with tqdm
- Batch processing support

### Requirements
```bash
# Install dependencies
pip install openai-whisper yt-dlp

# System dependency
sudo apt-get install -y ffmpeg
```

## Data Schema

Each episode document contains:
```json
{
  "id": "transcript_001",
  "source": "notion:transcripts | soundcloud | whisper",
  "source_type": "notion | soundcloud | audio",
  "url": "https://...",
  "title": "Episode Title",
  "content": "Full transcript text",
  "transcript": "Transcript text",
  "metadata": {
    "episode_number": 1,
    "guest_name": "Guest Name",
    "has_transcript": true,
    "transcript_source": "notion | whisper",
    "duration_ms": 3600000,
    "created_at": "2024-01-15T...",
    "fetched_at": "2024-01-20T..."
  }
}
```

## Performance Metrics

- **SoundCloud Collection**: ~30 seconds for 67 episodes
- **Notion Discovery**: ~45 seconds for 52 URLs
- **Notion Fetching**: 5 episodes in ~2 minutes (before blocking)
- **Audio Transcription**: ~2-5 minutes per episode
- **Full Pipeline**: ~3-6 hours for all episodes (with audio transcription)

## Next Steps

1. **Immediate**: Get Notion API credentials from Regen Network team
2. **Short-term**: Complete audio transcription for remaining episodes
3. **Long-term**: Set up automated updates for new episodes

## Contact

For Notion API access, contact the Regen Network team with:
- This documentation
- The list of transcript URLs in `docs/TODO_NOTION_API.md`
- Request for read-only API access to the PRP Transcripts database