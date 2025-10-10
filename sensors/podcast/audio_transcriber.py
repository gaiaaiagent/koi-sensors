#!/usr/bin/env python3
"""
Advanced Audio Transcription Module for Podcast Sensor
Based on proven YonEarth implementation with word-level timestamps and speaker diarization

Features:
- Word-level timestamps using Whisper
- Speaker diarization using PyAnnote
- Audio download from SoundCloud/URLs
- Async processing for KOI sensor integration
- Full transcript + segmented output
"""

import os
import logging
import asyncio
import aiohttp
import torch
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime

# Transcription dependencies
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    print("⚠️  Whisper not available. Install with: pip install openai-whisper")

try:
    from pyannote.audio import Pipeline
    PYANNOTE_AVAILABLE = True
except ImportError:
    PYANNOTE_AVAILABLE = False
    print("⚠️  PyAnnote not available. Install with: pip install pyannote.audio")

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionSegment:
    """A single transcript segment with timestamps and speaker"""
    start: float
    end: float
    text: str
    speaker: Optional[str] = None
    words: List[Dict[str, Any]] = None  # Word-level timestamps

    def to_dict(self) -> Dict[str, Any]:
        return {
            'start': self.start,
            'end': self.end,
            'text': self.text,
            'speaker': self.speaker,
            'words': self.words or []
        }


@dataclass
class TranscriptionResult:
    """Complete transcription result"""
    segments: List[TranscriptionSegment]
    full_transcript: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'segments': [seg.to_dict() for seg in self.segments],
            'full_transcript': self.full_transcript,
            'audio_transcription_metadata': self.metadata
        }


