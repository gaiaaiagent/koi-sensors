#!/usr/bin/env python3
"""
KOI Notion Sensor - Real-time monitoring for Notion databases and pages
Integrates with Notion API to monitor workspace content changes
"""

import asyncio
import aiohttp
import json
import hashlib
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta
from pathlib import Path
import os
from urllib.parse import urlparse

# KOI Protocol imports
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID, ORN
from koi_protocol.core.bundle_system import Bundle, document_to_bundle


class NotionPageRID(ORN):
    """Notion page RID: orn:notion.page:workspace/page_id"""
    namespace = "notion.page"
    
    def __init__(self, workspace: str, page_id: str):
        self.workspace = workspace
        self.page_id = page_id.replace('-', '')  # Remove hyphens from Notion IDs
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.workspace}/{self.page_id}"


class NotionDatabaseRID(ORN):
    """Notion database RID: orn:notion.database:workspace/database_id"""
    namespace = "notion.database"
    
    def __init__(self, workspace: str, database_id: str):
        self.workspace = workspace
        self.database_id = database_id.replace('-', '')
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.workspace}/{self.database_id}"


class NotionKOISensor:
    """KOI-compliant Notion monitoring sensor"""
    
    NOTION_API_VERSION = "2022-06-28"
    NOTION_API_BASE = "https://api.notion.com/v1"
    
    def __init__(self, 
                 node_id: str = "koi-notion-sensor",
                 coordinator_url: str = "http://localhost:8200",
                 notion_token: str = None):
        self.node_id = node_id
        self.coordinator_url = coordinator_url
        
        # Use provided token or get from environment
        self.notion_token = notion_token or os.getenv('NOTION_INTEGRATION_SECRET')
        if not self.notion_token:
            raise ValueError("Notion integration secret required. Set NOTION_INTEGRATION_SECRET env var.")
        
        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name="notion-sensor",
            coordinator_url=coordinator_url,
            poll_interval=30
        )
        
        # Monitoring state
        self.monitored_databases: Dict[str, Dict[str, Any]] = {}
        self.monitored_pages: Dict[str, Dict[str, Any]] = {}
        self.content_hashes: Dict[str, str] = {}  # page_id -> content hash
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Workspace identifier (extracted from pages/databases)
        self.workspace_id = "regen"  # Default workspace name
        
        print(f"📝 KOI Notion Sensor initialized")
        print(f"   Node ID: {self.node_id}")
        print(f"   Coordinator: {self.coordinator_url}")
        print(f"   API Version: {self.NOTION_API_VERSION}")
    
    async def __aenter__(self):
        """Async context manager entry"""
        headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Notion-Version": self.NOTION_API_VERSION,
            "Content-Type": "application/json"
        }
        self.session = aiohttp.ClientSession(headers=headers)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    async def search_workspace(self, query: str = None, filter_type: str = None) -> List[Dict]:
        """
        Search the Notion workspace for pages and databases
        
        Args:
            query: Optional search query
            filter_type: 'page' or 'database' to filter results
        """
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        search_params = {}
        if query:
            search_params["query"] = query
        if filter_type:
            search_params["filter"] = {"property": "object", "value": filter_type}
        
        try:
            async with self.session.post(
                f"{self.NOTION_API_BASE}/search",
                json=search_params
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("results", [])
                else:
                    error = await response.text()
                    print(f"❌ Search failed: {response.status} - {error}")
                    return []
        except Exception as e:
            print(f"❌ Error searching workspace: {e}")
            return []
    
    async def get_database(self, database_id: str) -> Optional[Dict]:
        """Get database metadata"""
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        try:
            async with self.session.get(
                f"{self.NOTION_API_BASE}/databases/{database_id}"
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error = await response.text()
                    print(f"❌ Failed to get database {database_id}: {error}")
                    return None
        except Exception as e:
            print(f"❌ Error getting database: {e}")
            return None
    
    async def query_database(self, database_id: str, 
                           filter_obj: Dict = None,
                           sorts: List[Dict] = None,
                           page_size: int = 100) -> List[Dict]:
        """
        Query a Notion database for pages
        
        Args:
            database_id: The database ID to query
            filter_obj: Optional filter object
            sorts: Optional sort configuration
            page_size: Number of results per page (max 100)
        """
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        query_params = {"page_size": min(page_size, 100)}
        if filter_obj:
            query_params["filter"] = filter_obj
        if sorts:
            query_params["sorts"] = sorts
        
        all_results = []
        has_more = True
        next_cursor = None
        
        while has_more:
            if next_cursor:
                query_params["start_cursor"] = next_cursor
            
            try:
                async with self.session.post(
                    f"{self.NOTION_API_BASE}/databases/{database_id}/query",
                    json=query_params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        all_results.extend(data.get("results", []))
                        has_more = data.get("has_more", False)
                        next_cursor = data.get("next_cursor")
                    else:
                        error = await response.text()
                        print(f"❌ Failed to query database: {error}")
                        break
            except Exception as e:
                print(f"❌ Error querying database: {e}")
                break
        
        return all_results
    
    async def get_page(self, page_id: str) -> Optional[Dict]:
        """Get page metadata and properties"""
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        try:
            async with self.session.get(
                f"{self.NOTION_API_BASE}/pages/{page_id}"
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error = await response.text()
                    print(f"❌ Failed to get page {page_id}: {error}")
                    return None
        except Exception as e:
            print(f"❌ Error getting page: {e}")
            return None
    
    async def get_page_content(self, page_id: str) -> str:
        """
        Get the full content of a page as text
        
        Args:
            page_id: The page ID to retrieve content from
        """
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        # Get blocks from the page
        blocks = await self.get_blocks(page_id)
        
        # Convert blocks to text
        content_parts = []
        for block in blocks:
            text = self.extract_text_from_block(block)
            if text:
                content_parts.append(text)
        
        return "\n\n".join(content_parts)
    
    async def get_blocks(self, block_id: str, page_size: int = 100) -> List[Dict]:
        """Get all blocks (content) from a page or block"""
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        all_blocks = []
        has_more = True
        next_cursor = None
        
        while has_more:
            params = {"page_size": page_size}
            if next_cursor:
                params["start_cursor"] = next_cursor
            
            try:
                async with self.session.get(
                    f"{self.NOTION_API_BASE}/blocks/{block_id}/children",
                    params=params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        blocks = data.get("results", [])
                        
                        # Recursively get children for certain block types
                        for block in blocks:
                            all_blocks.append(block)
                            
                            # If block has children, recursively get them
                            if block.get("has_children", False):
                                child_blocks = await self.get_blocks(block["id"])
                                all_blocks.extend(child_blocks)
                        
                        has_more = data.get("has_more", False)
                        next_cursor = data.get("next_cursor")
                    else:
                        error = await response.text()
                        print(f"❌ Failed to get blocks: {error}")
                        break
            except Exception as e:
                print(f"❌ Error getting blocks: {e}")
                break
        
        return all_blocks
    
    def extract_text_from_block(self, block: Dict) -> Optional[str]:
        """Extract text content from a Notion block"""
        block_type = block.get("type")
        if not block_type:
            return None
        
        block_data = block.get(block_type, {})
        
        # Handle text-based blocks
        text_types = [
            "paragraph", "heading_1", "heading_2", "heading_3",
            "bulleted_list_item", "numbered_list_item", "to_do",
            "toggle", "quote", "callout"
        ]
        
        if block_type in text_types:
            rich_text = block_data.get("rich_text", [])
            return self.extract_text_from_rich_text(rich_text)
        
        # Handle code blocks
        elif block_type == "code":
            rich_text = block_data.get("rich_text", [])
            language = block_data.get("language", "")
            code = self.extract_text_from_rich_text(rich_text)
            return f"```{language}\n{code}\n```" if code else None
        
        # Handle tables
        elif block_type == "table":
            return "[Table]"
        
        # Handle dividers
        elif block_type == "divider":
            return "---"
        
        return None
    
    def extract_text_from_rich_text(self, rich_text: List[Dict]) -> str:
        """Extract plain text from Notion rich text array"""
        text_parts = []
        for text_obj in rich_text:
            if text_obj.get("type") == "text":
                text_parts.append(text_obj.get("text", {}).get("content", ""))
        return "".join(text_parts)
    
    def extract_properties(self, properties: Dict) -> Dict[str, Any]:
        """Extract key-value pairs from Notion properties"""
        extracted = {}
        
        for prop_name, prop_data in properties.items():
            prop_type = prop_data.get("type")
            
            if prop_type == "title":
                title_text = self.extract_text_from_rich_text(
                    prop_data.get("title", [])
                )
                if title_text:
                    extracted[prop_name] = title_text
            
            elif prop_type == "rich_text":
                text = self.extract_text_from_rich_text(
                    prop_data.get("rich_text", [])
                )
                if text:
                    extracted[prop_name] = text
            
            elif prop_type == "number":
                extracted[prop_name] = prop_data.get("number")
            
            elif prop_type == "select":
                select = prop_data.get("select")
                if select:
                    extracted[prop_name] = select.get("name")
            
            elif prop_type == "multi_select":
                options = prop_data.get("multi_select", [])
                if options:
                    extracted[prop_name] = [opt.get("name") for opt in options]
            
            elif prop_type == "date":
                date_obj = prop_data.get("date")
                if date_obj:
                    extracted[prop_name] = date_obj.get("start")
            
            elif prop_type == "checkbox":
                extracted[prop_name] = prop_data.get("checkbox", False)
            
            elif prop_type == "url":
                extracted[prop_name] = prop_data.get("url")
            
            elif prop_type == "email":
                extracted[prop_name] = prop_data.get("email")
            
            elif prop_type == "phone_number":
                extracted[prop_name] = prop_data.get("phone_number")
        
        return extracted
    
    async def monitor_database(self, database_id: str, 
                              check_interval: int = 3600,
                              priority: str = "medium"):
        """Add a database to monitor for changes"""
        # Get database info
        db_info = await self.get_database(database_id)
        if not db_info:
            print(f"❌ Could not add database {database_id} to monitoring")
            return
        
        title = self.extract_text_from_rich_text(
            db_info.get("title", [])
        ) or f"Database {database_id[:8]}"
        
        self.monitored_databases[database_id] = {
            "title": title,
            "check_interval": check_interval,
            "priority": priority,
            "last_checked": None,
            "url": db_info.get("url", "")
        }
        
        print(f"✅ Monitoring database: {title}")
    
    async def check_for_changes(self) -> List[Dict]:
        """Check all monitored items for changes"""
        changes = []
        now = datetime.now(timezone.utc)
        
        # Check databases
        for db_id, db_info in self.monitored_databases.items():
            last_checked = db_info.get("last_checked")
            check_interval = timedelta(seconds=db_info["check_interval"])
            
            if not last_checked or (now - last_checked) > check_interval:
                print(f"🔍 Checking database: {db_info['title']}")
                
                # Query for recently modified pages
                filter_obj = None
                if last_checked:
                    # Get pages modified since last check
                    filter_obj = {
                        "timestamp": "last_edited_time",
                        "last_edited_time": {
                            "after": last_checked.isoformat()
                        }
                    }
                
                pages = await self.query_database(db_id, filter_obj=filter_obj)
                
                for page in pages:
                    page_id = page["id"]
                    content = await self.get_page_content(page_id)
                    
                    # Generate content hash
                    content_hash = hashlib.sha256(content.encode()).hexdigest()
                    
                    # Check if content changed
                    old_hash = self.content_hashes.get(page_id)
                    
                    if old_hash != content_hash:
                        event_type = "UPDATE" if old_hash else "NEW"
                        
                        # Extract properties
                        properties = self.extract_properties(page.get("properties", {}))
                        
                        # Get title from properties
                        title = None
                        for prop_name, prop_value in properties.items():
                            if prop_name.lower() in ["title", "name"]:
                                title = prop_value
                                break
                        
                        if not title:
                            title = f"Page {page_id[:8]}"
                        
                        # Extract Notion timestamps for publication date
                        created_time = page.get("created_time")
                        last_edited_time = page.get("last_edited_time")
                        
                        # Create change document
                        change = {
                            "event_type": event_type,
                            "source": "notion",
                            "rid": NotionPageRID(self.workspace_id, page_id).to_orn(),
                            "title": title,
                            "content": content,
                            "metadata": {
                                # Publication date metadata for Daily Curator
                                "published_at": created_time,  # Notion provides ISO format timestamps
                                "published_confidence": 0.85,  # Good confidence for API data
                                "last_modified": last_edited_time,
                                
                                # Original metadata
                                "database_id": db_id,
                                "database_title": db_info["title"],
                                "page_url": page.get("url", ""),
                                "created_time": created_time,
                                "last_edited_time": last_edited_time,
                                "properties": properties
                            }
                        }
                        
                        changes.append(change)
                        self.content_hashes[page_id] = content_hash
                        
                        print(f"   {'🆕' if event_type == 'NEW' else '🔄'} {title}")
                
                # Update last checked time
                self.monitored_databases[db_id]["last_checked"] = now
        
        return changes
    
    async def send_to_coordinator(self, changes: List[Dict]):
        """Send changes to KOI coordinator"""
        for change in changes:
            try:
                # Create bundle from document
                bundle = document_to_bundle(change)
                
                # Create KOI event
                event = {
                    "event_type": change["event_type"],
                    "source_sensor": self.node_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "bundle": bundle.to_dict()
                }
                
                # Send to coordinator
                await self.koi_node.emit_event(event)
                
                print(f"   ✅ Sent to coordinator: {change['rid']}")
                
            except Exception as e:
                print(f"   ❌ Failed to send event: {e}")
    
    async def run_monitoring_loop(self):
        """Main monitoring loop"""
        print(f"🚀 Starting Notion monitoring loop...")
        
        while True:
            try:
                # Check for changes
                changes = await self.check_for_changes()
                
                if changes:
                    print(f"📊 Found {len(changes)} changes")
                    await self.send_to_coordinator(changes)
                
                # Wait before next check
                await asyncio.sleep(60)  # Check every minute
                
            except Exception as e:
                print(f"❌ Error in monitoring loop: {e}")
                await asyncio.sleep(60)


async def main():
    """Main entry point for standalone testing"""
    import os
    from dotenv import load_dotenv
    
    # Load environment variables
    load_dotenv()
    
    # Get Notion token from environment or use provided one
    notion_token = os.getenv('NOTION_INTEGRATION_SECRET', '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')
    
    async with NotionKOISensor(notion_token=notion_token) as sensor:
        print("\n🔍 Searching Notion workspace...")
        
        # Search for all content
        all_items = await sensor.search_workspace()
        
        print(f"\n📊 Found {len(all_items)} items in workspace:")
        
        databases = []
        pages = []
        
        for item in all_items:
            if item["object"] == "database":
                databases.append(item)
                title = sensor.extract_text_from_rich_text(
                    item.get("title", [])
                ) or f"Database {item['id'][:8]}"
                print(f"   📁 Database: {title}")
            elif item["object"] == "page":
                pages.append(item)
                # Pages in search results don't have full properties
                print(f"   📄 Page: {item.get('url', item['id'][:8])}")
        
        print(f"\nSummary: {len(databases)} databases, {len(pages)} pages")
        
        # If databases found, monitor the first one as a test
        if databases:
            first_db = databases[0]
            db_id = first_db["id"]
            
            print(f"\n🎯 Testing with first database: {db_id}")
            
            # Add to monitoring
            await sensor.monitor_database(db_id)
            
            # Do one check
            changes = await sensor.check_for_changes()
            
            if changes:
                print(f"\n✅ Successfully collected {len(changes)} documents")
                for change in changes[:3]:  # Show first 3
                    print(f"   - {change['title']}: {len(change['content'])} chars")
            else:
                print("\n📝 No new content found (database may be empty or unchanged)")


if __name__ == "__main__":
    asyncio.run(main())