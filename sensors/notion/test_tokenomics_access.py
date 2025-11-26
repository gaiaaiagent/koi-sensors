#!/usr/bin/env python3
"""
Test script to verify TOKENOMICS_API_KEY access to Notion
"""

import asyncio
import aiohttp
import os
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()

NOTION_API_VERSION = "2022-06-28"
NOTION_API_BASE = "https://api.notion.com/v1"

async def test_notion_access(api_key, key_name):
    """Test Notion API access with the given key"""
    print(f"\n{'='*60}")
    print(f"Testing {key_name}")
    print(f"{'='*60}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        # Test 1: Search workspace
        print("\n1. Searching workspace...")
        search_params = {"page_size": 100}

        try:
            async with session.post(
                f"{NOTION_API_BASE}/search",
                json=search_params
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get("results", [])

                    print(f"   ✅ Success! Found {len(results)} items")

                    # Categorize results
                    databases = [r for r in results if r.get("object") == "database"]
                    pages = [r for r in results if r.get("object") == "page"]

                    print(f"\n   📊 Summary:")
                    print(f"      - Databases: {len(databases)}")
                    print(f"      - Pages: {len(pages)}")

                    # Show database details
                    if databases:
                        print(f"\n   📁 Databases:")
                        for db in databases:
                            title_parts = db.get("title", [])
                            title = "".join([t.get("plain_text", "") for t in title_parts]) or f"Untitled ({db['id'][:8]})"
                            url = db.get("url", "")
                            print(f"      - {title}")
                            print(f"        ID: {db['id']}")
                            print(f"        URL: {url}")

                    # Show first few pages
                    if pages:
                        print(f"\n   📄 Pages (showing first 5):")
                        for page in pages[:5]:
                            url = page.get("url", "")
                            # Try to extract title
                            title = "Untitled"
                            if 'properties' in page:
                                for prop_name, prop_value in page['properties'].items():
                                    if prop_value.get('type') == 'title' and prop_value.get('title'):
                                        title = ''.join(t['plain_text'] for t in prop_value['title'])
                                        break
                            print(f"      - {title}")
                            print(f"        URL: {url}")

                        if len(pages) > 5:
                            print(f"      ... and {len(pages) - 5} more pages")

                    # Check if any pages/databases are from regentokenomics.org
                    print(f"\n   🔍 Checking for regentokenomics.org content...")
                    tokenomics_items = []
                    for item in results:
                        url = item.get("url", "")
                        if "regentokenomics" in url.lower():
                            tokenomics_items.append(item)

                    if tokenomics_items:
                        print(f"      ✅ Found {len(tokenomics_items)} items related to regentokenomics!")
                        for item in tokenomics_items[:3]:
                            print(f"         - {item.get('url', 'No URL')}")
                    else:
                        print(f"      ⚠️  No items with 'regentokenomics' in URL found")
                        print(f"      Note: Notion pages may not show regentokenomics.org in their URLs")
                        print(f"      The site may be using Notion as a backend with a custom domain")

                    return True, len(databases), len(pages)

                elif response.status == 401:
                    print(f"   ❌ Authentication failed - invalid API key")
                    error = await response.text()
                    print(f"   Error: {error}")
                    return False, 0, 0

                elif response.status == 403:
                    print(f"   ❌ Access forbidden - API key lacks permissions")
                    error = await response.text()
                    print(f"   Error: {error}")
                    return False, 0, 0

                else:
                    print(f"   ❌ Request failed with status {response.status}")
                    error = await response.text()
                    print(f"   Error: {error}")
                    return False, 0, 0

        except Exception as e:
            print(f"   ❌ Exception occurred: {e}")
            return False, 0, 0


async def main():
    """Main test function"""
    print("\n🧪 Testing Notion API Access")
    print("="*60)

    # Get API keys
    notion_api_key = os.getenv('NOTION_API_KEY')
    tokenomics_api_key = os.getenv('TOKENOMICS_API_KEY')

    if not notion_api_key:
        print("❌ NOTION_API_KEY not found in environment")
    if not tokenomics_api_key:
        print("❌ TOKENOMICS_API_KEY not found in environment")

    if not notion_api_key and not tokenomics_api_key:
        print("\n⚠️  No API keys found. Please check your .env file")
        return

    results = {}

    # Test existing NOTION_API_KEY
    if notion_api_key:
        success, db_count, page_count = await test_notion_access(notion_api_key, "NOTION_API_KEY (existing)")
        results['NOTION_API_KEY'] = {
            'success': success,
            'databases': db_count,
            'pages': page_count
        }

    # Test new TOKENOMICS_API_KEY
    if tokenomics_api_key:
        success, db_count, page_count = await test_notion_access(tokenomics_api_key, "TOKENOMICS_API_KEY (new)")
        results['TOKENOMICS_API_KEY'] = {
            'success': success,
            'databases': db_count,
            'pages': page_count
        }

    # Summary
    print(f"\n{'='*60}")
    print("📊 SUMMARY")
    print(f"{'='*60}")

    for key_name, result in results.items():
        if result['success']:
            print(f"\n✅ {key_name}:")
            print(f"   - Can access Notion API")
            print(f"   - Found {result['databases']} databases")
            print(f"   - Found {result['pages']} pages")

            if key_name == 'TOKENOMICS_API_KEY':
                if result['databases'] > 0 or result['pages'] > 0:
                    print(f"\n   🎉 You can use the Notion sensor for regentokenomics.org!")
                    print(f"   💡 Recommendation: Update the Notion sensor to support multiple API keys")
                else:
                    print(f"\n   ⚠️  API key is valid but has no accessible content")
                    print(f"   💡 Check integration permissions in Notion")
        else:
            print(f"\n❌ {key_name}:")
            print(f"   - Failed to access Notion API")

    print()


if __name__ == "__main__":
    asyncio.run(main())
