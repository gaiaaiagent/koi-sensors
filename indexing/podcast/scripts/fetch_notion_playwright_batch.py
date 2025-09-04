#!/usr/bin/env python3
"""
Fetch Notion transcripts using Playwright browser automation in batches.
More robust against Cloudflare protection.
"""

import asyncio
import json
import random
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from playwright.async_api import async_playwright, Page
from loguru import logger
import sys

# Batch configuration based on successful pattern
BATCH_SIZE = 3  # Smaller batches for browser automation
DELAY_BETWEEN_PAGES = 15  # seconds between page loads
DELAY_BETWEEN_BATCHES = 120  # 2 minutes between batches
PAGE_LOAD_TIMEOUT = 60000  # 60 seconds


async def extract_transcript(page: Page, url: str) -> Optional[Dict[str, str]]:
    """Extract transcript content from loaded page."""
    
    try:
        # Wait for content to load
        await page.wait_for_timeout(5000)
        
        # Get page title
        title = await page.title()
        
        # Try multiple selectors for content
        content = None
        
        # Try Notion-specific selectors
        selectors = [
            'div[data-content-editable-root="true"]',
            'div.notion-page-content',
            'div.notion-selectable',
            'main',
            'article',
            'body'
        ]
        
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    content = await element.inner_text()
                    if content and len(content) > 100:  # Must have actual content
                        break
            except:
                continue
        
        # Check if we got blocked
        if not content or "Enable JavaScript and cookies" in content or len(content) < 100:
            return None
            
        return {
            'title': title,
            'content': content,
            'url': url
        }
        
    except Exception as e:
        logger.error(f"Error extracting content: {e}")
        return None


async def fetch_episode_with_browser(
    browser,
    episode_num: int,
    url: str,
    output_dir: Path
) -> bool:
    """Fetch a single episode using browser automation."""
    
    output_file = output_dir / f"episode_{episode_num:03d}_complete.json"
    
    # Check if already successfully fetched
    if output_file.exists():
        with open(output_file) as f:
            data = json.load(f)
            transcript = data.get('transcript', '')
            # Check for actual content
            if transcript and len(transcript) > 100 and "Enable JavaScript" not in transcript:
                logger.info(f"Episode {episode_num}: Already successfully fetched ({len(transcript)} chars)")
                return True
    
    logger.info(f"Episode {episode_num}: Fetching {url}")
    
    # Create new page with human-like settings
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        locale='en-US',
        timezone_id='America/New_York'
    )
    
    page = await context.new_page()
    
    try:
        # Add random delay
        await asyncio.sleep(DELAY_BETWEEN_PAGES + random.uniform(0, 5))
        
        # Navigate to page
        await page.goto(url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)
        
        # Extract content
        result = await extract_transcript(page, url)
        
        if result and result['content']:
            # Save the transcript
            doc = {
                'id': f'transcript_{episode_num:03d}',
                'source': 'notion:transcripts',
                'source_type': 'notion',
                'url': url,
                'title': result['title'],
                'content': result['content'],
                'transcript': result['content'],
                'metadata': {
                    'episode_number': episode_num,
                    'has_transcript': True,
                    'transcript_source': 'notion',
                    'fetched_at': datetime.now().isoformat()
                }
            }
            
            with open(output_file, 'w') as f:
                json.dump(doc, f, indent=2)
                
            logger.success(f"Episode {episode_num}: Saved ({len(result['content'])} chars)")
            return True
        else:
            logger.warning(f"Episode {episode_num}: No content or blocked")
            return False
            
    except Exception as e:
        logger.error(f"Episode {episode_num}: Error - {e}")
        return False
        
    finally:
        await page.close()
        await context.close()


async def process_batch_with_browser(
    browser,
    episodes: List[Dict],
    output_dir: Path,
    batch_num: int
) -> Dict[str, int]:
    """Process a batch of episodes using browser."""
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Batch {batch_num}: Processing {len(episodes)} episodes")
    logger.info(f"Episodes: {[e['episode_num'] for e in episodes]}")
    
    success = 0
    blocked = 0
    
    for episode in episodes:
        result = await fetch_episode_with_browser(
            browser,
            episode['episode_num'],
            episode['url'],
            output_dir
        )
        
        if result:
            success += 1
        else:
            blocked += 1
            # If multiple blocks, stop batch
            if blocked >= 2:
                logger.warning(f"Batch {batch_num}: Multiple blocks, stopping")
                break
    
    return {'success': success, 'blocked': blocked}


