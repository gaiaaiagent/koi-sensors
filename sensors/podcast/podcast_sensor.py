#!/usr/bin/env python3
"""
KOI Podcast Sensor - Real-time monitoring for Planetary Regeneration Podcast
Based on proven server implementation at /server-project/indexing/podcast
"""

import asyncio
import aiohttp
import re
import json
import hashlib
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# KOI Protocol imports
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID, ORN
from koi_protocol.core.bundle_system import Bundle, document_to_bundle

# Audio transcription (optional)
try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False


class PodcastEpisodeRID(ORN):
    """Podcast episode RID: orn:podcast.episode:platform/episode_id"""
    namespace = "podcast.episode"
    
    def __init__(self, platform: str, episode_id: str):
        self.platform = platform
        self.episode_id = episode_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.platform}/{self.episode_id}"


class PodcastKOISensor:
    """KOI-compliant podcast monitoring sensor"""
    
    # Default episodes from server implementation
    PLANETARY_REGEN_PODCAST = {
        "name": "planetary-regeneration", 
        "url": "https://soundcloud.com/planetaryregeneration",
        "description": "The Planetary Regeneration Podcast - 70+ episodes",
        "check_interval": 86400,  # 24 hours (podcasts don't change frequently)
        "priority": "medium"
    }
    
    def __init__(self, node_id: str = "koi-podcast-sensor", coordinator_url: str = "http://localhost:8000"):
        self.node_id = node_id
        self.coordinator_url = coordinator_url
        
        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name="podcast-sensor",
            coordinator_url=coordinator_url,
            poll_interval=30
        )
        
        # Podcast monitoring state
        self.monitored_podcasts: Dict[str, Dict[str, Any]] = {}
        self.episode_hashes: Dict[str, str] = {}  # episode_id -> content hash
        
        # SoundCloud API state
        self.soundcloud_client_id: Optional[str] = None
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Add default podcast
        self.add_podcast(**self.PLANETARY_REGEN_PODCAST)
        
        print(f"🎧 KOI Podcast Sensor initialized")
        print(f"   Node ID: {self.node_id}")
        print(f"   Coordinator: {self.coordinator_url}")
        print(f"   Default: Planetary Regeneration Podcast")
    
    def add_podcast(self, name: str, url: str, description: str = "", 
                   check_interval: int = 86400, priority: str = "medium"):
        """Add a podcast to monitor"""
        self.monitored_podcasts[name] = {
            "url": url,
            "description": description,
            "check_interval": check_interval,
            "priority": priority,
            "last_check": None,
            "episode_count": 0
        }
    
    async def send_heartbeat_event(self, response_to: str = None):
        """Send a heartbeat event to register with coordinator"""
        try:
            heartbeat_data = {
                "type": "sensor_heartbeat",
                "sensor_id": self.node_id,
                "sensor_type": "podcast",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "active",
                "monitoring": list(self.monitored_podcasts.keys()),
                "episode_count": sum(p.get('episode_count', 0) for p in self.monitored_podcasts.values())
            }

            if response_to:
                heartbeat_data["response_to"] = response_to

            # Create document for heartbeat
            heartbeat_document = {
                'id': f"podcast_heartbeat_{int(datetime.now().timestamp())}",
                'title': 'Podcast Sensor Heartbeat',
                'url': '',
                'type': 'heartbeat',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'content': json.dumps(heartbeat_data),
                'metadata': {
                    'sensor_type': 'podcast',
                    'sensor_id': self.node_id,
                    'event_type': 'HEARTBEAT'
                }
            }

            # Convert to bundle and emit
            bundle = document_to_bundle(heartbeat_document, self.koi_node.node_id)
            await self.koi_node.emit_new_event(bundle)

            if not response_to:
                print("💓 Sent heartbeat event to coordinator")
            else:
                print(f"🏓 Responded to ping request {response_to}")

        except Exception as e:
            print(f"❌ Error sending heartbeat: {e}")

    async def send_periodic_heartbeats(self):
        """Send periodic heartbeats every 30 minutes"""
        while True:
            await asyncio.sleep(1800)  # 30 minutes
            await self.send_heartbeat_event()

    async def handle_coordinator_events(self):
        """Listen for ping requests from coordinator"""
        try:
            # Subscribe to coordinator events
            async for event in self.koi_node.event_stream():
                if event.get('type') == 'PING_REQUEST':
                    # Check if this ping is for us
                    target = event.get('target')
                    if target == self.node_id or target == 'podcast-sensor' or target == 'all':
                        print(f"🏓 Received ping request, responding...")
                        await self.send_heartbeat_event(response_to=event.get('id'))
        except Exception as e:
            print(f"❌ Error handling coordinator events: {e}")

    async def start_monitoring(self):
        """Start podcast monitoring"""
        await self.koi_node.start()

        # Send initial heartbeat to register
        await self.send_heartbeat_event()

        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60),
            headers={'User-Agent': 'KOI-PodcastSensor/1.0'}
        )

        # Start background tasks
        tasks = []

        # Periodic heartbeat task
        tasks.append(asyncio.create_task(self.send_periodic_heartbeats()))

        # Ping response handler task
        tasks.append(asyncio.create_task(self.handle_coordinator_events()))

        # Monitoring loops for each podcast
        for podcast_name in self.monitored_podcasts.keys():
            task = asyncio.create_task(self.monitor_podcast(podcast_name))
            tasks.append(task)

        await asyncio.gather(*tasks)
    
    async def stop_monitoring(self):
        """Stop podcast monitoring"""
        if self.session:
            await self.session.close()
        await self.koi_node.stop()
    
    async def monitor_podcast(self, podcast_name: str):
        """Monitor a specific podcast for new episodes"""
        podcast_config = self.monitored_podcasts[podcast_name]
        
        while True:
            try:
                print(f"\n🎧 Checking podcast: {podcast_name}")
                await self.check_podcast_episodes(podcast_name)
                
                # Wait before next check
                await asyncio.sleep(podcast_config["check_interval"])
                
            except Exception as e:
                print(f"❌ Error monitoring {podcast_name}: {e}")
                await asyncio.sleep(300)  # 5 minute error backoff
    
    async def check_podcast_episodes(self, podcast_name: str):
        """Check for new or updated episodes"""
        podcast_config = self.monitored_podcasts[podcast_name]
        url = podcast_config["url"]
        
        if "soundcloud.com" in url:
            episodes = await self.collect_soundcloud_episodes(url)
        else:
            print(f"⚠️  Unsupported podcast platform: {url}")
            return
        
        print(f"   Found {len(episodes)} episodes")
        
        # Process each episode
        new_episodes = 0
        updated_episodes = 0
        
        for episode in episodes:
            event_type = await self.process_episode(podcast_name, episode)
            if event_type == "NEW":
                new_episodes += 1
            elif event_type == "UPDATE":
                updated_episodes += 1
        
        # Update podcast state
        podcast_config["last_check"] = datetime.now().isoformat()
        podcast_config["episode_count"] = len(episodes)
        
        print(f"   ✅ {new_episodes} new, {updated_episodes} updated episodes")
    
    async def collect_soundcloud_episodes(self, soundcloud_url: str) -> List[Dict[str, Any]]:
        """Collect episodes from SoundCloud using proven server methods"""
        episodes = []
        
        # Extract username from URL
        username = soundcloud_url.rstrip('/').split('/')[-1]
        
        try:
            # Try to get SoundCloud client_id for API access
            if not self.soundcloud_client_id:
                self.soundcloud_client_id = await self._extract_soundcloud_client_id(soundcloud_url)
            
            if self.soundcloud_client_id:
                # Use SoundCloud API (preferred method)
                episodes = await self._collect_via_soundcloud_api(username)
            else:
                # Fallback to scraping
                episodes = await self._collect_via_scraping(soundcloud_url)
                
        except Exception as e:
            print(f"❌ Error collecting SoundCloud episodes: {e}")
        
        return episodes
    
    async def _extract_soundcloud_client_id(self, soundcloud_url: str) -> Optional[str]:
        """Extract SoundCloud client_id from JavaScript (from server implementation)"""
        try:
            async with self.session.get(soundcloud_url) as response:
                html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            scripts = soup.find_all('script', src=True)
            
            for script in scripts:
                script_url = script['src']
                if not script_url.startswith('http'):
                    script_url = f"https://soundcloud.com{script_url}"
                
                async with self.session.get(script_url) as response:
                    js_content = await response.text()
                
                # Look for client_id pattern
                match = re.search(r'client_id["\']?\s*[:=]\s*["\']([a-zA-Z0-9]+)["\']', js_content)
                if match:
                    return match.group(1)
        
        except Exception as e:
            print(f"⚠️  Could not extract SoundCloud client_id: {e}")
        
        return None
    
    async def _collect_via_soundcloud_api(self, username: str) -> List[Dict[str, Any]]:
        """Collect episodes via SoundCloud API"""
        episodes = []
        
        try:
            # Resolve user
            api_base = "https://api-v2.soundcloud.com"
            resolve_url = f"{api_base}/resolve"
            params = {
                'url': f"https://soundcloud.com/{username}",
                'client_id': self.soundcloud_client_id
            }
            
            async with self.session.get(resolve_url, params=params) as response:
                if response.status == 200:
                    user_info = await response.json()
                    user_id = user_info.get('id')
                    
                    # Get tracks
                    tracks_url = f"{api_base}/users/{user_id}/tracks"
                    params = {
                        'client_id': self.soundcloud_client_id,
                        'limit': 200,  # Increased to get all episodes (server uses 200)
                        'offset': 0,
                        'linked_partitioning': 1  # Enable pagination to get ALL episodes
                    }
                    
                    # Implement pagination to get ALL episodes (like server does)
                    all_tracks = []
                    while True:
                        async with self.session.get(tracks_url, params=params) as response:
                            if response.status != 200:
                                break
                                
                            data = await response.json()
                            collection = data.get('collection', [])
                            
                            if not collection:
                                break
                                
                            all_tracks.extend(collection)
                            
                            # Check for next page
                            next_href = data.get('next_href')
                            if not next_href:
                                break
                            
                            # Update URL for next page
                            tracks_url = next_href
                            params = {}  # Clear params, next_href has everything
                    
                    episodes = all_tracks
        
        except Exception as e:
            print(f"❌ SoundCloud API error: {e}")
        
        return episodes
    
    async def _collect_via_scraping(self, soundcloud_url: str) -> List[Dict[str, Any]]:
        """Fallback scraping method"""
        episodes = []
        
        try:
            async with self.session.get(soundcloud_url) as response:
                html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # Look for track links (simplified for this implementation)
            track_links = soup.find_all('a', href=True)
            
            for link in track_links:
                href = link.get('href', '')
                if '/planetaryregeneration/' in href and href.count('/') >= 2:
                    track_url = f"https://soundcloud.com{href}" if not href.startswith('http') else href
                    
                    # Extract basic metadata from URL
                    track_id = href.split('/')[-1]
                    episodes.append({
                        'id': track_id,
                        'title': track_id.replace('-', ' ').title(),
                        'permalink_url': track_url,
                        'created_at': datetime.now().isoformat(),
                        'duration': None,
                        'description': ''
                    })
        
        except Exception as e:
            print(f"❌ Scraping error: {e}")
        
        return episodes
    
    async def process_episode(self, podcast_name: str, episode_data: Dict[str, Any]) -> str:
        """Process a single episode and emit KOI events"""
        episode_id = str(episode_data.get('id', ''))
        title = episode_data.get('title', 'Untitled Episode')
        
        # Generate RID
        rid = PodcastEpisodeRID("soundcloud", episode_id)
        
        # Build episode content
        content = self.build_episode_content(episode_data)
        
        # Check for changes
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        existing_hash = self.episode_hashes.get(episode_id)
        
        if existing_hash is None:
            # New episode
            event_type = "NEW"
            self.episode_hashes[episode_id] = content_hash
            await self.emit_episode_event(rid, episode_data, content, "NEW")
            print(f"   📄 NEW: {title[:50]}...")
            
        elif existing_hash != content_hash:
            # Updated episode
            event_type = "UPDATE"  
            self.episode_hashes[episode_id] = content_hash
            await self.emit_episode_event(rid, episode_data, content, "UPDATE")
            print(f"   🔄 UPDATE: {title[:50]}...")
            
        else:
            # No change
            event_type = "NO_CHANGE"
        
        return event_type
    
    def build_episode_content(self, episode_data: Dict[str, Any]) -> str:
        """Build episode content from metadata"""
        title = episode_data.get('title', 'Untitled Episode')
        description = episode_data.get('description', 'No description available')
        url = episode_data.get('permalink_url', '')
        created_at = episode_data.get('created_at', '')
        duration = episode_data.get('duration', 0)
        
        # Convert duration
        duration_str = "Unknown"
        if duration:
            duration_min = duration // 60000  # Convert ms to minutes
            duration_str = f"{duration_min} minutes"
        
        content_parts = [
            f"# {title}",
            "",
            f"**Episode URL:** {url}",
            f"**Published:** {created_at}",
            f"**Duration:** {duration_str}",
            "",
            "## Description",
            description,
            "",
            "## Transcript Status",
            "🔄 *Transcript monitoring enabled - will detect when transcript becomes available*",
            "",
            "## KOI Metadata",
            f"- Platform: SoundCloud",
            f"- Episode ID: {episode_data.get('id', 'Unknown')}",
            f"- Content Type: Podcast Episode",
            f"- Monitoring Status: Active"
        ]
        
        return "\n".join(content_parts)
    
    async def emit_episode_event(self, rid: PodcastEpisodeRID, episode_data: Dict[str, Any], 
                                content: str, event_type: str):
        """Emit KOI event for podcast episode"""
        try:
            # Parse publication date from created_at
            created_at = episode_data.get('created_at', '')
            published_at = None
            confidence = 0.0
            
            if created_at:
                try:
                    from dateutil import parser
                    published_at = parser.parse(created_at)
                    confidence = 0.95  # High confidence for API-provided dates
                except:
                    pass
            
            # Create document in server-compatible format
            document = {
                "id": f"podcast_{episode_data.get('id', '')}",
                "source": f"podcast:soundcloud:planetaryregeneration",
                "source_type": "podcast",
                "url": episode_data.get('permalink_url', ''),
                "title": episode_data.get('title', 'Untitled Episode'),
                "content": content,
                "metadata": {
                    # Publication date metadata for Daily Curator
                    "published_at": published_at.isoformat() if published_at else None,
                    "published_confidence": confidence,
                    
                    # Original metadata
                    "type": "podcast_episode",
                    "platform": "soundcloud",
                    "episode_id": str(episode_data.get('id', '')),
                    "duration_ms": episode_data.get('duration', 0),
                    "created_at": episode_data.get('created_at', ''),
                    "has_transcript": False,  # Will be updated when transcript detected
                    "audio_url": episode_data.get('stream_url', ''),
                    "podcast_name": "Planetary Regeneration Podcast",
                    "collected_at": datetime.now().isoformat(),
                    "rid": rid.to_orn()
                }
            }
            
            # Convert to KOI Bundle
            bundle = document_to_bundle(document, self.koi_node.node_id)
            
            # Emit appropriate event
            if event_type == "NEW":
                await self.koi_node.emit_new_event(bundle)
            elif event_type == "UPDATE":
                await self.koi_node.emit_update_event(bundle)
            
        except Exception as e:
            print(f"❌ Error emitting episode event: {e}")


# Test configuration matching server setup
PODCAST_CONFIG = {
    "sensor": {
        "name": "podcast-sensor",
        "type": "podcast", 
        "node_id": "koi-sensor-podcast-001",
        "coordinator_url": "http://localhost:8000"
    },
    
    "podcasts": [
        {
            "name": "planetary-regeneration",
            "url": "https://soundcloud.com/planetaryregeneration",
            "description": "The Planetary Regeneration Podcast - 70+ episodes with transcripts",
            "check_interval": 86400,  # 24 hours
            "priority": "medium",
            "current_status": "52 transcripts available, 18 missing - monitored for updates",
            "notes": "Uses proven SoundCloud collection methods from server"
        }
    ],
    
    "processing": {
        "user_agent": "KOI-Sensor-PodcastMonitor/1.0",
        "request_delay": 2.0,
        "timeout": 60,
        "retry_attempts": 3
    },
    
    "transcription": {
        "enabled": False,  # Transcription monitoring only for now
        "whisper_model": "base",
        "auto_transcribe": False,
        "notes": "Full transcription available via server implementation"
    }
}