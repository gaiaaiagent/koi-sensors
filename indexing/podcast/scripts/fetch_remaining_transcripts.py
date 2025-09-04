#!/usr/bin/env python3
"""
Fetch remaining Notion transcripts with advanced anti-rate-limiting techniques
"""

import json
import asyncio
import httpx
import random
import time
from pathlib import Path
from datetime import datetime
from loguru import logger
from typing import Dict, List, Optional
import sys

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

class SmartNotionFetcher:
    def __init__(self):
        self.storage_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.links_file = Path(__file__).parent.parent / "storage" / "notion_transcripts" / "transcript_links.json"
        
        # Load transcript links
        with open(self.links_file, 'r') as f:
            self.transcript_links = json.load(f)
        
        # User agents rotation
        self.user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.2.1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        ]
        
        # Advanced delays
        self.base_delay = 15  # Start with 15 seconds
        self.max_delay = 300  # Max 5 minutes
        self.backoff_multiplier = 2
        self.current_delay = self.base_delay
        self.consecutive_failures = 0
        
    def get_already_fetched(self) -> set:
        """Get set of already fetched episode numbers"""
        fetched = set()
        for file in self.storage_path.glob("episode_*_complete.json"):
            # Extract episode number from filename
            num_str = file.stem.split('_')[1]
            try:
                fetched.add(int(num_str))
            except ValueError:
                pass
        return fetched
    
    def get_headers(self) -> Dict:
        """Get randomized headers"""
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'Pragma': 'no-cache',
        }
    
    async def fetch_transcript(self, episode: Dict, client: httpx.AsyncClient) -> Optional[str]:
        """Fetch a single transcript with retries"""
        url = episode['url']
        episode_num = episode['episode_num']
        
        for attempt in range(3):  # 3 attempts per transcript
            try:
                logger.info(f"Attempt {attempt + 1}/3 for episode {episode_num}: {episode['guest']}")
                
                response = await client.get(
                    url,
                    headers=self.get_headers(),
                    timeout=30.0,
                    follow_redirects=True
                )
                
                if response.status_code == 200:
                    content = response.text
                    
                    # Check for Cloudflare block
                    if "Checking your browser" in content or "cf-browser-verification" in content:
                        logger.warning(f"Cloudflare block detected for episode {episode_num}")
                        self.consecutive_failures += 1
                        return None
                    
                    # Extract text content (simplified)
                    if len(content) > 1000:  # Reasonable transcript should be > 1KB
                        logger.success(f"✅ Successfully fetched episode {episode_num}")
                        self.consecutive_failures = 0
                        self.current_delay = max(self.base_delay, self.current_delay * 0.9)  # Reduce delay on success
                        return content
                    else:
                        logger.warning(f"Content too short for episode {episode_num}: {len(content)} bytes")
                        
                elif response.status_code == 403:
                    logger.error(f"403 Forbidden for episode {episode_num}")
                    self.consecutive_failures += 1
                    return None
                elif response.status_code == 429:
                    logger.error(f"429 Rate limited for episode {episode_num}")
                    self.consecutive_failures += 1
                    return None
                else:
                    logger.warning(f"Status {response.status_code} for episode {episode_num}")
                    
            except Exception as e:
                logger.error(f"Error fetching episode {episode_num}: {e}")
            
            # Wait between attempts
            if attempt < 2:
                wait_time = self.current_delay * (attempt + 1)
                logger.info(f"Waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
        
        return None
    
    def save_transcript(self, episode_num: int, content: str, metadata: Dict):
        """Save transcript to file"""
        filename = self.storage_path / f"episode_{episode_num:03d}_complete.json"
        
        doc = {
            "id": f"podcast_episode_{episode_num:03d}",
            "source": "notion:transcripts",
            "source_type": "notion",
            "url": metadata.get('url', ''),
            "title": metadata.get('title', f"Episode {episode_num}"),
            "content": content,
            "transcript": content,
            "metadata": {
                "episode_number": episode_num,
                "guest_name": metadata.get('guest', ''),
                "has_transcript": True,
                "transcript_source": "notion",
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
        logger.info(f"Already fetched {len(fetched)} episodes: {sorted(fetched)}")
        
        # Filter out already fetched
        remaining = [ep for ep in self.transcript_links if ep['episode_num'] not in fetched]
        logger.info(f"Need to fetch {len(remaining)} more episodes")
        
        if not remaining:
            logger.success("All episodes already fetched!")
            return
        
        # Sort by episode number for sequential fetching
        remaining.sort(key=lambda x: x['episode_num'])
        
        # Create client with custom settings
        async with httpx.AsyncClient(
            verify=False,  # Skip SSL verification (Cloudflare sometimes has issues)
            http2=True,    # Use HTTP/2
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        ) as client:
            
            fetched_count = 0
            blocked_count = 0
            
            for i, episode in enumerate(remaining):
                episode_num = episode['episode_num']
                
                # Check if we've been blocked too many times
                if self.consecutive_failures >= 3:
                    wait_time = min(self.current_delay * self.backoff_multiplier, self.max_delay)
                    logger.warning(f"Too many failures. Backing off for {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    self.current_delay = wait_time
                    self.consecutive_failures = 0
                
                logger.info(f"\n{'='*60}")
                logger.info(f"Processing episode {episode_num} ({i+1}/{len(remaining)})")
                logger.info(f"Guest: {episode['guest']}")
                
                # Fetch transcript
                content = await self.fetch_transcript(episode, client)
                
                if content:
                    # Parse and save
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # Try to extract main content
                    main_content = soup.get_text(separator='\n', strip=True)
                    
                    if len(main_content) > 1000:
                        self.save_transcript(episode_num, main_content, episode)
                        fetched_count += 1
                    else:
                        logger.warning(f"Parsed content too short: {len(main_content)} chars")
                        blocked_count += 1
                else:
                    blocked_count += 1
                
                # Adaptive delay
                if content:
                    # Success - use base delay with some randomization
                    delay = self.current_delay + random.uniform(-5, 10)
                else:
                    # Failure - increase delay
                    delay = min(self.current_delay * 1.5, self.max_delay)
                    self.current_delay = delay
                
                # Add extra delay every 5 episodes
                if (i + 1) % 5 == 0:
                    delay += 60  # Extra minute every 5 episodes
                    logger.info(f"Extra pause after 5 episodes...")
                
                if i < len(remaining) - 1:  # Don't wait after last episode
                    logger.info(f"Waiting {delay:.1f}s before next episode...")
                    await asyncio.sleep(delay)
            
            # Summary
            logger.info(f"\n{'='*60}")
            logger.info(f"SUMMARY:")
            logger.info(f"  Successfully fetched: {fetched_count}")
            logger.info(f"  Blocked/Failed: {blocked_count}")
            logger.info(f"  Total processed: {len(remaining)}")
            
            # Check final status
            final_fetched = self.get_already_fetched()
            logger.info(f"  Total episodes now: {len(final_fetched)}/70")
            
            if len(final_fetched) >= 52:
                logger.success("✅ All available Notion transcripts fetched!")
            else:
                logger.warning(f"⚠️ Still missing {52 - len(final_fetched)} transcripts")
                logger.info("Consider using audio transcription for remaining episodes")

async def main():
    """Main entry point"""
    logger.info("Starting smart Notion transcript fetcher...")
    logger.info("This will use advanced techniques to avoid Cloudflare blocking")
    logger.info("Features:")
    logger.info("  - Skip already fetched episodes")
    logger.info("  - Rotate user agents")
    logger.info("  - Adaptive delays with backoff")
    logger.info("  - Extra pauses every 5 episodes")
    
    fetcher = SmartNotionFetcher()
    await fetcher.run()

if __name__ == "__main__":
    asyncio.run(main())