async def main():
    """Main browser-based batch fetcher."""
    
    logger.info("="*60)
    logger.info("🎭 Notion Transcript Browser Fetcher")
    logger.info("="*60)
    
    # Load transcript links
    links_file = Path("indexing/storage/notion_transcripts/transcript_links.json")
    if not links_file.exists():
        logger.error("No transcript links found")
        return
        
    with open(links_file) as f:
        all_episodes = json.load(f)
    
    # Sort by episode number
    all_episodes.sort(key=lambda x: x['episode_num'])
    
    # Setup output directory
    output_dir = Path("indexing/storage/podcast_complete")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Check current status
    successful = []
    needs_fetching = []
    
    for episode in all_episodes:
        output_file = output_dir / f"episode_{episode['episode_num']:03d}_complete.json"
        if output_file.exists():
            with open(output_file) as f:
                data = json.load(f)
                transcript = data.get('transcript', '')
                if transcript and len(transcript) > 100 and "Enable JavaScript" not in transcript:
                    successful.append(episode['episode_num'])
                else:
                    needs_fetching.append(episode)
        else:
            needs_fetching.append(episode)
    
    logger.info(f"Status: {len(successful)} successful")
    logger.info(f"Need to fetch: {len(needs_fetching)} episodes")
    
    if not needs_fetching:
        logger.info("All episodes already fetched!")
        return
    
    # Start browser
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled']
        )
        
        batch_num = 1
        total_success = 0
        total_blocked = 0
        
        # Process in small batches
        for i in range(0, len(needs_fetching), BATCH_SIZE):
            batch = needs_fetching[i:i+BATCH_SIZE]
            
            stats = await process_batch_with_browser(browser, batch, output_dir, batch_num)
            total_success += stats['success']
            total_blocked += stats['blocked']
            
            logger.info(f"Batch {batch_num} stats: {stats}")
            
            # Adjust wait time based on results
            if stats['blocked'] > 0:
                wait_time = DELAY_BETWEEN_BATCHES * 3
                logger.warning(f"Blocks detected. Waiting {wait_time/60:.1f} minutes...")
                await asyncio.sleep(wait_time)
            elif i + BATCH_SIZE < len(needs_fetching):
                logger.info(f"Waiting {DELAY_BETWEEN_BATCHES/60:.1f} minutes...")
                await asyncio.sleep(DELAY_BETWEEN_BATCHES)
            
            batch_num += 1
            
            # Stop if getting too many blocks
            if total_blocked > total_success * 2:
                logger.error("Too many blocks. Stopping to avoid detection.")
                break
        
        await browser.close()
    
    # Final summary
    logger.info("\n" + "="*60)
    logger.info("✅ Browser Fetching Complete")
    logger.info(f"Successfully fetched: {total_success} new episodes")
    logger.info(f"Blocked attempts: {total_blocked}")
    
    # Final count
    final_success = 0
    for episode in all_episodes:
        output_file = output_dir / f"episode_{episode['episode_num']:03d}_complete.json"
        if output_file.exists():
            with open(output_file) as f:
                data = json.load(f)
                transcript = data.get('transcript', '')
                if transcript and len(transcript) > 100:
                    final_success += 1
    
    logger.info(f"Total successful transcripts: {final_success}/{len(all_episodes)}")


if __name__ == "__main__":
    if "--help" in sys.argv:
        print("Usage: python fetch_notion_playwright_batch.py [--test]")
        print("")
        print("Options:")
        print("  --test   Test with first 3 episodes only")
        print("  --help   Show this help")
        sys.exit(0)
    
    if "--test" in sys.argv:
        BATCH_SIZE = 1
        logger.info("TEST MODE: Single episode batches")
    
    asyncio.run(main())