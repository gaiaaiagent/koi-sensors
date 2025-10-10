#!/usr/bin/env python3
"""
Test transcription on ONE episode to verify everything works
"""
import asyncio
import sys
sys.path.insert(0, '/Users/darrenzal/projects/RegenAI/koi-sensors')

from enhanced_podcast_sensor_with_transcription import EnhancedPodcastKOISensor

async def test_one_episode():
    print("="*70)
    print("🧪 TESTING TRANSCRIPTION ON ONE EPISODE")
    print("="*70)
    
    sensor = EnhancedPodcastKOISensor(
        node_id="test-podcast-sensor",
        coordinator_url="http://localhost:8005",
        enable_transcription=True,
        whisper_model="base",
        enable_diarization=True
    )
    
    # Initialize session
    import aiohttp
    sensor.session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=300),
        headers={'User-Agent': 'KOI-PodcastSensor-Test/1.0'}
    )
    
    try:
        await sensor.koi_node.start()
        
        # Get episodes
        print("\n📡 Fetching episodes from SoundCloud...")
        episodes = await sensor.collect_soundcloud_episodes(
            "https://soundcloud.com/planetaryregeneration"
        )
        
        if not episodes:
            print("❌ No episodes found!")
            return
            
        print(f"✓ Found {len(episodes)} episodes")
        
        # Test on first episode
        test_episode = episodes[0]
        episode_id = str(test_episode.get('id', ''))
        title = test_episode.get('title', 'Untitled')
        
        print(f"\n🎯 Testing on: {title}")
        print(f"   Episode ID: {episode_id}")
        print(f"   URL: {test_episode.get('permalink_url', 'N/A')}")
        
        # Process episode
        print("\n⚙️  Processing episode...")
        await sensor.process_episode("planetary-regeneration", test_episode)
        
        print("\n" + "="*70)
        print("✅ TEST COMPLETE!")
        print("="*70)
        print(f"Check transcript at: transcripts/episode_{episode_id}.json")
        
    finally:
        await sensor.session.close()
        await sensor.koi_node.stop()

if __name__ == "__main__":
    asyncio.run(test_one_episode())
