#!/usr/bin/env python3
"""
GitHub Sensor Runner
Tests and runs the KOI GitHub monitoring sensor
"""

import asyncio
import logging
import yaml
import sys
from pathlib import Path

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from github_sensor import GitHubSensor, GitHubConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Run the GitHub sensor"""
    
    # Load configuration
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, 'r') as f:
        config_data = yaml.safe_load(f)
    
    print("🐙 KOI GitHub Sensor - Starting")
    print("=" * 50)
    print(f"Node ID: {config_data['sensor']['node_id']}")
    print(f"Monitoring {len(config_data['repositories'])} repositories")
    print("=" * 50)
    
    # Create configuration object
    config = GitHubConfig(
        repos=config_data['repositories'],
        koi_bridge_url=config_data['sensor']['coordinator_url'],
        source_sensor=config_data['sensor']['name'],
        doc_extensions=config_data.get('doc_extensions', None),
        excluded_dirs=config_data.get('excluded_dirs', None)
    )
    
    # Create sensor instance
    sensor = GitHubSensor(config, logger)
    
    try:
        # Show repository status
        print("\n📊 Repository Configuration:")
        for repo in config_data['repositories']:
            print(f"   {repo['name']}: {repo['url']}")
            print(f"     Branch: {repo['branch']}, Paths: {repo['paths']}")
            print(f"     Priority: {repo['priority']}, Interval: {repo['check_interval']}s")
            print(f"     Notes: {repo.get('notes', 'N/A')}")
            print()
        
        print("🚀 Starting GitHub repository collection...")
        
        # Collect documents from all repositories
        documents = await sensor.collect_all_repos()
        
        print(f"✅ Collected {len(documents)} documents from {len(config.repos)} repositories")
        
        # Send to KOI coordinator
        if documents:
            print(f"📤 Sending documents to KOI coordinator at {config.koi_bridge_url}")
            success_count = await sensor.send_to_koi(documents)
            print(f"✅ Successfully sent {success_count}/{len(documents)} documents to KOI")
        else:
            print("⚠️  No documents found to send")
        
    except KeyboardInterrupt:
        print("\n🛑 Shutting down GitHub sensor...")
    except Exception as e:
        logger.error(f"Error in GitHub sensor: {e}")
        raise
    finally:
        # Cleanup temporary files
        sensor.cleanup()

if __name__ == "__main__":
    asyncio.run(main())