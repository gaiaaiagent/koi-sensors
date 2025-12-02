#!/usr/bin/env python3
"""
Emit a Notion page with existing transcript to the KOI pipeline.
Uses already-transcribed content from a file.
"""

import asyncio
import os
import sys
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / '.env')

import aiohttp
from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.bundle_system import document_to_bundle


async def emit_page_with_transcript(page_id: str, transcript_file: str):
    """Emit page with existing transcript to KOI pipeline"""
    notion_token = os.getenv('REGENTOKENOMICS_NOTION_API_KEY')
    if not notion_token:
        print("❌ REGENTOKENOMICS_NOTION_API_KEY not found")
        return

    # Read existing transcript
    with open(transcript_file, 'r') as f:
        content = f.read()
    print(f"📄 Loaded transcript: {len(content)} chars")

    # Fetch page metadata from Notion
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(f"https://api.notion.com/v1/pages/{page_id}") as resp:
            if resp.status != 200:
                print(f"❌ Failed to fetch page: {await resp.text()}")
                return
            page = await resp.json()

    # Extract title
    title = None
    for prop_name, prop_value in page.get("properties", {}).items():
        if prop_value.get("type") == "title":
            title_parts = prop_value.get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_parts)
            break
    if not title:
        title = f"Page {page_id[:8]}"

    print(f"📝 Title: {title}")

    created_time = page.get("created_time")
    last_edited_time = page.get("last_edited_time")
    page_url = page.get("url", "")

    # Create document (same format as notion_sensor uses)
    rid = f"orn:notion:regentokenomics:page:{page_id}"

    document = {
        "event_type": "NEW",
        "source": "notion",
        "source_type": "notion",
        "rid": rid,
        "title": title,
        "content": content,
        "metadata": {
            "page_id": page_id,
            "published_at": created_time,
            "published_confidence": 0.85,
            "last_modified": last_edited_time,
            "page_url": page_url,
            "url": page_url,
            "source_url": page_url,
            "created_time": created_time,
            "last_edited_time": last_edited_time,
        }
    }

    # Convert to bundle
    bundle = document_to_bundle(document)

    # Initialize KOI node and emit (must use async context for session)
    koi_node = KOIPartialNode(
        node_name="notion-sensor",
        coordinator_url="http://localhost:8005",
        poll_interval=30
    )

    print("📡 Emitting to KOI coordinator...")
    await koi_node.start()  # Creates the aiohttp session
    try:
        await koi_node.emit_new_event(bundle)
        print("✅ Event emitted successfully!")
    finally:
        await koi_node.stop()

    # Update sensor state
    from sensors.notion.notion_sensor import PersistentSensorState
    state = PersistentSensorState('notion', Path(__file__).parent)
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    state.metadata[f"hash_{page_id}"] = content_hash
    state.mark_processed("regentokenomics", page_id)
    state.save()
    print("💾 State updated")


if __name__ == "__main__":
    page_id = "2b1a7551-41ee-8063-981a-e02d7bb790a7"
    transcript_file = Path(__file__).parent / "transcript_2b1a7551.txt"

    if not transcript_file.exists():
        print(f"❌ Transcript file not found: {transcript_file}")
        sys.exit(1)

    asyncio.run(emit_page_with_transcript(page_id, str(transcript_file)))
