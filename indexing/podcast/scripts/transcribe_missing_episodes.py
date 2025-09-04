#!/usr/bin/env python3
"""
Transcribe missing podcast episodes from SoundCloud audio using Whisper AI
"""

import json
import subprocess
import asyncio
from pathlib import Path
from datetime import datetime
from loguru import logger
import sys
import os

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

class MissingEpisodeTranscriber:
    def __init__(self):
        self.storage_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
        self.audio_path = Path(__file__).parent.parent / "storage" / "audio_cache"
        self.audio_path.mkdir(parents=True, exist_ok=True)
        
        # Load SoundCloud episodes metadata
        self.soundcloud_file = Path(__file__).parent.parent / "storage" / "soundcloud_episodes.json"
        if not self.soundcloud_file.exists():
            # Try alternative location
            self.soundcloud_file = Path(__file__).parent.parent.parent / "storage" / "soundcloud_episodes.json"
        
        if self.soundcloud_file.exists():
            with open(self.soundcloud_file, 'r') as f:
                self.soundcloud_episodes = json.load(f)
        else:
            self.soundcloud_episodes = []
            logger.warning("SoundCloud episodes file not found")
    
    def check_existing_transcripts(self) -> dict:
        """Check which episodes have real transcripts"""
        transcript_status = {}
        
        for episode_num in range(1, 71):  # Episodes 1-70
            filename = self.storage_path / f"episode_{episode_num:03d}_complete.json"
            
            if filename.exists():
                with open(filename, 'r') as f:
                    data = json.load(f)
                
                content = data.get('transcript', data.get('content', ''))
                metadata = data.get('metadata', {})
                
                # Check if it's a real transcript
                if len(content) > 1000:
                    transcript_status[episode_num] = {
                        'has_transcript': True,
                        'source': metadata.get('transcript_source', 'unknown'),
                        'word_count': len(content.split())
                    }
                else:
                    transcript_status[episode_num] = {
                        'has_transcript': False,
                        'source': 'stub',
                        'word_count': len(content.split())
                    }
            else:
                transcript_status[episode_num] = {
                    'has_transcript': False,
                    'source': 'missing',
                    'word_count': 0
                }
        
        return transcript_status
    
    def get_soundcloud_url(self, episode_num: int) -> str:
        """Get SoundCloud URL for an episode"""
        # Try to find in our SoundCloud data
        for episode in self.soundcloud_episodes:
            # Check various fields for episode number
            title = episode.get('title', '')
            if f"{episode_num:03d}:" in title or f"{episode_num:02d}:" in title:
                return episode.get('url', '')
        
        # Fallback: construct URL pattern (may not always work)
        logger.warning(f"Could not find SoundCloud URL for episode {episode_num}")
        return None
    
    async def download_audio(self, url: str, episode_num: int) -> Path:
        """Download audio from SoundCloud using yt-dlp"""
        output_file = self.audio_path / f"episode_{episode_num:03d}.mp3"
        
        # Check if already downloaded
        if output_file.exists() and output_file.stat().st_size > 1000000:  # > 1MB
            logger.info(f"Audio already cached for episode {episode_num}")
            return output_file
        
        logger.info(f"Downloading audio for episode {episode_num}...")
        
        cmd = [
            'yt-dlp',
            '-x',  # Extract audio
            '--audio-format', 'mp3',
            '--audio-quality', '5',  # Medium quality for faster download
            '-o', str(output_file),
            url
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                logger.success(f"Downloaded audio for episode {episode_num}")
                return output_file
            else:
                logger.error(f"Failed to download: {result.stderr}")
                return None
        except subprocess.TimeoutExpired:
            logger.error(f"Download timeout for episode {episode_num}")
            return None
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None
    
    async def transcribe_audio(self, audio_file: Path, episode_num: int, model: str = "base") -> str:
        """Transcribe audio using Whisper"""
        logger.info(f"Transcribing episode {episode_num} with Whisper {model} model...")
        
        try:
            import whisper
            
            # Load model
            model = whisper.load_model(model)
            
            # Transcribe
            result = model.transcribe(str(audio_file), language="en")
            
            # Get full text
            transcript = result["text"]
            
            logger.success(f"Transcribed episode {episode_num}: {len(transcript)} chars")
            return transcript
            
        except ImportError:
            logger.error("Whisper not installed. Run: pip install openai-whisper")
            return None
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None
    
    def save_transcript(self, episode_num: int, transcript: str, source: str, soundcloud_url: str = None):
        """Save transcript with proper metadata"""
        filename = self.storage_path / f"episode_{episode_num:03d}_complete.json"
        
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
        
        # Update content and metadata
        doc['content'] = transcript
        doc['transcript'] = transcript
        
        if 'metadata' not in doc:
            doc['metadata'] = {}
        
        doc['metadata'].update({
            "episode_number": episode_num,
            "has_transcript": True,
            "transcript_source": source,
            "word_count": len(transcript.split()),
            "char_count": len(transcript),
            "transcribed_at": datetime.now().isoformat()
        })
        
        if soundcloud_url:
            doc['url'] = soundcloud_url
            doc['metadata']['audio_source'] = soundcloud_url
        
        # Save
        with open(filename, 'w') as f:
            json.dump(doc, f, indent=2)
        
        logger.info(f"Saved transcript for episode {episode_num} (source: {source})")
    
    async def process_episode(self, episode_num: int, model: str = "base"):
        """Process a single episode"""
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing episode {episode_num}")
        
        # Get SoundCloud URL
        soundcloud_url = self.get_soundcloud_url(episode_num)
        if not soundcloud_url:
            logger.warning(f"No SoundCloud URL for episode {episode_num}")
            return False
        
        # Download audio
        audio_file = await self.download_audio(soundcloud_url, episode_num)
        if not audio_file:
            logger.error(f"Could not download audio for episode {episode_num}")
            return False
        
        # Transcribe
        transcript = await self.transcribe_audio(audio_file, episode_num, model)
        if not transcript:
            logger.error(f"Could not transcribe episode {episode_num}")
            return False
        
        # Save with metadata
        self.save_transcript(episode_num, transcript, "whisper", soundcloud_url)
        
        return True
    
    async def run(self, test_mode: bool = False, model: str = "base"):
        """Main execution"""
        logger.info("Checking existing transcripts...")
        
        # Check current status
        status = self.check_existing_transcripts()
        
        # Find episodes needing transcription
        missing_episodes = []
        for episode_num, info in status.items():
            if not info['has_transcript'] or info['source'] in ['stub', 'missing']:
                missing_episodes.append(episode_num)
        
        logger.info(f"Found {len(missing_episodes)} episodes needing transcription")
        logger.info(f"Episodes: {missing_episodes}")
        
        # Summary of current status
        sources = {}
        for info in status.values():
            source = info['source']
            sources[source] = sources.get(source, 0) + 1
        
        logger.info("\nCurrent transcript sources:")
        for source, count in sources.items():
            logger.info(f"  {source}: {count} episodes")
        
        if test_mode:
            # Test with first 3 missing episodes
            missing_episodes = missing_episodes[:3]
            logger.info(f"\nTest mode: Processing first {len(missing_episodes)} episodes")
        
        # Check dependencies
        try:
            subprocess.run(['yt-dlp', '--version'], capture_output=True, check=True)
        except:
            logger.error("yt-dlp not installed. Run: pip install yt-dlp")
            return
        
        try:
            import whisper
        except:
            logger.error("Whisper not installed. Run: pip install openai-whisper")
            return
        
        # Process missing episodes
        success_count = 0
        for episode_num in missing_episodes:
            success = await self.process_episode(episode_num, model)
            if success:
                success_count += 1
            
            # Rate limiting
            await asyncio.sleep(2)
        
        # Final summary
        logger.info(f"\n{'='*60}")
        logger.info(f"Transcription complete!")
        logger.info(f"Successfully transcribed: {success_count}/{len(missing_episodes)} episodes")
        
        # Check final status
        final_status = self.check_existing_transcripts()
        final_sources = {}
        total_words = 0
        for info in final_status.values():
            source = info['source']
            final_sources[source] = final_sources.get(source, 0) + 1
            if info['has_transcript']:
                total_words += info['word_count']
        
        logger.info("\nFinal transcript sources:")
        for source, count in final_sources.items():
            logger.info(f"  {source}: {count} episodes")
        
        logger.info(f"\nTotal words: {total_words:,}")
        logger.info(f"Estimated pages: {total_words/250:.0f}")

async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Test mode (first 3 episodes)')
    parser.add_argument('--model', default='base', choices=['tiny', 'base', 'small', 'medium', 'large'],
                       help='Whisper model to use')
    args = parser.parse_args()
    
    logger.info("Starting missing episode transcription...")
    logger.info(f"Model: {args.model}")
    
    transcriber = MissingEpisodeTranscriber()
    await transcriber.run(test_mode=args.test, model=args.model)

if __name__ == "__main__":
    asyncio.run(main())