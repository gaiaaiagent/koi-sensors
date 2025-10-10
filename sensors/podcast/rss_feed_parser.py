#!/usr/bin/env python3
"""
RSS Feed Parser for Podcast Episodes
Extracts episode metadata and direct MP3 download URLs from RSS feeds
"""

import aiohttp
import feedparser
from typing import List, Dict, Any
from datetime import datetime


async def fetch_rss_episodes(rss_url: str) -> List[Dict[str, Any]]:
    """
    Fetch and parse podcast episodes from RSS feed

    Args:
        rss_url: URL to podcast RSS feed

    Returns:
        List of episode dictionaries with metadata and direct MP3 URLs
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(rss_url) as response:
            response.raise_for_status()
            rss_content = await response.text()

    # Parse RSS feed
    feed = feedparser.parse(rss_content)

    episodes = []
    for entry in feed.entries:
        # Extract SoundCloud track ID from RSS ID format: tag:soundcloud,2010:tracks/2078695880
        raw_id = entry.get('id', entry.get('link', ''))
        track_id = raw_id
        if 'tracks/' in raw_id:
            track_id = raw_id.split('tracks/')[-1]

        # Extract episode metadata
        episode = {
            'id': track_id,  # Use numeric track ID
            'raw_id': raw_id,  # Keep original for reference
            'title': entry.get('title', 'Untitled'),
            'description': entry.get('summary', entry.get('description', '')),
            'permalink_url': entry.get('link', ''),
            'created_at': entry.get('published', ''),
            'duration': 0,  # Will be set from audio if available
            'direct_mp3_url': None,
        }

        # Extract direct MP3 URL from enclosure
        if hasattr(entry, 'enclosures') and entry.enclosures:
            for enclosure in entry.enclosures:
                if 'audio' in enclosure.get('type', ''):
                    episode['direct_mp3_url'] = enclosure.get('href', enclosure.get('url'))
                    # Try to get duration from enclosure
                    if 'length' in enclosure:
                        try:
                            # Length is in bytes, we need duration in ms
                            # We'll get actual duration from Whisper during transcription
                            pass
                        except:
                            pass
                    break

        # Parse published date
        if entry.get('published_parsed'):
            try:
                dt = datetime(*entry.published_parsed[:6])
                episode['created_at'] = dt.isoformat()
            except:
                pass

        # Extract duration from iTunes tags if available
        if hasattr(entry, 'itunes_duration'):
            try:
                # Duration can be in HH:MM:SS or seconds
                duration_str = entry.itunes_duration
                if ':' in duration_str:
                    parts = duration_str.split(':')
                    if len(parts) == 3:  # HH:MM:SS
                        hours, minutes, seconds = map(int, parts)
                        episode['duration'] = (hours * 3600 + minutes * 60 + seconds) * 1000
                    elif len(parts) == 2:  # MM:SS
                        minutes, seconds = map(int, parts)
                        episode['duration'] = (minutes * 60 + seconds) * 1000
                else:
                    episode['duration'] = int(float(duration_str)) * 1000
            except:
                pass

        # Only add episodes that have a direct MP3 URL
        if episode['direct_mp3_url']:
            episodes.append(episode)

    return episodes


async def get_planetary_regeneration_episodes() -> List[Dict[str, Any]]:
    """
    Get all episodes from Planetary Regeneration podcast RSS feed

    Returns:
        List of episode dictionaries
    """
    rss_url = "https://feeds.soundcloud.com/users/soundcloud:users:672989060/sounds.rss"
    return await fetch_rss_episodes(rss_url)


if __name__ == "__main__":
    import asyncio

    async def test():
        print("Fetching Planetary Regeneration episodes from RSS feed...")
        episodes = await get_planetary_regeneration_episodes()

        print(f"\n✓ Found {len(episodes)} episodes\n")

        # Show first 3 episodes
        for i, ep in enumerate(episodes[:3], 1):
            print(f"{i}. {ep['title']}")
            print(f"   ID: {ep['id']}")
            print(f"   Published: {ep['created_at']}")
            print(f"   Direct MP3: {ep['direct_mp3_url'][:80]}...")
            print(f"   Duration: {ep['duration'] / 1000:.0f}s" if ep['duration'] else "   Duration: Unknown")
            print()

    asyncio.run(test())
