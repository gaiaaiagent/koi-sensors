#!/usr/bin/env python3
"""
YouTube Sensor for KOI System
Monitors YouTube channels and transcribes videos using Whisper

Features:
- Channel monitoring via YouTube Data API or yt-dlp
- Audio extraction from videos
- Whisper transcription (large model for high accuracy)
- KOI protocol integration
- Persistent state management
"""

import os
import sys
import json
import hashlib
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dotenv import load_dotenv

# Add parent directories to path for KOI imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import ORN
from koi_protocol.core.bundle_system import document_to_bundle
from shared.persistent_state import PersistentSensorState

# YouTube and transcription dependencies
try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False
    print("⚠️  yt-dlp not available. Install with: pip install yt-dlp")

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    print("⚠️  Whisper not available. Install with: pip install openai-whisper")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class YouTubeVideoRID(ORN):
    """YouTube video RID: orn:youtube.video:channel_id/video_id"""
    namespace = "youtube.video"

    def __init__(self, channel_id: str, video_id: str):
        self.channel_id = channel_id
        self.video_id = video_id
        super().__init__()

    @property
    def reference(self) -> str:
        return f"{self.channel_id}/{self.video_id}"


class YouTubeKOISensor:
    """
    YouTube sensor using yt-dlp for video/metadata fetching and Whisper transcription
    """

    def __init__(self):
        # Load environment variables
        load_dotenv(Path(__file__).parent.parent.parent / '.env')

        # Configuration
        self.channel_url = os.getenv("YOUTUBE_CHANNEL_URL", "https://www.youtube.com/@RegenNetwork")
        self.whisper_model_name = os.getenv("WHISPER_MODEL", "large")
        self.max_videos_first_run = int(os.getenv("YOUTUBE_MAX_VIDEOS_FIRST_RUN", "5"))
        self.check_interval = int(os.getenv("YOUTUBE_CHECK_INTERVAL", "86400"))  # 24 hours

        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name="youtube-sensor",
            coordinator_url="http://localhost:8005"
        )

        # Persistent state
        self.state = PersistentSensorState('youtube', Path(__file__).parent)

        # Whisper model (loaded on first use)
        self.whisper_model = None

        # Output directories
        self.videos_dir = Path(__file__).parent / 'videos'
        self.videos_dir.mkdir(exist_ok=True)

        logger.info(f"YouTube Sensor initialized")
        logger.info(f"  Channel: {self.channel_url}")
        logger.info(f"  Whisper model: {self.whisper_model_name}")
        logger.info(f"  Max videos (first run): {self.max_videos_first_run}")
        logger.info(f"  Check interval: {self.check_interval}s ({self.check_interval/3600:.1f}h)")

    def _load_whisper_model(self):
        """Lazy-load Whisper model"""
        if not WHISPER_AVAILABLE:
            raise ImportError("Whisper is required. Install with: pip install openai-whisper")

        if self.whisper_model is None:
            logger.info(f"Loading Whisper model: {self.whisper_model_name}")
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.whisper_model = whisper.load_model(self.whisper_model_name, device=device)
            logger.info(f"✓ Whisper model loaded on {device}")

    async def fetch_channel_videos(self, max_videos: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Fetch videos from the YouTube channel using yt-dlp

        Args:
            max_videos: Maximum number of videos to fetch (None = all)

        Returns:
            List of video metadata dictionaries
        """
        if not YTDLP_AVAILABLE:
            raise ImportError("yt-dlp is required. Install with: pip install yt-dlp")

        # Make sure we're fetching from the videos tab
        videos_url = self.channel_url.rstrip('/') + '/videos'
        logger.info(f"Fetching videos from: {videos_url}")

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': 'in_playlist',  # Don't download, just get metadata
            'playlistend': max_videos,      # Limit number of videos
            'ignoreerrors': True,            # Continue on errors
        }

        try:
            # Run yt-dlp in thread pool (it's blocking)
            def extract_info():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(videos_url, download=False)

            result = await asyncio.to_thread(extract_info)

            if not result or 'entries' not in result:
                logger.error("Failed to fetch channel videos")
                return []

            videos = []
            for entry in result['entries']:
                if entry is None:
                    continue

                video_id = entry.get('id')
                if not video_id:
                    continue

                # Filter out non-video entries
                # When using extract_flat, entries are URLs to videos
                # We don't skip based on duration since extract_flat doesn't fetch full metadata

                # Extract metadata
                videos.append({
                    'video_id': video_id,
                    'channel_id': entry.get('channel_id', result.get('channel_id', 'unknown')),
                    'title': entry.get('title', 'Untitled'),
                    'description': entry.get('description', ''),
                    'duration': entry.get('duration', 0),
                    'upload_date': entry.get('upload_date', ''),
                    'view_count': entry.get('view_count', 0),
                    'like_count': entry.get('like_count', 0),
                    'url': f"https://www.youtube.com/watch?v={video_id}",
                    'thumbnail': entry.get('thumbnail', ''),
                })

            logger.info(f"✓ Found {len(videos)} videos")
            return videos

        except Exception as e:
            logger.error(f"Failed to fetch channel videos: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    async def download_audio(self, video_url: str, video_id: str) -> Optional[Path]:
        """
        Download audio from YouTube video

        Args:
            video_url: YouTube video URL
            video_id: Video ID for filename

        Returns:
            Path to downloaded audio file or None if failed
        """
        audio_path = self.videos_dir / f"{video_id}.mp3"

        # Skip if already downloaded
        if audio_path.exists():
            logger.info(f"Using cached audio: {audio_path.name}")
            return audio_path

        logger.info(f"Downloading audio from: {video_url}")

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(audio_path.with_suffix('')),  # yt-dlp adds extension
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
        }

        try:
            def download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])

            await asyncio.to_thread(download)

            if audio_path.exists():
                file_size_mb = audio_path.stat().st_size / 1024 / 1024
                logger.info(f"✓ Downloaded audio: {audio_path.name} ({file_size_mb:.1f} MB)")
                return audio_path
            else:
                logger.error(f"Audio file not created: {audio_path}")
                return None

        except Exception as e:
            logger.error(f"Failed to download audio: {e}")
            return None

    async def transcribe_audio(self, audio_path: Path) -> Optional[Dict[str, Any]]:
        """
        Transcribe audio using Whisper

        Args:
            audio_path: Path to audio file

        Returns:
            Transcription result with text and metadata
        """
        logger.info(f"Transcribing: {audio_path.name}")

        try:
            # Load model if needed
            self._load_whisper_model()

            # Run transcription in thread pool (blocking operation)
            def transcribe():
                return self.whisper_model.transcribe(
                    str(audio_path),
                    word_timestamps=True,
                    verbose=False
                )

            result = await asyncio.to_thread(transcribe)

            # Build formatted transcript with timestamps
            segments = []
            for seg in result['segments']:
                segments.append({
                    'start': seg['start'],
                    'end': seg['end'],
                    'text': seg['text'].strip()
                })

            full_transcript = "\n\n".join([
                f"[{seg['start']:.1f}s - {seg['end']:.1f}s]: {seg['text']}"
                for seg in segments
            ])

            logger.info(f"✓ Transcription complete: {len(segments)} segments, {result.get('duration', 0):.1f}s")

            return {
                'full_transcript': full_transcript,
                'segments': segments,
                'language': result.get('language', 'en'),
                'duration': result.get('duration', 0),
                'model': self.whisper_model_name,
            }

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def process_video_to_document(
        self,
        video_metadata: Dict[str, Any],
        transcription: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Convert video metadata and transcription to KOI document

        Args:
            video_metadata: Video metadata from yt-dlp
            transcription: Whisper transcription result

        Returns:
            KOI document dictionary or None if already processed
        """
        video_id = video_metadata['video_id']

        # Check if already processed
        if self.state.is_processed(video_id):
            return None

        # Generate RID
        rid = YouTubeVideoRID(
            video_metadata['channel_id'],
            video_id
        ).to_string()

        # Build content with transcript if available
        content_parts = [video_metadata.get('description', '')]
        if transcription:
            content_parts.append("\n\n=== TRANSCRIPT ===\n\n")
            content_parts.append(transcription['full_transcript'])

        content = "".join(content_parts)

        # Parse upload date to ISO format
        upload_date = video_metadata.get('upload_date', '')
        try:
            if upload_date:
                # YouTube format: YYYYMMDD
                dt = datetime.strptime(upload_date, '%Y%m%d')
                timestamp = dt.replace(tzinfo=timezone.utc).isoformat()
            else:
                timestamp = datetime.now(timezone.utc).isoformat()
        except:
            timestamp = datetime.now(timezone.utc).isoformat()

        # Build KOI document
        document = {
            'rid': rid,
            'source': f"youtube:{video_metadata['channel_id']}",
            'source_type': 'youtube',
            'url': video_metadata['url'],
            'title': video_metadata['title'],
            'content': content,
            'timestamp': timestamp,
            'metadata': {
                'platform': 'youtube',
                'video_id': video_id,
                'channel_id': video_metadata['channel_id'],
                'duration': video_metadata.get('duration', 0),
                'view_count': video_metadata.get('view_count', 0),
                'like_count': video_metadata.get('like_count', 0),
                'upload_date': upload_date,
                'thumbnail': video_metadata.get('thumbnail', ''),
                'transcribed': transcription is not None,
                'transcription_language': transcription.get('language') if transcription else None,
                'whisper_model': self.whisper_model_name if transcription else None,
            }
        }

        # Mark as processed
        self.state.mark_processed("youtube", video_id)
        self.state.save()

        return document

    async def send_to_koi(self, document: Dict[str, Any]) -> bool:
        """
        Send document to KOI coordinator

        Args:
            document: KOI document dictionary

        Returns:
            True if successful, False otherwise
        """
        try:
            bundle = document_to_bundle(document)
            await self.koi_node.emit_new_event(bundle)
            logger.info(f"✅ Sent to KOI: {document['title']}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send to KOI: {e}")
            return False

    async def send_heartbeat_event(self):
        """Send heartbeat to coordinator"""
        heartbeat_data = {
            "type": "sensor_heartbeat",
            "sensor": "youtube",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "active",
            "channel": self.channel_url
        }

        heartbeat_doc = {
            'id': f"youtube_heartbeat_{int(datetime.now().timestamp())}",
            'title': 'YouTube Sensor Heartbeat',
            'content': json.dumps(heartbeat_data),
            'metadata': {
                'sensor_type': 'youtube',
                'event_type': 'HEARTBEAT'
            }
        }

        try:
            bundle = document_to_bundle(heartbeat_doc)
            await self.koi_node.emit_new_event(bundle)
            logger.info("💓 Heartbeat sent")
        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")

    async def send_periodic_heartbeats(self):
        """Send heartbeats every 30 minutes"""
        while True:
            await asyncio.sleep(1800)  # 30 minutes
            await self.send_heartbeat_event()

    async def process_video(self, video_metadata: Dict[str, Any]) -> bool:
        """
        Process a single video: download audio, transcribe, send to KOI

        Args:
            video_metadata: Video metadata dictionary

        Returns:
            True if successful, False otherwise
        """
        video_id = video_metadata['video_id']
        title = video_metadata['title']

        logger.info(f"{'='*80}")
        logger.info(f"Processing: {title}")
        logger.info(f"Video ID: {video_id}")
        logger.info(f"{'='*80}")

        try:
            # Download audio
            audio_path = await self.download_audio(video_metadata['url'], video_id)
            if not audio_path:
                logger.error("Failed to download audio, skipping transcription")
                return False

            # Transcribe audio
            transcription = await self.transcribe_audio(audio_path)
            if not transcription:
                logger.warning("Transcription failed, continuing without transcript")

            # Create KOI document
            document = self.process_video_to_document(video_metadata, transcription)
            if not document:
                logger.info("Video already processed, skipping")
                return True

            # Send to KOI
            success = await self.send_to_koi(document)

            # Clean up audio file to save space
            if audio_path.exists() and not os.getenv("KEEP_AUDIO_FILES"):
                audio_path.unlink()
                logger.info(f"Cleaned up audio file: {audio_path.name}")

            return success

        except Exception as e:
            logger.error(f"Failed to process video {video_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def run(self, continuous: bool = False):
        """
        Main run loop

        Args:
            continuous: If True, run continuously with periodic checks
        """
        logger.info("🎥 YOUTUBE SENSOR STARTING")
        logger.info(f"Channel: {self.channel_url}")
        logger.info(f"Continuous mode: {continuous}")

        # Start KOI node
        await self.koi_node.start()
        await self.send_heartbeat_event()

        # Start periodic heartbeats
        asyncio.create_task(self.send_periodic_heartbeats())

        try:
            iteration = 0
            while True:
                iteration += 1
                logger.info(f"\n{'='*80}")
                logger.info(f"ITERATION {iteration}")
                logger.info(f"{'='*80}\n")

                # Determine max videos to fetch
                # First run: process last N videos
                # Subsequent runs: check all recent videos (but skip already processed)
                max_videos = self.max_videos_first_run if iteration == 1 else 20

                # Fetch videos
                videos = await self.fetch_channel_videos(max_videos=max_videos)

                if not videos:
                    logger.warning("No videos found")
                else:
                    # Process videos (newest first)
                    success_count = 0
                    for i, video in enumerate(videos, 1):
                        logger.info(f"\n[{i}/{len(videos)}] Processing video...")

                        success = await self.process_video(video)
                        if success:
                            success_count += 1

                        # Small delay between videos to avoid rate limits
                        if i < len(videos):
                            await asyncio.sleep(2)

                    logger.info(f"\n✅ Processed {success_count}/{len(videos)} videos")

                # Break if not continuous
                if not continuous:
                    logger.info("Single run complete, exiting")
                    break

                # Wait before next check
                logger.info(f"\n💤 Sleeping for {self.check_interval}s ({self.check_interval/3600:.1f}h)")
                await asyncio.sleep(self.check_interval)

        except KeyboardInterrupt:
            logger.info("\n⚠️  Interrupted by user")
        except Exception as e:
            logger.error(f"Sensor error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            logger.info("Shutting down...")
            await self.koi_node.stop()
            logger.info("✓ YouTube sensor stopped")


async def main():
    """Main entry point"""
    # Check for continuous mode flag
    continuous = '--continuous' in sys.argv or '-c' in sys.argv

    sensor = YouTubeKOISensor()
    await sensor.run(continuous=continuous)


if __name__ == "__main__":
    asyncio.run(main())
