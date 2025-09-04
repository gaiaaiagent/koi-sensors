# Podcast Indexing Guide

## Overview
This guide documents the complete process for indexing the Planetary Regeneration Podcast, including lessons learned and working solutions.

## Data Sources

### 1. Notion Transcripts
- **URL**: https://regennetwork.notion.site/PRP-Trascripts-3b97bc2cf21246e09e599b615e483b8d
- **Episodes Available**: 52 out of 70 episodes have Notion pages
- **Transcript Types**:
  - **Inline Text**: Most episodes (44) have transcripts as text blocks in the page
  - **File Attachments**: Some episodes (8) have transcripts as attached files (`.txt` files from Otter.ai)
  - **Missing**: 18 episodes don't have Notion pages at all

### 2. SoundCloud Audio
- **URL**: https://soundcloud.com/planetaryregeneration
- **Episodes Available**: 50 episodes currently on SoundCloud
- **Use Case**: Fallback for episodes without Notion transcripts

## Working Solutions

### Solution 1: Notion API v3 (SUCCESSFUL)
**Key Discovery**: The Notion API v3 `loadPageChunk` endpoint bypasses Cloudflare protection.

```python
api_endpoint = "https://www.notion.so/api/v3/loadPageChunk"
payload = {
    "pageId": formatted_id,  # UUID format: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    "limit": 100,
    "cursor": {"stack": []},
    "chunkNumber": 0,
    "verticalColumns": False
}
```

**Script**: `indexing/podcast/scripts/fetch_via_notion_api.py`
- Successfully fetched 44 episodes with inline transcripts
- Total: ~400,000 words / 1,597 pages

### Solution 2: Audio Transcription with Whisper (WORKING)
For episodes without accessible transcripts, use Whisper AI to transcribe from SoundCloud.

**Key Fixes for Download Issues**:
1. **Force IPv4**: `--force-ipv4` flag avoids IPv6 routing issues
2. **Proper Headers**: Browser-like user agent and accept headers
3. **Retry Logic**: Multiple attempts with progressive delays
4. **Alternative Methods**: Extract URL first, then use curl as fallback

**Script**: `indexing/podcast/scripts/transcribe_direct.py`
- Downloads audio from SoundCloud using yt-dlp
- Transcribes with OpenAI Whisper (tiny/base models)
- Tracks transcript source in metadata

## Failed Approaches (Learning)

### 1. Direct Web Scraping
- **Issue**: Cloudflare protection blocks all requests
- **Tried**: WebFetch, curl with browser headers, httpx with sessions
- **Result**: All returned Cloudflare JavaScript challenge page

### 2. Playwright Browser Automation
- **Issue**: Timeouts even with headless browser
- **Script**: `fetch_with_playwright.py` (archived)
- **Result**: Cloudflare still detected automation

### 3. Notion File Attachments via API
- **Issue**: `getSignedFileUrls` API returned None values
- **Script**: `fetch_transcripts_from_file_blocks.py`
- **Result**: Could identify file attachments but couldn't access them

## Episode Categories

### Category 1: Successfully Indexed (50 episodes)
- 44 episodes with Notion inline transcripts
- 6 episodes with older transcript formats
- Total: ~400,000 words

### Category 2: Need Audio Transcription (20 episodes)
- Episodes 20-36: Not in Notion database
- Episode 43: Missing from Notion
- Episodes 67, 70: File attachments only

### Category 3: Problematic Episodes
- Episodes that may not exist on SoundCloud
- Episodes with very short or corrupted transcripts

## Metadata Tracking

Each episode document includes:
```json
{
  "metadata": {
    "episode_number": 67,
    "guest_name": "Josiah Hunt",
    "has_transcript": true,
    "transcript_source": "whisper",  // or "notion", "notion_api_v3"
    "word_count": 12000,
    "char_count": 65000,
    "transcribed_at": "2025-08-08T06:30:00Z",
    "audio_source": "https://soundcloud.com/..."
  }
}
```

## Performance Metrics

### Notion API v3 Fetching
- **Speed**: ~1-2 seconds per episode
- **Success Rate**: 100% for inline transcripts
- **Rate Limiting**: 2-second delay between requests recommended

### Audio Transcription
- **Download Time**: 1-5 minutes per episode (depending on network)
- **Transcription Time**: 
  - Tiny model: ~3-5 minutes per hour of audio
  - Base model: ~10-15 minutes per hour of audio
- **File Size**: ~30-40MB per episode audio file

## Commands Reference

### Check Episode Status
```bash
python indexing/podcast/scripts/check_transcript_status.py
```

### Fetch from Notion API
```bash
python indexing/podcast/scripts/fetch_via_notion_api.py
```

### Transcribe Missing Episodes
```bash
# Test with one episode
python indexing/podcast/scripts/transcribe_direct.py --episodes 67

# Process all missing
python indexing/podcast/scripts/transcribe_direct.py

# Use better model
python indexing/podcast/scripts/transcribe_direct.py --base-model
```

### Update Statistics
```bash
python indexing/podcast/scripts/count_final_transcripts.py
```

## Troubleshooting

### Download Timeouts
1. Check network connectivity
2. Try `--force-ipv4` flag
3. Update yt-dlp: `pip install -U yt-dlp`
4. Use curl fallback method

### Transcription Issues
1. Ensure Whisper is installed: `pip install openai-whisper`
2. Check audio file size (should be >1MB)
3. Try base model for better accuracy
4. Disable FP16 for compatibility

### Cloudflare Blocking
1. Don't use direct web scraping
2. Use Notion API v3 endpoints
3. Fall back to audio transcription

## Future Improvements

1. **Batch Processing**: Process multiple episodes in parallel
2. **Quality Checks**: Validate transcript length and content
3. **Speaker Diarization**: Identify different speakers
4. **Timestamp Alignment**: Match transcript with audio timestamps
5. **Notion API Access**: Request official API access for file attachments

## Document Count Methodology

Each episode page counts as ONE document, regardless of transcript length. This aligns with how users would search for and reference episodes.

**Current Status**: 
- 50 episodes indexed = 50 documents
- ~400,000 words total
- ~1,600 pages of content