#!/usr/bin/env python3
"""
Transcribe podcast episodes from audio and combine metadata from multiple sources.
Merges SoundCloud metadata with Notion page info and audio transcriptions.
"""

import asyncio
import json
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import whisper
import yt_dlp
from loguru import logger
from tqdm import tqdm


def extract_episode_number(title: str) -> Optional[int]:
    """Extract episode number from title."""
    patterns = [
        r'^(\d+):',           # "01: Guest Name"
        r'^0?(\d+):',         # "001: Guest Name"  
        r'Episode\s+(\d+)',   # "Episode 01"
        r'#(\d+)',            # "#01"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def extract_guest_name(title: str) -> str:
    """Extract guest name from title."""
    # Remove episode number patterns
    title = re.sub(r'^(\d+:|0?\d+:|Episode\s+\d+:?|#\d+:?)\s*', '', title, flags=re.IGNORECASE)
    # Remove extra formatting
    title = title.split('|')[0].strip()
    return title


async def download_audio(url: str, output_path: Path) -> bool:
    """Download audio from SoundCloud using yt-dlp."""
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(output_path),
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        # Check if file exists (might have .mp3 extension added)
        if output_path.exists():
            return True
        elif output_path.with_suffix('.mp3').exists():
            return True
        else:
            logger.error(f"Audio file not found after download: {output_path}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to download audio from {url}: {e}")
        return False


def transcribe_audio(audio_path: Path, model_name: str = "base") -> Optional[Dict]:
    """Transcribe audio file using Whisper."""
    try:
        logger.info(f"Loading Whisper model: {model_name}")
        model = whisper.load_model(model_name)
        
        logger.info(f"Transcribing: {audio_path.name}")
        result = model.transcribe(
            str(audio_path),
            language="en",
            fp16=False,  # Disable for CPU
            verbose=False
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return None


def format_transcript(result: Dict) -> str:
    """Format Whisper transcript with timestamps."""
    if not result:
        return ""
        
    lines = []
    
    # Add full transcript
    lines.append("## Full Transcript\n")
    lines.append(result.get('text', '').strip())
    lines.append("")
    
    # Add timestamped segments
    if 'segments' in result:
        lines.append("## Timestamped Segments\n")
        
        for segment in result['segments']:
            start = int(segment['start'])
            end = int(segment['end'])
            text = segment['text'].strip()
            
            # Format as MM:SS
            start_min = start // 60
            start_sec = start % 60
            end_min = end // 60
            end_sec = end % 60
            
            lines.append(f"[{start_min:02d}:{start_sec:02d} - {end_min:02d}:{end_sec:02d}] {text}")
            
    return "\n".join(lines)


def combine_metadata(soundcloud_doc: Dict, notion_info: Optional[Dict] = None) -> Dict:
    """Combine metadata from SoundCloud and Notion sources."""
    
    # Start with SoundCloud as base
    combined = soundcloud_doc.copy()
    
    # Extract additional info from title
    episode_num = extract_episode_number(soundcloud_doc['title'])
    guest_name = extract_guest_name(soundcloud_doc['title'])
    
    # Enhance metadata
    combined['metadata']['episode_number'] = episode_num
    combined['metadata']['guest_name'] = guest_name
    
    # Add Notion info if available
    if notion_info:
        combined['metadata']['notion_url'] = notion_info.get('url')
        combined['metadata']['notion_title'] = notion_info.get('title')
        
        # Notion might have better formatted guest name
        if notion_info.get('guest'):
            combined['metadata']['guest_name'] = notion_info['guest']
            
    return combined


async def process_episode(
    soundcloud_doc: Dict,
    notion_info: Optional[Dict],
    cache_dir: Path,
    whisper_model: str = "base",
    force_download: bool = False
) -> Dict:
    """Process a single episode: download, transcribe, and combine metadata."""
    
    episode_id = soundcloud_doc['id']
    episode_num = extract_episode_number(soundcloud_doc['title'])
    
    # Prepare audio file path
    audio_file = cache_dir / f"{episode_id}.mp3"
    
    # Download audio if needed
    if not audio_file.exists() or force_download:
        logger.info(f"Downloading audio for episode {episode_num}")
        success = await download_audio(soundcloud_doc['url'], audio_file.with_suffix(''))
        
        # Check for file with .mp3 extension
        if not audio_file.exists() and audio_file.with_suffix('.mp3.mp3').exists():
            audio_file = audio_file.with_suffix('.mp3.mp3')
        elif not audio_file.exists():
            temp_file = cache_dir / f"{episode_id}"
            if temp_file.exists():
                temp_file.rename(audio_file)
                
        if not audio_file.exists():
            logger.error(f"Failed to download episode {episode_num}")
            return combine_metadata(soundcloud_doc, notion_info)
    else:
        logger.info(f"Using cached audio for episode {episode_num}")
        
    # Transcribe audio
    logger.info(f"Transcribing episode {episode_num}: {soundcloud_doc['title'][:50]}...")
    result = transcribe_audio(audio_file, whisper_model)
    
    # Combine all data
    combined = combine_metadata(soundcloud_doc, notion_info)
    
    if result:
        # Add transcript
        transcript_text = format_transcript(result)
        combined['transcript'] = transcript_text
        combined['metadata']['has_transcript'] = True
        combined['metadata']['transcript_source'] = 'whisper'
        combined['metadata']['transcript_model'] = whisper_model
        combined['metadata']['transcript_length'] = len(result.get('text', ''))
        
        # Update content with transcript
        combined['content'] = combined['content'].replace(
            "*Note: Audio transcription not yet implemented. This document contains metadata only.*",
            transcript_text
        )
        
        logger.success(f"Transcribed episode {episode_num}: {len(result['text'])} chars")
    else:
        logger.warning(f"Failed to transcribe episode {episode_num}")
        
    return combined


async def main():
    """Main transcription pipeline."""
    
    logger.info("="*60)
    logger.info("🎙️ Podcast Audio Transcription Pipeline")
    logger.info("="*60)
    
    # Load SoundCloud documents
    soundcloud_dir = Path("indexing/storage/documents")
    soundcloud_docs = []
    
    for doc_path in soundcloud_dir.glob("soundcloud_*.json"):
        with open(doc_path) as f:
            soundcloud_docs.append(json.load(f))
            
    # Sort by episode number
    for doc in soundcloud_docs:
        doc['_episode_num'] = extract_episode_number(doc['title']) or 999
    soundcloud_docs.sort(key=lambda x: x['_episode_num'])
    
    logger.info(f"Loaded {len(soundcloud_docs)} SoundCloud episodes")
    
    # Load Notion transcript links for metadata
    notion_links_file = Path("indexing/storage/notion_transcripts/transcript_links.json")
    notion_links = {}
    
    if notion_links_file.exists():
        with open(notion_links_file) as f:
            links = json.load(f)
            for link in links:
                notion_links[link['episode_num']] = link
        logger.info(f"Loaded {len(notion_links)} Notion transcript references")
    
    # Setup directories
    cache_dir = Path("indexing/cache/audio")
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    output_dir = Path("indexing/storage/podcast_transcribed")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Ask user for options
    import sys
    if len(sys.argv) > 1:
        if '--test' in sys.argv:
            soundcloud_docs = soundcloud_docs[:3]  # Test with first 3
            logger.info("TEST MODE: Processing first 3 episodes")
        if '--tiny' in sys.argv:
            whisper_model = 'tiny'
            logger.info("Using tiny Whisper model for faster processing")
        elif '--small' in sys.argv:
            whisper_model = 'small'
            logger.info("Using small Whisper model")
        elif '--medium' in sys.argv:
            whisper_model = 'medium'
            logger.info("Using medium Whisper model")
        else:
            whisper_model = 'base'
    else:
        whisper_model = 'base'
        
    logger.info(f"Whisper model: {whisper_model}")
    logger.info(f"Episodes to process: {len(soundcloud_docs)}")
    
    # Process episodes
    successful = 0
    failed = 0
    
    with tqdm(total=len(soundcloud_docs), desc="Processing episodes") as pbar:
        for doc in soundcloud_docs:
            try:
                episode_num = doc['_episode_num']
                
                # Get Notion info if available
                notion_info = notion_links.get(episode_num)
                
                # Process episode
                result = await process_episode(
                    doc,
                    notion_info,
                    cache_dir,
                    whisper_model
                )
                
                # Save result
                output_file = output_dir / f"episode_{episode_num:03d}_transcribed.json"
                with open(output_file, 'w') as f:
                    json.dump(result, f, indent=2)
                    
                if result.get('transcript'):
                    successful += 1
                else:
                    failed += 1
                    
                pbar.update(1)
                
            except Exception as e:
                logger.error(f"Error processing episode: {e}")
                failed += 1
                pbar.update(1)
                
    # Summary
    logger.info("\n" + "="*60)
    logger.info("✅ Transcription Complete!")
    logger.info(f"Successfully transcribed: {successful} episodes")
    logger.info(f"Failed: {failed} episodes") 
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Audio cache: {cache_dir}")
    logger.info("="*60)
    
    # Show sample
    if successful > 0:
        sample_files = list(output_dir.glob("*.json"))[:3]
        logger.info("\nSample transcribed files:")
        for f in sample_files:
            with open(f) as fp:
                data = json.load(fp)
                trans_len = len(data.get('transcript', ''))
                logger.info(f"  {f.name}: {trans_len} chars")


if __name__ == "__main__":
    import sys
    
    # Check if whisper is installed
    try:
        import whisper
    except ImportError:
        logger.error("Whisper not installed! Run: pip install openai-whisper")
        sys.exit(1)
        
    # Check if yt-dlp is installed
    try:
        import yt_dlp
    except ImportError:
        logger.error("yt-dlp not installed! Run: pip install yt-dlp")
        sys.exit(1)
        
    asyncio.run(main())