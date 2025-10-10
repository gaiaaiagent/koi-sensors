# Podcast Transcription Setup Guide

## Overview

The podcast sensor now includes **production-ready transcription** based on the proven YonEarth implementation that successfully transcribed 172 episodes with:

- **Word-level timestamps** for precise audio navigation
- **Speaker diarization** (identifies who spoke when)
- **95%+ accuracy** using Whisper base model
- **Async integration** with KOI sensor architecture

## Features

### 1. Word-Level Timestamps
Every word gets precise start/end timestamps:
```json
{
  "word": "regeneration",
  "start": 12.5,
  "end": 13.2
}
```

### 2. Speaker Diarization
Automatically identifies different speakers:
```json
{
  "start": 10.0,
  "end": 25.3,
  "text": "Welcome to the podcast!",
  "speaker": "SPEAKER_00"
}
```

### 3. Full Transcript + Segments
- Segmented output with timestamps for precise navigation
- Full transcript for text search and analysis
- SHA256 tracking for version control

## System Requirements

### 1. FFmpeg (System Package)

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y ffmpeg

# Verify
ffmpeg -version
```

### 2. Python Dependencies

```bash
cd /Users/darrenzal/projects/RegenAI/koi-sensors/sensors/podcast

# Activate virtual environment
source venv/bin/activate  # Create if needed: python3 -m venv venv

# Install dependencies
pip install -r requirements.txt
```

This installs:
- **Whisper** (OpenAI) - Accurate transcription with word-level timestamps
- **PyAnnote Audio** - Speaker diarization
- **PyTorch** - Deep learning framework
- **yt-dlp** - Audio download from various sources
- Audio processing libraries

### 3. HuggingFace Setup (for Speaker Diarization)

1. Create account at https://huggingface.co
2. Go to https://huggingface.co/settings/tokens
3. Create a new token (read access)

4. Accept model licenses:
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0

5. Add to `.env` file in koi-sensors root:
```bash
HUGGINGFACE_TOKEN=your_token_here
```

## Quick Start

### Test Transcription (Standalone)

```python
python3 audio_transcriber.py <audio_url> <episode_id>
```

Example:
```bash
python3 audio_transcriber.py \
  "https://example.com/episode1.mp3" \
  "ep001"
```

### Integrate with Podcast Sensor

The transcriber is designed to integrate seamlessly with the podcast sensor:

```python
from audio_transcriber import PodcastAudioTranscriber

# Initialize transcriber
transcriber = PodcastAudioTranscriber(
    whisper_model="base",  # base, small, medium, large
    enable_diarization=True,
    huggingface_token=os.getenv("HUGGINGFACE_TOKEN")
)

# Transcribe episode
result = await transcriber.transcribe_episode(
    audio_url="https://example.com/audio.mp3",
    episode_id="ep001"
)

# Access results
print(f"Segments: {len(result.segments)}")
print(f"Duration: {result.metadata['duration']:.1f}s")
print(f"Speakers: {result.metadata['speakers_detected']}")

# Convert to dict for JSON storage
transcription_dict = result.to_dict()
```

## Configuration Options

### Whisper Model Sizes

| Model | Speed | Accuracy | Memory | Use Case |
|-------|-------|----------|--------|----------|
| `base` | Fast | 95% | ~1GB | **Recommended** - Good balance |
| `small` | Medium | 97% | ~2GB | Higher accuracy needed |
| `medium` | Slow | 98% | ~5GB | Critical accuracy |
| `large` | Very Slow | 99% | ~10GB | Maximum accuracy |

### Environment Variables

```bash
# Required for speaker diarization
HUGGINGFACE_TOKEN=your_token_here

# Optional: Keep audio files after transcription
KEEP_AUDIO_FILES=true

