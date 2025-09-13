#!/usr/bin/env python3
"""
Test Notion Sensor in standalone mode
Tests Notion API connection and content extraction
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from notion_sensor import NotionKOISensor, NotionPageRID, NotionDatabaseRID


async def test_notion_sensor():
    """Test Notion sensor functionality"""
    
    print("📝 KOI Notion Sensor - Standalone Test")
    print("=" * 60)
    print("Testing Notion API integration and content extraction")
    print("=" * 60)
    
    # Test RID generation
    print("\n🆔 Testing RID Generation:")
    test_items = [
        ("page", "12345678-1234-5678-1234-567812345678"),
        ("database", "87654321-8765-4321-8765-432187654321"),
    ]
    
    for item_type, item_id in test_items:
        if item_type == "page":
            rid = NotionPageRID("regen", item_id)
        else:
            rid = NotionDatabaseRID("regen", item_id)
        print(f"   {item_type}/{item_id[:8]}... → {rid.to_orn()}")
    
    # Set up Notion token
    notion_token = os.getenv('NOTION_API_KEY')
    
    print(f"\n🔧 Testing Sensor Setup:")
    print(f"   Token configured: {'✅' if notion_token else '❌'}")
    
    if not notion_token:
        print("   ❌ No Notion token found. Set NOTION_INTEGRATION_SECRET env var.")
        return
    
    # Create sensor
    async with NotionKOISensor(notion_token=notion_token) as sensor:
        print(f"   ✅ Sensor created successfully")
        
        # Test workspace search
        print(f"\n🔍 Testing Workspace Search:")
        
        try:
            # Search for all items
            all_items = await sensor.search_workspace()
            print(f"   ✅ Found {len(all_items)} total items")
            
            # Search for databases only
            databases = await sensor.search_workspace(filter_type="database")
            print(f"   📁 Found {len(databases)} databases")
            
            # Search for pages only
            pages = await sensor.search_workspace(filter_type="page")
            print(f"   📄 Found {len(pages)} pages")
            
            # Show first few databases
            if databases:
                print(f"\n📊 Sample Databases:")
                for db in databases[:3]:
                    title = sensor.extract_text_from_rich_text(
                        db.get("title", [])
                    ) or f"Database {db['id'][:8]}"
                    print(f"   - {title}")
                    print(f"     ID: {db['id']}")
                    print(f"     URL: {db.get('url', 'N/A')}")
            
            # Test database query if we have databases
            if databases:
                first_db = databases[0]
                db_id = first_db["id"]
                db_title = sensor.extract_text_from_rich_text(
                    first_db.get("title", [])
                ) or "First Database"
                
                print(f"\n📖 Testing Database Query:")
                print(f"   Database: {db_title}")
                
                # Query the database
                db_pages = await sensor.query_database(db_id, page_size=5)
                print(f"   ✅ Found {len(db_pages)} pages in database")
                
                # Test content extraction on first page
                if db_pages:
                    first_page = db_pages[0]
                    page_id = first_page["id"]
                    
                    print(f"\n📄 Testing Content Extraction:")
                    print(f"   Page ID: {page_id}")
                    
                    # Get page content
                    content = await sensor.get_page_content(page_id)
                    
                    # Get page properties
                    properties = sensor.extract_properties(
                        first_page.get("properties", {})
                    )
                    
                    print(f"   ✅ Extracted {len(content)} characters")
                    print(f"   ✅ Found {len(properties)} properties")
                    
                    # Show sample content
                    if content:
                        sample = content[:200] + "..." if len(content) > 200 else content
                        print(f"\n   Sample content:")
                        print(f"   {sample}")
                    
                    # Show properties
                    if properties:
                        print(f"\n   Properties:")
                        for key, value in list(properties.items())[:5]:
                            print(f"   - {key}: {value}")
            
            # Test monitoring setup
            if databases:
                print(f"\n🔄 Testing Monitoring Setup:")
                
                first_db_id = databases[0]["id"]
                await sensor.monitor_database(first_db_id)
                
                # Check for changes once
                changes = await sensor.check_for_changes()
                
                print(f"   ✅ Monitoring configured")
                print(f"   📊 Initial scan found {len(changes)} documents")
                
                if changes:
                    print(f"\n   Sample documents:")
                    for change in changes[:3]:
                        print(f"   - {change['title']}")
                        print(f"     Type: {change['event_type']}")
                        print(f"     Content: {len(change['content'])} chars")
                        print(f"     RID: {change['rid']}")
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'=' * 60}")
    print("✅ Notion sensor test complete!")


async def test_specific_database(database_id: str):
    """Test a specific database by ID"""
    
    notion_token = os.getenv('NOTION_API_KEY')
    
    async with NotionKOISensor(notion_token=notion_token) as sensor:
        print(f"\n🎯 Testing specific database: {database_id}")
        
        # Get database info
        db_info = await sensor.get_database(database_id)
        if db_info:
            title = sensor.extract_text_from_rich_text(
                db_info.get("title", [])
            )
            print(f"   Database: {title}")
            
            # Query all pages
            pages = await sensor.query_database(database_id)
            print(f"   Found {len(pages)} pages")
            
            # Extract content from each page
            total_content = 0
            for page in pages:
                content = await sensor.get_page_content(page["id"])
                total_content += len(content)
                
                properties = sensor.extract_properties(page.get("properties", {}))
                title = "Untitled"
                for prop_name, prop_value in properties.items():
                    if prop_name.lower() in ["title", "name"]:
                        title = prop_value
                        break
                
                print(f"   - {title}: {len(content)} chars")
            
            print(f"\n   Total content: {total_content} characters")
        else:
            print(f"   ❌ Could not access database")


if __name__ == "__main__":
    # Check for specific database ID argument
    if len(sys.argv) > 1:
        database_id = sys.argv[1]
        asyncio.run(test_specific_database(database_id))
    else:
        asyncio.run(test_notion_sensor())