#!/usr/bin/env python3
"""
YouTube Sensor for KOI System
Monitors YouTube channels and sends videos to remote transcription service

Features:
- Channel monitoring via yt-dlp
- Remote transcription via Scribe API (no local Whisper needed)
- KOI protocol integration
- Persistent state management
"""

import os
import sys
import json
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

# YouTube dependencies (lightweight - no Whisper/torch needed)
try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False
    print("⚠️  yt-dlp not available. Install with: pip install yt-dlp")

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    print("⚠️  httpx not available. Install with: pip install httpx")

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
    YouTube sensor using yt-dlp for video discovery and remote Scribe API for transcription
    """

    def __init__(self):
        # Load environment variables
        load_dotenv(Path(__file__).parent.parent.parent / '.env')

        # Configuration - support multiple channels (comma-separated)
        channel_urls_str = os.getenv("YOUTUBE_CHANNEL_URLS", os.getenv("YOUTUBE_CHANNEL_URL", "https://www.youtube.com/@RegenNetwork"))
        self.channel_urls = [url.strip() for url in channel_urls_str.split(",") if url.strip()]
        self.max_videos_per_channel = int(os.getenv("YOUTUBE_MAX_VIDEOS_PER_CHANNEL", os.getenv("YOUTUBE_MAX_VIDEOS_FIRST_RUN", "50")))
        self.check_interval = int(os.getenv("YOUTUBE_CHECK_INTERVAL", "86400"))  # 24 hours

        # Remote transcription API configuration
        self.transcription_api_url = os.getenv(
            "TRANSCRIPTION_API_URL",
            "http://37.27.48.12:8080/api"
        )
        self.transcription_api_key = os.getenv(
            "TRANSCRIPTION_API_KEY",
            "2936f1f72ab7c042e0ace10cb815800bafce2a6fa55a642f4109a00b501b6b15"
        )
        self.whisper_model = os.getenv("WHISPER_MODEL", "large")

        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name="youtube-sensor",
            coordinator_url="http://localhost:8005"
        )

        # Persistent state
        self.state = PersistentSensorState('youtube', Path(__file__).parent)

        # HTTP client for transcription API
        self.http_client = None

        logger.info(f"YouTube Sensor initialized")
        logger.info(f"  Channels ({len(self.channel_urls)}):")
        for url in self.channel_urls:
            logger.info(f"    - {url}")
        logger.info(f"  Transcription API: {self.transcription_api_url}")
        logger.info(f"  Whisper model: {self.whisper_model}")
        logger.info(f"  Max videos per channel: {self.max_videos_per_channel}")
        logger.info(f"  Check interval: {self.check_interval}s ({self.check_interval/3600:.1f}h)")

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, read=600.0),  # Long read timeout for transcription
                headers={
                    "X-API-Key": self.transcription_api_key,
                    "Content-Type": "application/json"
                }
            )
        return self.http_client

    async def fetch_channel_videos(self, channel_url: str, max_videos: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Fetch videos from a YouTube channel using yt-dlp

        Args:
            channel_url: YouTube channel URL to fetch from
            max_videos: Maximum number of videos to fetch (None = all)

        Returns:
            List of video metadata dictionaries
        """
        if not YTDLP_AVAILABLE:
            raise ImportError("yt-dlp is required. Install with: pip install yt-dlp")

        # Make sure we're fetching from the videos tab
        videos_url = channel_url.rstrip('/') + '/videos'
        logger.info(f"Fetching videos from: {videos_url}")

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': 'in_playlist',  # Don't download, just get metadata
            'playlistend': max_videos,      # Limit number of videos
            'ignoreerrors': True,           # Continue on errors
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

    async def transcribe_via_api(self, video_url: str, video_title: str) -> Optional[Dict[str, Any]]:
        """
        Send video URL to remote transcription API and wait for result

        Args:
            video_url: YouTube video URL
            video_title: Video title for logging

        Returns:
            Transcription result or None if failed
        """
        if not HTTPX_AVAILABLE:
            raise ImportError("httpx is required. Install with: pip install httpx")

        client = await self._get_http_client()

        logger.info(f"Submitting to transcription API: {video_url}")

        try:
            # Submit URL for transcription
            response = await client.post(
                f"{self.transcription_api_url}/transcribe/url",
                json={
                    "url": video_url,
                    "model": self.whisper_model
                }
            )

            if response.status_code != 200:
                logger.error(f"API error: {response.status_code} - {response.text}")
                return None

            result = response.json()
            job_id = result.get("job_id")

            if not job_id:
                logger.error(f"No job_id in response: {result}")
                return None

            logger.info(f"Job submitted: {job_id}")

            # Poll for completion
            max_polls = 180  # 30 minutes max (10s intervals)
            poll_interval = 10  # seconds

            for i in range(max_polls):
                await asyncio.sleep(poll_interval)

                status_response = await client.get(
                    f"{self.transcription_api_url}/transcribe/{job_id}"
                )

                if status_response.status_code != 200:
                    logger.warning(f"Status check failed: {status_response.status_code}")
                    continue

                status_data = status_response.json()
                status = status_data.get("status")

                if status == "completed":
                    logger.info(f"✓ Transcription complete for: {video_title}")

                    # Extract transcript from result
                    transcription = status_data.get("result", {})
                    text = transcription.get("text", "")
                    segments = transcription.get("segments", [])

                    # Format transcript with timestamps if segments available
                    if segments:
                        formatted_transcript = "\n\n".join([
                            f"[{seg.get('start', 0):.1f}s - {seg.get('end', 0):.1f}s]: {seg.get('text', '').strip()}"
                            for seg in segments
                        ])
                    else:
                        formatted_transcript = text

                    return {
                        'full_transcript': formatted_transcript,
                        'text': text,
                        'segments': segments,
                        'language': transcription.get('language', 'en'),
                        'duration': transcription.get('duration', 0),
                        'model': self.whisper_model,
                    }

                elif status == "failed":
                    error = status_data.get("error", "Unknown error")
                    logger.error(f"Transcription failed: {error}")
                    return None

                elif status in ["queued", "processing", "downloading"]:
                    if i % 6 == 0:  # Log every minute
                        logger.info(f"Still {status}... ({i * poll_interval}s elapsed)")
                else:
                    logger.warning(f"Unknown status: {status}")

            logger.error(f"Transcription timed out after {max_polls * poll_interval}s")
            return None

        except Exception as e:
            logger.error(f"Transcription API error: {e}")
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
            transcription: Transcription result from API

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
            'id': video_id,
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
                'whisper_model': self.whisper_model if transcription else None,
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
            "channels": self.channel_urls
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
        Process a single video: send to transcription API, then to KOI

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
            # Check if already processed
            if self.state.is_processed(video_id):
                logger.info("Video already processed, skipping")
                return True

            # Send to remote transcription API
            transcription = await self.transcribe_via_api(
                video_metadata['url'],
                title
            )

            if not transcription:
                logger.warning("Transcription failed, continuing without transcript")

            # Create KOI document
            document = self.process_video_to_document(video_metadata, transcription)
            if not document:
                logger.info("Video already processed, skipping")
                return True

            # Send to KOI
            success = await self.send_to_koi(document)
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
        logger.info(f"Channels ({len(self.channel_urls)}):")
        for url in self.channel_urls:
            logger.info(f"  - {url}")
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

                # Process each channel
                total_videos = 0
                total_success = 0

                for channel_idx, channel_url in enumerate(self.channel_urls, 1):
                    logger.info(f"\n📺 CHANNEL {channel_idx}/{len(self.channel_urls)}: {channel_url}")
                    logger.info(f"{'─'*60}")

                    # Fetch videos from this channel
                    videos = await self.fetch_channel_videos(channel_url, max_videos=self.max_videos_per_channel)

                    if not videos:
                        logger.warning(f"No videos found for channel: {channel_url}")
                        continue

                    total_videos += len(videos)

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

                    total_success += success_count
                    logger.info(f"\n✅ Channel complete: {success_count}/{len(videos)} videos processed")

                logger.info(f"\n{'='*80}")
                logger.info(f"📊 ITERATION {iteration} SUMMARY: {total_success}/{total_videos} total videos across {len(self.channel_urls)} channels")
                logger.info(f"{'='*80}")

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
            if self.http_client:
                await self.http_client.aclose()
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
