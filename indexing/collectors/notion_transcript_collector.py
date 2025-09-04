#!/usr/bin/env python3
"""
Notion transcript collector for Regen Network podcast episodes.
Collects transcripts from the Notion database.
"""

import re
import asyncio
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
import aiohttp
from bs4 import BeautifulSoup
from loguru import logger

from .base_collector import BaseCollector, Document


class NotionTranscriptCollector(BaseCollector):
    """Collector for podcast transcripts from Notion."""
    
    def __init__(self, config: Dict[str, Any], cache_dir: Path = None):
        super().__init__(config)
        self.notion_url = config.get('url', '')
        self.cache_dir = cache_dir or Path("cache")
        
    def validate_config(self) -> bool:
        """Validate the collector configuration."""
        if not self.notion_url:
            logger.error("No Notion URL configured")
            return False
        return True
        
    async def _get_transcript_links(self, session: aiohttp.ClientSession) -> List[Dict[str, str]]:
        """Get all transcript page links from the main Notion page."""
        transcript_links = []
        
        try:
            async with session.get(self.notion_url) as response:
                html = await response.text()
                
            soup = BeautifulSoup(html, 'html.parser')
            
            # Look for all links that appear to be episode transcripts
            # Notion uses specific patterns for internal links
            links = soup.find_all('a', href=True)
            
            # Also look for divs/sections that might contain episode info
            # Notion often renders content in specific div structures
            content_blocks = soup.find_all(['div', 'article'], class_=True)
            
            episode_pattern = re.compile(r'(\d+):\s*(.+?)(?:\s*\||\s*$)')
            
            for link in links:
                text = link.get_text(strip=True)
                href = link.get('href', '')
                
                # Check if this looks like an episode link
                match = episode_pattern.search(text)
                if match:
                    episode_num = match.group(1)
                    guest_name = match.group(2).strip()
                    
                    # Build full URL if needed
                    if href and not href.startswith('http'):
                        if href.startswith('/'):
                            href = f"https://regennetwork.notion.site{href}"
                        else:
                            href = f"https://regennetwork.notion.site/{href}"
                    
                    if href and 'notion.site' in href:
                        transcript_links.append({
                            'episode_num': episode_num,
                            'guest': guest_name,
                            'title': text,
                            'url': href
                        })
                        logger.debug(f"Found transcript: {text} -> {href}")
            
            # If we didn't find many links, try a different approach
            if len(transcript_links) < 10:
                logger.warning(f"Only found {len(transcript_links)} transcripts via links, searching content blocks...")
                
                # Look for episode patterns in the page content
                page_text = soup.get_text()
                episodes = episode_pattern.findall(page_text)
                
                for episode_num, guest in episodes:
                    # Try to construct a URL based on common Notion patterns
                    # This is a fallback - actual URLs would need to be discovered
                    title = f"{episode_num}: {guest}"
                    if not any(t['title'] == title for t in transcript_links):
                        transcript_links.append({
                            'episode_num': episode_num,
                            'guest': guest.strip(),
                            'title': title,
                            'url': None  # Will need to be discovered
                        })
                        
        except Exception as e:
            logger.error(f"Error getting transcript links: {e}")
            
        return transcript_links
        
    async def _fetch_transcript(self, session: aiohttp.ClientSession, episode_info: Dict[str, str]) -> Optional[str]:
        """Fetch the transcript content from a Notion page."""
        
        if not episode_info.get('url'):
            logger.warning(f"No URL for episode: {episode_info.get('title')}")
            return None
            
        try:
            async with session.get(episode_info['url']) as response:
                if response.status != 200:
                    logger.warning(f"Failed to fetch {episode_info['url']}: {response.status}")
                    return None
                    
                html = await response.text()
                
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove navigation and unnecessary elements
            for element in soup.find_all(['nav', 'header', 'footer', 'script', 'style']):
                element.decompose()
                
            # Look for main content area
            # Notion pages typically have the content in specific containers
            content = None
            
            # Try different selectors that Notion might use
            selectors = [
                'div[class*="notion-page-content"]',
                'main',
                'article',
                'div[class*="content"]',
                'div[class*="transcript"]'
            ]
            
            for selector in selectors:
                content_elem = soup.select_one(selector)
                if content_elem:
                    content = content_elem.get_text(separator='\n', strip=True)
                    if len(content) > 500:  # Make sure we got substantial content
                        break
                        
            # Fallback to all text if we couldn't find specific content area
            if not content or len(content) < 500:
                content = soup.get_text(separator='\n', strip=True)
                
            # Clean up the transcript
            if content:
                # Remove multiple newlines
                content = re.sub(r'\n{3,}', '\n\n', content)
                # Remove Notion-specific UI text
                ui_patterns = [
                    r'Share\s+to\s+web',
                    r'Add\s+to\s+Favorites',
                    r'Search\s+or\s+ask\s+anything',
                    r'Type\s+to\s+search'
                ]
                for pattern in ui_patterns:
                    content = re.sub(pattern, '', content, flags=re.IGNORECASE)
                    
            return content
            
        except Exception as e:
            logger.error(f"Error fetching transcript from {episode_info.get('url')}: {e}")
            return None
            
    async def collect(self) -> List[Document]:
        """Collect transcript documents from Notion."""
        documents = []
        
        async with aiohttp.ClientSession() as session:
            # Get all transcript links
            logger.info("Fetching transcript links from Notion...")
            transcript_links = await self._get_transcript_links(session)
            
            logger.info(f"Found {len(transcript_links)} transcript links")
            
            # Fetch each transcript
            for episode_info in transcript_links:
                try:
                    episode_num = episode_info['episode_num']
                    
                    # Skip if no URL (would need manual discovery)
                    if not episode_info.get('url'):
                        logger.warning(f"Skipping episode {episode_num}: No URL available")
                        continue
                        
                    logger.info(f"Fetching transcript for episode {episode_num}: {episode_info['guest']}")
                    
                    transcript = await self._fetch_transcript(session, episode_info)
                    
                    if not transcript:
                        logger.warning(f"No transcript found for episode {episode_num}")
                        continue
                        
                    # Create document
                    doc = Document(
                        id=f"notion_transcript_{episode_num.zfill(3)}",
                        source="notion:prp-transcripts",
                        source_type="notion",
                        url=episode_info['url'],
                        title=f"Episode {episode_num}: {episode_info['guest']} (Transcript)",
                        content=transcript,
                        metadata={
                            'type': 'podcast_transcript',
                            'episode_number': episode_num,
                            'guest': episode_info['guest'],
                            'source': 'notion',
                            'has_transcript': True,
                            'collected_at': datetime.now().isoformat()
                        }
                    )
                    
                    documents.append(doc)
                    
                    # Apply test limit if configured
                    if self.config.get('test_limit') and len(documents) >= self.config['test_limit']:
                        logger.info(f"Reached test limit of {self.config['test_limit']} transcripts")
                        break
                        
                except Exception as e:
                    logger.error(f"Error processing episode {episode_info.get('title')}: {e}")
                    continue
                    
        logger.info(f"Collected {len(documents)} transcripts from Notion")
        return documents
        
    def get_cache_key(self) -> str:
        """Generate cache key for this collector."""
        return f"notion_{self.notion_url.replace('/', '_')}"