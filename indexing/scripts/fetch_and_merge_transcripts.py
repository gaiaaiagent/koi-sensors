#!/usr/bin/env python3
"""
Fetch all Notion transcripts and merge with SoundCloud metadata.
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from playwright.async_api import async_playwright
from loguru import logger
from tqdm import tqdm


def extract_episode_number(title: str) -> Optional[int]:
    """Extract episode number from title."""
    patterns = [
        r'^(\d+):',           # "01: Guest Name"
        r'^0?(\d+):',         # "001: Guest Name"
        r'Episode\s+(\d+)',   # "Episode 01"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


async def fetch_transcript_batch(urls: List[str], batch_size: int = 3) -> List[Dict]:
    """Fetch multiple transcripts in parallel batches."""
    results = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i+batch_size]
            batch_results = await asyncio.gather(
                *[fetch_single_transcript(browser, url) for url in batch],
                return_exceptions=True
            )
            
            for result in batch_results:
                if isinstance(result, Exception):
                    logger.error(f"Error fetching transcript: {result}")
                    results.append(None)
                else:
                    results.append(result)
                    
        await browser.close()
        
    return results


async def fetch_single_transcript(browser, url: str) -> Optional[Dict]:
    """Fetch a single transcript."""
    try:
        page = await browser.new_page()
        
        # Navigate with relaxed timeout
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Get title
        title = await page.title()
        
        # Extract content
        content = await page.evaluate("""
            () => {
                // Remove UI elements
                const toRemove = ['nav', 'header', '.notion-topbar', '.notion-sidebar'];
                toRemove.forEach(selector => {
                    const elements = document.querySelectorAll(selector);
                    elements.forEach(el => el.remove());
                });
                
                // Get main content
                const main = document.querySelector('main') || document.body;
                return main.innerText || main.textContent || '';
            }
        """)
        
        await page.close()
        
        # Clean content
        if content:
            # Remove excessive whitespace
            content = re.sub(r'\n{3,}', '\n\n', content)
            # Remove common Notion UI text
            ui_patterns = [
                r'Share to web.*?(?=\n)',
                r'Add to Favorites.*?(?=\n)',
                r'Search or ask.*?(?=\n)',
                r'Type.*?to.*?search.*?(?=\n)',
            ]
            for pattern in ui_patterns:
                content = re.sub(pattern, '', content, flags=re.IGNORECASE)
                
        return {
            'url': url,
            'title': title,
            'content': content
        }
        
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None


async def main():
    """Main process to fetch and merge transcripts."""
    
    # Load transcript links
    links_file = Path("indexing/storage/notion_transcripts/transcript_links.json")
    with open(links_file) as f:
        transcript_links = json.load(f)
        
    logger.info(f"Found {len(transcript_links)} transcript links")
    
    # Load SoundCloud episodes
    soundcloud_dir = Path("indexing/storage/documents")
    soundcloud_episodes = {}
    
    for doc_path in soundcloud_dir.glob("soundcloud_*.json"):
        with open(doc_path) as f:
            doc = json.load(f)
            ep_num = extract_episode_number(doc['title'])
            if ep_num:
                soundcloud_episodes[ep_num] = doc
                
    logger.info(f"Loaded {len(soundcloud_episodes)} SoundCloud episodes")
    
    # Create output directory
    output_dir = Path("indexing/storage/podcast_complete")
    output_dir.mkdir(exist_ok=True, parents=True)
    
    # Process transcripts
    logger.info("Fetching transcripts...")
    
    successful = 0
    failed = 0
    
    with tqdm(total=len(transcript_links), desc="Fetching transcripts") as pbar:
        for i in range(0, len(transcript_links), 5):  # Process 5 at a time
            batch = transcript_links[i:i+5]
            
            # Fetch transcripts
            urls = [t['url'] for t in batch if t['url']]
            if urls:
                transcripts = await fetch_transcript_batch(urls)
                
                # Process each transcript
                for j, link_info in enumerate(batch):
                    if j < len(transcripts) and transcripts[j]:
                        transcript = transcripts[j]
                        ep_num = link_info['episode_num']
                        
                        # Merge with SoundCloud data if available
                        if ep_num in soundcloud_episodes:
                            merged = soundcloud_episodes[ep_num].copy()
                            merged['transcript'] = transcript['content']
                            merged['transcript_url'] = transcript['url']
                            merged['metadata']['has_transcript'] = True
                            merged['metadata']['transcript_source'] = 'notion'
                            
                            # Update content
                            merged['content'] = merged['content'].replace(
                                "*Note: Audio transcription not yet implemented. This document contains metadata only.*",
                                f"\n## Transcript\n\n{transcript['content'][:5000]}..."  # Preview
                            )
                        else:
                            # Create standalone transcript document
                            merged = {
                                'id': f"transcript_{ep_num:03d}",
                                'source': 'notion:transcripts',
                                'source_type': 'notion',
                                'url': transcript['url'],
                                'title': f"Episode {ep_num}: {link_info['guest']}",
                                'content': transcript['content'],
                                'transcript': transcript['content'],
                                'metadata': {
                                    'episode_number': ep_num,
                                    'guest': link_info['guest'],
                                    'has_transcript': True,
                                    'transcript_source': 'notion'
                                }
                            }
                            
                        # Save merged document
                        output_file = output_dir / f"episode_{ep_num:03d}_complete.json"
                        with open(output_file, 'w') as f:
                            json.dump(merged, f, indent=2)
                            
                        successful += 1
                        logger.debug(f"Saved episode {ep_num}")
                    else:
                        failed += 1
                        
                    pbar.update(1)
                    
    # Summary
    logger.info("\n=== Summary ===")
    logger.info(f"Successfully processed: {successful} episodes")
    logger.info(f"Failed: {failed} episodes")
    logger.info(f"Output directory: {output_dir}")
    
    # Show sample
    if successful > 0:
        sample_files = list(output_dir.glob("*.json"))[:3]
        logger.info("\nSample merged files:")
        for f in sample_files:
            with open(f) as fp:
                data = json.load(fp)
                has_transcript = 'transcript' in data and len(data['transcript']) > 100
                logger.info(f"  {f.name}: {data['title'][:50]} (transcript: {has_transcript})")


if __name__ == "__main__":
    asyncio.run(main())