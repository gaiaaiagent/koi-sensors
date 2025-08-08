#!/usr/bin/env python3
"""
Try fetching Notion transcripts using requests with session and cookie handling
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import time
import random
from pathlib import Path
from datetime import datetime
from loguru import logger
import sys

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

class SessionNotionFetcher:
    def __init__(self):
        self.storage_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.links_file = Path(__file__).parent.parent / "storage" / "notion_transcripts" / "transcript_links.json"
        
        # Load transcript links
        with open(self.links_file, 'r') as f:
            self.transcript_links = json.load(f)
        
        # Create session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set headers
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
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
        })
    
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
    
    def fetch_transcript(self, episode: dict) -> str:
        """Fetch a single transcript"""
        url = episode['url']
        episode_num = episode['episode_num']
        
        logger.info(f"Fetching episode {episode_num}: {episode['guest']}")
        
        try:
            # First request to get cookies
            response = self.session.get(url, timeout=30, allow_redirects=True)
            
            if response.status_code == 200:
                content = response.text
                
                # Check for Cloudflare
                if "Checking your browser" in content or "cf-browser-verification" in content:
                    logger.warning(f"Cloudflare detected for episode {episode_num}")
                    
                    # Try to get the actual content URL from the page
                    import re
                    # Look for API endpoint or data URL
                    api_pattern = r'"url":"([^"]+)"'
                    matches = re.findall(api_pattern, content)
                    if matches:
                        for api_url in matches[:3]:  # Try first 3 URLs found
                            if 'api' in api_url or 'loadPageChunk' in api_url:
                                logger.info(f"Found API URL: {api_url}")
                                # Try API endpoint
                                api_response = self.session.get(api_url, timeout=30)
                                if api_response.status_code == 200:
                                    return api_response.text
                    
                    return None
                
                # Parse with BeautifulSoup to extract text
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(content, 'html.parser')
                
                # Remove script and style elements
                for script in soup(["script", "style"]):
                    script.decompose()
                
                # Get text
                text = soup.get_text(separator='\n', strip=True)
                
                if len(text) > 1000:
                    logger.success(f"Got {len(text)} chars for episode {episode_num}")
                    return text
                else:
                    logger.warning(f"Content too short for episode {episode_num}: {len(text)} chars")
                    return None
                    
            else:
                logger.error(f"Status {response.status_code} for episode {episode_num}")
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
                "transcript_source": "notion_session",
                "fetched_at": datetime.now().isoformat()
            }
        }
        
        with open(filename, 'w') as f:
            json.dump(doc, f, indent=2)
        
        logger.info(f"Saved transcript to {filename}")
    
    def run(self):
        """Main execution"""
        # Get already fetched episodes
        fetched = self.get_already_fetched()
        logger.info(f"Already have {len(fetched)} real transcripts: {sorted(fetched)}")
        
        # Test with a few episodes
        test_episodes = []
        for ep in self.transcript_links:
            if ep['episode_num'] not in fetched:
                test_episodes.append(ep)
                if len(test_episodes) >= 5:  # Test with 5 episodes
                    break
        
        if not test_episodes:
            logger.success("All episodes already fetched!")
            return
        
        logger.info(f"Testing with {len(test_episodes)} episodes")
        
        success_count = 0
        
        for i, episode in enumerate(test_episodes):
            episode_num = episode['episode_num']
            
            # Delay between requests
            if i > 0:
                delay = random.uniform(5, 15)
                logger.info(f"Waiting {delay:.1f}s before next request...")
                time.sleep(delay)
            
            content = self.fetch_transcript(episode)
            
            if content and len(content) > 1000:
                self.save_transcript(episode_num, content, episode)
                success_count += 1
            
            # Stop if we're getting blocked consistently
            if i >= 2 and success_count == 0:
                logger.warning("Getting blocked, stopping...")
                break
        
        logger.info(f"\nTotal success: {success_count}/{len(test_episodes)}")
        
        # If this worked, continue with more
        if success_count > 0:
            logger.success(f"Method worked! Can continue with more episodes.")

def main():
    """Main entry point"""
    logger.info("Starting session-based Notion fetcher...")
    fetcher = SessionNotionFetcher()
    fetcher.run()

if __name__ == "__main__":
    main()