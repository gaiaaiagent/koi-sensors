#!/usr/bin/env python3
"""
Simple test script for YouTube sensor functionality
Tests video fetching and transcription without KOI coordinator
"""

import asyncio
import sys
from pathlib import Path

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from youtube_sensor import YouTubeKOISensor


async def test_fetch_videos():
    """Test fetching video metadata"""
    print("🎥 Testing YouTube video fetching...")
    print("="*80)

    sensor = YouTubeKOISensor()

    # Fetch just 2 videos for testing
    videos = await sensor.fetch_channel_videos(max_videos=2)

    if not videos:
        print("❌ No videos found!")
        return False

    print(f"\n✅ Found {len(videos)} videos\n")

    for i, video in enumerate(videos, 1):
        print(f"[{i}] {video['title']}")
        print(f"    ID: {video['video_id']}")
        print(f"    URL: {video['url']}")
        print(f"    Duration: {video.get('duration', 0)}s")
        views = video.get('view_count')
        print(f"    Views: {views:,}" if views else "    Views: N/A")
        print(f"    Upload: {video.get('upload_date', 'N/A')}")
        print()

    return True


async def test_download_audio():
    """Test downloading audio from a video"""
    print("\n🎵 Testing audio download...")
    print("="*80)

    sensor = YouTubeKOISensor()

    # Fetch one video
    videos = await sensor.fetch_channel_videos(max_videos=1)
    if not videos:
        print("❌ No videos found!")
        return False

    video = videos[0]
    print(f"Downloading audio from: {video['title']}")

    audio_path = await sensor.download_audio(video['url'], video['video_id'])

    if audio_path and audio_path.exists():
        file_size_mb = audio_path.stat().st_size / 1024 / 1024
        print(f"✅ Audio downloaded: {audio_path.name} ({file_size_mb:.1f} MB)")
        return True
    else:
        print("❌ Audio download failed!")
        return False


async def test_transcription():
    """Test transcription (WARNING: slow with large model!)"""
    print("\n🎙️  Testing transcription...")
    print("="*80)
    print("⚠️  This will use the Whisper 'large' model and may take several minutes!")
    print("⚠️  Press Ctrl+C to skip this test\n")

    # Give user a chance to cancel
    await asyncio.sleep(3)

    sensor = YouTubeKOISensor()

    # Find the first downloaded audio file
    audio_files = list(sensor.videos_dir.glob("*.mp3"))
    if not audio_files:
        print("No audio files found. Run test_download_audio() first.")
        return False

    audio_path = audio_files[0]
    print(f"Transcribing: {audio_path.name}")

    result = await sensor.transcribe_audio(audio_path)

    if result:
        print(f"\n✅ Transcription complete!")
        print(f"   Language: {result['language']}")
        print(f"   Duration: {result['duration']:.1f}s")
        print(f"   Segments: {len(result['segments'])}")
        print("\nFirst 500 characters of transcript:")
        print("-" * 80)
        print(result['full_transcript'][:500])
        print("-" * 80)
        return True
    else:
        print("❌ Transcription failed!")
        return False


async def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("YOUTUBE SENSOR TEST SUITE")
    print("="*80 + "\n")

    results = {}

    # Test 1: Fetch videos
    try:
        results['fetch'] = await test_fetch_videos()
    except Exception as e:
        print(f"❌ Fetch test failed: {e}")
        results['fetch'] = False

    # Test 2: Download audio
    if results['fetch']:
        try:
            results['download'] = await test_download_audio()
        except Exception as e:
            print(f"❌ Download test failed: {e}")
            results['download'] = False
    else:
        print("\n⏭️  Skipping download test (fetch failed)")
        results['download'] = False

    # Test 3: Transcription (optional, slow)
    if results['download']:
        try:
            print("\n" + "="*80)
            choice = input("Run transcription test? (slow, may take 5-10 min) [y/N]: ")
            if choice.lower() == 'y':
                results['transcribe'] = await test_transcription()
            else:
                print("⏭️  Skipping transcription test")
                results['transcribe'] = None
        except KeyboardInterrupt:
            print("\n⏭️  Skipping transcription test")
            results['transcribe'] = None
        except Exception as e:
            print(f"❌ Transcription test failed: {e}")
            results['transcribe'] = False
    else:
        results['transcribe'] = None

    # Summary
    print("\n" + "="*80)
    print("TEST RESULTS")
    print("="*80)
    print(f"Fetch videos:     {'✅ PASS' if results['fetch'] else '❌ FAIL'}")
    print(f"Download audio:   {'✅ PASS' if results['download'] else '❌ FAIL'}")
    if results['transcribe'] is not None:
        print(f"Transcription:    {'✅ PASS' if results['transcribe'] else '❌ FAIL'}")
    else:
        print(f"Transcription:    ⏭️  SKIPPED")
    print("="*80 + "\n")

    all_passed = results['fetch'] and results['download']
    if all_passed:
        print("🎉 Core functionality working! Sensor is ready to use.")
        print("\nNext steps:")
        print("1. Start the KOI coordinator (if not running)")
        print("2. Run the sensor: ./start.sh")
    else:
        print("⚠️  Some tests failed. Check the errors above.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