# Optional: Whisper model size
WHISPER_MODEL=base
```

## Output Format

### Complete Result Structure

```json
{
  "segments": [
    {
      "start": 0.5,
      "end": 5.2,
      "text": "Welcome to the Planetary Regeneration Podcast.",
      "speaker": "SPEAKER_00",
      "words": [
        {"word": "Welcome", "start": 0.5, "end": 1.0},
        {"word": "to", "start": 1.0, "end": 1.1},
        {"word": "the", "start": 1.1, "end": 1.2}
      ]
    }
  ],
  "full_transcript": "[0.5s - 5.2s] SPEAKER_00: Welcome to the Planetary Regeneration Podcast...",
  "audio_transcription_metadata": {
    "whisper_model": "base",
    "language": "en",
    "duration": 3241.5,
    "speakers_detected": 2,
    "segments_count": 485,
    "diarization_available": true,
    "word_timestamps": true,
    "transcribed_at": "2025-10-10T12:00:00",
    "device": "cpu"
  }
}
```

## Performance

Based on YonEarth production results (172 episodes):

- **Speed**: ~2-5 minutes per episode (CPU)
  - With GPU: 5-10x faster
- **Accuracy**: ~95% with base model
- **Storage**: Audio files ~40MB each (temporary)
- **Memory**: ~4GB RAM per episode during processing

### GPU Acceleration

If you have NVIDIA GPU with CUDA:

```bash
# Check CUDA availability
python3 -c "import torch; print(torch.cuda.is_available())"

# If True, transcription will automatically use GPU
# Install CUDA-enabled PyTorch if needed:
pip install torch==2.0.0+cu118 torchaudio==2.0.0+cu118 \
  --index-url https://download.pytorch.org/whl/cu118
```

## Troubleshooting

### FFmpeg Not Found
```bash
# Install FFmpeg (see System Requirements above)
ffmpeg -version
```

### HuggingFace 403 Error
- Make sure you've accepted BOTH model licenses
- Verify token is set: `echo $HUGGINGFACE_TOKEN`

### Out of Memory
1. Close other applications
2. Use smaller Whisper model: `whisper_model="base"`
3. Disable diarization: `enable_diarization=False`

### Import Errors
```bash
# Reinstall dependencies in virtual environment
source venv/bin/activate
pip install -r requirements.txt --upgrade
```

### Slow Transcription
- CPU processing is slower (~3-5 min/episode)
- Consider GPU acceleration for production use
- Use `base` model for speed, `small` for better accuracy

## Integration with KOI Sensor

The transcriber is designed to work asynchronously with the podcast sensor:

```python
# In podcast_sensor.py
from audio_transcriber import PodcastAudioTranscriber

class PodcastKOISensor:
    def __init__(self):
        # Initialize transcriber
        self.transcriber = PodcastAudioTranscriber(
            whisper_model=os.getenv("WHISPER_MODEL", "base"),
            enable_diarization=True,
            huggingface_token=os.getenv("HUGGINGFACE_TOKEN")
        )

    async def process_episode(self, episode_data):
        # Get audio URL from SoundCloud
        audio_url = episode_data.get('stream_url') or \
                    episode_data.get('permalink_url')

        # Transcribe
        result = await self.transcriber.transcribe_episode(
            audio_url=audio_url,
            episode_id=str(episode_data['id']),
            session=self.session  # Reuse aiohttp session
        )

        # Add to episode metadata
        episode_data['transcript'] = result.to_dict()

        # Emit KOI event with transcript
        await self.emit_episode_event(rid, episode_data, result.full_transcript, "NEW")
```

## Knowledge Graph Extraction

Once episodes are transcribed, you can extract knowledge graphs using the YonEarth v3.2.2 system:

```bash
# See: /yonearth-gaia-chatbot/scripts/extract_kg_v3_2_2.py
python3 extract_kg_v3_2_2.py
```

Features:
- **Three-stage pipeline**: Extract → Type Validate → Score
- **95% high confidence** relationships
- **Evidence tracking** with SHA256
- **$6 cost** for 172 episodes using gpt-4o-mini

## Next Steps

1. **Test transcription** on 1-2 episodes
2. **Verify output quality** (check segments, speakers, timestamps)
3. **Integrate with sensor** for automatic transcription
4. **Extract knowledge graph** for semantic search
5. **Build visualization** with audio timestamp navigation

## Resources

- **YonEarth Implementation**: `/yonearth-gaia-chatbot/scripts/retranscribe_episodes_lightweight.py`
- **KG Extraction**: `/yonearth-gaia-chatbot/scripts/extract_kg_v3_2_2.py`
- **YonEarth Docs**: `/yonearth-gaia-chatbot/docs/TRANSCRIPTION_SETUP.md`

## Credits

This transcription system is based on the proven YonEarth implementation that successfully processed 172 podcast episodes with 100% coverage and word-level timestamp precision.
