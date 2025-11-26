#!/usr/bin/env python3
"""
Emit KOI events from existing transcript files
NO RE-TRANSCRIPTION - just loads JSON files and emits events
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, Any
from enhanced_podcast_sensor_with_transcription import EnhancedPodcastKOISensor
from podcast_sensor import PodcastEpisodeRID
from rss_feed_parser import get_planetary_regeneration_episodes
from audio_transcriber import TranscriptionResult


async def emit_from_existing_transcripts():
    """
    Load existing transcript files and emit UPDATE events
    This is FAST - no transcription needed!
    """

    print("="*70)
    print("⚡ EMIT EVENTS FROM EXISTING TRANSCRIPTS")
    print("="*70)
    print()
    print("This will:")
    print("  1. Load existing transcript JSON files (NO re-transcription!)")
    print("  2. Fetch episode metadata from RSS feed")
    print("  3. Emit UPDATE events to KOI coordinator")
    print("  4. Events flow to event bridge → database")
    print()
    print("Expected time: ~1-2 minutes (vs 22-28 hours for re-transcription)")
    print()

    # Initialize sensor (transcription DISABLED - we already have transcripts!)
    sensor = EnhancedPodcastKOISensor(
        node_id="emit-from-transcripts",
        coordinator_url="http://localhost:8005",
        enable_transcription=False,  # No transcription needed!
        whisper_model="base",
        enable_diarization=False
    )

    # Initialize session
    import aiohttp
    sensor.session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=60),
        headers={'User-Agent': 'KOI-PodcastSensor-EmitTranscripts/1.0'}
    )

    try:
        # Start KOI node
        await sensor.koi_node.start()

        # Find all transcript files
        transcript_dir = Path(__file__).parent / "transcripts"
        transcript_files = sorted(transcript_dir.glob("episode_*.json"))

        print(f"📁 Found {len(transcript_files)} transcript files")
        print()

        # Fetch episode metadata from RSS
        print("📡 Fetching episode metadata from RSS feed...")
        all_episodes = await get_planetary_regeneration_episodes()
        episodes_by_id = {str(ep.get('id', '')): ep for ep in all_episodes}
        print(f"✓ Fetched metadata for {len(all_episodes)} episodes")
        print()

        # Process each transcript
        total = len(transcript_files)
        success = 0
        failed = 0

        for i, transcript_file in enumerate(transcript_files, 1):
            # Extract episode ID from filename: episode_677303778.json
            episode_id = transcript_file.stem.replace('episode_', '')

            try:
                # Load transcript
                with open(transcript_file, 'r') as f:
                    transcript_data = json.load(f)

                # Get episode metadata
                episode_data = episodes_by_id.get(episode_id)
                if not episode_data:
                    print(f"[{i}/{total}] ⚠️  Episode {episode_id}: No metadata in RSS feed (skipping)")
                    failed += 1
                    continue

                title = episode_data.get('title', 'Untitled')
                print(f"[{i}/{total}] {title[:60]}...")

                # Reconstruct TranscriptionResult from saved JSON
                transcription_result = TranscriptionResult.from_dict(transcript_data)

                # Build content with transcript
                content = sensor.build_episode_content_with_transcript(
                    episode_data,
                    transcription_result
                )

                # Emit UPDATE event (treating as update since these are re-loads)
                rid = PodcastEpisodeRID("soundcloud", episode_id)
                await sensor.emit_episode_event(rid, episode_data, content, "UPDATE")

                success += 1
                print(f"  ✓ Event emitted")

            except Exception as e:
                failed += 1
                print(f"  ✗ Failed: {e}")
                import traceback
                traceback.print_exc()
                continue

        # Summary
        print("\n" + "="*70)
        print("📊 SUMMARY")
        print("="*70)
        print(f"Total Transcripts: {total}")
        print(f"Successfully Emitted: {success}")
        print(f"Failed: {failed}")
        print("="*70)
        print()
        print("✓ Events emitted to coordinator → forwarder → event bridge → database")
        print("  Check event bridge logs to verify successful ingestion")

    finally:
        # Clean up
        await sensor.session.close()
        await sensor.koi_node.stop()


if __name__ == "__main__":
    asyncio.run(emit_from_existing_transcripts())
