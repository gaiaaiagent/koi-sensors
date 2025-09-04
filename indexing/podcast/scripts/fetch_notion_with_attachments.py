#!/usr/bin/env python3
"""
Fetch Notion transcripts including embedded file attachments
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

class NotionTranscriptFetcher:
    def __init__(self):
        self.storage_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.links_file = Path(__file__).parent.parent / "storage" / "notion_transcripts" / "transcript_links.json"
        
        # Load transcript links
        with open(self.links_file, 'r') as f:
            self.transcript_links = json.load(f)
        
        self.api_endpoint = "https://www.notion.so/api/v3/loadPageChunk"
    
    def extract_page_id(self, url: str) -> tuple:
        """Extract and format page ID from URL"""
        match = re.search(r'-([a-f0-9]{32})', url)
        if match:
            page_id = match.group(1)
            formatted_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"
            return page_id, formatted_id
        return None, None
    
    async def fetch_notion_page(self, episode: dict, client: httpx.AsyncClient) -> dict:
        """Fetch Notion page data including metadata"""
        url = episode['url']
        episode_num = episode['episode_num']
        
        page_id, formatted_id = self.extract_page_id(url)
        if not formatted_id:
            logger.error(f"Could not extract page ID from {url}")
            return None
        
        logger.info(f"Fetching episode {episode_num} page data...")
        
        payload = {
            "pageId": formatted_id,
            "limit": 100,
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
                    "User-Agent": "Mozilla/5.0"
                },
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Episode {episode_num}: Status {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching episode {episode_num}: {e}")
            return None
    
    def extract_content_and_metadata(self, page_data: dict) -> dict:
        """Extract all content including file URLs, summary, and metadata"""
        result = {
            'inline_text': [],
            'file_urls': [],
            'summary': '',
            'streaming_links': [],
            'images': [],
            'metadata': {}
        }
        
        if not page_data or 'recordMap' not in page_data:
            return result
        
        record_map = page_data['recordMap']
        
        # Extract blocks
        if 'block' in record_map:
            for block_id, block_data in record_map['block'].items():
                if 'value' not in block_data:
                    continue
                    
                value = block_data['value']
                block_type = value.get('type', '')
                
                # Extract text content
                if 'properties' in value:
                    props = value['properties']
                    
                    # Text fields
                    for field in ['title', 'text', 'caption']:
                        if field in props:
                            for text_item in props[field]:
                                if isinstance(text_item, list) and len(text_item) > 0:
                                    text = str(text_item[0])
                                    result['inline_text'].append(text)
                                    
                                    # Check for streaming links
                                    if any(platform in text.lower() for platform in ['spotify', 'apple', 'soundcloud', 'stitcher']):
                                        result['streaming_links'].append(text)
                                    
                                    # Check for summary
                                    if 'summary' in text.lower() or block_type == 'callout':
                                        result['summary'] += text + '\n'
                    
                    # File attachments
                    if 'file_ids' in props:
                        for file_id in props['file_ids']:
                            if isinstance(file_id, list) and len(file_id) > 0:
                                file_id_str = file_id[0]
                                # Look up file info
                                if 'file' in record_map and file_id_str in record_map['file']:
                                    file_info = record_map['file'][file_id_str]['value']
                                    if 'url' in file_info:
                                        file_url = file_info['url']
                                        result['file_urls'].append({
                                            'url': file_url,
                                            'name': file_info.get('name', 'transcript.txt'),
                                            'type': file_info.get('type', 'text')
                                        })
                
                # Images
                if block_type == 'image' and 'format' in value:
                    if 'display_source' in value['format']:
                        result['images'].append(value['format']['display_source'])
        
        # Extract files from the file map
        if 'file' in record_map:
            for file_id, file_data in record_map['file'].items():
                if 'value' in file_data and 'url' in file_data['value']:
                    file_info = file_data['value']
                    file_url = file_info['url']
                    
                    # Check if it's a transcript file (txt, pdf, etc)
                    if any(ext in file_url.lower() for ext in ['.txt', '.pdf', 'otter', 'transcript']):
                        result['file_urls'].append({
                            'url': file_url,
                            'name': file_info.get('name', 'transcript.txt'),
                            'type': file_info.get('type', 'text')
                        })
        
        return result
    
    async def fetch_file_content(self, file_info: dict, client: httpx.AsyncClient) -> str:
        """Fetch content from a file URL"""
        try:
            logger.info(f"Fetching file: {file_info['name']}")
            response = await client.get(file_info['url'], timeout=30)
            if response.status_code == 200:
                content = response.text
                logger.success(f"Got {len(content)} chars from {file_info['name']}")
                return content
            else:
                logger.warning(f"Could not fetch file: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching file: {e}")
            return None
    
    async def process_episode(self, episode: dict, client: httpx.AsyncClient):
        """Process a single episode - fetch page and attachments"""
        episode_num = episode['episode_num']
        
        # Fetch Notion page
        page_data = await self.fetch_notion_page(episode, client)
        if not page_data:
            return None
        
        # Extract content and metadata
        content_data = self.extract_content_and_metadata(page_data)
        
        logger.info(f"Episode {episode_num}:")
        logger.info(f"  - Inline text: {len(' '.join(content_data['inline_text']))} chars")
        logger.info(f"  - File attachments: {len(content_data['file_urls'])}")
        logger.info(f"  - Streaming links: {len(content_data['streaming_links'])}")
        logger.info(f"  - Images: {len(content_data['images'])}")
        
        # Fetch transcript files
        full_transcript = ""
        for file_info in content_data['file_urls']:
            file_content = await self.fetch_file_content(file_info, client)
            if file_content:
                full_transcript += f"\n\n--- {file_info['name']} ---\n\n{file_content}"
        
        # Combine all content
        if not full_transcript:
            # Use inline text if no file attachments
            full_transcript = '\n'.join(content_data['inline_text'])
        
        # Create document
        doc = {
            "id": f"podcast_episode_{episode_num:03d}",
            "source": "notion:transcripts",
            "source_type": "notion",
            "url": episode.get('url', ''),
            "title": f"Planetary Regeneration Podcast Episode {episode_num}: {episode.get('guest', '')}",
            "content": full_transcript,
            "transcript": full_transcript,
            "metadata": {
                "episode_number": episode_num,
                "guest_name": episode.get('guest', ''),
                "has_transcript": len(full_transcript) > 1000,
                "transcript_source": "notion_with_attachments",
                "summary": content_data['summary'],
                "streaming_links": content_data['streaming_links'],
                "has_images": len(content_data['images']) > 0,
                "file_attachments": len(content_data['file_urls']),
                "fetched_at": datetime.now().isoformat()
            }
        }
        
        # Save
        filename = self.storage_path / f"episode_{episode_num:03d}_complete.json"
        with open(filename, 'w') as f:
            json.dump(doc, f, indent=2)
        
        logger.info(f"Saved episode {episode_num}: {len(full_transcript)} chars total")
        return doc
    
    async def run(self):
        """Process episodes that need fixing"""
        # Focus on episodes with short content
        episodes_to_check = [
            {"episode_num": 37, "guest": "Frank Van Gansbeke", "url": "https://regennetwork.notion.site/037-Frank-Van-Gansbeke-A-Bold-Proposal-for-IMF-Backed-Stable-Currency-for-Climate-Action-9d88864912d74797bcdcc3e8e3c87187?pvs=25"},
            {"episode_num": 46, "guest": "Genevieve Guenther", "url": "https://regennetwork.notion.site/046-Genevieve-Guenther-Climate-Communication-in-Dark-Times-11e29f3e8b204bb883d0b49e39e95f67?pvs=25"},
            {"episode_num": 64, "guest": "Carol Sanford", "url": "https://regennetwork.notion.site/064-Carol-Sanford-Round-2-Seeing-Life-from-Life-s-Perspective-f7d1b6c95e3f422f9e0a582bb4b5cf84?pvs=25"},
            {"episode_num": 65, "guest": "Jim Bendell", "url": "https://regennetwork.notion.site/065-Jem-Bendell-Deep-Adaptation-Post-Climate-Catastrophe-Reality-cc628e09fb134c5bb2c97a87cc03e3e9?pvs=25"},
            {"episode_num": 66, "guest": "Paul Stamets", "url": "https://regennetwork.notion.site/066-Paul-Stamets-Mycoremediation-for-the-Planet-9c2f18903cb94e918b67e959c33cc7f9?pvs=25"},
            {"episode_num": 67, "guest": "Josiah Hunt", "url": "https://regennetwork.notion.site/067-Josiah-Hunt-Pacific-Biochar-040b675477fa4f03974fb5699f91a8d0?pvs=25"},
            {"episode_num": 68, "guest": "David Shearer", "url": "https://regennetwork.notion.site/068-David-Shearer-Bioregional-Regeneration-How-We-The-Trees-Wants-to-Regenerate-the-Earth-2bb44bd967fb42bdbe88c1fabe8a4c5d?pvs=25"},
            {"episode_num": 69, "guest": "Mark Plotkin", "url": "https://regennetwork.notion.site/069-Mark-Plotkin-The-Amazon-Sacred-Headwaters-Initiative-2aaad76c6fb048e9bfaaf825c95ba52f?pvs=25"},
            {"episode_num": 70, "guest": "Bayo Akomolafe", "url": "https://regennetwork.notion.site/070-Bayo-Akomolafe-Rituals-of-Incompleteness-in-the-Age-of-AI-1e425b77eda1809cbd4ad388931662d9?pvs=25"}
        ]
        
        async with httpx.AsyncClient() as client:
            for i, episode in enumerate(episodes_to_check):
                logger.info(f"\n{'='*60}")
                logger.info(f"Processing episode {episode['episode_num']}: {episode['guest']}")
                
                await self.process_episode(episode, client)
                
                # Rate limiting
                if i < len(episodes_to_check) - 1:
                    await asyncio.sleep(3)
        
        logger.success("\n✅ Finished processing episodes with attachments")

async def main():
    fetcher = NotionTranscriptFetcher()
    await fetcher.run()

if __name__ == "__main__":
    asyncio.run(main())