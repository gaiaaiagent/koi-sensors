#!/usr/bin/env python3
"""
Discourse Forum Sensor for KOI System
Collects discussions from Regen Network Discourse forums
"""

import asyncio
import httpx
import json
import hashlib
import logging
import traceback
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
import time

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import Bundle, document_to_bundle

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('discourse_sensor.log', mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('discourse_sensor')

class DiscourseSensor:
    """
    Sensor for collecting data from Discourse forums
    Supports both forum.regen.network and regencommons.discourse.group
    """
    
    def __init__(self):
        """Initialize Discourse sensor"""
        self.client = httpx.AsyncClient(timeout=30.0)

        # Initialize KOI node for real-time event broadcasting
        self.koi_node = KOIPartialNode(
            node_name="discourse-sensor",
            coordinator_url="http://localhost:8005",
            poll_interval=30
        )

        # Rate limiting to avoid 429 errors
        self.last_request_time = 0
        self.min_request_interval = 1.0  # Minimum 1 second between requests

        self.forums = [
            {
                'name': 'forum.regen.network',
                'url': 'https://forum.regen.network',
                'categories': ['all']  # Fetch all categories
            },
            {
                'name': 'regencommons.discourse.group', 
                'url': 'https://regencommons.discourse.group',
                'categories': ['all']
            }
        ]
        
        # Cache for avoiding duplicates
        self.processed_topics = set()
        self.output_dir = Path(__file__).parent / 'output'
        self.output_dir.mkdir(exist_ok=True)
    
    def generate_rid(self, content: str) -> str:
        """
        Generate RID for content using SHA-256 hash

        Args:
            content: Content to hash

        Returns:
            RID string (first 16 chars of hex hash)
        """
        hash_obj = hashlib.sha256(content.encode('utf-8'))
        return hash_obj.hexdigest()[:16]

    async def rate_limit(self):
        """Enforce rate limiting to avoid 429 errors"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            await asyncio.sleep(self.min_request_interval - time_since_last)
        self.last_request_time = time.time()
    
    async def fetch_categories(self, forum_url: str) -> List[Dict]:
        """
        Fetch list of categories from forum
        
        Args:
            forum_url: Base forum URL
            
        Returns:
            List of category objects
        """
        try:
            await self.rate_limit()  # Apply rate limiting
            response = await self.client.get(
                f"{forum_url}/categories.json",
                headers={'User-Agent': 'Regen-KOI-Sensor/1.0'}
            )
            
            if response.status_code == 200:
                data = response.json()
                categories = data.get('category_list', {}).get('categories', [])
                print(f"Found {len(categories)} categories in {forum_url}")
                return categories
            else:
                print(f"Failed to fetch categories from {forum_url}: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error fetching categories from {forum_url}: {e}")
            logger.debug(traceback.format_exc())
            return []
    
    async def fetch_topics(self, forum_url: str, category: Optional[str] = None, page: int = 0) -> List[Dict]:
        """
        Fetch topics from forum or specific category
        
        Args:
            forum_url: Base forum URL
            category: Category slug (optional)
            page: Page number for pagination
            
        Returns:
            List of topic objects
        """
        try:
            # Build endpoint
            if category and category != 'all':
                endpoint = f"{forum_url}/c/{category}.json"
            else:
                endpoint = f"{forum_url}/latest.json"
            
            # Add pagination
            if page > 0:
                endpoint += f"?page={page}"

            await self.rate_limit()  # Apply rate limiting
            response = await self.client.get(
                endpoint,
                headers={'User-Agent': 'Regen-KOI-Sensor/1.0'}
            )
            
            if response.status_code == 200:
                data = response.json()
                topics = data.get('topic_list', {}).get('topics', [])
                return topics
            else:
                print(f"Failed to fetch topics: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error fetching topics from {forum_url}: {e}")
            logger.debug(traceback.format_exc())
            return []
    
    async def fetch_topic_content(self, forum_url: str, topic_id: int) -> Optional[Dict]:
        """
        Fetch full topic content including ALL posts using pagination

        Args:
            forum_url: Base forum URL
            topic_id: Topic ID

        Returns:
            Topic data with all posts
        """
        try:
            # First fetch to get initial posts and metadata
            await self.rate_limit()  # Apply rate limiting
            response = await self.client.get(
                f"{forum_url}/t/{topic_id}.json",
                headers={'User-Agent': 'Regen-KOI-Sensor/1.0'}
            )

            if response.status_code != 200:
                print(f"Failed to fetch topic {topic_id}: {response.status_code}")
                return None

            topic_data = response.json()
            posts_count = topic_data.get('posts_count', 0)
            current_posts = topic_data.get('post_stream', {}).get('posts', [])

            # If we have all posts already, return
            if len(current_posts) >= posts_count:
                return topic_data

            # Fetch remaining posts in batches
            # The API returns ~20 posts at a time when using /t/{id}/{post_number}.json
            while len(current_posts) < posts_count:
                # Start from the next post after what we have
                next_post_num = len(current_posts) + 1

                await self.rate_limit()  # Apply rate limiting
                response = await self.client.get(
                    f"{forum_url}/t/{topic_id}/{next_post_num}.json",
                    headers={'User-Agent': 'Regen-KOI-Sensor/1.0'}
                )

                if response.status_code != 200:
                    # No more posts available
                    break

                batch_data = response.json()
                new_posts = batch_data.get('post_stream', {}).get('posts', [])

                if not new_posts:
                    break

                # Add new posts that we don't have yet
                existing_ids = {p['id'] for p in current_posts}
                for post in new_posts:
                    if post['id'] not in existing_ids:
                        current_posts.append(post)

                # If we didn't get any new posts, avoid infinite loop
                if len(new_posts) == 0:
                    break

            # Update the topic data with all posts
            topic_data['post_stream']['posts'] = current_posts
            print(f"        Fetched {len(current_posts)}/{posts_count} posts for topic {topic_id}")

            return topic_data

        except Exception as e:
            logger.error(f"Error fetching topic {topic_id} from {forum_url}: {e}")
            logger.debug(traceback.format_exc())
            return None
    
    def extract_text_from_html(self, html: str) -> str:
        """
        Extract plain text from HTML content
        
        Args:
            html: HTML content
            
        Returns:
            Plain text
        """
        # Remove HTML tags
        text = re.sub('<[^<]+?>', '', html)
        # Decode HTML entities
        text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
        text = text.replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&quot;', '"').replace('&#39;', "'")
        text = text.replace('&mdash;', '—').replace('&ndash;', '–')
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def extract_tags(self, topic_data: Dict, content: str) -> List[str]:
        """
        Extract relevant tags from topic
        
        Args:
            topic_data: Topic metadata
            content: Topic content
            
        Returns:
            List of tags
        """
        tags = []
        
        # Add existing tags
        if 'tags' in topic_data:
            tags.extend(topic_data['tags'])
        
        # Content-based tags
        content_lower = content.lower()
        
        if any(term in content_lower for term in ['proposal', 'vote', 'voting', 'governance']):
            tags.append('governance')
        if any(term in content_lower for term in ['credit', 'carbon', 'batch', 'retire']):
            tags.append('ecocredit')
        if any(term in content_lower for term in ['marketplace', 'sell', 'buy', 'trade']):
            tags.append('marketplace')
        if any(term in content_lower for term in ['validator', 'stake', 'delegation']):
            tags.append('validator')
        if any(term in content_lower for term in ['token', 'regen', 'tokenomics']):
            tags.append('tokenomics')
        if any(term in content_lower for term in ['community', 'commons', 'dao']):
            tags.append('community')
        
        return list(set(tags))
    
    async def process_posts_as_documents(self, forum_name: str, forum_url: str, topic: Dict) -> List[Dict]:
        """
        Process a topic and create individual documents for each post

        Args:
            forum_name: Name of the forum
            forum_url: Base forum URL
            topic: Topic metadata

        Returns:
            List of KOI documents (one per post)
        """
        topic_id = topic['id']
        topic_slug = topic.get('slug', '')
        topic_url_full = f"{forum_url}/t/{topic_slug}/{topic_id}"

        # Fetch full topic content
        topic_data = await self.fetch_topic_content(forum_url, topic_id)
        if not topic_data:
            return []

        # Extract posts
        posts = topic_data.get('post_stream', {}).get('posts', [])
        if not posts:
            return []

        topic_title = topic_data.get('title', 'Untitled')
        topic_tags = self.extract_tags(topic_data, "")  # Get topic-level tags

        documents = []

        # Create a document for each post
        for post in posts:
            post_id = post.get('id')
            post_number = post.get('post_number', 0)

            # Skip if already processed
            post_key = f"{forum_name}:{topic_id}:post_{post_number}"
            if post_key in self.processed_topics:
                continue

            # Extract post data
            username = post.get('username', 'anonymous')
            created = post.get('created_at', '')
            html_content = post.get('cooked', '')

            # Parse post date
            post_date = None
            if created:
                try:
                    post_date = datetime.fromisoformat(created.replace('Z', '+00:00'))
                except:
                    post_date = datetime.now(timezone.utc)
            else:
                post_date = datetime.now(timezone.utc)

            # Convert HTML to text
            text = self.extract_text_from_html(html_content)

            # Generate unique RID for this post
            rid = self.generate_rid(f"{forum_name}:{topic_id}:post_{post_number}:{username}:{created}")

            # Create document for this individual post
            document = {
                'id': f"{forum_name}_{topic_id}_post_{post_number}",
                'rid': rid,
                'source': f'discourse:{forum_name}',
                'source_type': 'forum-post',
                'url': f"{topic_url_full}/{post_number}",
                'title': f"Re: {topic_title}" if post_number > 1 else topic_title,
                'content': text,
                'author': username,
                'timestamp': post_date.isoformat(),
                'metadata': {
                    # Publication date for this specific post
                    'published_at': post_date.isoformat(),
                    'published_confidence': 0.95,

                    # Topic context
                    'forum': forum_name,
                    'topic_id': topic_id,
                    'topic_title': topic_title,
                    'topic_url': topic_url_full,
                    'post_id': post_id,
                    'post_number': post_number,
                    'is_first_post': post_number == 1,

                    # Post metadata
                    'reply_to_post_number': post.get('reply_to_post_number'),
                    'reply_count': post.get('reply_count', 0),
                    'reads': post.get('reads', 0),
                    'readers_count': post.get('readers_count', 0),
                    'score': post.get('score', 0),
                    'like_count': post.get('like_count', 0),

                    # Inherit topic tags
                    'tags': topic_tags,
                    'category': topic_data.get('category_id')
                }
            }

            documents.append(document)
            self.processed_topics.add(post_key)

        return documents

    async def process_topic(self, forum_name: str, forum_url: str, topic: Dict) -> Optional[Dict]:
        """
        Process a single topic and create KOI document
        (Legacy method kept for backwards compatibility)

        Args:
            forum_name: Name of the forum
            forum_url: Base forum URL
            topic: Topic metadata

        Returns:
            KOI document or None
        """
        topic_id = topic['id']
        topic_slug = topic.get('slug', '')
        
        # Check if already processed
        topic_key = f"{forum_name}:{topic_id}"
        if topic_key in self.processed_topics:
            return None
        
        # Fetch full topic content
        topic_data = await self.fetch_topic_content(forum_url, topic_id)
        if not topic_data:
            return None
        
        # Extract posts
        posts = topic_data.get('post_stream', {}).get('posts', [])
        if not posts:
            return None
        
        # Build content
        title = topic_data.get('title', 'Untitled')
        content_parts = [f"# {title}\n"]

        # Track the latest post date for published_at
        latest_post_date = None

        # Process all posts (no limit - we want complete discussion threads)
        for post in posts:
            username = post.get('username', 'anonymous')
            created = post.get('created_at', '')
            html_content = post.get('cooked', '')

            # Track latest post date
            if created:
                try:
                    post_date = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    if not latest_post_date or post_date > latest_post_date:
                        latest_post_date = post_date
                except:
                    pass

            # Convert HTML to text
            text = self.extract_text_from_html(html_content)

            # Format post
            content_parts.append(f"\n## Post by {username} ({created})\n{text}\n")

        content = '\n'.join(content_parts)
        
        # Create document
        topic_url_full = f"{forum_url}/t/{topic_slug}/{topic_id}"
        
        # Generate RID
        rid = self.generate_rid(f"{forum_name}:{topic_id}:{title}")
        
        # Extract tags
        tags = self.extract_tags(topic_data, content)
        
        # Parse dates
        created_at = None
        if topic_data.get('created_at'):
            try:
                created_at = datetime.fromisoformat(
                    topic_data['created_at'].replace('Z', '+00:00')
                ).isoformat()
            except:
                created_at = datetime.now().isoformat()

        # Use the latest post date as the published_at date
        # This ensures recent activity is captured in daily digests
        published_at = None
        if latest_post_date:
            published_at = latest_post_date.isoformat()
        elif topic_data.get('last_posted_at'):
            try:
                published_at = datetime.fromisoformat(
                    topic_data['last_posted_at'].replace('Z', '+00:00')
                ).isoformat()
            except:
                published_at = created_at
        else:
            published_at = created_at

        document = {
            'id': f"{forum_name}_{topic_id}",  # Add id field for RID generation
            'rid': rid,
            'source': f'discourse:{forum_name}',
            'source_type': 'forum',
            'url': topic_url_full,
            'title': title,
            'content': content,
            'author': posts[0].get('username') if posts else 'anonymous',
            'timestamp': published_at or datetime.now().isoformat(),  # Use latest activity
            'metadata': {
                # Publication date metadata for Daily Curator
                'published_at': published_at,  # Latest post date for recent activity
                'published_confidence': 0.95,  # High confidence for API data
                'topic_created_at': created_at,  # Original topic creation
                'last_modified': published_at,
                
                'forum': forum_name,
                'topic_id': topic_id,
                'category': topic_data.get('category_id'),
                'posts_count': len(posts),
                'views': topic_data.get('views', 0),
                'like_count': topic_data.get('like_count', 0),
                'reply_count': topic_data.get('reply_count', 0),
                'tags': tags,
                'pinned': topic_data.get('pinned', False),
                'archived': topic_data.get('archived', False)
            }
        }
        
        # Mark as processed
        self.processed_topics.add(topic_key)
        
        return document
    
    async def collect_forum(self, forum_config: Dict, limit: int = 50) -> List[Dict]:
        """
        Collect documents from a single forum
        
        Args:
            forum_config: Forum configuration
            limit: Maximum number of topics to collect
            
        Returns:
            List of KOI documents
        """
        forum_name = forum_config['name']
        forum_url = forum_config['url']
        
        print(f"\n📡 Collecting from {forum_name}")
        print(f"   URL: {forum_url}")
        
        documents = []
        
        # Fetch categories if needed
        if 'all' in forum_config.get('categories', ['all']):
            categories = await self.fetch_categories(forum_url)
            # Process main categories (limit to important ones)
            category_slugs = [cat['slug'] for cat in categories[:10]]
        else:
            category_slugs = forum_config['categories']
        
        # Add 'latest' to get recent topics across all categories
        category_slugs = ['latest'] + category_slugs
        
        # Collect topics from each category
        topics_collected = 0
        for category in category_slugs:
            if topics_collected >= limit:
                break
            
            print(f"   📂 Category: {category}")
            
            # Fetch topics (with pagination)
            for page in range(3):  # Check first 3 pages
                if topics_collected >= limit:
                    break
                
                topics = await self.fetch_topics(forum_url, category if category != 'latest' else None, page)
                
                if not topics:
                    break
                
                # Process topics
                for topic in topics:
                    if topics_collected >= limit:
                        break

                    # Get individual post documents for this topic
                    post_docs = await self.process_posts_as_documents(forum_name, forum_url, topic)
                    if post_docs:
                        documents.extend(post_docs)
                        topics_collected += 1
                        print(f"      ✅ Collected {len(post_docs)} posts from: {topic.get('title', 'Untitled')[:50]}...")
        
        print(f"   📊 Total posts collected: {len(documents)} from {topics_collected} topics")
        return documents
    
    
    async def run(self, limit_per_forum: int = 20):
        """
        Run the Discourse sensor
        
        Args:
            limit_per_forum: Maximum topics to collect per forum
        """
        print("=" * 60)
        print("🌐 DISCOURSE FORUM SENSOR")
        print("=" * 60)
        
        all_documents = []
        
        # Collect from each forum
        for forum_config in self.forums:
            try:
                docs = await self.collect_forum(forum_config, limit_per_forum)
                all_documents.extend(docs)
            except Exception as e:
                logger.error(f"Error collecting from {forum_config['name']}: {e}")
                logger.debug(traceback.format_exc())
                print(f"❌ Error collecting from {forum_config['name']}: {e}")
        
        print("\n" + "=" * 60)
        print(f"📊 COLLECTION SUMMARY")
        print(f"   Total documents: {len(all_documents)}")
        
        if all_documents:
            # Save to file
            output_file = self.output_dir / f"discourse_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(output_file, 'w') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'source': 'discourse_sensor',
                    'document_count': len(all_documents),
                    'documents': all_documents
                }, f, indent=2)
            print(f"   💾 Saved to: {output_file}")
            
            # Send to KOI coordinator
            await self.send_to_koi(all_documents)
            print(f"   ✅ Documents saved locally and sent to KOI coordinator")
        
        print("=" * 60)

    async def send_to_koi(self, documents: List[Dict]):
        """Send documents to KOI coordinator as events"""
        try:
            # Initialize session for KOI node if not started
            if not hasattr(self, 'koi_started'):
                # Don't call start() which creates infinite polling loop
                # Just initialize the session for sending events
                import aiohttp
                self.koi_node.session = aiohttp.ClientSession()
                self.koi_node.running = True
                self.koi_started = True

                # Send heartbeat to register
                await self.send_heartbeat()

                # Start background tasks for periodic heartbeats and coordinator event handling
                heartbeat_task = asyncio.create_task(self.send_periodic_heartbeats())
                coordinator_task = asyncio.create_task(self.handle_coordinator_events())

            # Send each document as an event
            for doc in documents:
                try:
                    # Use the RID from the document if available
                    if 'rid' in doc:
                        rid_str = doc['rid']
                    else:
                        # Create RID for the discourse post using document ID
                        doc_id = doc.get('id', '').replace(':', '_').replace('.', '_')
                        rid_str = f"discourse_{doc_id}"

                    # Ensure required fields for KOI bundle
                    if 'content' not in doc or not doc['content']:
                        doc['content'] = doc.get('title', 'No content')

                    # Ensure content is a string
                    if not isinstance(doc['content'], str):
                        doc['content'] = str(doc['content'])

                    # Ensure rid field exists
                    if 'rid' not in doc or not doc['rid']:
                        doc['rid'] = rid_str

                    try:
                        bundle = document_to_bundle(doc, source_node="discourse-sensor")
                    except Exception as bundle_error:
                        logger.error(f"Bundle creation failed for {doc.get('id')}: {bundle_error}")
                        logger.error(f"Document structure: {list(doc.keys())}")
                        continue

                    # Emit event
                    await self.koi_node.emit_new_event(bundle)

                except Exception as e:
                    logger.error(f"Error sending document to KOI: {e}")
                    logger.error(f"Document ID: {doc.get('id', 'NO_ID')}")
                    logger.error(f"Document keys: {list(doc.keys())}")
                    logger.debug(traceback.format_exc())
                    print(f"   ⚠️ Error sending document {doc.get('id', 'NO_ID')} to KOI: {e}")

            print(f"   📡 Sent {len(documents)} documents to KOI coordinator")

        except Exception as e:
            logger.error(f"Error connecting to KOI coordinator: {e}")
            logger.debug(traceback.format_exc())
            print(f"   ❌ Error connecting to KOI coordinator: {e}")

    async def send_heartbeat(self, response_to: Optional[str] = None):
        """Send heartbeat event to register with coordinator

        Args:
            response_to: Optional RID to respond to for ping requests
        """
        try:
            heartbeat_data = {
                "type": "sensor_heartbeat",
                "sensor": "discourse",
                "node_id": "discourse-sensor",
                "forums": [f['name'] for f in self.forums],
                "timestamp": datetime.now().isoformat(),
                "status": "active"
            }

            # Add response_to if this is a ping response
            if response_to:
                heartbeat_data["response_to"] = response_to

            # Create proper document structure for heartbeat
            heartbeat_document = {
                'id': f"discourse_heartbeat_{int(datetime.now().timestamp())}",
                'source': 'discourse_sensor',
                'source_type': 'heartbeat',
                'title': 'Discourse Sensor Heartbeat',
                'url': '',
                'content': json.dumps(heartbeat_data),
                'timestamp': datetime.now().isoformat(),
                'metadata': {
                    'sensor_type': 'discourse',
                    'sensor_id': 'discourse-sensor',
                    'event_type': 'HEARTBEAT'
                }
            }

            # Create bundle from heartbeat document
            bundle = document_to_bundle(heartbeat_document, source_node="discourse-sensor")

            # Emit event
            await self.koi_node.emit_new_event(bundle)
            if response_to:
                print(f"   💓 Sent ping response heartbeat to KOI coordinator (responding to {response_to})")
            else:
                print("   💓 Sent heartbeat to KOI coordinator")

        except Exception as e:
            logger.error(f"Error sending heartbeat: {e}")
            logger.debug(traceback.format_exc())
            print(f"   ⚠️ Error sending heartbeat: {e}")

    async def send_periodic_heartbeats(self):
        """Send periodic heartbeats every 30 minutes"""
        while True:
            try:
                await asyncio.sleep(1800)  # 30 minutes
                await self.send_heartbeat()
                print("💓 Sent periodic heartbeat")
            except asyncio.CancelledError:
                print("🛑 Periodic heartbeat task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in periodic heartbeat: {e}")
                logger.debug(traceback.format_exc())
                print(f"❌ Error in periodic heartbeat: {e}")

    async def handle_coordinator_events(self):
        """Listen for and handle coordinator events like ping requests"""
        while True:
            try:
                # KOIPartialNode doesn't have poll_coordinator_events, skip for now
                await asyncio.sleep(30)
                continue

                # Check for coordinator events
                # events = await self.koi_node.poll_coordinator_events()

                # for event in events:
                #     event_type = event.get('event_type')

                #     if event_type == 'PING_REQUEST':
                #         # Check if ping is for this sensor
                #         target_sensor = event.get('target_sensor')
                #         if target_sensor == 'discourse-sensor' or target_sensor == 'discourse':
                #             print(f"📡 Received ping request: {event.get('rid')}")
                #             # Respond with heartbeat
                #             await self.send_heartbeat(response_to=event.get('rid'))

                # await asyncio.sleep(30)  # Check every 30 seconds

            except asyncio.CancelledError:
                print("🛑 Coordinator event handler cancelled")
                break
            except Exception as e:
                logger.error(f"Error handling coordinator events: {e}")
                logger.debug(traceback.format_exc())
                print(f"❌ Error handling coordinator events: {e}")
                await asyncio.sleep(30)

    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.client.aclose()
        # Close KOI node session if initialized
        if hasattr(self, 'koi_started') and self.koi_node.session:
            await self.koi_node.session.close()


async def main():
    """Main entry point with continuous polling"""
    import os
    from dotenv import load_dotenv

    # Load environment variables
    load_dotenv()

    # Get polling interval (default 1 hour)
    poll_interval = int(os.getenv('DISCOURSE_POLL_INTERVAL', 3600))

    async with DiscourseSensor() as sensor:
        print(f"Starting Discourse sensor with {poll_interval} second polling interval")

        while True:
            try:
                await sensor.run(limit_per_forum=20)
                print(f"\n⏰ Next collection in {poll_interval} seconds ({poll_interval/60:.1f} minutes)")
                await asyncio.sleep(poll_interval)

            except KeyboardInterrupt:
                print("\n🛑 Received interrupt signal, shutting down...")
                break
            except Exception as e:
                logger.error(f"Error in collection cycle: {e}")
                logger.error(f"Full traceback: {traceback.format_exc()}")
                print(f"❌ Error in collection cycle: {e}")
                print(f"⏰ Retrying in {poll_interval} seconds...")
                await asyncio.sleep(poll_interval)


if __name__ == "__main__":
    try:
        logger.info("Starting Discourse Sensor")
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Fatal error in discourse sensor: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(1)