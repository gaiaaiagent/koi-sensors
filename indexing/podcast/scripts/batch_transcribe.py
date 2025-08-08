#!/usr/bin/env python3
"""
Batch transcribe episodes efficiently using Whisper
"""

import os
import json
import subprocess
from pathlib import Path
from datetime import datetime
from loguru import logger
import sys

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

def transcribe_with_cli(audio_path, output_dir):
    """Use whisper CLI which is often faster than Python API"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Run whisper CLI
    cmd = [
        'whisper',
        str(audio_path),
        '--model', 'tiny',
        '--output_dir', str(output_dir),
        '--output_format', 'txt',
        '--language', 'en',
        '--verbose', 'False'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        # Find the output txt file
        base_name = audio_path.stem
        txt_file = output_dir / f"{base_name}.txt"
        
        if txt_file.exists():
            with open(txt_file, 'r') as f:
                transcript = f.read()
            return transcript
        else:
            logger.error(f"No output file found for {audio_path}")
            return None
            
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout transcribing {audio_path}")
        return None
    except Exception as e:
        logger.error(f"Error transcribing {audio_path}: {e}")
        return None

def process_episode(episode_num):
    """Process a single episode"""
    storage_path = Path(__file__).parent.parent / "storage"
    audio_cache = storage_path / "audio_cache"
    output_path = storage_path / "podcast_complete" / f"episode_{episode_num:03d}_complete.json"
    
    # Check if already completed
    if output_path.exists():
        with open(output_path, 'r') as f:
            data = json.load(f)
        if len(data.get('transcript', '')) > 1000:
            logger.info(f"Episode {episode_num} already has transcript")
            return True
    
    # Find audio file
    audio_patterns = [
        f"episode_{episode_num:03d}_*.mp3",
        f"episode_{episode_num:03d}.mp3",
        f"episode_{episode_num:03d}_*.m4a",
        f"episode_{episode_num:03d}.m4a"
    ]
    
    audio_file = None
    for pattern in audio_patterns:
        matches = list(audio_cache.glob(pattern))
        if matches:
            # Prefer mp3 over m4a
            mp3_matches = [m for m in matches if m.suffix == '.mp3']
            if mp3_matches:
                audio_file = mp3_matches[0]
            else:
                audio_file = matches[0]
            break
    
    if not audio_file:
        logger.warning(f"No audio file found for episode {episode_num}")
        return False
    
    logger.info(f"Transcribing episode {episode_num} from {audio_file.name}")
    
    # Transcribe
    transcripts_dir = storage_path / "transcripts_raw"
    transcript = transcribe_with_cli(audio_file, transcripts_dir)
    
    if not transcript:
        logger.error(f"Failed to transcribe episode {episode_num}")
        return False
    
    # Save result
    data = {
        "id": f"podcast_episode_{episode_num:03d}",
        "source": "soundcloud:audio",
        "source_type": "audio_transcription",
        "episode_number": episode_num,
        "title": f"Planetary Regeneration Podcast Episode {episode_num}",
        "transcript": transcript,
        "metadata": {
            "episode_number": episode_num,
            "has_transcript": True,
            "transcript_source": "whisper_tiny",
            "word_count": len(transcript.split()),
            "char_count": len(transcript),
            "transcribed_at": datetime.now().isoformat(),
            "audio_file": audio_file.name,
            "audio_size_mb": audio_file.stat().st_size / 1024 / 1024
        }
    }
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    logger.success(f"✅ Episode {episode_num}: {len(transcript.split())} words")
    return True

def main():
    """Main entry point"""
    # Episodes that need transcription
    stub_episodes = [67, 70]
    missing_episodes = list(range(20, 37)) + [43]
    
    all_episodes = stub_episodes + missing_episodes
    
    logger.info(f"Processing {len(all_episodes)} episodes")
    
    # Process stub episodes first (they have audio cached)
    for episode_num in stub_episodes:
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing stub episode {episode_num}")
        logger.info('='*60)
        process_episode(episode_num)
    
    # Then process missing episodes if needed
    for episode_num in missing_episodes:
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing missing episode {episode_num}")
        logger.info('='*60)
        
        # Check if audio exists
        audio_cache = Path(__file__).parent.parent / "storage" / "audio_cache"
        if not any(audio_cache.glob(f"episode_{episode_num:03d}*")):
            logger.warning(f"No audio for episode {episode_num}, skipping")
            continue
            
        process_episode(episode_num)
    
    logger.info("\n" + "="*60)
    logger.info("BATCH TRANSCRIPTION COMPLETE")
    logger.info("="*60)

if __name__ == "__main__":
    main()