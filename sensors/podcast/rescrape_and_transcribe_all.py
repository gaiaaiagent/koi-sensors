#!/usr/bin/env python3
"""
Re-scrape and transcribe all Planetary Regeneration podcast episodes
Forces a complete re-processing with the new transcription system
"""

import asyncio
import json
from pathlib import Path
from enhanced_podcast_sensor_with_transcription import EnhancedPodcastKOISensor
from rss_feed_parser import get_planetary_regeneration_episodes

async def rescrape_all_episodes():
    """
    Re-scrape all episodes and force transcription
    Clears the persistent state to treat all episodes as new
    """

    print("="*70)
    print("🔄 RE-SCRAPE AND TRANSCRIBE ALL EPISODES")
    print("="*70)
    print()
    print("This will:")
    print("  1. Clear the sensor's persistent state")
    print("  2. Re-scrape all episodes from SoundCloud")
    print("  3. Transcribe all episodes with word-level timestamps")
    print("  4. Extract speaker diarization")
    print("  5. Save transcripts and emit KOI events")
    print()
    print("⚡ Starting automatic overnight re-scrape...")
    print()

    # Initialize enhanced sensor
    sensor = EnhancedPodcastKOISensor(
        node_id="rescrape-podcast-sensor",
        coordinator_url="http://localhost:8005",
        enable_transcription=True,
        whisper_model="base",  # Fast and accurate
        enable_diarization=False  # Disabled - diarization too slow on CPU
    )

    print("\n" + "="*70)
    print("📋 CONFIGURATION")
    print("="*70)
    print(f"Transcription: {'✓' if sensor.enable_transcription else '✗'}")
    print(f"Speaker Diarization: {'✓' if sensor.enable_diarization else '✗'}")
    print(f"Whisper Model: {sensor.whisper_model}")
    print(f"Transcript Storage: {sensor.transcript_dir}")
    print("="*70)
    print()

    # Clear persistent state to force re-processing
    state_file = Path(__file__).parent / "sensor_state_podcast.json"
    if state_file.exists():
        print(f"🗑️  Clearing persistent state: {state_file}")
        state_file.unlink()
        sensor.state = sensor.state.__class__('podcast', Path(__file__).parent)

    # Initialize session
    import aiohttp
    sensor.session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=300),  # 5 min timeout for audio download
        headers={'User-Agent': 'KOI-PodcastSensor-Rescrape/1.0'}
    )

    try:
        # Start KOI node
        await sensor.koi_node.start()

        # Collect all episodes from RSS feed (20-30x faster downloads)
        print("\n📡 Collecting episodes from RSS feed...")
        episodes = await get_planetary_regeneration_episodes()

        print(f"✓ Found {len(episodes)} episodes")
        print()

        # Process each episode
        total = len(episodes)
        success = 0
        failed = 0

        for i, episode in enumerate(episodes, 1):
            episode_id = str(episode.get('id', ''))
            title = episode.get('title', 'Untitled')

            print(f"\n[{i}/{total}] Processing: {title[:50]}...")

            try:
                # Clear state for this episode to force transcription
                # Remove from processed set
                if episode_id in sensor.state.processed:
                    sensor.state.processed.remove(episode_id)

                # Force transcription by directly calling the transcription method
                await sensor.transcribe_and_update_episode(episode_id, episode, title)

                success += 1
                print(f"  ✓ Success (TRANSCRIBED & UPDATE)")

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
        print(f"Total Episodes: {total}")
        print(f"Successful: {success}")
        print(f"Failed: {failed}")
        print(f"Transcripts saved to: {sensor.transcript_dir}")
        print("="*70)

    finally:
        # Clean up
        await sensor.session.close()
        await sensor.koi_node.stop()


async def rescrape_specific_episodes(episode_ids: list):
    """
    Re-scrape and transcribe specific episodes by ID

    Args:
        episode_ids: List of SoundCloud track IDs to process
    """

    print("="*70)
    print(f"🔄 RE-SCRAPING {len(episode_ids)} SPECIFIC EPISODES")
    print("="*70)
    print()

    # Initialize sensor
    sensor = EnhancedPodcastKOISensor(
        node_id="rescrape-podcast-sensor",
        coordinator_url="http://localhost:8005",
        enable_transcription=True,
        whisper_model="base",
        enable_diarization=False  # Disabled - diarization too slow on CPU
    )

    # Initialize session
    import aiohttp
    sensor.session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=300),
        headers={'User-Agent': 'KOI-PodcastSensor-Rescrape/1.0'}
    )

    try:
        await sensor.koi_node.start()

        # Collect all episodes from RSS feed
        print("📡 Collecting episodes from RSS feed...")
        all_episodes = await get_planetary_regeneration_episodes()

        # Filter to requested episodes
        episodes_to_process = [
            ep for ep in all_episodes
            if str(ep.get('id', '')) in [str(eid) for eid in episode_ids]
        ]

        print(f"✓ Found {len(episodes_to_process)}/{len(episode_ids)} requested episodes")
        print()

        # Process each episode
        for i, episode in enumerate(episodes_to_process, 1):
            episode_id = str(episode.get('id', ''))
            title = episode.get('title', 'Untitled')

            print(f"\n[{i}/{len(episodes_to_process)}] {title[:50]}...")

            # Clear state for this episode to force re-processing
            if episode_id in sensor.state.processed:
                sensor.state.processed.remove(episode_id)

            try:
                await sensor.transcribe_and_update_episode(episode_id, episode, title)
                print(f"  ✓ Complete")
            except Exception as e:
                print(f"  ✗ Failed: {e}")

        print("\n✓ Specific episodes re-scraped")

    finally:
        await sensor.session.close()
        await sensor.koi_node.stop()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Re-scrape specific episodes by ID
        episode_ids = sys.argv[1:]
        asyncio.run(rescrape_specific_episodes(episode_ids))
    else:
        # Re-scrape all episodes
        asyncio.run(rescrape_all_episodes())
