#!/usr/bin/env python3
"""
Backfill author metadata for existing Notion documents.

This script fetches the created_by information from the Notion API
and updates the metadata in koi_memories for all Notion documents.

Supports TWO Notion workspaces:
- Regen Main: Uses NOTION_API_KEY
- Regentokenomics: Uses REGENTOKENOMICS_NOTION_API_KEY

The correct API key is selected based on the access_source column.

Usage:
    python scripts/backfill-notion-authors.py [--dry-run]

Requires:
    - NOTION_API_KEY and/or REGENTOKENOMICS_NOTION_API_KEY environment variables
    - POSTGRES_URL or DB_* environment variables for PostgreSQL connection
"""

import os
import sys
import asyncio
import argparse
from datetime import datetime
import json

# Add parent directories for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv


NOTION_API_VERSION = "2022-06-28"
NOTION_API_BASE = "https://api.notion.com/v1"


async def get_notion_page(token: str, page_id: str) -> dict:
    """Fetch page metadata from Notion API with specified token."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json"
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(f"{NOTION_API_BASE}/pages/{page_id}") as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 404:
                    return None
                else:
                    error = await response.text()
                    print(f"   ❌ Failed to get page {page_id}: {response.status} - {error[:100]}")
                    return None
    except Exception as e:
        print(f"   ❌ Error getting page {page_id}: {e}")
        return None


async def get_notion_user(token: str, user_id: str) -> dict:
    """Fetch user details from Notion API to get the user name."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json"
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(f"{NOTION_API_BASE}/users/{user_id}") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    return None
    except Exception as e:
        return None


