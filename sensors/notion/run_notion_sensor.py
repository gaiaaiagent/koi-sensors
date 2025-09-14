#!/usr/bin/env python3
"""
Run Notion Sensor with KOI Coordinator Integration
Monitors Notion workspace and sends events to KOI Event Bridge
"""

import asyncio
import os
import sys
import yaml
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path)

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from notion_sensor import NotionKOISensor


async def run_with_coordinator():
    """Run Notion sensor with coordinator integration"""
    
    print("📝 KOI Notion Sensor - Production Mode")
    print("=" * 60)
    print(f"Starting at {datetime.now().isoformat()}")
    print("=" * 60)
    
    # Load configuration
    config_path = Path(__file__).parent / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f)
        print(f"✅ Loaded configuration from {config_path}")
    else:
        config = {
            "sensor": {
                "coordinator_url": "http://localhost:8200",
                "default_check_interval": 3600,
                "default_priority": "medium"
            },
            "databases": [],
            "pages": []
        }
        print(f"⚠️  Using default configuration")
    
    # Get Notion token
    notion_token = os.getenv('NOTION_API_KEY')
    
    if not notion_token:
        print("❌ No Notion token found. Set NOTION_INTEGRATION_SECRET env var.")
        return
    
    # Create sensor
    coordinator_url = config["sensor"].get("coordinator_url", "http://localhost:8200")
    
    async with NotionKOISensor(
        notion_token=notion_token,
        coordinator_url=coordinator_url
    ) as sensor:
        print(f"✅ Notion sensor initialized")
        print(f"   Coordinator: {coordinator_url}")
        
        # Discover and add databases if none configured
        configured_databases = config.get("databases", [])
        
        if not configured_databases:
            print("\n🔍 No databases configured. Discovering workspace...")
            
            # Search for all databases
            databases = await sensor.search_workspace(filter_type="database")
            
            if databases:
                print(f"📊 Found {len(databases)} databases:")
                
                # Add all discovered databases to monitoring
                for db in databases:
                    db_id = db["id"]
                    title = sensor.extract_text_from_rich_text(
                        db.get("title", [])
                    ) or f"Database {db_id[:8]}"
                    
                    print(f"   - {title}")
                    
                    # Add to monitoring
                    await sensor.monitor_database(
                        db_id,
                        check_interval=config["sensor"]["default_check_interval"],
                        priority=config["sensor"]["default_priority"]
                    )
                
                print(f"\n✅ Added {len(databases)} databases to monitoring")
            else:
                print("⚠️  No databases found in workspace")
                print("   Make sure the integration has access to databases")
                print("   Check: https://www.notion.so/my-integrations")
        else:
            # Use configured databases
            print(f"\n📊 Loading {len(configured_databases)} configured databases:")
            
            for db_config in configured_databases:
                db_id = db_config["id"]
                db_name = db_config.get("name", f"Database {db_id[:8]}")
                check_interval = db_config.get("check_interval", 
                                              config["sensor"]["default_check_interval"])
                priority = db_config.get("priority", 
                                       config["sensor"]["default_priority"])
                
                print(f"   - {db_name}")
                
                await sensor.monitor_database(db_id, check_interval, priority)
        
        # Start monitoring loop
        print("\n🚀 Starting monitoring loop...")
        print("   Press Ctrl+C to stop")
        print("-" * 60)
        
        try:
            await sensor.run_monitoring_loop()
        except KeyboardInterrupt:
            print("\n\n⏹️  Monitoring stopped by user")
        except Exception as e:
            print(f"\n❌ Error in monitoring loop: {e}")
            import traceback
            traceback.print_exc()


async def run_standalone():
    """Run Notion sensor in standalone mode (no coordinator)"""
    
    print("📝 KOI Notion Sensor - Standalone Mode")
    print("=" * 60)
    print("Running without coordinator (test mode)")
    print("=" * 60)
    
    notion_token = os.getenv('NOTION_API_KEY')
    
    async with NotionKOISensor(notion_token=notion_token) as sensor:
        # Discover workspace
        print("\n🔍 Discovering workspace content...")
        
        databases = await sensor.search_workspace(filter_type="database")
        pages = await sensor.search_workspace(filter_type="page")
        
        print(f"\n📊 Workspace Summary:")
        print(f"   Databases: {len(databases)}")
        print(f"   Pages: {len(pages)}")
        
        if databases:
            # Monitor first database
            first_db = databases[0]
            db_id = first_db["id"]
            title = sensor.extract_text_from_rich_text(
                first_db.get("title", [])
            ) or "First Database"
            
            print(f"\n🎯 Monitoring: {title}")
            
            await sensor.monitor_database(db_id)
            
            # Run a few check cycles
            for i in range(3):
                print(f"\n🔄 Check cycle {i+1}/3...")
                
                changes = await sensor.check_for_changes()
                
                if changes:
                    print(f"   Found {len(changes)} changes:")
                    for change in changes[:5]:
                        print(f"   - {change['event_type']}: {change['title']}")
                else:
                    print(f"   No changes detected")
                
                if i < 2:
                    print(f"   Waiting 30 seconds...")
                    await asyncio.sleep(30)
        else:
            print("\n⚠️  No databases found to monitor")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run KOI Notion Sensor")
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="Run in standalone mode without coordinator"
    )
    parser.add_argument(
        "--coordinator-url",
        default="http://localhost:8200",
        help="KOI Coordinator URL (default: http://localhost:8200)"
    )
    
    args = parser.parse_args()
    
    # Set coordinator URL if provided
    if args.coordinator_url:
        os.environ["KOI_COORDINATOR_URL"] = args.coordinator_url
    
    try:
        if args.standalone:
            asyncio.run(run_standalone())
        else:
            asyncio.run(run_with_coordinator())
    except KeyboardInterrupt:
        print("\n\nShutdown complete.")


if __name__ == "__main__":
    main()