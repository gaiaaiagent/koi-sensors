#!/usr/bin/env python3
"""
Fetch Notion transcripts in small batches with delays to avoid Cloudflare blocking.
Successfully fetched episodes 1-5, then got blocked. This script uses that learning.
"""

import asyncio
import json
import time
import random
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import httpx
from bs4 import BeautifulSoup
from loguru import logger
import sys

# Successful fetch pattern observed: 5 episodes then blocked
BATCH_SIZE = 5
DELAY_BETWEEN_REQUESTS = 10  # seconds between individual requests
DELAY_BETWEEN_BATCHES = 300  # 5 minutes between batches
MAX_RETRIES = 2
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


async def fetch_transcript(
    session: httpx.AsyncClient,
    episode_num: int,
    url: str,
    output_dir: Path
) -> bool:
    """Fetch a single transcript with careful rate limiting."""
    
    output_file = output_dir / f"episode_{episode_num:03d}_complete.json"
    
    # Check if already successfully fetched
    if output_file.exists():
        with open(output_file) as f:
            data = json.load(f)
            if "Enable JavaScript and cookies" not in data.get('transcript', ''):
                logger.info(f"Episode {episode_num}: Already successfully fetched")
                return True
    
    logger.info(f"Episode {episode_num}: Fetching {url}")
    
    try:
        # Add random jitter to delay
        jitter = random.uniform(0, 2)
        await asyncio.sleep(DELAY_BETWEEN_REQUESTS + jitter)
        
        response = await session.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Cache-Control": "max-age=0"
            },
            timeout=30.0,
            follow_redirects=True
        )
        
        content = response.text
        
        # Check if blocked
        if "Enable JavaScript and cookies" in content:
            logger.warning(f"Episode {episode_num}: Cloudflare blocked")
            return False
            
        # Parse the content
        soup = BeautifulSoup(content, 'html.parser')
        
        # Extract title
        title_elem = soup.find('h1') or soup.find('title')
        title = title_elem.get_text(strip=True) if title_elem else f"Episode {episode_num}"
        
        # Extract main content
        main_content = soup.find('div', class_='notion-page-content')
        if not main_content:
            main_content = soup.find('main') or soup.find('article') or soup.body
        
        transcript_text = main_content.get_text(separator='\n', strip=True) if main_content else content
        
        # Save the transcript
        doc = {
            'id': f'transcript_{episode_num:03d}',
            'source': 'notion:transcripts',
            'source_type': 'notion',
            'url': url,
            'title': title,
            'content': transcript_text,
            'transcript': transcript_text,
            'metadata': {
                'episode_number': episode_num,
                'has_transcript': True,
                'transcript_source': 'notion',
                'fetched_at': datetime.now().isoformat()
            }
        }
        
        with open(output_file, 'w') as f:
            json.dump(doc, f, indent=2)
            
        logger.success(f"Episode {episode_num}: Successfully saved ({len(transcript_text)} chars)")
        return True
        
    except httpx.TimeoutException:
        logger.error(f"Episode {episode_num}: Timeout")
        return False
    except Exception as e:
        logger.error(f"Episode {episode_num}: Error - {e}")
        return False


async def process_batch(
    session: httpx.AsyncClient,
    episodes: List[Dict],
    output_dir: Path,
    batch_num: int
) -> Dict[str, int]:
    """Process a batch of episodes."""
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Batch {batch_num}: Processing {len(episodes)} episodes")
    logger.info(f"Episodes: {[e['episode_num'] for e in episodes]}")
    
    success = 0
    blocked = 0
    failed = 0
    
    for episode in episodes:
        result = await fetch_transcript(
            session,
            episode['episode_num'],
            episode['url'],
            output_dir
        )
        
        if result:
            success += 1
        else:
            blocked += 1
            # If we get blocked, stop this batch
            if blocked >= 2:
                logger.warning(f"Batch {batch_num}: Multiple blocks detected, stopping batch")
                break
    
    return {'success': success, 'blocked': blocked, 'failed': failed}


