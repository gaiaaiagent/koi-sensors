#!/usr/bin/env python3
"""
Discourse Forum Sensor for KOI System with Full KOI Integration
Collects discussions from Regen Network Discourse forums and sends to KOI coordinator
"""

import asyncio
import httpx
import json
import hashlib
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
import re
import sys

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import Bundle, document_to_bundle


class DiscourseKOISensor:
    """
    Sensor for collecting data from Discourse forums with KOI integration
    Supports both forum.regen.network and hub.regencoordination.xyz
    """
    
    def __init__(self):
        """Initialize Discourse sensor with KOI integration"""
        self.client = httpx.AsyncClient(timeout=30.0)
        self.forums = [
            {
                'name': 'forum.regen.network',
                'url': 'https://forum.regen.network',
                'categories': ['all']  # Fetch all categories
            },
            {
                'name': 'hub.regencoordination.xyz',
                'url': 'https://hub.regencoordination.xyz',
                'categories': ['33']  # Regen Commons category only
            }
        ]
        
        # Initialize KOI node for sending events
        self.koi_node = KOIPartialNode(
            node_name="discourse-sensor",
            coordinator_url="http://localhost:8005"
        )
        
        # Cache for avoiding duplicates
        self.processed_topics = set()
        self.output_dir = Path(__file__).parent / 'output'
        self.output_dir.mkdir(exist_ok=True)
    
    def generate_rid(self, content: str) -> str:
        """Generate RID for content using SHA-256 hash"""
        hash_obj = hashlib.sha256(content.encode('utf-8'))
        return hash_obj.hexdigest()[:16]
    
    async def fetch_topics(self, forum_url: str, category: Optional[str] = None, page: int = 0) -> List[Dict]:
        """Fetch topics from forum or specific category"""
        try:
            # Build endpoint
            if category and category != 'all':
                endpoint = f"{forum_url}/c/{category}.json"
            else:
                endpoint = f"{forum_url}/latest.json"
            
            # Add pagination
            if page > 0:
                endpoint += f"?page={page}"
            
            response = await self.client.get(
                endpoint,
                headers={'User-Agent': 'Regen-KOI-Sensor/1.0'}
            )
            
            if response.status_code == 200:
                data = response.json()
                topics = data.get('topic_list', {}).get('topics', [])
                return topics
            else:
                return []
                
        except Exception as e:
            print(f"Error fetching topics: {e}")
            return []
    
    async def fetch_topic_details(self, forum_url: str, topic_id: int) -> Optional[Dict]:
        """Fetch detailed topic with posts"""
        try:
            response = await self.client.get(
                f"{forum_url}/t/{topic_id}.json",
                headers={'User-Agent': 'Regen-KOI-Sensor/1.0'}
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return None
                
        except Exception as e:
            print(f"Error fetching topic {topic_id}: {e}")
            return None
    
    async def process_topic(self, forum_url: str, forum_name: str, topic_data: Dict) -> List[Dict]:
        """Process a topic and create KOI bundles for each post"""
        topic_id = topic_data.get('id')
        topic_slug = topic_data.get('slug', '')
        title = topic_data.get('title', 'Untitled')

        # Skip if already processed
        topic_key = f"{forum_name}:{topic_id}"
        if topic_key in self.processed_topics:
            return []

        # Fetch full topic details
        details = await self.fetch_topic_details(forum_url, topic_id)
        if not details:
            return []

        # Extract posts
        posts = details.get('post_stream', {}).get('posts', [])
        if not posts:
            return []

        documents = []
        topic_url_base = f"{forum_url}/t/{topic_slug}/{topic_id}"

        # Process each post as a separate document
        for post in posts[:20]:  # Limit to first 20 posts
            post_number = post.get('post_number', 1)
            post_id = post.get('id')
            username = post.get('username', 'anonymous')
            created = post.get('created_at', '')
            updated = post.get('updated_at', created)
            text = post.get('cooked', '')  # HTML content

            # Strip HTML tags but preserve structure
            text = re.sub('<[^<]+?>', '', text).strip()

            # Skip empty posts
            if not text or len(text) < 50:
                continue

            # Generate unique RID for this post
            rid = f"orn:discourse.post.{self.generate_rid(f'{forum_name}:{topic_id}:{post_id}')}"

            # Parse dates
            created_at = None
            if created:
                try:
                    created_at = datetime.fromisoformat(
                        created.replace('Z', '+00:00')
                    ).isoformat()
                except:
                    created_at = datetime.now().isoformat()

            # Build post URL
            post_url = f"{topic_url_base}/{post_number}"

            # Create document for this post
            document = {
                'rid': rid,
                'source': f'discourse:{forum_name}',
                'source_type': 'discourse',
                'url': post_url,
                'title': f"{title} - Post #{post_number} by {username}",
                'content': text,
                'author': username,
                'timestamp': created_at or datetime.now().isoformat(),
                'metadata': {
                    # Post-specific metadata
                    'post_id': post_id,
                    'post_number': post_number,
                    'post_url': post_url,
                    'author': username,
                    'author_id': post.get('user_id'),
                    'created_at': created,
                    'updated_at': updated,
                    'reply_to_post_number': post.get('reply_to_post_number'),
                    'reply_count': post.get('reply_count', 0),
                    'quote_count': post.get('quote_count', 0),
                    'like_count': post.get('actions_summary', [{}])[0].get('count', 0) if post.get('actions_summary') else 0,
                    'reads': post.get('reads', 0),

                    # Topic context
                    'forum': forum_name,
                    'topic_id': topic_id,
                    'topic_slug': topic_slug,
                    'topic_title': title,
                    'category': topic_data.get('category_slug', 'general'),
                    'topic_views': topic_data.get('views', 0),
                    'topic_reply_count': topic_data.get('reply_count', 0),
                    'topic_like_count': topic_data.get('like_count', 0),

                    # Confidence for publication date
                    'published_at': created_at,
                    'published_confidence': 0.9  # High confidence for API data
                }
            }

            documents.append(document)

        self.processed_topics.add(topic_key)
        return documents
    
    async def send_to_koi(self, document: Dict) -> bool:
        """Send document to KOI coordinator as bundle"""
        try:
            # Create bundle from document
            bundle = document_to_bundle(document)
            
            # Emit as NEW event through KOI node
            await self.koi_node.emit_new_event(bundle)
            
            print(f"   📤 Sent to KOI: {document['title'][:50]}...")
            return True
            
        except Exception as e:
            print(f"   ❌ Failed to send to KOI: {e}")
            return False
    
    async def collect_forum(self, forum_config: Dict, limit: int = 20) -> int:
        """Collect topics from a single forum and send to KOI"""
        forum_name = forum_config['name']
        forum_url = forum_config['url']

        print(f"\n📡 Collecting from {forum_name}")
        print(f"   URL: {forum_url}")

        sent_count = 0

        try:
            # Fetch latest topics
            topics = await self.fetch_topics(forum_url)

            print(f"   📂 Found {len(topics)} topics")

            for topic in topics[:limit]:
                # Process topic - now returns list of documents (one per post)
                documents = await self.process_topic(forum_url, forum_name, topic)

                if documents:
                    print(f"   📝 Processing {len(documents)} posts from topic: {topic.get('title', 'Unknown')[:50]}...")

                    # Send each post document to KOI
                    for doc in documents:
                        if await self.send_to_koi(doc):
                            sent_count += 1

                    await asyncio.sleep(1)  # Rate limiting between topics

            print(f"   ✅ Sent {sent_count} posts to KOI")

        except Exception as e:
            print(f"   ❌ Error collecting from {forum_name}: {e}")

        return sent_count
    
    async def run(self, limit_per_forum: int = 20):
        """Run the Discourse sensor with KOI integration"""
        print("=" * 60)
        print("🌐 DISCOURSE FORUM SENSOR (KOI Integrated)")
        print("=" * 60)
        
        # Start KOI node
        await self.koi_node.start()
        
        total_sent = 0
        
        # Collect from each forum
        for forum_config in self.forums:
            sent = await self.collect_forum(forum_config, limit_per_forum)
            total_sent += sent
        
        print("\n" + "=" * 60)
        print(f"📊 COLLECTION SUMMARY")
        print(f"   Total posts sent to KOI: {total_sent}")
        print("=" * 60)
        
        # Stop KOI node
        await self.koi_node.stop()
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.client.aclose()


async def main():
    """Main entry point for continuous monitoring"""
    async with DiscourseKOISensor() as sensor:
        while True:
            print(f"\n🕐 Starting collection cycle at {datetime.now().isoformat()}")
            await sensor.run(limit_per_forum=10)
            
            # Wait 30 minutes before next collection
            print("\n💤 Waiting 30 minutes before next collection...")
            await asyncio.sleep(1800)  # 30 minutes


if __name__ == "__main__":
    asyncio.run(main())