async def backfill_notion_authors(dry_run: bool = False):
    """Main backfill function."""
    load_dotenv()

    # Get BOTH Notion tokens
    notion_token_main = os.getenv('NOTION_API_KEY') or os.getenv('NOTION_INTEGRATION_SECRET')
    notion_token_regentokenomics = os.getenv('REGENTOKENOMICS_NOTION_API_KEY')

    if not notion_token_main and not notion_token_regentokenomics:
        print("❌ No Notion API keys found in environment")
        print("   Need NOTION_API_KEY and/or REGENTOKENOMICS_NOTION_API_KEY")
        sys.exit(1)

    print(f"🔑 API Keys available:")
    print(f"   Regen Main (NOTION_API_KEY): {'✓' if notion_token_main else '✗'}")
    print(f"   Regentokenomics (REGENTOKENOMICS_NOTION_API_KEY): {'✓' if notion_token_regentokenomics else '✗'}")

    # Database connection - try POSTGRES_URL first, then individual vars
    postgres_url = os.getenv('POSTGRES_URL')
    if postgres_url:
        print(f"🔧 Connecting to database via POSTGRES_URL...")
        conn = psycopg2.connect(postgres_url)
    else:
        db_config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': int(os.getenv('DB_PORT', 5433)),
            'database': os.getenv('DB_NAME', 'eliza'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', ''),
        }
        print(f"🔧 Connecting to database...")
        conn = psycopg2.connect(**db_config)
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Find all Notion documents without author metadata, including access_source
    cursor.execute("""
        SELECT DISTINCT ON (SUBSTRING(rid FROM 'orn:notion.page:[^/]+/([^#]+)'))
            SUBSTRING(rid FROM 'orn:notion.page:[^/]+/([^#]+)') as page_id,
            rid,
            metadata->>'author' as current_author,
            metadata->>'access_source' as access_source
        FROM koi_memories
        WHERE superseded_at IS NULL
          AND metadata->>'source' = 'notion'
          AND rid LIKE 'orn:notion.page:%'
          AND COALESCE(metadata->>'author', '') = ''
        ORDER BY SUBSTRING(rid FROM 'orn:notion.page:[^/]+/([^#]+)'), rid
        LIMIT 500
    """)

    rows = cursor.fetchall()
    print(f"📊 Found {len(rows)} unique Notion pages without author metadata")

    if not rows:
        print("✅ All Notion pages already have author metadata")
        cursor.close()
        conn.close()
        return

    # Count by workspace
    main_count = sum(1 for r in rows if r['access_source'] != 'notion-main-workspace-backfill')
    regentokenomics_count = sum(1 for r in rows if r['access_source'] == 'notion-main-workspace-backfill')
    print(f"   Regen Main workspace: {main_count} pages")
    print(f"   Regentokenomics workspace: {regentokenomics_count} pages")

    updated = 0
    skipped = 0
    errors = 0

    for i, row in enumerate(rows, 1):
        page_id = row['page_id']
        rid = row['rid']
        access_source = row['access_source'] or ''

        if not page_id:
            print(f"   ⚠️ Could not extract page_id from RID: {rid}")
            skipped += 1
            continue

        # Select the right token based on access_source
        # Pages with 'notion-main-workspace-backfill' are actually from regentokenomics
        if access_source == 'notion-main-workspace-backfill':
            token = notion_token_regentokenomics
            workspace = "regentokenomics"
        else:
            token = notion_token_main
            workspace = "regen-main"

        if not token:
            print(f"   ⚠️ No API key for {workspace} workspace, skipping page {page_id[:16]}")
            skipped += 1
            continue

        # Format page_id with hyphens for Notion API
        if len(page_id) == 32 and '-' not in page_id:
            formatted_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"
        else:
            formatted_id = page_id

        print(f"[{i}/{len(rows)}] Fetching page {formatted_id[:16]}... ({workspace})")

        # Fetch page from Notion API
        page_data = await get_notion_page(token, formatted_id)

        if not page_data:
            print(f"   ⚠️ Page not found or inaccessible")
            errors += 1
            continue

        # Extract author info
        created_by = page_data.get("created_by", {})
        author_name = created_by.get("name")
        author_id = created_by.get("id")

        # If name not in page response, fetch user details
        if not author_name and author_id:
            user_data = await get_notion_user(token, author_id)
            if user_data:
                author_name = user_data.get("name")
            await asyncio.sleep(0.2)  # Rate limit for extra API call

        last_edited_by = page_data.get("last_edited_by", {})
        last_editor_name = last_edited_by.get("name")
        last_editor_id = last_edited_by.get("id")

        # Fetch editor name if not in response
        if not last_editor_name and last_editor_id:
            editor_data = await get_notion_user(token, last_editor_id)
            if editor_data:
                last_editor_name = editor_data.get("name")
            await asyncio.sleep(0.2)

        if not author_name:
            print(f"   ⚠️ No author name found for page {page_id[:16]}")
            skipped += 1
            continue

        print(f"   ✓ Author: {author_name}")

        if dry_run:
            print(f"   [DRY RUN] Would update metadata for {rid[:50]}...")
            updated += 1
            continue

        # Update all chunks for this page
        try:
            cursor.execute("""
                UPDATE koi_memories
                SET metadata = jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            metadata,
                            '{author}',
                            %s::jsonb
                        ),
                        '{author_id}',
                        %s::jsonb
                    ),
                    '{last_edited_by}',
                    %s::jsonb
                )
                WHERE superseded_at IS NULL
                  AND rid LIKE %s
            """, (
                json.dumps(author_name),
                json.dumps(author_id),
                json.dumps(last_editor_name),
                f"orn:notion.page:%/{page_id}%"
            ))

            rows_updated = cursor.rowcount
            conn.commit()

            if rows_updated > 0:
                print(f"   ✓ Updated {rows_updated} chunks")
                updated += 1
            else:
                print(f"   ⚠️ No chunks updated")
                skipped += 1

        except Exception as e:
            print(f"   ❌ Error updating: {e}")
            conn.rollback()
            errors += 1

        # Rate limit - Notion API allows ~3 requests/second
        await asyncio.sleep(0.35)

    cursor.close()
    conn.close()

    print(f"\n📊 Summary:")
    print(f"   ✅ Updated: {updated}")
    print(f"   ⏭️ Skipped: {skipped}")
    print(f"   ❌ Errors: {errors}")

    if dry_run:
        print(f"\n⚠️ This was a dry run. No changes were made.")


def main():
    parser = argparse.ArgumentParser(description='Backfill Notion author metadata')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    args = parser.parse_args()

    asyncio.run(backfill_notion_authors(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
