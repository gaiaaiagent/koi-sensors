#!/usr/bin/env python3
"""
Use Playwright headless browser with advanced techniques to fetch Notion transcripts
"""

import asyncio
import json
import random
import time
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright
from loguru import logger
import sys

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

class PlaywrightNotionFetcher:
    def __init__(self):
        self.storage_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.links_file = Path(__file__).parent.parent / "storage" / "notion_transcripts" / "transcript_links.json"
        
        # Load transcript links
        with open(self.links_file, 'r') as f:
            self.transcript_links = json.load(f)
    
    def get_already_fetched(self) -> set:
        """Get set of already fetched episode numbers with real content"""
        fetched = set()
        for file in self.storage_path.glob("episode_*_complete.json"):
            # Check if it has real content
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
    
    async def fetch_with_browser(self, episode: dict, browser):
        """Fetch a single transcript using Playwright browser"""
        url = episode['url']
        episode_num = episode['episode_num']
        
        logger.info(f"Fetching episode {episode_num} with Playwright...")
        
        try:
            # Create new context for each page (fresh cookies)
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                locale='en-US',
                timezone_id='America/Los_Angeles',
            )
            
            page = await context.new_page()
            
            # Navigate with extended timeout
            logger.info(f"Navigating to {url}")
            await page.goto(url, wait_until='networkidle', timeout=60000)
            
            # Wait for content to load
            await page.wait_for_timeout(5000)
            
            # Try multiple selectors for transcript content
            selectors = [
                'div[data-content-editable-root="true"]',
                'div.notion-page-content',
                'div.notion-scroller',
                'main',
                'article',
                '[role="main"]',
                'div.layout-content',
            ]
            
            content = None
            for selector in selectors:
                try:
                    element = await page.wait_for_selector(selector, timeout=5000)
                    if element:
                        text = await element.inner_text()
                        if len(text) > 1000:  # Found substantial content
                            content = text
                            logger.success(f"Found content with selector: {selector}")
                            break
                except:
                    continue
            
            # If no content found with selectors, get all text
            if not content:
                content = await page.inner_text('body')
            
            await context.close()
            
            # Check if we got real content or Cloudflare block
            if "Checking your browser" in content or len(content) < 1000:
                logger.warning(f"Episode {episode_num}: Blocked or no content")
                return None
            
            logger.success(f"Episode {episode_num}: Got {len(content)} chars")
            return content
            
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
                "transcript_source": "notion_playwright",
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
        
        # Filter out already fetched and select test episodes
        test_episodes = []
        for ep in self.transcript_links:
            if ep['episode_num'] not in fetched:
                test_episodes.append(ep)
                if len(test_episodes) >= 10:  # Test with 10 episodes
                    break
        
        if not test_episodes:
            logger.success("All episodes already fetched!")
            return
        
        logger.info(f"Testing with {len(test_episodes)} episodes")
        
        async with async_playwright() as p:
            # Try different browsers
            browsers = [
                ('chromium', await p.chromium.launch(headless=True)),
                # ('firefox', await p.firefox.launch(headless=True)),
                # ('webkit', await p.webkit.launch(headless=True)),
            ]
            
            success_count = 0
            
            for browser_name, browser in browsers:
                logger.info(f"\nTrying with {browser_name}...")
                
                for i, episode in enumerate(test_episodes):
                    episode_num = episode['episode_num']
                    
                    # Random delay between requests
                    if i > 0:
                        delay = random.uniform(10, 30)
                        logger.info(f"Waiting {delay:.1f}s before next request...")
                        await asyncio.sleep(delay)
                    
                    content = await self.fetch_with_browser(episode, browser)
                    
                    if content and len(content) > 1000:
                        self.save_transcript(episode_num, content, episode)
                        success_count += 1
                    
                    # Stop if we're getting blocked
                    if i > 2 and success_count == 0:
                        logger.warning("Getting blocked, stopping...")
                        break
                
                await browser.close()
                
                if success_count > 0:
                    logger.success(f"Successfully fetched {success_count} transcripts with {browser_name}")
                    break
            
            logger.info(f"\nTotal success: {success_count}/{len(test_episodes)}")

async def main():
    """Main entry point"""
    logger.info("Starting Playwright Notion fetcher...")
    logger.info("Installing Playwright browsers if needed...")
    
    # Ensure Playwright browsers are installed
    import subprocess
    result = subprocess.run(['playwright', 'install', 'chromium'], capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning("Installing Playwright browsers...")
        subprocess.run(['python', '-m', 'playwright', 'install'], check=True)
    
    fetcher = PlaywrightNotionFetcher()
    await fetcher.run()

if __name__ == "__main__":
    asyncio.run(main())