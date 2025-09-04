#!/usr/bin/env python3
"""
Fetch Notion transcripts using the API v3 endpoint that works!
"""

import httpx
import json
import asyncio
import re
import time
from pathlib import Path
from datetime import datetime
from loguru import logger
import sys

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

class NotionAPIFetcher:
    def __init__(self):
        self.storage_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.links_file = Path(__file__).parent.parent / "storage" / "notion_transcripts" / "transcript_links.json"
        
        # Load transcript links
        with open(self.links_file, 'r') as f:
            self.transcript_links = json.load(f)
        
        self.api_endpoint = "https://www.notion.so/api/v3/loadPageChunk"
    
    def get_already_fetched(self) -> set:
        """Get set of already fetched episode numbers with real content"""
        fetched = set()
        for file in self.storage_path.glob("episode_*_complete.json"):
            with open(file, 'r') as f:
                data = json.load(f)
            content = data.get('transcript', data.get('content', ''))
            if len(content) > 1000:  # Real transcript
                num_str = file.stem.split('_')[1]
                try:
                    fetched.add(int(num_str))
                except ValueError:
                    pass
        return fetched
    
    def extract_page_id(self, url: str) -> tuple:
        """Extract and format page ID from URL"""
        match = re.search(r'-([a-f0-9]{32})', url)
        if match:
            page_id = match.group(1)
            # Format for API
            formatted_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"
            return page_id, formatted_id
        return None, None
    
    def extract_text_from_response(self, response_data: dict) -> str:
        """Extract text content from Notion API response"""
        text_parts = []
        
        try:
            # Navigate through the response structure
            if 'recordMap' in response_data:
                record_map = response_data['recordMap']
                
                # Look for blocks with text content
                if 'block' in record_map:
                    for block_id, block_data in record_map['block'].items():
                        if 'value' in block_data:
                            value = block_data['value']
                            
                            # Extract text from properties
                            if 'properties' in value:
                                properties = value['properties']
                                
                                # Common text fields in Notion
                                text_fields = ['title', 'text', 'caption']
                                for field in text_fields:
                                    if field in properties:
                                        # Notion text is stored as nested arrays
                                        text_array = properties[field]
                                        if isinstance(text_array, list):
                                            for text_item in text_array:
                                                if isinstance(text_item, list) and len(text_item) > 0:
                                                    text_parts.append(str(text_item[0]))
                            
                            # Also check content field
                            if 'content' in value:
                                # Recursively process content blocks
                                pass  # Would need recursive processing
        
        except Exception as e:
            logger.error(f"Error extracting text: {e}")
        
        return '\n'.join(text_parts)
    
    async def fetch_transcript(self, episode: dict, client: httpx.AsyncClient) -> str:
        """Fetch a single transcript using Notion API"""
        url = episode['url']
        episode_num = episode['episode_num']
        
        page_id, formatted_id = self.extract_page_id(url)
        if not formatted_id:
            logger.error(f"Could not extract page ID from {url}")
            return None
        
        logger.info(f"Fetching episode {episode_num} (ID: {formatted_id[:8]}...)")
        
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
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                },
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Extract text content
                text = self.extract_text_from_response(data)
                
                # If extraction didn't work, try raw JSON
                if len(text) < 1000:
                    # Fallback: get all text from JSON
                    raw_text = json.dumps(data)
                    # Look for transcript markers
                    if "transcript" in raw_text.lower() or len(raw_text) > 50000:
                        logger.success(f"Episode {episode_num}: Got {len(raw_text)} bytes of data")
                        return raw_text  # Return raw for now, can process later
                    else:
                        logger.warning(f"Episode {episode_num}: Response too short or no transcript markers")
                        return None
                else:
                    logger.success(f"Episode {episode_num}: Extracted {len(text)} chars of text")
                    return text
            else:
                logger.error(f"Episode {episode_num}: Status {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching episode {episode_num}: {e}")
            return None
    
    def save_transcript(self, episode_num: int, content: str, metadata: dict):
        """Save transcript to file"""
        filename = self.storage_path / f"episode_{episode_num:03d}_complete.json"
        
        doc = {
            "id": f"podcast_episode_{episode_num:03d}",
            "source": "notion:transcripts",
            "source_type": "notion",
            "url": metadata.get('url', ''),
            "title": f"Planetary Regeneration Podcast Episode {episode_num}: {metadata.get('guest', '')}",
            "content": content,
            "transcript": content,
            "metadata": {
                "episode_number": episode_num,
                "guest_name": metadata.get('guest', ''),
                "has_transcript": True,
                "transcript_source": "notion_api_v3",
                "fetched_at": datetime.now().isoformat()
            }
        }
        
        with open(filename, 'w') as f:
            json.dump(doc, f, indent=2)
        
        logger.info(f"Saved transcript to {filename}")
    
    async def run(self):
        """Main execution"""
        # Get already fetched episodes
        fetched = self.get_already_fetched()
        logger.info(f"Already have {len(fetched)} real transcripts: {sorted(fetched)}")
        
        # Filter out already fetched
        remaining = [ep for ep in self.transcript_links if ep['episode_num'] not in fetched]
        logger.info(f"Need to fetch {len(remaining)} more episodes")
        
        if not remaining:
            logger.success("All episodes already fetched!")
            return
        
        # Sort by episode number
        remaining.sort(key=lambda x: x['episode_num'])
        
        async with httpx.AsyncClient() as client:
            success_count = 0
            failed_count = 0
            
            for i, episode in enumerate(remaining):
                episode_num = episode['episode_num']
                
                # Rate limiting - be respectful
                if i > 0:
                    delay = 3  # 3 seconds between requests
                    logger.info(f"Waiting {delay}s before next request...")
                    await asyncio.sleep(delay)
                
                logger.info(f"\n{'='*50}")
                logger.info(f"Processing episode {episode_num} ({i+1}/{len(remaining)})")
                logger.info(f"Guest: {episode['guest']}")
                
                content = await self.fetch_transcript(episode, client)
                
                if content and len(content) > 1000:
                    self.save_transcript(episode_num, content, episode)
                    success_count += 1
                else:
                    failed_count += 1
                    logger.warning(f"Failed to fetch episode {episode_num}")
                
                # Stop if we're getting blocked
                if failed_count >= 5 and success_count == 0:
                    logger.error("Too many failures, stopping...")
                    break
                
                # Progress update every 10 episodes
                if (i + 1) % 10 == 0:
                    logger.info(f"\nProgress: {success_count} success, {failed_count} failed")
            
            # Final summary
            logger.info(f"\n{'='*60}")
            logger.info(f"SUMMARY:")
            logger.info(f"  Successfully fetched: {success_count}")
            logger.info(f"  Failed: {failed_count}")
            logger.info(f"  Total processed: {len(remaining)}")
            
            # Check final status
            final_fetched = self.get_already_fetched()
            logger.info(f"  Total episodes with transcripts now: {len(final_fetched)}/70")

async def main():
    """Main entry point"""
    logger.info("Starting Notion API v3 fetcher...")
    logger.info("This uses the working loadPageChunk endpoint")
    
    fetcher = NotionAPIFetcher()
    await fetcher.run()

if __name__ == "__main__":
    asyncio.run(main())