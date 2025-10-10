#!/usr/bin/env python3
"""
Quick test script to verify speaker diarization on first 10 minutes of podcast
Faster verification than waiting for full episode transcription
"""

import asyncio
import logging
import sys
from pathlib import Path
from audio_transcriber import PodcastAudioTranscriber

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_diarization_short_segment(audio_path: str, duration_seconds: int = 600):
    """
    Test diarization on a short segment of audio

    Args:
        audio_path: Path to full audio file
        duration_seconds: Duration to test (default 600 = 10 minutes)
    """

    audio_path = Path(audio_path)

    if not audio_path.exists():
        logger.error(f"Audio file not found: {audio_path}")
        logger.info("Available audio files:")
        temp_dir = Path("/tmp/koi_podcast_audio")
        if temp_dir.exists():
            for f in temp_dir.glob("episode_*.mp3"):
                logger.info(f"  - {f}")
        return

    # Create short segment using FFmpeg
    short_segment_path = audio_path.parent / f"{audio_path.stem}_10min.mp3"

    logger.info(f"Creating {duration_seconds/60:.0f}-minute test segment...")
    logger.info(f"Input: {audio_path}")
    logger.info(f"Output: {short_segment_path}")

    # Extract first N seconds
    import subprocess
    result = subprocess.run([
        'ffmpeg',
        '-i', str(audio_path),
        '-t', str(duration_seconds),
        '-c', 'copy',
        '-y',  # Overwrite if exists
        str(short_segment_path)
    ], capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(f"FFmpeg failed: {result.stderr}")
        return

    file_size_mb = short_segment_path.stat().st_size / 1024 / 1024
    logger.info(f"✓ Created test segment: {short_segment_path} ({file_size_mb:.1f} MB)")

    # Initialize transcriber with diarization enabled
    logger.info("\nInitializing transcriber...")
    transcriber = PodcastAudioTranscriber(
        whisper_model="base",
        enable_diarization=True,
        temp_audio_dir=audio_path.parent
    )

    # Transcribe the short segment
    logger.info(f"\n{'='*70}")
    logger.info(f"TRANSCRIBING {duration_seconds/60:.0f}-MINUTE SEGMENT")
    logger.info(f"{'='*70}\n")

    # Run transcription (sync, in executor)
    whisper_result = await asyncio.to_thread(
        transcriber.transcribe_with_whisper,
        short_segment_path
    )

    logger.info(f"✓ Whisper complete: {len(whisper_result['segments'])} segments")

    # Run diarization
    whisper_segments = await asyncio.to_thread(
        transcriber.add_speaker_diarization,
        short_segment_path,
        whisper_result['segments']
    )

    # Analyze results
    logger.info(f"\n{'='*70}")
    logger.info("DIARIZATION RESULTS")
    logger.info(f"{'='*70}")

    # Count speakers
    speakers = set(seg.get('speaker') for seg in whisper_segments if seg.get('speaker'))
    logger.info(f"Speakers detected: {len(speakers)}")

    if len(speakers) > 0:
        logger.info(f"Speaker labels: {sorted(speakers)}")

        # Count segments per speaker
        speaker_counts = {}
        for seg in whisper_segments:
            speaker = seg.get('speaker', 'UNKNOWN')
            speaker_counts[speaker] = speaker_counts.get(speaker, 0) + 1

        logger.info("\nSegments per speaker:")
        for speaker, count in sorted(speaker_counts.items()):
            logger.info(f"  {speaker}: {count} segments")

        # Show first few segments with speakers
        logger.info("\nFirst 10 segments:")
        for i, seg in enumerate(whisper_segments[:10], 1):
            speaker = seg.get('speaker', 'UNKNOWN')
            text = seg['text'][:60]
            logger.info(f"  [{i}] {speaker}: {text}...")
    else:
        logger.warning("⚠️  NO SPEAKERS DETECTED!")
        logger.warning("Diarization may not be working correctly")

        # Show first few segments anyway
        logger.info("\nFirst 10 segments (no speakers):")
        for i, seg in enumerate(whisper_segments[:10], 1):
            text = seg['text'][:60]
            logger.info(f"  [{i}] {text}...")

    logger.info(f"\n{'='*70}")
    logger.info("TEST COMPLETE")
    logger.info(f"{'='*70}")

    # Clean up test segment
    short_segment_path.unlink()
    logger.info(f"Cleaned up test segment: {short_segment_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_diarization_10min.py <audio_file_path> [duration_seconds]")
        print("\nExample:")
        print("  python test_diarization_10min.py /tmp/koi_podcast_audio/episode_2078695880.mp3")
        print("  python test_diarization_10min.py /tmp/koi_podcast_audio/episode_2078695880.mp3 300  # 5 minutes")
        sys.exit(1)

    audio_path = sys.argv[1]
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 600

    asyncio.run(test_diarization_short_segment(audio_path, duration))
