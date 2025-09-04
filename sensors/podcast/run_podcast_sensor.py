#!/usr/bin/env python3
"""
Podcast Sensor Runner
Tests and runs the KOI podcast monitoring sensor
"""

import asyncio
import logging
import yaml
import sys
from pathlib import Path

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from podcast_sensor import PodcastKOISensor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Run the podcast sensor"""
    
    # Load configuration
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    print("🎧 KOI Podcast Sensor - Starting")
    print("=" * 50)
    print(f"Node ID: {config['sensor']['node_id']}")
    print(f"Monitoring {len(config['podcasts'])} podcasts")
    print("=" * 50)
    
    # Create sensor instance
    sensor = PodcastKOISensor(
        node_id=config['sensor']['node_id'],
        coordinator_url=config['sensor']['coordinator_url']
    )
    
    # Configure with additional podcasts if any
    for podcast in config['podcasts']:
        if podcast['name'] != 'planetary-regeneration':  # Already added by default
            print(f"Adding podcast: {podcast['name']}")
            sensor.add_podcast(
                name=podcast['name'],
                url=podcast['url'],
                description=podcast.get('description', ''),
                check_interval=podcast.get('check_interval', 86400),
                priority=podcast.get('priority', 'medium')
            )
    
    try:
        # Show current status
        print(f"\n📊 Server Data Status:")
        main_podcast = config['podcasts'][0]
        if 'server_stats' in main_podcast:
            stats = main_podcast['server_stats']
            print(f"   Total Episodes: {stats['total_episodes']}")
            print(f"   Transcripts Complete: {stats['transcripts_complete']}")
            print(f"   Missing Transcripts: {stats['missing_transcripts']}")
            print(f"   Total Words: {stats['total_words']:,}")
        
        print(f"\n🚀 Starting podcast monitoring...")
        print(f"   Check interval: {main_podcast['check_interval']} seconds")
        print(f"   Current status: {main_podcast['current_status']}")
        
        # Start monitoring
        await sensor.start_monitoring()
        
    except KeyboardInterrupt:
        print("\n🛑 Shutting down podcast sensor...")
        await sensor.stop_monitoring()
    except Exception as e:
        logger.error(f"Error in podcast sensor: {e}")
        await sensor.stop_monitoring()
        raise

if __name__ == "__main__":
    asyncio.run(main())