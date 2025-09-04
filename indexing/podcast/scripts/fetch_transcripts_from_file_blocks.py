#!/usr/bin/env python3
"""
Fetch transcripts from Notion file blocks using the proper signed URLs
"""

import httpx
import json
import asyncio
import re
from pathlib import Path
from datetime import datetime
from loguru import logger
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))

class NotionFileTranscriptFetcher:
    def __init__(self):
        self.storage_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
        self.api_endpoint = "https://www.notion.so/api/v3/getSignedFileUrls"
        self.page_endpoint = "https://www.notion.so/api/v3/loadPageChunk"
    
    def extract_page_id(self, url: str) -> tuple:
        """Extract and format page ID from URL"""
        match = re.search(r'-([a-f0-9]{32})', url)
        if match:
            page_id = match.group(1)
            formatted_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"
            return page_id, formatted_id
        return None, None
    
    async def get_page_file_ids(self, url: str, client: httpx.AsyncClient) -> dict:
        """Get file IDs from the page"""
        page_id, formatted_id = self.extract_page_id(url)
        if not formatted_id:
            return None
        
        payload = {
            "pageId": formatted_id,
            "limit": 100,
            "cursor": {"stack": []},
            "chunkNumber": 0,
            "verticalColumns": False
        }
        
        try:
            response = await client.post(
                self.page_endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Extract file IDs and blocks
                file_ids = []
                block_ids = []
                
                if 'recordMap' in data and 'block' in data['recordMap']:
                    for block_id, block_data in data['recordMap']['block'].items():
                        if 'value' in block_data:
                            value = block_data['value']
                            
                            # Look for file blocks
                            if value.get('type') == 'file':
                                file_ids.append(block_id)
                                block_ids.append(block_id)
                            
                            # Look for file_ids in any block
                            if 'file_ids' in value:
                                for fid in value['file_ids']:
                                    if fid not in file_ids:
                                        file_ids.append(fid)
                            
                            # Look in properties for file references
                            if 'properties' in value and 'source' in value['properties']:
                                source = value['properties']['source']
                                if isinstance(source, list) and len(source) > 0:
                                    if isinstance(source[0], list) and len(source[0]) > 1:
                                        # Format: [["url"], [["type", "file"], ["file_id", "xxx"]]]
                                        if len(source[0]) > 1 and isinstance(source[0][1], list):
                                            for item in source[0][1]:
                                                if len(item) == 2 and item[0] == "file_id":
                                                    file_ids.append(item[1])
                
                return {
                    'page_id': formatted_id,
                    'file_ids': file_ids,
                    'block_ids': block_ids,
                    'space_id': data['recordMap']['block'].get(formatted_id, {}).get('value', {}).get('space_id', 'f5b9e671-9ada-4109-b3b5-07cc02a1ae8e')
                }
            
        except Exception as e:
            logger.error(f"Error getting file IDs: {e}")
        
        return None
    
    async def get_signed_urls(self, file_ids: list, page_id: str, space_id: str, client: httpx.AsyncClient) -> list:
        """Get signed URLs for file IDs"""
        if not file_ids:
            return []
        
        # Prepare request for signed URLs
        urls = []
        for file_id in file_ids:
            urls.append({
                "url": f"https://s3.us-west-2.amazonaws.com/secure.notion-static.com/{space_id}/{file_id}/placeholder.txt",
                "permissionRecord": {
                    "table": "block",
                    "id": page_id
                }
            })
        
        payload = {"urls": urls}
        
        try:
            response = await client.post(
                self.api_endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get('signedUrls', [])
            else:
                logger.error(f"Failed to get signed URLs: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error getting signed URLs: {e}")
        
        return []
    
    async def fetch_file_content(self, url: str, client: httpx.AsyncClient) -> str:
        """Fetch content from a signed URL"""
        try:
            logger.info(f"Fetching file content...")
            response = await client.get(url, timeout=60)
            if response.status_code == 200:
                content = response.text
                logger.success(f"Got {len(content)} chars")
                return content
            else:
                logger.warning(f"Failed to fetch: {response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching file: {e}")
        return None
    
    async def process_episode(self, episode_num: int, url: str, guest: str, client: httpx.AsyncClient):
        """Process a single episode"""
        logger.info(f"\n{'='*60}")
        logger.info(f"Episode {episode_num}: {guest}")
        
        # Get file IDs from the page
        file_info = await self.get_page_file_ids(url, client)
        if not file_info:
            logger.error("Could not get file IDs")
            return
        
        logger.info(f"Found {len(file_info['file_ids'])} file IDs")
        
        if not file_info['file_ids']:
            logger.warning("No file IDs found")
            return
        
        # Get signed URLs
        signed_urls = await self.get_signed_urls(
            file_info['file_ids'], 
            file_info['page_id'],
            file_info['space_id'],
            client
        )
        
        logger.info(f"Got {len(signed_urls)} signed URLs")
        
        # Debug: show what we got
        for i, url in enumerate(signed_urls[:3]):
            logger.info(f"URL {i}: {url}")
        
        # Try to fetch transcript files
        full_transcript = ""
        for signed_url in signed_urls:
            if signed_url:  # Check if URL is not None
                logger.info(f"Checking URL: {signed_url[:100]}...")
                if 'otter' in signed_url.lower() or 'transcript' in signed_url.lower() or '.txt' in signed_url.lower():
                    content = await self.fetch_file_content(signed_url, client)
                    if content and len(content) > 1000:
                        full_transcript = content
                        break
        
        # If no transcript found in specific files, try all files
        if not full_transcript:
            for signed_url in signed_urls:
                if signed_url:  # Check if URL is not None
                    content = await self.fetch_file_content(signed_url, client)
                    if content and len(content) > 1000 and not content.startswith('<!DOCTYPE'):
                        full_transcript = content
                        break
        
        if full_transcript:
            # Update the episode file
            filename = self.storage_path / f"episode_{episode_num:03d}_complete.json"
            
            # Load existing or create new
            if filename.exists():
                with open(filename, 'r') as f:
                    doc = json.load(f)
            else:
                doc = {
                    "id": f"podcast_episode_{episode_num:03d}",
                    "source": "notion:transcripts",
                    "source_type": "notion",
                    "url": url,
                    "title": f"Planetary Regeneration Podcast Episode {episode_num}: {guest}",
                    "metadata": {}
                }
            
            # Update content
            doc['content'] = full_transcript
            doc['transcript'] = full_transcript
            doc['metadata'].update({
                "episode_number": episode_num,
                "guest_name": guest,
                "has_transcript": True,
                "transcript_source": "notion_file_attachment",
                "fixed_at": datetime.now().isoformat()
            })
            
            # Save
            with open(filename, 'w') as f:
                json.dump(doc, f, indent=2)
            
            logger.success(f"✅ Saved transcript: {len(full_transcript)} chars")
        else:
            logger.warning("❌ No transcript content found")
    
    async def run(self):
        """Process problematic episodes"""
        episodes_to_fix = [
            {"num": 70, "guest": "Bayo Akomolafe", "url": "https://regennetwork.notion.site/070-Bayo-Akomolafe-Rituals-of-Incompleteness-in-the-Age-of-AI-1e425b77eda1809cbd4ad388931662d9"},
            {"num": 67, "guest": "Josiah Hunt", "url": "https://regennetwork.notion.site/067-Josiah-Hunt-Pacific-Biochar-040b675477fa4f03974fb5699f91a8d0"},
            {"num": 37, "guest": "Frank Van Gansbeke", "url": "https://regennetwork.notion.site/037-Frank-Van-Gansbeke-A-Bold-Proposal-for-IMF-Backed-Stable-Currency-for-Climate-Action-9d88864912d74797bcdcc3e8e3c87187"},
            {"num": 46, "guest": "Genevieve Guenther", "url": "https://regennetwork.notion.site/046-Genevieve-Guenther-Climate-Communication-in-Dark-Times-11e29f3e8b204bb883d0b49e39e95f67"},
        ]
        
        async with httpx.AsyncClient() as client:
            for episode in episodes_to_fix:
                await self.process_episode(episode['num'], episode['url'], episode['guest'], client)
                await asyncio.sleep(2)  # Rate limiting

async def main():
    fetcher = NotionFileTranscriptFetcher()
    await fetcher.run()

if __name__ == "__main__":
    asyncio.run(main())