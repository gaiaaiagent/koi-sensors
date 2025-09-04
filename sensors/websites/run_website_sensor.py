#!/usr/bin/env python3
"""
Website Sensor Runner
Tests the website monitoring functionality
"""

import asyncio
import logging
import yaml
from pathlib import Path
from website_sensor import WebsiteKOISensor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Run the website sensor"""
    
    # Load configuration
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    logger.info("Starting Website KOI Sensor")
    logger.info(f"Node ID: {config['sensor']['node_id']}")
    logger.info(f"Monitoring {len(config['websites'])} websites")
    
    # Create sensor instance
    sensor = WebsiteKOISensor(
        node_id=config['sensor']['node_id'],
        coordinator_url=config['sensor']['coordinator_url']
    )
    
    # Configure sensor with websites
    for website in config['websites']:
        logger.info(f"Adding website: {website['name']} ({website['url']})")
        sensor.add_website(
            name=website['name'],
            url=website['url'],
            check_interval=website.get('check_interval', 3600),
            max_depth=website.get('max_depth', 2),
            paths=website.get('paths', [])
        )
    
    try:
        # Start monitoring
        logger.info("Starting website monitoring...")
        await sensor.start_monitoring()
        
        # Keep running
        while True:
            await asyncio.sleep(60)
            logger.info("Website sensor running...")
            
    except KeyboardInterrupt:
        logger.info("Shutting down website sensor...")
        await sensor.stop_monitoring()
    except Exception as e:
        logger.error(f"Error in website sensor: {e}")
        await sensor.stop_monitoring()
        raise

if __name__ == "__main__":
    asyncio.run(main())