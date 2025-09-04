#!/usr/bin/env python3
"""
Improved podcast transcription with better error handling and performance
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from loguru import logger
import time
import hashlib

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

def check_episodes():
    """Check which episodes need transcription"""
    storage_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
    missing = []
    
    for episode_num in range(1, 71):
        filename = storage_path / f"episode_{episode_num:03d}_complete.json"
        
        if filename.exists():
            with open(filename, 'r') as f:
                data = json.load(f)
            
            content = data.get('transcript', data.get('content', ''))
            
            # Check if it's a real transcript (more than 1000 chars)
            if len(content) < 1000:
                missing.append(episode_num)
        else:
            missing.append(episode_num)
    
    return missing

def get_soundcloud_url(episode_num):
    """Get SoundCloud URL for episode with better matching"""
    # Load SoundCloud episodes
    episodes_file = Path(__file__).parent.parent / "storage" / "soundcloud_episodes.json"
    
    if episodes_file.exists():
        with open(episodes_file, 'r') as f:
            episodes = json.load(f)
        
        # Search for episode by number in title - improved matching
        for ep in episodes:
            title = ep.get('title', '').lower()
            url = ep.get('url', '').lower()
            
            # Check various formats (case-insensitive)
            patterns = [
                f"{episode_num:03d}:",
                f"{episode_num:02d}:",
                f"episode {episode_num}",
                f"ep {episode_num}",
                f"episode-{episode_num}",
                f"ep-{episode_num}",
                f"#{episode_num}",
            ]
            
            for pattern in patterns:
                if pattern in title or pattern in url:
                    return ep.get('url')  # Return original URL (not lowercased)
    
    # Fallback: construct URL (common pattern)
    logger.warning(f"No URL found for episode {episode_num}, using fallback pattern")
    return f"https://soundcloud.com/planetaryregeneration/episode-{episode_num}"

def test_yt_dlp_installation():
    """Test if yt-dlp is properly installed and updated"""
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'yt_dlp', '--version'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            logger.info(f"yt-dlp version: {version}")
            
            # Check if version is recent (crude check)
            if "2025" not in version and "2024.12" not in version:
                logger.warning("yt-dlp might be outdated. Consider updating: pip install -U yt-dlp")
            return True
        else:
            logger.error("yt-dlp not properly installed")
            return False
    except Exception as e:
        logger.error(f"Error checking yt-dlp: {e}")
        return False

def download_with_retry(url, audio_file, max_retries=3):
    """Download with multiple retry strategies"""
    
    strategies = [
        {
            "name": "Standard with timeouts",
            "cmd": [
                sys.executable, '-m', 'yt_dlp',
                '-x', '--audio-format', 'mp3',
                '--audio-quality', '5',
                '-o', str(audio_file),
                '--force-ipv4',
                '--socket-timeout', '30',
                '--retries', '3',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                '--add-header', 'Accept-Language:en-US,en;q=0.9',
                '--add-header', 'Accept:text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                url
            ],
            "timeout": 300
        },
        {
            "name": "No certificate check",
            "cmd": [
                sys.executable, '-m', 'yt_dlp',
                '-x', '--audio-format', 'mp3',
                '-o', str(audio_file),
                '--force-ipv4',
                '--no-check-certificate',
                '--prefer-insecure',
                url
            ],
            "timeout": 300
        },
        {
            "name": "Extract audio URL only",
            "cmd": [
                sys.executable, '-m', 'yt_dlp',
                '--get-url',
                '-f', 'bestaudio',
                '--force-ipv4',
                url
            ],
            "timeout": 60
        }
    ]
    
    for strategy in strategies:
        logger.info(f"Trying strategy: {strategy['name']}")
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait_time = attempt * 10
                    logger.info(f"Waiting {wait_time} seconds before retry {attempt + 1}...")
                    time.sleep(wait_time)
                
                result = subprocess.run(
                    strategy['cmd'],
                    capture_output=True,
                    text=True,
                    timeout=strategy['timeout']
                )
                
                if result.returncode == 0:
                    if strategy['name'] == "Extract audio URL only":
                        # Got URL, now download with wget or curl
                        audio_url = result.stdout.strip()
                        logger.info(f"Got audio URL, downloading with curl...")
                        
                        curl_cmd = [
                            'curl', '-L', '-o', str(audio_file),
                            '--max-time', '300',
                            '--retry', '3',
                            '--user-agent', 'Mozilla/5.0',
                            audio_url
                        ]
                        
                        curl_result = subprocess.run(curl_cmd, capture_output=True, timeout=300)
                        if curl_result.returncode == 0:
                            logger.success(f"Downloaded successfully with {strategy['name']}")
                            return True
                    else:
                        logger.success(f"Downloaded successfully with {strategy['name']}")
                        return True
                else:
                    logger.warning(f"Attempt {attempt + 1} failed: {result.stderr[:200]}")
                    
            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout on attempt {attempt + 1}")
            except Exception as e:
                logger.warning(f"Error on attempt {attempt + 1}: {e}")
        
        logger.error(f"All attempts failed for strategy: {strategy['name']}")
    
    return False

def download_and_transcribe(episode_num, use_base_model=False):
    """Download audio and transcribe with whisper"""
    logger.info(f"\nProcessing episode {episode_num}")
    
    # Get URL
    url = get_soundcloud_url(episode_num)
    if not url:
        logger.error(f"No URL for episode {episode_num}")
        return None
    
    logger.info(f"URL: {url}")
    
    # Paths
    audio_dir = Path(__file__).parent.parent / "storage" / "audio_cache"
    audio_dir.mkdir(parents=True, exist_ok=True)
    
    # Use URL hash in filename to handle retries with different URLs
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    audio_file = audio_dir / f"episode_{episode_num:03d}_{url_hash}.mp3"
    
    # Check for any existing audio file for this episode
    existing_files = list(audio_dir.glob(f"episode_{episode_num:03d}_*.mp3"))
    if existing_files:
        for existing in existing_files:
            if existing.stat().st_size > 1000000:  # > 1MB
                logger.info(f"Using existing audio file: {existing}")
                audio_file = existing
                break
    
    # Download if needed
    if not audio_file.exists() or audio_file.stat().st_size < 1000000:
        logger.info("Downloading audio...")
        
        success = download_with_retry(url, audio_file)
        
        if not success:
            logger.error(f"Failed to download episode {episode_num}")
            return None
            
        # Verify download
        if not audio_file.exists() or audio_file.stat().st_size < 1000000:
            logger.error(f"Downloaded file is too small or missing")
            return None
            
        logger.success(f"Downloaded to {audio_file} ({audio_file.stat().st_size / 1024 / 1024:.1f} MB)")
    else:
        logger.info(f"Using cached audio: {audio_file} ({audio_file.stat().st_size / 1024 / 1024:.1f} MB)")
    
    # Transcribe
    model_name = "base" if use_base_model else "tiny"
    logger.info(f"Transcribing with Whisper ({model_name} model)...")
    
    try:
        import whisper
        
        # Load model with error handling
        try:
            model = whisper.load_model(model_name)
        except Exception as e:
            logger.warning(f"Failed to load {model_name} model: {e}")
            if model_name != "tiny":
                logger.info("Falling back to tiny model...")
                model = whisper.load_model("tiny")
            else:
                raise
        
        # Transcribe with progress callback if possible
        result = model.transcribe(
            str(audio_file),
            language="en",
            verbose=False,  # Reduce output noise
            fp16=False  # Disable FP16 for better compatibility
        )
        
        transcript = result["text"]
        
        # Basic quality check
        if len(transcript) < 500:
            logger.warning(f"Transcript seems too short ({len(transcript)} chars)")
            if model_name == "tiny" and not use_base_model:
                logger.info("Retrying with base model for better quality...")
                return download_and_transcribe(episode_num, use_base_model=True)
        
        logger.success(f"Transcribed: {len(transcript)} chars, {len(transcript.split())} words")
        return transcript
        
    except ImportError:
        logger.error("Whisper not installed. Install with: pip install openai-whisper")
        return None
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        
        # If transcription fails, we might still have the audio
        if audio_file.exists():
            logger.info(f"Audio file saved at: {audio_file}")
            logger.info("You can try transcribing manually later")
        
        return None

def save_transcript(episode_num, transcript):
    """Save transcript to file"""
    storage_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
    storage_path.mkdir(parents=True, exist_ok=True)
    
    filename = storage_path / f"episode_{episode_num:03d}_complete.json"
    
    # Load existing or create new
    if filename.exists():
        with open(filename, 'r') as f:
            doc = json.load(f)
    else:
        doc = {
            "id": f"podcast_episode_{episode_num:03d}",
            "source": "podcast:planetary_regeneration",
            "source_type": "podcast_transcript",
            "title": f"Planetary Regeneration Podcast Episode {episode_num}"
        }
    
    # Update
    doc['content'] = transcript
    doc['transcript'] = transcript
    
    if 'metadata' not in doc:
        doc['metadata'] = {}
    
    doc['metadata'].update({
        "episode_number": episode_num,
        "has_transcript": True,
        "transcript_source": "whisper",
        "word_count": len(transcript.split()),
        "char_count": len(transcript),
        "transcribed_at": datetime.now().isoformat()
    })
    
    # Add SoundCloud URL
    url = get_soundcloud_url(episode_num)
    if url:
        doc['url'] = url
        doc['metadata']['audio_source'] = url
    
    # Save
    with open(filename, 'w') as f:
        json.dump(doc, f, indent=2)
    
    logger.info(f"Saved episode {episode_num} to {filename}")

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--episodes', nargs='+', type=int, help='Specific episodes to transcribe')
    parser.add_argument('--test', action='store_true', help='Test with first episode')
    parser.add_argument('--skip-check', action='store_true', help='Skip yt-dlp version check')
    parser.add_argument('--base-model', action='store_true', help='Use base whisper model (better quality, slower)')
    args = parser.parse_args()
    
    # Check yt-dlp installation
    if not args.skip_check:
        if not test_yt_dlp_installation():
            logger.error("Please install/update yt-dlp: pip install -U yt-dlp")
            sys.exit(1)
    
    # Determine which episodes to process
    if args.episodes:
        episodes_to_process = args.episodes
    else:
        missing = check_episodes()
        logger.info(f"Episodes needing transcription: {missing}")
        
        if args.test:
            episodes_to_process = missing[:1] if missing else []
        else:
            episodes_to_process = missing
    
    if not episodes_to_process:
        logger.info("No episodes to process!")
        return
    
    logger.info(f"Will process {len(episodes_to_process)} episodes: {episodes_to_process}")
    
    # Process each episode
    success_count = 0
    failed_episodes = []
    
    for i, episode_num in enumerate(episodes_to_process, 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"Episode {i}/{len(episodes_to_process)}")
        logger.info(f"{'='*60}")
        
        transcript = download_and_transcribe(episode_num, use_base_model=args.base_model)
        
        if transcript:
            save_transcript(episode_num, transcript)
            success_count += 1
        else:
            failed_episodes.append(episode_num)
            logger.error(f"Failed to process episode {episode_num}")
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Completed: {success_count}/{len(episodes_to_process)} episodes")
    
    if failed_episodes:
        logger.warning(f"Failed episodes: {failed_episodes}")
    
    # Final status
    final_missing = check_episodes()
    logger.info(f"Remaining episodes without transcripts: {len(final_missing)}")
    if final_missing:
        logger.info(f"Episodes still missing: {final_missing}")

if __name__ == "__main__":
    main()