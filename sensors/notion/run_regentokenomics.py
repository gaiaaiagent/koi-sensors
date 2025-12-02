#!/usr/bin/env python3
"""
Run Notion sensor for Regen Tokenomics workspace (regentokenomics.org)

This script monitors the Notion databases that power regentokenomics.org,
with PII filtering enabled to protect personal data.
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent.parent / '.env')

from sensors.notion.notion_sensor import NotionKOISensor


# Regentokenomics database IDs (discovered via API)
REGENTOKENOMICS_DATABASES = {
    'weekly_meetups': '1f9a7551-41ee-80a4-8d44-d4b676cdcb30',
    'reports': '1f9a7551-41ee-8056-8343-fdfb23d8e70e',
    'projects': 'a3ad5540-195f-4dc9-b530-935ec549c57e',
    'q2_kanban': '1f9a7551-41ee-816f-856f-e8baffb9332a',
}

# Pages to skip (archive pages with many videos that would take weeks to transcribe)
SKIP_PAGES = [
    '152a7551-41ee-80ba-a6fe-f457f7601368',  # "2024" archive page - contains 78+ video recordings
]


async def main():
    """Main entry point for Regentokenomics Notion sensor"""
    print("=" * 60)
    print("🚀 Regen Tokenomics Notion Sensor")
    print("=" * 60)
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}")

    # Get API key from environment
    notion_token = os.getenv('REGENTOKENOMICS_NOTION_API_KEY')
    if not notion_token:
        print("❌ REGENTOKENOMICS_NOTION_API_KEY not found in environment")
        print("   Please add it to .env file")
        return

    print(f"✓ API key loaded: {notion_token[:15]}...")

    # Get polling interval (default 30 minutes)
    poll_interval = int(os.getenv('REGENTOKENOMICS_SITE_POLL_INTERVAL', 1800))
    print(f"✓ Poll interval: {poll_interval}s ({poll_interval/60:.0f} minutes)")

    # Initialize sensor with PII filtering, video transcription, and section skipping
    async with NotionKOISensor(
        node_id="koi-notion-regentokenomics",
        notion_token=notion_token,
        workspace_id="regentokenomics",
        pii_filter_enabled=True,
        pii_filter_types=['email', 'telegram', 'phone', 'discord'],
        # Enable video transcription for meeting recordings
        transcribe_videos=True,
        whisper_model="base",  # "tiny" for faster, "small"/"medium" for better accuracy
        # Skip "Projects" section - it's an embedded database already scraped separately
        skip_sections=["Projects"],
        # Skip archive pages with many videos (would take weeks to transcribe)
        skip_pages=SKIP_PAGES
    ) as sensor:
        print("\n🔍 Configuring database monitoring...")

        # Add databases to monitor
        for name, db_id in REGENTOKENOMICS_DATABASES.items():
            # Use appropriate check intervals
            if name == 'weekly_meetups':
                check_interval = 1800  # 30 min - high priority
                priority = "high"
            elif name in ['reports', 'projects']:
                check_interval = 3600  # 1 hour
                priority = "medium"
            else:
                check_interval = 7200  # 2 hours - lower priority
                priority = "low"

            await sensor.monitor_database(
                db_id,
                check_interval=check_interval,
                priority=priority
            )

        # Also search and track individual pages
        print("\n🔍 Searching workspace for pages...")
        all_items = await sensor.search_workspace()
        pages = [item for item in all_items if item.get('object') == 'page']

        print(f"   Found {len(pages)} pages")

        # Track pages for heartbeat reporting
        for page in pages:
            page_id = page.get('id', '')
            page_url = page.get('url', f"https://notion.so/{page_id}")
            page_title = "Untitled"

            if 'properties' in page:
                for prop_name, prop_value in page['properties'].items():
                    if prop_value.get('type') == 'title' and prop_value.get('title'):
                        page_title = ''.join(t['plain_text'] for t in prop_value['title'])
                        break

            sensor.monitored_pages[page_id] = {
                'id': page_id,
                'url': page_url,
                'title': page_title,
                'last_checked': datetime.now(timezone.utc).isoformat()
            }

        print(f"\n📊 Monitoring configuration:")
        print(f"   Databases: {len(sensor.monitored_databases)}")
        print(f"   Pages tracked: {len(sensor.monitored_pages)}")
        print(f"   PII Filter: enabled (email, telegram, phone, discord)")
        print(f"   Video Transcription: enabled (whisper base model)")
        print(f"   Skip Sections: Projects (embedded database)")
        print(f"   Skip Pages: {len(SKIP_PAGES)} (2024 archive)")

        # Start monitoring loop
        print(f"\n🚀 Starting monitoring loop...")
        await sensor.run_monitoring_loop(poll_interval)


if __name__ == "__main__":
    print("Starting Regen Tokenomics Notion sensor...")
    asyncio.run(main())
