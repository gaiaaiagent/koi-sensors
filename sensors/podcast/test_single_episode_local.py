#!/usr/bin/env python3
"""
Test script to verify complete podcast sensor pipeline on a single episode
Tests: RSS feed parsing, direct MP3 download, Whisper transcription, speaker diarization
"""

import asyncio
import json
from pathlib import Path
from enhanced_podcast_sensor_with_transcription import EnhancedPodcastKOISensor
from rss_feed_parser import get_planetary_regeneration_episodes


async def test_single_episode():
    """Test complete pipeline on one episode"""

    print("="*70)
    print("🧪 TESTING SINGLE EPISODE PIPELINE")
    print("="*70)
    print()

    # Initialize sensor
    sensor = EnhancedPodcastKOISensor(
        node_id="test-podcast-sensor",
        coordinator_url="http://localhost:8005",
        enable_transcription=True,
        whisper_model="base",  # Fast and accurate
        enable_diarization=True  # Requires HUGGINGFACE_TOKEN
    )

    print("Configuration:")
    print(f"  Transcription: {'✓' if sensor.enable_transcription else '✗'}")
    print(f"  Speaker Diarization: {'✓' if sensor.enable_diarization else '✗'}")
    print(f"  Whisper Model: {sensor.whisper_model}")
    print(f"  Transcript Storage: {sensor.transcript_dir}")
    print()

    # Initialize session
    import aiohttp
    sensor.session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=300),
        headers={'User-Agent': 'KOI-PodcastSensor-Test/1.0'}
    )

    try:
        # Start KOI node
        await sensor.koi_node.start()

        # Fetch episodes from RSS feed
        print("📡 Fetching episodes from RSS feed...")
        episodes = await get_planetary_regeneration_episodes()

        if not episodes:
            print("❌ No episodes found in RSS feed")
            return

        print(f"✓ Found {len(episodes)} episodes in RSS feed")
        print()

        # Test with the first episode
        episode = episodes[0]
        episode_id = str(episode.get('id', ''))
        title = episode.get('title', 'Untitled')

        print("="*70)
        print(f"📻 TESTING EPISODE")
        print("="*70)
        print(f"Title: {title}")
        print(f"ID: {episode_id}")
        print(f"Published: {episode.get('created_at', 'Unknown')}")
        print(f"Direct MP3 URL: {episode.get('direct_mp3_url', 'N/A')[:80]}...")
        print(f"Permalink: {episode.get('permalink_url', 'N/A')}")
        print()

        # Show episode metadata
        print("Episode Metadata:")
        print(f"  Duration: {episode.get('duration', 0) / 1000 / 60:.1f} minutes")
        print(f"  Description length: {len(episode.get('description', ''))} chars")
        print()

        # Check if we already have a transcript
        transcript_path = sensor.transcript_dir / f"episode_{episode_id}.json"
        if transcript_path.exists():
            print(f"⚠️  Transcript already exists: {transcript_path}")
            print("   Deleting to force re-transcription...")
            transcript_path.unlink()

        # Transcribe the episode
        print("="*70)
        print("🎤 STARTING TRANSCRIPTION PIPELINE")
        print("="*70)
        print()

        await sensor.transcribe_and_update_episode(episode_id, episode, title)

        # Verify transcript was created
        if transcript_path.exists():
            print()
            print("="*70)
            print("✅ TRANSCRIPT VERIFICATION")
            print("="*70)

            with open(transcript_path, 'r') as f:
                transcript_data = json.load(f)

            metadata = transcript_data.get('audio_transcription_metadata', {})
            segments = transcript_data.get('segments', [])

            print(f"✓ Transcript file created: {transcript_path}")
            print(f"  Duration: {metadata.get('duration', 0):.1f}s")
            print(f"  Language: {metadata.get('language', 'Unknown')}")
            print(f"  Segments: {metadata.get('segments_count', 0)}")
            print(f"  Speakers detected: {metadata.get('speakers_detected', 0)}")
            print(f"  Word timestamps: {'✓' if metadata.get('word_timestamps') else '✗'}")
            print()

            # Show first 3 segments with speaker labels
            print("First 3 segments:")
            for i, seg in enumerate(segments[:3], 1):
                speaker = seg.get('speaker', 'Unknown')
                start = seg.get('start', 0)
                end = seg.get('end', 0)
                text = seg.get('text', '')
                word_count = len(seg.get('words', []))

                print(f"  {i}. [{start:.1f}s - {end:.1f}s] {speaker}")
                print(f"     Text: {text[:100]}{'...' if len(text) > 100 else ''}")
                print(f"     Words: {word_count}")
                print()

            # Verify speaker diarization worked
            speakers = set(seg.get('speaker') for seg in segments if seg.get('speaker'))
            if speakers and len(speakers) > 1:
                print(f"✅ Speaker diarization successful!")
                print(f"   Detected speakers: {', '.join(sorted(speakers))}")
            elif speakers and len(speakers) == 1:
                print(f"⚠️  Only 1 speaker detected: {list(speakers)[0]}")
                print(f"   (This might be a monologue or diarization may need tuning)")
            else:
                print(f"❌ No speakers detected")
                print(f"   Speaker diarization may have failed")

        else:
            print()
            print("❌ TRANSCRIPT FILE NOT CREATED")
            print(f"   Expected: {transcript_path}")

        print()
        print("="*70)
        print("✅ TEST COMPLETE")
        print("="*70)

    except Exception as e:
        print()
        print("="*70)
        print(f"❌ TEST FAILED: {e}")
        print("="*70)
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        await sensor.session.close()
        await sensor.koi_node.stop()


if __name__ == "__main__":
    asyncio.run(test_single_episode())
