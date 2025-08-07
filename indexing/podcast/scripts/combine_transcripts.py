#!/usr/bin/env python3
"""
Combine successful Notion transcripts with audio transcriptions for blocked episodes.
Creates a complete podcast dataset using the best available source for each episode.
"""

import json
from pathlib import Path
from typing import Dict, List
from loguru import logger
import shutil


def check_transcript_quality(transcript: str) -> bool:
    """Check if a transcript is valid and not blocked."""
    if not transcript:
        return False
    if len(transcript) < 100:
        return False
    if "Enable JavaScript and cookies" in transcript:
        return False
    if "Waiting for regennetwork.notion.site" in transcript:
        return False
    return True


def main():
    logger.info("="*60)
    logger.info("📚 Combining Podcast Transcripts")
    logger.info("="*60)
    
    # Directories
    notion_dir = Path("indexing/storage/podcast_complete")
    audio_dir = Path("indexing/storage/podcast_transcribed")
    soundcloud_dir = Path("indexing/storage/documents")
    output_dir = Path("indexing/storage/podcast_final")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Track statistics
    stats = {
        'notion_success': 0,
        'audio_transcribed': 0,
        'metadata_only': 0,
        'total': 0
    }
    
    # Get all episode numbers
    all_episodes = set()
    
    # From Notion attempts
    for f in notion_dir.glob("episode_*.json"):
        try:
            num = int(f.stem.split('_')[1])
            all_episodes.add(num)
        except:
            pass
    
    # From SoundCloud
    for f in soundcloud_dir.glob("soundcloud_*.json"):
        with open(f) as fp:
            data = json.load(fp)
            title = data.get('title', '')
            # Extract episode number from title
            import re
            match = re.search(r'^(\d+):', title)
            if match:
                all_episodes.add(int(match.group(1)))
    
    logger.info(f"Found {len(all_episodes)} total episodes")
    
    # Process each episode
    for episode_num in sorted(all_episodes):
        logger.info(f"\nProcessing Episode {episode_num:03d}")
        
        output_file = output_dir / f"episode_{episode_num:03d}_final.json"
        
        # Try Notion transcript first
        notion_file = notion_dir / f"episode_{episode_num:03d}_complete.json"
        if notion_file.exists():
            with open(notion_file) as f:
                data = json.load(f)
                
            if check_transcript_quality(data.get('transcript', '')):
                # Good Notion transcript
                logger.success(f"  ✓ Using Notion transcript ({len(data['transcript'])} chars)")
                with open(output_file, 'w') as f:
                    json.dump(data, f, indent=2)
                stats['notion_success'] += 1
                stats['total'] += 1
                continue
        
        # Try audio transcription
        audio_file = audio_dir / f"episode_{episode_num:03d}_transcribed.json"
        if audio_file.exists():
            with open(audio_file) as f:
                data = json.load(f)
                
            if data.get('transcript'):
                logger.success(f"  ✓ Using audio transcription ({len(data['transcript'])} chars)")
                with open(output_file, 'w') as f:
                    json.dump(data, f, indent=2)
                stats['audio_transcribed'] += 1
                stats['total'] += 1
                continue
        
        # Fall back to SoundCloud metadata only
        for sc_file in soundcloud_dir.glob("soundcloud_*.json"):
            with open(sc_file) as f:
                data = json.load(f)
                title = data.get('title', '')
                
            import re
            match = re.search(r'^(\d+):', title)
            if match and int(match.group(1)) == episode_num:
                logger.warning(f"  ⚠ Using metadata only (no transcript available)")
                
                # Mark as needing transcription
                data['metadata']['needs_transcription'] = True
                data['metadata']['transcript_status'] = 'pending'
                
                with open(output_file, 'w') as f:
                    json.dump(data, f, indent=2)
                stats['metadata_only'] += 1
                stats['total'] += 1
                break
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("✅ Combination Complete!")
    logger.info(f"Total episodes: {stats['total']}")
    logger.info(f"  - Notion transcripts: {stats['notion_success']}")
    logger.info(f"  - Audio transcriptions: {stats['audio_transcribed']}")
    logger.info(f"  - Metadata only: {stats['metadata_only']}")
    logger.info(f"Output directory: {output_dir}")
    
    # List episodes needing transcription
    needs_transcription = []
    for f in output_dir.glob("episode_*.json"):
        with open(f) as fp:
            data = json.load(fp)
            if data.get('metadata', {}).get('needs_transcription'):
                num = int(f.stem.split('_')[1])
                needs_transcription.append(num)
    
    if needs_transcription:
        logger.info(f"\n📝 Episodes needing transcription: {needs_transcription[:10]}...")
        logger.info("Run transcribe_podcast_audio.py to transcribe these from audio")


if __name__ == "__main__":
    main()