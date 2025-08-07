#!/usr/bin/env python3
"""
Merge SoundCloud metadata with Notion transcripts.
Since Notion page is dynamic, we'll match based on episode numbers and titles.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple
from loguru import logger
import asyncio
import aiohttp
from bs4 import BeautifulSoup

def extract_episode_number(title: str) -> Optional[int]:
    """Extract episode number from title."""
    # Various patterns for episode numbers
    patterns = [
        r'^(\d+):',           # "01: Guest Name"
        r'^#(\d+)',           # "#01 Guest Name"
        r'Episode\s+(\d+)',   # "Episode 01"
        r'Ep\.?\s*(\d+)',     # "Ep. 01" or "Ep 01"
        r'^\[(\d+)\]',        # "[01] Guest Name"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None

def load_soundcloud_episodes() -> List[Dict]:
    """Load all SoundCloud episodes we've collected."""
    doc_dir = Path("indexing/storage/documents")
    episodes = []
    
    for doc_path in doc_dir.glob("soundcloud_*.json"):
        with open(doc_path) as f:
            doc = json.load(f)
            ep_num = extract_episode_number(doc['title'])
            if ep_num:
                doc['episode_number'] = ep_num
            episodes.append(doc)
            
    # Sort by episode number (if available) or by date
    episodes.sort(key=lambda x: (x.get('episode_number', 999), x['metadata'].get('created_at', '')))
    
    return episodes

async def fetch_notion_transcript(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """Attempt to fetch a single Notion transcript."""
    try:
        async with session.get(url) as response:
            if response.status != 200:
                return None
            html = await response.text()
            
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove scripts and styles
        for element in soup(['script', 'style', 'nav', 'header', 'footer']):
            element.decompose()
            
        # Get text content
        text = soup.get_text(separator='\n', strip=True)
        
        # Basic cleanup
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Check if it looks like a transcript (should have substantial content)
        if len(text) > 1000 and ('transcript' in text.lower() or 'speaker' in text.lower() or len(text) > 5000):
            return text
            
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        
    return None

async def try_notion_urls(episode_num: int, guest_name: str) -> Optional[str]:
    """Try various Notion URL patterns to find a transcript."""
    
    # Common Notion URL patterns we might try
    base_url = "https://regennetwork.notion.site/"
    
    # Clean guest name for URL
    guest_slug = re.sub(r'[^\w\s-]', '', guest_name.lower())
    guest_slug = re.sub(r'[-\s]+', '-', guest_slug)
    
    # Potential URL patterns
    url_patterns = [
        # Try with episode number and guest name
        f"{base_url}{episode_num:02d}-{guest_slug}",
        f"{base_url}{episode_num:03d}-{guest_slug}",
        f"{base_url}episode-{episode_num}-{guest_slug}",
        f"{base_url}{episode_num}-{guest_slug}",
        
        # Try just episode number
        f"{base_url}{episode_num:02d}",
        f"{base_url}{episode_num:03d}",
        f"{base_url}episode-{episode_num}",
    ]
    
    async with aiohttp.ClientSession() as session:
        for url in url_patterns:
            logger.debug(f"Trying URL: {url}")
            transcript = await fetch_notion_transcript(session, url)
            if transcript:
                logger.success(f"Found transcript at: {url}")
                return transcript
                
    return None

async def main():
    """Main merge process."""
    
    logger.info("Loading SoundCloud episodes...")
    episodes = load_soundcloud_episodes()
    logger.info(f"Loaded {len(episodes)} SoundCloud episodes")
    
    # Display all episodes to understand what we have
    print("\n=== SoundCloud Episodes ===")
    for i, ep in enumerate(episodes):
        ep_num = ep.get('episode_number', '?')
        print(f"{ep_num:3}: {ep['title'][:80]}")
        
    # Known Notion transcript URLs (you can add more here)
    known_transcripts = {
        # Add known URLs here as we discover them
        # Format: episode_number: "url"
        # 1: "https://regennetwork.notion.site/01-ethan-buchman-...",
    }
    
    # Try to match and merge
    merged_count = 0
    output_dir = Path("indexing/storage/podcast_merged")
    output_dir.mkdir(exist_ok=True, parents=True)
    
    for episode in episodes[:5]:  # Test with first 5
        ep_num = episode.get('episode_number')
        
        if not ep_num:
            logger.warning(f"No episode number for: {episode['title']}")
            continue
            
        logger.info(f"Processing episode {ep_num}: {episode['title'][:50]}")
        
        # Check if we have a known transcript URL
        transcript = None
        if ep_num in known_transcripts:
            async with aiohttp.ClientSession() as session:
                transcript = await fetch_notion_transcript(session, known_transcripts[ep_num])
                
        # If no transcript yet, try to find it
        if not transcript:
            # Extract guest name from title
            title_parts = episode['title'].split(':', 1)
            if len(title_parts) > 1:
                guest_name = title_parts[1].strip()
                guest_name = guest_name.split('|')[0].strip()  # Remove any additional info
                
                logger.info(f"Searching for transcript: Episode {ep_num} - {guest_name}")
                # transcript = await try_notion_urls(ep_num, guest_name)
                
        if transcript:
            # Merge transcript with metadata
            episode['transcript'] = transcript
            episode['metadata']['has_transcript'] = True
            episode['metadata']['transcript_source'] = 'notion'
            merged_count += 1
            
            # Save merged document
            output_path = output_dir / f"episode_{ep_num:03d}_merged.json"
            with open(output_path, 'w') as f:
                json.dump(episode, f, indent=2)
                
            logger.success(f"Merged episode {ep_num} with transcript")
        else:
            logger.warning(f"No transcript found for episode {ep_num}")
            
    logger.info(f"\n=== Summary ===")
    logger.info(f"Total episodes: {len(episodes)}")
    logger.info(f"Transcripts merged: {merged_count}")
    logger.info(f"Output directory: {output_dir}")

if __name__ == "__main__":
    asyncio.run(main())