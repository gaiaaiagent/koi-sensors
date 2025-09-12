#!/usr/bin/env python3
"""
Fixed Website Sensor Runner for KOI Pipeline
"""

import asyncio
import os
import sys
import yaml
from pathlib import Path

# Add parent to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from website_sensor import WebsiteKOISensor, WebsiteMonitorConfig
from shared.config.base import APIConfig, KoiNetConfig

async def main():
    # Load configuration
    config_path = Path(__file__).parent / 'config.yaml'
    
    print("🌐 Starting Website KOI Sensor")
    print("="*50)
    
    # Get coordinator URL from environment
    coordinator_url = os.getenv('KOI_COORDINATOR_URL', 'http://localhost:8005/api/event')
    
    # Load config from YAML file
    config_data = {}
    if config_path.exists():
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
            print(f"📋 Loaded configuration from {config_path}")
    
    # Ensure required fields are present
    if 'sensor' not in config_data:
        config_data['sensor'] = {}
    
    config_data['sensor'].update({
        'sensor_name': config_data.get('sensor', {}).get('node_id', 'website-sensor'),
        'platform': 'website',
        'api': {
            'type': 'http',
            'base_url': coordinator_url
        },
        'koi_net': {
            'coordinator_url': coordinator_url,
            'node_type': 'partial',
            'node_name': 'website-sensor-001'
        }
    })
    
    # Create config from the merged data
    # Use the sensor config to create WebsiteMonitorConfig
    config = WebsiteMonitorConfig(**config_data['sensor'])
    
    # Add websites if they exist in config_data
    if 'websites' in config_data:
        config.websites = config_data['websites']
        print(f"🌐 Monitoring {len(config.websites)} websites")
    
    # Create and start sensor
    sensor = WebsiteKOISensor(config)
    
    print(f"🔗 Coordinator URL: {coordinator_url}")
    print("="*50)
    
    try:
        # Start the sensor
        await sensor.start()
        
        # Keep running until interrupted
        print("✅ Sensor started successfully! Monitoring websites...")
        while True:
            await asyncio.sleep(60)  # Keep alive
            
    except KeyboardInterrupt:
        print("\n🛑 Stopping website sensor...")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
