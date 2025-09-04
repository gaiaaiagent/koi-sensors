#!/usr/bin/env python3
"""
SoundCloud collector for Regen Network podcast episodes.
Collects metadata and optionally downloads audio for transcription.
"""

import re
import json
import asyncio
import subprocess
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
import aiohttp
from bs4 import BeautifulSoup
from loguru import logger

from .base_collector import BaseCollector, Document

# Check if yt-dlp is available
try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False
    logger.warning("yt-dlp not installed. Audio download disabled.")


class SoundCloudCollector(BaseCollector):
    """Collector for SoundCloud podcast episodes."""
    
    def __init__(self, config: Dict[str, Any], cache_dir: Path = None):
        super().__init__(config)
        self.soundcloud_url = config.get('url', '')
        self.client_id = None  # Will be extracted from page
        self.api_base = "https://api-v2.soundcloud.com"
        self.cache_dir = cache_dir or Path("cache")
        
    def validate_config(self) -> bool:
        """Validate the collector configuration."""
        if not self.soundcloud_url:
            logger.error("No SoundCloud URL configured")
            return False
        if not self.soundcloud_url.startswith('https://soundcloud.com/'):
            logger.error(f"Invalid SoundCloud URL: {self.soundcloud_url}")
            return False
        return True
        
    async def _extract_client_id(self, session: aiohttp.ClientSession) -> Optional[str]:
        """Extract the client_id from SoundCloud's JavaScript files."""
        try:
            # Get main page
            async with session.get(self.soundcloud_url) as response:
                html = await response.text()
                
            # Find script URLs
            soup = BeautifulSoup(html, 'html.parser')
            scripts = soup.find_all('script', src=True)
            
            for script in scripts:
                script_url = script['src']
                if not script_url.startswith('http'):
                    script_url = f"https://soundcloud.com{script_url}"
                    
                # Download script and look for client_id
                async with session.get(script_url) as response:
                    js_content = await response.text()
                    
                # Look for client_id pattern
                match = re.search(r'client_id["\']?\s*[:=]\s*["\']([a-zA-Z0-9]+)["\']', js_content)
                if match:
                    return match.group(1)
                    
        except Exception as e:
            logger.warning(f"Could not extract client_id: {e}")
            
        return None
        
    async def _get_user_info(self, session: aiohttp.ClientSession, username: str) -> Optional[Dict]:
        """Get user information from SoundCloud API."""
        try:
            # Try to resolve user
            resolve_url = f"{self.api_base}/resolve"
            params = {
                'url': f"https://soundcloud.com/{username}",
                'client_id': self.client_id
            }
            
            async with session.get(resolve_url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                    
        except Exception as e:
            logger.warning(f"Could not get user info: {e}")
            
        return None
        
    async def _get_user_tracks(self, session: aiohttp.ClientSession, user_id: int) -> List[Dict]:
        """Get all tracks (episodes) for a user."""
        tracks = []
        
        try:
            tracks_url = f"{self.api_base}/users/{user_id}/tracks"
            params = {
                'client_id': self.client_id,
                'limit': 200,  # Increased to get all episodes
                'offset': 0,
                'linked_partitioning': 1
            }
            
            while True:
                async with session.get(tracks_url, params=params) as response:
                    if response.status != 200:
                        break
                        
                    data = await response.json()
                    collection = data.get('collection', [])
                    
                    if not collection:
                        break
                        
                    tracks.extend(collection)
                    
                    # Check for next page
                    next_href = data.get('next_href')
                    if not next_href:
                        break
                        
                    # Parse next offset
                    import urllib.parse
                    parsed = urllib.parse.urlparse(next_href)
                    query = urllib.parse.parse_qs(parsed.query)
                    params['offset'] = int(query.get('offset', [0])[0])
                    
        except Exception as e:
            logger.error(f"Error fetching tracks: {e}")
            
        return tracks
        
    async def _scrape_without_api(self, session: aiohttp.ClientSession) -> List[Dict]:
        """Fallback: Scrape track information directly from the page."""
        tracks = []
        
        try:
            async with session.get(self.soundcloud_url) as response:
                html = await response.text()
                
            soup = BeautifulSoup(html, 'html.parser')
            
            # Look for track links
            track_links = soup.find_all('a', href=True)
            
            for link in track_links:
                href = link.get('href', '')
                # Pattern for SoundCloud track URLs
                if '/planetaryregeneration/' in href and href.count('/') >= 2:
                    track_url = f"https://soundcloud.com{href}" if not href.startswith('http') else href
                    
                    # Get track page for metadata
                    try:
                        async with session.get(track_url) as response:
                            track_html = await response.text()
                            
                        track_soup = BeautifulSoup(track_html, 'html.parser')
                        
                        # Extract metadata from meta tags
                        title = None
                        description = None
                        duration = None
                        date = None
                        
                        # Title
                        title_meta = track_soup.find('meta', property='og:title')
                        if title_meta:
                            title = title_meta.get('content', '')
                            
                        # Description
                        desc_meta = track_soup.find('meta', property='og:description')
                        if desc_meta:
                            description = desc_meta.get('content', '')
                            
                        # Duration
                        duration_meta = track_soup.find('meta', property='music:duration')
                        if duration_meta:
                            duration = int(duration_meta.get('content', 0))
                            
                        # Date - look for time tag
                        time_tag = track_soup.find('time')
                        if time_tag:
                            date = time_tag.get('datetime', '')
                            
                        if title:
                            tracks.append({
                                'title': title,
                                'description': description or '',
                                'duration': duration,
                                'created_at': date,
                                'permalink_url': track_url,
                                'id': track_url.split('/')[-1]
                            })
                            
                    except Exception as e:
                        logger.warning(f"Could not scrape track {track_url}: {e}")
                        
        except Exception as e:
            logger.error(f"Error scraping without API: {e}")
            
        return tracks
        
    async def collect(self) -> List[Document]:
        """Collect podcast episodes from SoundCloud."""
        documents = []
        
        # Extract username from URL
        username = self.soundcloud_url.rstrip('/').split('/')[-1]
        
        async with aiohttp.ClientSession() as session:
            # Try API approach first
            self.client_id = await self._extract_client_id(session)
            
            if self.client_id:
                logger.info(f"Found SoundCloud client_id, using API approach")
                
                # Get user info
                user_info = await self._get_user_info(session, username)
                
                if user_info:
                    user_id = user_info.get('id')
                    logger.info(f"Found user: {user_info.get('username')} (ID: {user_id})")
                    
                    # Get tracks
                    tracks = await self._get_user_tracks(session, user_id)
                    logger.info(f"Found {len(tracks)} podcast episodes via API")
                else:
                    logger.warning("Could not get user info, falling back to scraping")
                    tracks = await self._scrape_without_api(session)
            else:
                logger.warning("Could not extract client_id, using scraping approach")
                tracks = await self._scrape_without_api(session)
                
            # Convert tracks to documents
            for track in tracks:
                # Build content
                content_parts = [
                    f"# {track.get('title', 'Untitled')}",
                    "",
                    f"**Episode URL:** {track.get('permalink_url', '')}",
                    f"**Published:** {track.get('created_at', 'Unknown')}",
                ]
                
                if track.get('duration'):
                    duration_min = track['duration'] // 60000  # Convert ms to minutes
                    content_parts.append(f"**Duration:** {duration_min} minutes")
                    
                content_parts.extend([
                    "",
                    "## Description",
                    track.get('description', 'No description available'),
                    "",
                    "## Transcription Status",
                    "*Note: Audio transcription not yet implemented. This document contains metadata only.*"
                ])
                
                # Try to get audio URL if yt-dlp is available
                audio_url = None
                if YTDLP_AVAILABLE and self.config.get('fetch_audio_urls', False):
                    audio_url = await self.get_audio_url(track.get('permalink_url', ''))
                    if audio_url:
                        logger.debug(f"Got audio URL for: {track.get('title')}")
                
                doc = Document(
                    id=f"soundcloud_{track.get('id', '')}",
                    source=f"soundcloud:{username}",
                    source_type="soundcloud",
                    url=track.get('permalink_url', ''),
                    title=track.get('title', 'Untitled'),
                    content="\n".join(content_parts),
                    metadata={
                        'type': 'podcast_episode',
                        'platform': 'soundcloud',
                        'duration_ms': track.get('duration', 0),
                        'created_at': track.get('created_at', ''),
                        'has_transcription': False,
                        'audio_url': audio_url or track.get('stream_url', ''),
                        'audio_available': bool(audio_url),
                        'username': username,
                        'collected_at': datetime.now().isoformat()
                    }
                )
                
                documents.append(doc)
                
                # Apply test limit if configured
                if self.config.get('test_limit') and len(documents) >= self.config['test_limit']:
                    logger.info(f"Reached test limit of {self.config['test_limit']} episodes")
                    break
                    
        logger.info(f"Collected {len(documents)} podcast episodes from SoundCloud")
        return documents
        
    def get_cache_key(self) -> str:
        """Generate cache key for this collector."""
        return f"soundcloud_{self.soundcloud_url.replace('/', '_')}"
        
    async def get_audio_url(self, track_url: str) -> Optional[str]:
        """
        Get direct audio URL using yt-dlp.
        
        Args:
            track_url: SoundCloud track URL
            
        Returns:
            Direct audio URL or None if failed
        """
        if not YTDLP_AVAILABLE:
            return None
            
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'format': 'bestaudio/best',
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(track_url, download=False)
                if info and 'url' in info:
                    return info['url']
                elif info and 'formats' in info:
                    # Get best audio format
                    for fmt in info['formats']:
                        if fmt.get('url'):
                            return fmt['url']
                            
        except Exception as e:
            logger.warning(f"Failed to get audio URL for {track_url}: {e}")
            
        return None
        
    async def download_audio(self, track_url: str, output_path: Path) -> bool:
        """
        Download audio file using yt-dlp.
        
        Args:
            track_url: SoundCloud track URL
            output_path: Path to save audio file
            
        Returns:
            True if successful, False otherwise
        """
        if not YTDLP_AVAILABLE:
            logger.warning("yt-dlp not available for audio download")
            return False
            
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'outtmpl': str(output_path),
                'format': 'bestaudio[ext=mp3]/bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                }] if output_path.suffix == '.mp3' else []
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([track_url])
                
            return output_path.exists()
            
        except Exception as e:
            logger.error(f"Failed to download audio from {track_url}: {e}")
            return False