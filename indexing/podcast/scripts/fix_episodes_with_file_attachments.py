#!/usr/bin/env python3
"""
Fix episodes by properly extracting file attachment URLs from Notion API v3 response
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

class NotionFileAttachmentFetcher:
    def __init__(self):
        self.storage_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.api_endpoint = "https://www.notion.so/api/v3/loadPageChunk"
    
    def extract_page_id(self, url: str) -> tuple:
        """Extract and format page ID from URL"""
        match = re.search(r'-([a-f0-9]{32})', url)
        if match:
            page_id = match.group(1)
            formatted_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"
            return page_id, formatted_id
        return None, None
    
    async def fetch_notion_page_full(self, url: str, episode_num: int, client: httpx.AsyncClient) -> dict:
        """Fetch full Notion page data with all blocks"""
        page_id, formatted_id = self.extract_page_id(url)
        if not formatted_id:
            logger.error(f"Could not extract page ID from {url}")
            return None
        
        logger.info(f"Fetching episode {episode_num} with ID {formatted_id[:8]}...")
        
        # Try to get more data by requesting the full page
        payload = {
            "pageId": formatted_id,
            "limit": 1000,  # Higher limit
            "cursor": {"stack": []},
            "chunkNumber": 0,
            "verticalColumns": False
        }
        
        try:
            response = await client.post(
                self.api_endpoint,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                },
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Status {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error: {e}")
            return None
    
    def extract_all_content(self, data: dict) -> dict:
        """Extract all content including file URLs from API response"""
        result = {
            'text_content': [],
            'file_urls': [],
            'all_urls': [],
            'raw_json': json.dumps(data)[:5000]  # Keep sample for debugging
        }
        
        if not data:
            return result
        
        # Method 1: Search entire JSON for file URLs
        json_str = json.dumps(data)
        
        # Look for file.notion.so URLs
        file_url_pattern = r'(https://[^"\'\\s]*file\.notion\.so[^"\'\\s]*)'
        file_urls = re.findall(file_url_pattern, json_str)
        result['file_urls'].extend(file_urls)
        
        # Look for any URLs that might be transcripts
        all_url_pattern = r'(https://[^"\'\\s]+(?:otter|transcript|\.txt|\.pdf)[^"\'\\s]*)'
        all_urls = re.findall(all_url_pattern, json_str, re.IGNORECASE)
        result['all_urls'].extend(all_urls)
        
        # Method 2: Navigate the structure
        if 'recordMap' in data:
            record_map = data['recordMap']
            
            # Check blocks
            if 'block' in record_map:
                for block_id, block_data in record_map['block'].items():
                    if 'value' in block_data:
                        value = block_data['value']
                        
                        # Extract text
                        if 'properties' in value:
                            props = value['properties']
                            for field in ['title', 'text', 'caption']:
                                if field in props:
                                    for text_item in props[field]:
                                        if isinstance(text_item, list) and len(text_item) > 0:
                                            result['text_content'].append(str(text_item[0]))
                        
                        # Look for file_ids
                        if 'file_ids' in value:
                            logger.info(f"Found file_ids: {value['file_ids']}")
                        
                        # Check format for URLs
                        if 'format' in value:
                            format_str = json.dumps(value['format'])
                            urls = re.findall(r'(https://[^"\'\\s]+)', format_str)
                            result['all_urls'].extend(urls)
            
            # Check files section
            if 'file' in record_map:
                logger.info(f"Found 'file' section with {len(record_map['file'])} items")
                for file_id, file_data in record_map['file'].items():
                    logger.info(f"File {file_id}: {json.dumps(file_data)[:200]}")
                    if 'value' in file_data:
                        file_value = file_data['value']
                        if 'url' in file_value:
                            result['file_urls'].append(file_value['url'])
                        # Check all fields for URLs
                        file_str = json.dumps(file_value)
                        urls = re.findall(r'(https://[^"\'\\s]+)', file_str)
                        result['all_urls'].extend(urls)
        
        # Deduplicate
        result['file_urls'] = list(set(result['file_urls']))
        result['all_urls'] = list(set(result['all_urls']))
        
        return result
    
    async def fetch_file_content(self, url: str, client: httpx.AsyncClient) -> str:
        """Fetch content from a file URL"""
        try:
            logger.info(f"Fetching file from: {url[:100]}...")
            response = await client.get(url, timeout=30, follow_redirects=True)
            if response.status_code == 200:
                content = response.text
                logger.success(f"Got {len(content)} chars from file")
                return content
            else:
                logger.warning(f"Could not fetch file: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching file: {e}")
            return None
    
    async def process_episode(self, episode_num: int, url: str, guest: str, client: httpx.AsyncClient):
        """Process a single episode"""
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing episode {episode_num}: {guest}")
        
        # Fetch page data
        page_data = await self.fetch_notion_page_full(url, episode_num, client)
        if not page_data:
            logger.error(f"Could not fetch page data")
            return
        
        # Extract content
        content = self.extract_all_content(page_data)
        
        logger.info(f"Found:")
        logger.info(f"  - Text content: {len(' '.join(content['text_content']))} chars")
        logger.info(f"  - File URLs: {len(content['file_urls'])}")
        logger.info(f"  - All URLs: {len(content['all_urls'])}")
        
        if content['file_urls']:
            logger.info(f"File URLs found:")
            for url in content['file_urls'][:3]:  # Show first 3
                logger.info(f"  - {url[:100]}...")
        
        if content['all_urls']:
            logger.info(f"All URLs found:")
            for url in content['all_urls'][:5]:  # Show first 5
                logger.info(f"  - {url[:100]}...")
        
        # Try to fetch transcript files
        full_transcript = ""
        
        # First try file.notion.so URLs
        for file_url in content['file_urls']:
            if 'otter' in file_url.lower() or 'transcript' in file_url.lower() or '.txt' in file_url.lower():
                file_content = await self.fetch_file_content(file_url, client)
                if file_content and len(file_content) > 1000:
                    full_transcript = file_content
                    break
        
        # If no transcript yet, try other URLs
        if not full_transcript:
            for url in content['all_urls']:
                if 'otter' in url.lower() or 'transcript' in url.lower() or '.txt' in url.lower():
                    file_content = await self.fetch_file_content(url, client)
                    if file_content and len(file_content) > 1000:
                        full_transcript = file_content
                        break
        
        # If still no transcript, use inline text
        if not full_transcript:
            full_transcript = '\n'.join(content['text_content'])
        
        # Update the episode file
        filename = self.storage_path / f"episode_{episode_num:03d}_complete.json"
        
        # Load existing data
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
        
        # Update with new content
        doc['content'] = full_transcript
        doc['transcript'] = full_transcript
        doc['metadata'].update({
            "episode_number": episode_num,
            "guest_name": guest,
            "has_transcript": len(full_transcript) > 1000,
            "transcript_source": "notion_api_v3_with_files",
            "file_urls_found": len(content['file_urls']),
            "all_urls_found": len(content['all_urls']),
            "fixed_at": datetime.now().isoformat()
        })
        
        # Save
        with open(filename, 'w') as f:
            json.dump(doc, f, indent=2)
        
        logger.info(f"Saved episode {episode_num}: {len(full_transcript)} chars")
        
        # Also save debug info
        debug_file = self.storage_path / f"episode_{episode_num:03d}_debug.json"
        with open(debug_file, 'w') as f:
            json.dump({
                "file_urls": content['file_urls'],
                "all_urls": content['all_urls'],
                "text_preview": ' '.join(content['text_content'])[:500],
                "raw_json_sample": content['raw_json']
            }, f, indent=2)
    
    async def run(self):
        """Process problematic episodes"""
        # Episodes that need fixing (those with stub content)
        episodes_to_fix = [
            {"num": 37, "guest": "Frank Van Gansbeke", "url": "https://regennetwork.notion.site/037-Frank-Van-Gansbeke-A-Bold-Proposal-for-IMF-Backed-Stable-Currency-for-Climate-Action-9d88864912d74797bcdcc3e8e3c87187"},
            {"num": 46, "guest": "Genevieve Guenther", "url": "https://regennetwork.notion.site/046-Genevieve-Guenther-Climate-Communication-in-Dark-Times-11e29f3e8b204bb883d0b49e39e95f67"},
            {"num": 64, "guest": "Carol Sanford", "url": "https://regennetwork.notion.site/064-Carol-Sanford-Round-2-Seeing-Life-from-Life-s-Perspective-f7d1b6c95e3f422f9e0a582bb4b5cf84"},
            {"num": 65, "guest": "Jem Bendell", "url": "https://regennetwork.notion.site/065-Jem-Bendell-Deep-Adaptation-Post-Climate-Catastrophe-Reality-cc628e09fb134c5bb2c97a87cc03e3e9"},
            {"num": 66, "guest": "Paul Stamets", "url": "https://regennetwork.notion.site/066-Paul-Stamets-Mycoremediation-for-the-Planet-9c2f18903cb94e918b67e959c33cc7f9"},
            {"num": 67, "guest": "Josiah Hunt", "url": "https://regennetwork.notion.site/067-Josiah-Hunt-Pacific-Biochar-040b675477fa4f03974fb5699f91a8d0"},
            {"num": 68, "guest": "David Shearer", "url": "https://regennetwork.notion.site/068-David-Shearer-Bioregional-Regeneration-How-We-The-Trees-Wants-to-Regenerate-the-Earth-2bb44bd967fb42bdbe88c1fabe8a4c5d"},
            {"num": 69, "guest": "Mark Plotkin", "url": "https://regennetwork.notion.site/069-Mark-Plotkin-The-Amazon-Sacred-Headwaters-Initiative-2aaad76c6fb048e9bfaaf825c95ba52f"},
            {"num": 70, "guest": "Bayo Akomolafe", "url": "https://regennetwork.notion.site/070-Bayo-Akomolafe-Rituals-of-Incompleteness-in-the-Age-of-AI-1e425b77eda1809cbd4ad388931662d9"}
        ]
        
        async with httpx.AsyncClient() as client:
            for episode in episodes_to_fix:
                await self.process_episode(episode['num'], episode['url'], episode['guest'], client)
                await asyncio.sleep(3)  # Rate limiting
        
        logger.success("\n✅ Finished processing episodes")

async def main():
    fetcher = NotionFileAttachmentFetcher()
    await fetcher.run()

if __name__ == "__main__":
    asyncio.run(main())