class PodcastAudioTranscriber:
    """
    Advanced audio transcription with word-level timestamps and speaker diarization
    Based on YonEarth implementation at /yonearth-gaia-chatbot/scripts/retranscribe_episodes_lightweight.py
    """

    def __init__(
        self,
        whisper_model: str = "base",
        enable_diarization: bool = True,
        huggingface_token: Optional[str] = None,
        temp_audio_dir: Optional[Path] = None
    ):
        """
        Initialize transcriber

        Args:
            whisper_model: Whisper model size (base, small, medium, large)
            enable_diarization: Enable speaker diarization (requires HuggingFace token)
            huggingface_token: HuggingFace API token for PyAnnote models
            temp_audio_dir: Directory for temporary audio files
        """
        self.whisper_model_name = whisper_model
        self.enable_diarization = enable_diarization and PYANNOTE_AVAILABLE
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # Temp storage
        self.temp_audio_dir = temp_audio_dir or Path("/tmp/koi_podcast_audio")
        self.temp_audio_dir.mkdir(exist_ok=True, parents=True)

        # Initialize models
        self.whisper_model = None
        self.diarization_pipeline = None

        if WHISPER_AVAILABLE:
            logger.info(f"Loading Whisper model: {whisper_model} on {self.device}")
            self.whisper_model = whisper.load_model(whisper_model, device=self.device)
            logger.info("✓ Whisper model loaded")
        else:
            raise ImportError("Whisper is required. Install with: pip install openai-whisper")

        if self.enable_diarization:
            if not huggingface_token:
                huggingface_token = os.getenv("HUGGINGFACE_TOKEN")

            if not huggingface_token:
                logger.warning("No HuggingFace token found. Diarization disabled.")
                logger.warning("Set HUGGINGFACE_TOKEN env variable to enable speaker diarization")
                self.enable_diarization = False
            else:
                logger.info("Loading PyAnnote diarization pipeline...")
                try:
                    self.diarization_pipeline = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-3.1",
                        token=huggingface_token  # Updated from use_auth_token (deprecated)
                    )
                    self.diarization_pipeline.to(torch.device(self.device))
                    logger.info("✓ Diarization pipeline loaded")
                except Exception as e:
                    logger.error(f"Failed to load diarization pipeline: {e}")
                    logger.warning("Continuing without speaker diarization")
                    self.enable_diarization = False

    async def download_audio(
        self,
        url: str,
        episode_id: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> Path:
        """
        Download audio file from URL (handles SoundCloud, direct URLs, etc.)

        Args:
            url: Audio file URL or SoundCloud permalink
            episode_id: Unique episode identifier
            session: Optional aiohttp session (will create if not provided)

        Returns:
            Path to downloaded audio file
        """
        audio_path = self.temp_audio_dir / f"episode_{episode_id}.mp3"

        # Skip if already downloaded
        if audio_path.exists():
            logger.info(f"Using cached audio: {audio_path}")
            return audio_path

        logger.info(f"Downloading audio from: {url}")

        # Check if this is a SoundCloud URL (needs yt-dlp)
        if 'soundcloud.com' in url:
            return await self._download_with_ytdlp(url, audio_path)
        else:
            # Direct download for non-SoundCloud URLs
            return await self._download_direct(url, audio_path, session)

    async def _download_with_ytdlp(self, url: str, output_path: Path) -> Path:
        """Download audio using yt-dlp (handles SoundCloud auth)"""
        try:
            import yt_dlp

            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': str(output_path.with_suffix('')),  # yt-dlp adds extension
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
                'concurrent_fragment_downloads': 4,  # Download 4 fragments at once (3-4x faster)
            }

            # Run yt-dlp in thread pool (it's blocking)
            await asyncio.to_thread(
                lambda: yt_dlp.YoutubeDL(ydl_opts).download([url])
            )

            # yt-dlp may create .mp3 file
            if output_path.exists():
                file_size_mb = output_path.stat().st_size / 1024 / 1024
                logger.info(f"✓ Downloaded via yt-dlp: {output_path} ({file_size_mb:.1f} MB)")
                return output_path
            else:
                raise FileNotFoundError(f"yt-dlp failed to create {output_path}")

        except ImportError:
            logger.error("yt-dlp not installed. Install with: pip install yt-dlp")
            raise
        except Exception as e:
            logger.error(f"yt-dlp download failed: {e}")
            raise

    async def _download_direct(
        self,
        url: str,
        output_path: Path,
        session: Optional[aiohttp.ClientSession]
    ) -> Path:
        """Direct download for non-SoundCloud URLs"""
        close_session = False
        if not session:
            session = aiohttp.ClientSession()
            close_session = True

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as response:
                response.raise_for_status()

                with open(output_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)

            file_size_mb = output_path.stat().st_size / 1024 / 1024
            logger.info(f"✓ Downloaded: {output_path} ({file_size_mb:.1f} MB)")
            return output_path

        except Exception as e:
            logger.error(f"Direct download failed: {e}")
            raise
        finally:
            if close_session:
                await session.close()

    def transcribe_with_whisper(self, audio_path: Path) -> Dict[str, Any]:
        """
        Transcribe audio with Whisper (word-level timestamps)

        Args:
            audio_path: Path to audio file

        Returns:
            Whisper transcription result with segments and word timestamps
        """
        logger.info("Transcribing with Whisper...")

        result = self.whisper_model.transcribe(
            str(audio_path),
            word_timestamps=True,  # Enable word-level timestamps
            verbose=False
        )

        logger.info(f"✓ Transcription complete ({len(result['segments'])} segments)")
        return result

    def _convert_to_wav(self, audio_path: Path) -> Path:
        """
        Convert MP3 to WAV with consistent sample rate for PyAnnote compatibility

        PyAnnote requires exact sample counts, which MP3s don't always provide.
        Converting to WAV at 16kHz ensures consistent processing.

        Args:
            audio_path: Path to MP3 file

        Returns:
            Path to converted WAV file
        """
        wav_path = audio_path.with_suffix('.wav')

        # Skip if WAV already exists
        if wav_path.exists():
            logger.info(f"Using cached WAV: {wav_path}")
            return wav_path

        try:
            import ffmpeg
            logger.info(f"Converting {audio_path} to WAV for diarization...")

            # Convert to 16kHz mono WAV (standard for speech processing)
            ffmpeg.input(str(audio_path)).output(
                str(wav_path),
                ar=16000,  # 16kHz sample rate
                ac=1,      # Mono audio
                acodec='pcm_s16le'  # Standard WAV codec
            ).overwrite_output().run(quiet=True, capture_stderr=True)

            logger.info(f"✓ Converted to WAV: {wav_path}")
            return wav_path

        except ImportError:
            logger.error("ffmpeg-python not installed. Install with: pip install ffmpeg-python")
            logger.warning("Attempting diarization with MP3 file (may fail)")
            return audio_path
        except Exception as e:
            logger.error(f"WAV conversion failed: {e}")
            logger.warning("Attempting diarization with MP3 file (may fail)")
            return audio_path

    def add_speaker_diarization(
        self,
        audio_path: Path,
        whisper_segments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Add speaker labels to whisper segments using PyAnnote

        Args:
            audio_path: Path to audio file
            whisper_segments: Whisper transcription segments

        Returns:
            Segments with speaker labels added
        """
        if not self.enable_diarization:
            logger.info("Speaker diarization disabled, skipping")
            return whisper_segments

        logger.info("Running speaker diarization...")

        try:
            # Convert MP3 to WAV for PyAnnote compatibility
            # PyAnnote requires exact sample counts which MP3s don't always provide
            wav_path = self._convert_to_wav(audio_path)

            # Run diarization with parameters optimized for podcasts
            # num_speakers can be set if known, or left as None for automatic detection
            diarization = self.diarization_pipeline(
                str(wav_path),  # Use WAV instead of MP3
                min_speakers=2,  # Expect at least 2 speakers in interviews
                max_speakers=5   # Limit to reasonable number for podcasts
            )

            # Debug: Count total turns detected
            turn_count = sum(1 for _ in diarization.itertracks())
            logger.info(f"  Detected {turn_count} speaker turns")

            # Assign speakers to segments
            for segment in whisper_segments:
                segment_start = segment['start']
                segment_end = segment['end']
                segment_mid = (segment_start + segment_end) / 2

                # Find speaker at segment midpoint
                speaker = None
                for turn, _, speaker_label in diarization.itertracks(yield_label=True):
                    if turn.start <= segment_mid <= turn.end:
                        speaker = speaker_label
                        break

                segment['speaker'] = speaker

            # Count unique speakers
            speakers = set(seg.get('speaker') for seg in whisper_segments if seg.get('speaker'))
            logger.info(f"✓ Diarization complete ({len(speakers)} speakers detected)")

            # If no speakers detected, log warning
            if len(speakers) == 0:
                logger.warning("No speakers were assigned to segments!")
                logger.warning("This might indicate audio quality issues or single-speaker content")

        except Exception as e:
            logger.error(f"Diarization failed: {e}")
            logger.warning("Continuing without speaker labels")
            import traceback
            logger.error(traceback.format_exc())
            for segment in whisper_segments:
                segment['speaker'] = None

        return whisper_segments

    async def transcribe_episode(
        self,
        audio_url: str,
        episode_id: str,
        session: Optional[aiohttp.ClientSession] = None,
        keep_audio: bool = False
    ) -> TranscriptionResult:
        """
        Complete transcription pipeline for one episode

        Args:
            audio_url: URL to audio file
            episode_id: Unique episode identifier
            session: Optional aiohttp session
            keep_audio: Keep audio file after transcription (for debugging)

        Returns:
            TranscriptionResult with segments, full transcript, and metadata
        """
        logger.info(f"{'='*70}")
        logger.info(f"TRANSCRIBING EPISODE {episode_id}")
        logger.info(f"{'='*70}")

        try:
            # Download audio
            audio_path = await self.download_audio(audio_url, episode_id, session)

            # Transcribe with Whisper (sync - runs in executor in async context)
            whisper_result = await asyncio.to_thread(
                self.transcribe_with_whisper,
                audio_path
            )

            # Add speaker diarization if enabled
            if self.enable_diarization:
                whisper_segments = await asyncio.to_thread(
                    self.add_speaker_diarization,
                    audio_path,
                    whisper_result['segments']
                )
            else:
                whisper_segments = whisper_result['segments']

            # Convert to TranscriptionSegment objects
            segments = []
            for seg in whisper_segments:
                segments.append(TranscriptionSegment(
                    start=seg['start'],
                    end=seg['end'],
                    text=seg['text'].strip(),
                    speaker=seg.get('speaker'),
                    words=seg.get('words', [])
                ))

            # Generate full transcript with timestamps
            full_transcript = "\n\n".join([
                f"[{seg.start:.1f}s - {seg.end:.1f}s]{' ' + seg.speaker if seg.speaker else ''}: {seg.text}"
                for seg in segments
            ])

            # Build metadata
            speakers_detected = len(set(seg.speaker for seg in segments if seg.speaker))
            metadata = {
                'whisper_model': self.whisper_model_name,
                'language': whisper_result.get('language', 'en'),
                'duration': whisper_result.get('duration', 0),
                'speakers_detected': speakers_detected,
                'segments_count': len(segments),
                'diarization_available': self.enable_diarization,
                'word_timestamps': True,
                'transcribed_at': datetime.now().isoformat(),
                'device': self.device
            }

            logger.info(f"✓ Episode {episode_id} transcribed successfully")
            logger.info(f"  Duration: {metadata['duration']:.1f}s")
            logger.info(f"  Segments: {len(segments)}")
            logger.info(f"  Speakers: {speakers_detected}")

            # Clean up audio file unless keep_audio=True
            if not keep_audio and not os.getenv("KEEP_AUDIO_FILES"):
                audio_path.unlink()
                logger.info(f"  Cleaned up audio file")

            return TranscriptionResult(
                segments=segments,
                full_transcript=full_transcript,
                metadata=metadata
            )

        except Exception as e:
            logger.error(f"Failed to transcribe episode {episode_id}: {e}")
            raise


# Convenience function for simple use cases
async def transcribe_podcast_episode(
    audio_url: str,
    episode_id: str,
    whisper_model: str = "base",
    enable_speakers: bool = True,
    huggingface_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Simple interface for transcribing a single podcast episode

    Args:
        audio_url: URL to audio file
        episode_id: Unique episode identifier
        whisper_model: Whisper model size (base, small, medium, large)
        enable_speakers: Enable speaker diarization
        huggingface_token: HuggingFace API token (or set HUGGINGFACE_TOKEN env var)

    Returns:
        Dictionary with segments, full_transcript, and metadata
    """
    transcriber = PodcastAudioTranscriber(
        whisper_model=whisper_model,
        enable_diarization=enable_speakers,
        huggingface_token=huggingface_token
    )

    result = await transcriber.transcribe_episode(audio_url, episode_id)
    return result.to_dict()


if __name__ == "__main__":
    # Test transcription
    import sys

    async def test():
        if len(sys.argv) < 3:
            print("Usage: python audio_transcriber.py <audio_url> <episode_id>")
            sys.exit(1)

        audio_url = sys.argv[1]
        episode_id = sys.argv[2]

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

        result = await transcribe_podcast_episode(audio_url, episode_id)

        print("\n" + "="*70)
        print("TRANSCRIPTION RESULT")
        print("="*70)
        print(f"Segments: {len(result['segments'])}")
        print(f"Duration: {result['audio_transcription_metadata']['duration']:.1f}s")
        print(f"Speakers: {result['audio_transcription_metadata']['speakers_detected']}")
        print("\nFirst 3 segments:")
        for seg in result['segments'][:3]:
            print(f"  [{seg['start']:.1f}s - {seg['end']:.1f}s] {seg.get('speaker', 'UNKNOWN')}: {seg['text']}")

    asyncio.run(test())
