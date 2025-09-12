#!/usr/bin/env python3
"""
Medium Sensor Runner
Tests and runs the KOI Medium monitoring sensor
"""

import asyncio
import logging
import yaml
import sys
from pathlib import Path

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from medium_sensor import MediumKOISensor, MediumMonitorConfig
from shared.config.base import APIConfig, KoiNetConfig, MonitoringConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Run the Medium sensor"""
    
    # Load configuration
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, 'r') as f:
        config_data = yaml.safe_load(f)
    
    print("📰 KOI Medium Sensor - Starting")
    print("=" * 50)
    print(f"Node ID: {config_data['sensor']['node_id']}")
    print(f"Monitoring {len(config_data['medium_sources'])} Medium sources")
    print("=" * 50)
    
    # Create configuration object
    config = MediumMonitorConfig(
        sensor_name=config_data['sensor']['name'],
        platform="medium",
        api=APIConfig(),  # No API needed for RSS/scraping
        koi_net=KoiNetConfig(
            node_name=config_data['sensor']['node_id'],
            coordinator_url=config_data['sensor']['coordinator_url']
        ),
        monitoring=MonitoringConfig(
            log_level=config_data['logging']['level']
        ),
        medium_sources=config_data['medium_sources'],
        max_articles_per_check=config_data['collection']['max_articles_per_check'],
        use_rss=config_data['collection']['use_rss'],
        use_scraping=config_data['collection']['use_scraping'],
        historical_years=config_data['collection']['historical_years'],
        min_content_length=config_data['content_filtering']['min_content_length'],
        extract_images=config_data['content_filtering']['extract_images'],
        request_delay=config_data['http']['request_delay'],
        user_agent=config_data['http']['user_agent'],
        timeout_seconds=config_data['http']['timeout_seconds']
    )
    
    # Create sensor instance
    sensor = MediumKOISensor(config)
    
    try:
        # Show source status
        print("\n📊 Medium Source Configuration:")
        for source in config_data['medium_sources']:
            print(f"   {source['name']}: {source['url']}")
            print(f"     RSS: {source.get('rss_url', 'N/A')}")
            print(f"     Priority: {source['priority']}, Interval: {source['check_interval']}s")
            print(f"     Notes: {source.get('notes', 'N/A')}")
            print()
        
        print("🚀 Starting Medium blog monitoring...")
        print(f"   Collection settings:")
        print(f"     RSS enabled: {config.use_rss}")
        print(f"     Scraping enabled: {config.use_scraping}")
        print(f"     Max articles per check: {config.max_articles_per_check}")
        print(f"     Historical years: {config.historical_years}")
        
        # Start monitoring
        await sensor.start()
        
    except KeyboardInterrupt:
        print("\n🛑 Shutting down Medium sensor...")
        await sensor.stop()
    except Exception as e:
        logger.error(f"Error in Medium sensor: {e}")
        await sensor.stop()
        raise

if __name__ == "__main__":
    asyncio.run(main())