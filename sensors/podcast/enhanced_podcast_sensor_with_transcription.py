#!/usr/bin/env python3
"""
Enhanced KOI Podcast Sensor with Advanced Transcription
Integrates YonEarth-proven transcription approach with KOI sensor architecture
"""

import asyncio
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# Import the base podcast sensor
from podcast_sensor import PodcastKOISensor, PodcastEpisodeRID

# Import the transcriber
try:
    from audio_transcriber import PodcastAudioTranscriber
    TRANSCRIPTION_AVAILABLE = True
except ImportError:
    TRANSCRIPTION_AVAILABLE = False
    print("⚠️  Transcription not available. Install dependencies from requirements.txt")


class EnhancedPodcastKOISensor(PodcastKOISensor):
    """
    Enhanced podcast sensor with automatic transcription

    Features:
    - Automatic audio transcription on episode discovery
    - Word-level timestamps for precise navigation
    - Speaker diarization (identifies who spoke when)
    - Seamless integration with KOI event system
    """

    def __init__(
        self,
        node_id: str = "koi-podcast-sensor",
        coordinator_url: str = "http://localhost:8000",
        enable_transcription: bool = True,
        whisper_model: str = "base",
        enable_diarization: bool = True
    ):
        """
        Initialize enhanced podcast sensor

        Args:
            node_id: KOI node identifier
            coordinator_url: KOI coordinator URL
            enable_transcription: Enable automatic transcription
            whisper_model: Whisper model size (base, small, medium, large)
            enable_diarization: Enable speaker diarization
        """
        # Initialize base sensor
        super().__init__(node_id, coordinator_url)

        # Transcription settings
        self.enable_transcription = enable_transcription and TRANSCRIPTION_AVAILABLE
        self.whisper_model = whisper_model
        self.enable_diarization = enable_diarization

        # Transcript storage
        self.transcript_dir = Path(__file__).parent / "transcripts"
        self.transcript_dir.mkdir(exist_ok=True)

        # Initialize transcriber
        self.transcriber: Optional[PodcastAudioTranscriber] = None

        if self.enable_transcription:
            try:
                huggingface_token = os.getenv("HUGGINGFACE_TOKEN")
                self.transcriber = PodcastAudioTranscriber(
                    whisper_model=whisper_model,
                    enable_diarization=enable_diarization and bool(huggingface_token),
                    huggingface_token=huggingface_token,
                    temp_audio_dir=Path(__file__).parent / "temp_audio"
                )
                print(f"✓ Transcription enabled (model: {whisper_model}, speakers: {enable_diarization})")
            except Exception as e:
                print(f"⚠️  Failed to initialize transcriber: {e}")
                self.enable_transcription = False
        else:
            print("⚠️  Transcription disabled")

    async def process_episode(self, podcast_name: str, episode_data: Dict[str, Any]) -> str:
        """
        Process episode with transcription

        Args:
            podcast_name: Name of podcast
            episode_data: Episode metadata from SoundCloud

        Returns:
            Event type (NEW, UPDATE, NO_CHANGE)
        """
        episode_id = str(episode_data.get('id', ''))
        title = episode_data.get('title', 'Untitled Episode')

        # Check if we already have a transcript
        transcript_path = self.transcript_dir / f"episode_{episode_id}.json"
        has_transcript = transcript_path.exists()

        # Process normally first (call parent method)
        event_type = await super().process_episode(podcast_name, episode_data)

        # If new episode and transcription enabled, transcribe it
        if self.enable_transcription and not has_transcript and event_type == "NEW":
            await self.transcribe_and_update_episode(episode_id, episode_data, title)

        return event_type

    async def transcribe_and_update_episode(
        self,
        episode_id: str,
        episode_data: Dict[str, Any],
        title: str
    ):
        """
        Transcribe episode and emit update event

        Args:
            episode_id: Episode identifier
            episode_data: Episode metadata
            title: Episode title
        """
        print(f"\n🎤 Starting transcription: {title[:50]}...")

        try:
            # Get audio URL - SoundCloud needs special handling
            audio_url = None

            # Best approach: Use permalink_url with yt-dlp (handles auth automatically)
            if episode_data.get('permalink_url'):
                audio_url = episode_data['permalink_url']
            # Fallback: Try direct stream URL with client_id
            elif episode_data.get('stream_url') and self.soundcloud_client_id:
                audio_url = f"{episode_data['stream_url']}?client_id={self.soundcloud_client_id}"
            # Try media.transcodings
            elif episode_data.get('media', {}).get('transcodings'):
                for transcoding in episode_data['media']['transcodings']:
                    if transcoding.get('url'):
                        audio_url = transcoding['url']
                        break

            if not audio_url:
                print(f"  ⚠️  No audio URL found for episode {episode_id}")
                return

            print(f"  🎵 Audio URL: {audio_url[:80]}...")

            # Transcribe episode
            result = await self.transcriber.transcribe_episode(
                audio_url=audio_url,
                episode_id=episode_id,
                session=self.session  # Reuse sensor's aiohttp session
            )

            # Save transcript to file
            transcript_path = self.transcript_dir / f"episode_{episode_id}.json"
            with open(transcript_path, 'w') as f:
                json.dump(result.to_dict(), f, indent=2)

            print(f"  ✓ Transcript saved: {transcript_path}")
            print(f"  Duration: {result.metadata['duration']:.1f}s")
            print(f"  Segments: {len(result.segments)}")
            print(f"  Speakers: {result.metadata['speakers_detected']}")

            # Build updated content with transcript
            content = self.build_episode_content_with_transcript(
                episode_data,
                result
            )

            # Emit update event with transcript
            rid = PodcastEpisodeRID("soundcloud", episode_id)
            await self.emit_episode_event(rid, episode_data, content, "UPDATE")

            print(f"  ✓ Transcription complete and event emitted")

        except Exception as e:
            print(f"  ❌ Transcription failed: {e}")
            import traceback
            traceback.print_exc()

    def build_episode_content_with_transcript(
        self,
        episode_data: Dict[str, Any],
        transcription_result
    ) -> str:
        """
        Build episode content including full transcript

        Args:
            episode_data: Episode metadata
            transcription_result: TranscriptionResult object

        Returns:
            Formatted content string
        """
        title = episode_data.get('title', 'Untitled Episode')
        description = episode_data.get('description', 'No description available')
        url = episode_data.get('permalink_url', '')
        created_at = episode_data.get('created_at', '')
        duration = episode_data.get('duration', 0)

        # Convert duration
        duration_str = "Unknown"
        if duration:
            duration_min = duration // 60000
            duration_str = f"{duration_min} minutes"

        # Build content with transcript
        content_parts = [
            f"# {title}",
            "",
            f"**Episode URL:** {url}",
            f"**Published:** {created_at}",
            f"**Duration:** {duration_str}",
            "",
            "## Description",
            description,
            "",
            "## Transcript",
            "",
            f"**Transcription Quality:**",
            f"- Model: {transcription_result.metadata['whisper_model']}",
            f"- Language: {transcription_result.metadata['language']}",
            f"- Segments: {transcription_result.metadata['segments_count']}",
            f"- Speakers: {transcription_result.metadata['speakers_detected']}",
            f"- Word-level timestamps: {'✓' if transcription_result.metadata['word_timestamps'] else '✗'}",
            "",
            "### Full Transcript",
            "",
            transcription_result.full_transcript,
            "",
            "## KOI Metadata",
            f"- Platform: SoundCloud",
            f"- Episode ID: {episode_data.get('id', 'Unknown')}",
            f"- Content Type: Podcast Episode (Transcribed)",
            f"- Transcribed: {transcription_result.metadata['transcribed_at']}",
            f"- Monitoring Status: Active"
        ]

        return "\n".join(content_parts)


async def main():
    """Test the enhanced podcast sensor"""
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Initialize enhanced sensor with transcription
    sensor = EnhancedPodcastKOISensor(
        node_id="enhanced-podcast-sensor-001",
        coordinator_url="http://localhost:8005",
        enable_transcription=True,
        whisper_model="base",  # Fast and accurate
        enable_diarization=True  # Requires HUGGINGFACE_TOKEN
    )

    print("\n" + "="*70)
    print("🎧 Enhanced Podcast Sensor with Transcription")
    print("="*70)
    print(f"Transcription: {'✓ Enabled' if sensor.enable_transcription else '✗ Disabled'}")
    print(f"Speaker Diarization: {'✓ Enabled' if sensor.enable_diarization else '✗ Disabled'}")
    print(f"Whisper Model: {sensor.whisper_model}")
    print(f"Transcript Storage: {sensor.transcript_dir}")
    print("="*70)
    print()

    # Start monitoring
    try:
        await sensor.start_monitoring()
    except KeyboardInterrupt:
        print("\n\nShutting down enhanced podcast sensor...")
    finally:
        await sensor.stop_monitoring()


if __name__ == "__main__":
    asyncio.run(main())
