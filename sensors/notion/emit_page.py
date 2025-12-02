#!/usr/bin/env python3
"""
Emit a specific Notion page to the KOI pipeline with transcript.
Usage: python emit_page.py <page_id>
"""

import asyncio
import os
import sys
import hashlib
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / '.env')

from sensors.notion.notion_sensor import NotionKOISensor


async def emit_page(page_id: str):
    """Process and emit a specific page to KOI pipeline"""
    notion_token = os.getenv('REGENTOKENOMICS_NOTION_API_KEY')
    if not notion_token:
        print("❌ REGENTOKENOMICS_NOTION_API_KEY not found")
        return

    print(f"📤 Emitting page to KOI pipeline: {page_id}")

    async with NotionKOISensor(
        node_id="koi-notion-regentokenomics",
        notion_token=notion_token,
        workspace_id="regentokenomics",
        pii_filter_enabled=True,
        pii_filter_types=['email', 'telegram', 'phone', 'discord'],
        transcribe_videos=True,
        whisper_model="base"
    ) as sensor:
        # Get page metadata
        page = await sensor.get_page(page_id)
        if not page:
            print(f"❌ Could not fetch page {page_id}")
            return

        # Get page content with transcript
        print("📄 Fetching page content (with video transcription)...")
        content = await sensor.get_page_content(page_id)
        print(f"   Retrieved {len(content)} chars of content")

        # Extract properties
        properties = sensor.extract_properties(page.get("properties", {}))

        # Get title
        title = None
        for prop_name, prop_value in properties.items():
            if prop_name.lower() in ["title", "name"]:
                title = prop_value
                break
        if not title:
            title = f"Page {page_id[:8]}"

        print(f"   Title: {title}")

        # Create bundle
        from koi_protocol.identifiers import ORN
        from koi_protocol.bundle import Bundle

        rid = f"orn:notion:regentokenomics:page:{page_id}"

        created_time = page.get("created_time")
        last_edited_time = page.get("last_edited_time")
        page_url = page.get("url", "")

        bundle = Bundle(
            rid=rid,
            source="notion",
            title=title,
            content=content,
            metadata={
                "page_id": page_id,
                "published_at": created_time,
                "published_confidence": 0.85,
                "last_modified": last_edited_time,
                "page_url": page_url,
                "url": page_url,
                "source_url": page_url,
                "created_time": created_time,
                "last_edited_time": last_edited_time,
                "properties": properties
            }
        )

        # Emit to coordinator
        print("📡 Emitting to KOI coordinator...")
        await sensor.koi_node.emit_new_event(bundle)
        print("✅ Event emitted successfully!")

        # Update state so sensor doesn't re-process
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        sensor.state.metadata[f"hash_{page_id}"] = content_hash
        sensor.state.mark_processed("regentokenomics", page_id)
        sensor.state.save()
        print("💾 State updated")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python emit_page.py <page_id>")
        print("Example: python emit_page.py 2b1a755141ee8063981ae02d7bb790a7")
        sys.exit(1)

    page_id = sys.argv[1].replace('-', '')
    # Add hyphens if needed
    if len(page_id) == 32:
        page_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"

    asyncio.run(emit_page(page_id))
