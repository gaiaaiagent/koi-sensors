#!/usr/bin/env python3
"""
Quick script to transcribe a specific Notion page's video
Usage: python transcribe_page.py <page_id>
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / '.env')

from sensors.notion.notion_sensor import NotionKOISensor


async def transcribe_page(page_id: str):
    """Transcribe videos from a specific page"""
    notion_token = os.getenv('REGENTOKENOMICS_NOTION_API_KEY')
    if not notion_token:
        print("❌ REGENTOKENOMICS_NOTION_API_KEY not found")
        return

    print(f"🎬 Transcribing videos from page: {page_id}")

    async with NotionKOISensor(
        node_id="transcribe-single-page",
        notion_token=notion_token,
        workspace_id="regentokenomics",
        pii_filter_enabled=True,
        pii_filter_types=['email', 'telegram', 'phone', 'discord'],
        transcribe_videos=True,
        whisper_model="base"
    ) as sensor:
        # Get page content (this will transcribe videos)
        content = await sensor.get_page_content(page_id)

        print(f"\n{'='*60}")
        print(f"📄 Page content ({len(content)} characters):")
        print(f"{'='*60}")
        print(content)

        # Save to file
        output_file = Path(__file__).parent / f"transcript_{page_id[:8]}.txt"
        with open(output_file, 'w') as f:
            f.write(content)
        print(f"\n✅ Saved to: {output_file}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python transcribe_page.py <page_id>")
        print("Example: python transcribe_page.py 2b1a755141ee8063981ae02d7bb790a7")
        sys.exit(1)

    page_id = sys.argv[1].replace('-', '')
    # Add hyphens if needed
    if len(page_id) == 32:
        page_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"

    asyncio.run(transcribe_page(page_id))