async def main():
    """Main batch processing with smart delays."""
    
    logger.info("="*60)
    logger.info("🎙️ Notion Transcript Batch Fetcher")
    logger.info("="*60)
    
    # Load transcript links
    links_file = Path("indexing/storage/notion_transcripts/transcript_links.json")
    if not links_file.exists():
        logger.error("No transcript links found. Run scrape_notion_transcripts.py first")
        return
        
    with open(links_file) as f:
        all_episodes = json.load(f)
    
    # Sort by episode number
    all_episodes.sort(key=lambda x: x['episode_num'])
    
    # Setup output directory
    output_dir = Path("indexing/storage/podcast_complete")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Check what we already have
    successful_episodes = []
    blocked_episodes = []
    
    for episode in all_episodes:
        output_file = output_dir / f"episode_{episode['episode_num']:03d}_complete.json"
        if output_file.exists():
            with open(output_file) as f:
                data = json.load(f)
                if "Enable JavaScript and cookies" in data.get('transcript', ''):
                    blocked_episodes.append(episode['episode_num'])
                else:
                    successful_episodes.append(episode['episode_num'])
    
    logger.info(f"Status: {len(successful_episodes)} successful, {len(blocked_episodes)} blocked")
    logger.info(f"Successful: {successful_episodes[:10]}..." if len(successful_episodes) > 10 else f"Successful: {successful_episodes}")
    
    # Filter episodes to process
    episodes_to_process = [
        e for e in all_episodes 
        if e['episode_num'] not in successful_episodes
    ]
    
    logger.info(f"Episodes to process: {len(episodes_to_process)}")
    
    if not episodes_to_process:
        logger.info("All episodes already processed!")
        return
    
    # Process in batches
    async with httpx.AsyncClient() as session:
        batch_num = 1
        
        for i in range(0, len(episodes_to_process), BATCH_SIZE):
            batch = episodes_to_process[i:i+BATCH_SIZE]
            
            # Process batch
            stats = await process_batch(session, batch, output_dir, batch_num)
            
            logger.info(f"Batch {batch_num} complete: {stats}")
            
            # If we got blocked, wait longer before next batch
            if stats['blocked'] > 0:
                wait_time = DELAY_BETWEEN_BATCHES * 2  # Double the wait time
                logger.warning(f"Cloudflare blocking detected. Waiting {wait_time/60:.1f} minutes...")
                await asyncio.sleep(wait_time)
            elif i + BATCH_SIZE < len(episodes_to_process):
                # Normal delay between batches
                logger.info(f"Waiting {DELAY_BETWEEN_BATCHES/60:.1f} minutes before next batch...")
                await asyncio.sleep(DELAY_BETWEEN_BATCHES)
            
            batch_num += 1
    
    # Final summary
    logger.info("\n" + "="*60)
    logger.info("✅ Batch Processing Complete")
    
    # Recount final stats
    final_success = 0
    final_blocked = 0
    
    for episode in all_episodes:
        output_file = output_dir / f"episode_{episode['episode_num']:03d}_complete.json"
        if output_file.exists():
            with open(output_file) as f:
                data = json.load(f)
                if "Enable JavaScript and cookies" not in data.get('transcript', ''):
                    final_success += 1
                else:
                    final_blocked += 1
    
    logger.info(f"Final Stats:")
    logger.info(f"  Successfully fetched: {final_success}")
    logger.info(f"  Still blocked: {final_blocked}")
    logger.info(f"  Total episodes: {len(all_episodes)}")
    
    if final_blocked > 0:
        logger.info("\n💡 Recommendation:")
        logger.info("1. Wait a few hours and try again")
        logger.info("2. Or use audio transcription for blocked episodes")
        logger.info("3. Best: Get Notion API access from Regen Network team")


if __name__ == "__main__":
    # Parse command line args
    if "--help" in sys.argv:
        print("Usage: python fetch_notion_transcripts_batch.py [--aggressive]")
        print("")
        print("Options:")
        print("  --aggressive  Use smaller delays (higher risk of blocking)")
        print("  --help        Show this help message")
        sys.exit(0)
    
    if "--aggressive" in sys.argv:
        DELAY_BETWEEN_REQUESTS = 3
        DELAY_BETWEEN_BATCHES = 60
        logger.warning("Aggressive mode: Reduced delays (higher blocking risk)")
    
    asyncio.run(main())