#!/usr/bin/env python3
"""
Discourse Forum Sensor for KOI System
Collects discussions from Regen Network Discourse forums
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

from indexing.koi_client import KOIClient


class DiscourseSensor:
    """
    Sensor for collecting data from Discourse forums
    Supports both forum.regen.network and regencommons.discourse.group
    """
    
    def __init__(self):
        """Initialize Discourse sensor"""
        self.koi_client = KOIClient()
        self.client = httpx.AsyncClient(timeout=30.0)
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
    
    async def fetch_categories(self, forum_url: str) -> List[Dict]:
        """
        Fetch list of categories from forum
        
        Args:
            forum_url: Base forum URL
            
        Returns:
            List of category objects
        """
        try:
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
            print(f"Error fetching categories: {e}")
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
            print(f"Error fetching topics: {e}")
            return []
    
    async def fetch_topic_content(self, forum_url: str, topic_id: int) -> Optional[Dict]:
        """
        Fetch full topic content including all posts
        
        Args:
            forum_url: Base forum URL
            topic_id: Topic ID
            
        Returns:
            Topic data with posts
        """
        try:
            response = await self.client.get(
                f"{forum_url}/t/{topic_id}.json",
                headers={'User-Agent': 'Regen-KOI-Sensor/1.0'}
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Failed to fetch topic {topic_id}: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"Error fetching topic {topic_id}: {e}")
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
    
    async def process_topic(self, forum_name: str, forum_url: str, topic: Dict) -> Optional[Dict]:
        """
        Process a single topic and create KOI document
        
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
        
        # Process posts (limit to first 30 for reasonable size)
        for post in posts[:30]:
            username = post.get('username', 'anonymous')
            created = post.get('created_at', '')
            html_content = post.get('cooked', '')
            
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
        
        # Parse date
        created_at = None
        if topic_data.get('created_at'):
            try:
                created_at = datetime.fromisoformat(
                    topic_data['created_at'].replace('Z', '+00:00')
                ).isoformat()
            except:
                created_at = datetime.now().isoformat()
        
        # Extract updated_at if available
        updated_at = None
        if topic_data.get('updated_at'):
            try:
                updated_at = datetime.fromisoformat(
                    topic_data['updated_at'].replace('Z', '+00:00')
                ).isoformat()
            except:
                updated_at = created_at
        
        document = {
            'rid': rid,
            'source': f'discourse:{forum_name}',
            'source_type': 'forum',
            'url': topic_url_full,
            'title': title,
            'content': content,
            'author': posts[0].get('username') if posts else 'anonymous',
            'timestamp': created_at or datetime.now().isoformat(),
            'metadata': {
                # Publication date metadata for Daily Curator
                'published_at': created_at,  # Discourse API provides exact timestamps
                'published_confidence': 0.95,  # High confidence for API data
                'last_modified': updated_at,
                
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
                    
                    doc = await self.process_topic(forum_name, forum_url, topic)
                    if doc:
                        documents.append(doc)
                        topics_collected += 1
                        print(f"      ✅ Collected: {doc['title'][:50]}...")
        
        print(f"   📊 Total topics collected: {len(documents)}")
        return documents
    
    async def send_to_koi(self, documents: List[Dict]) -> bool:
        """
        Send documents to KOI Event Bridge
        
        Args:
            documents: List of documents to send
            
        Returns:
            True if successful
        """
        success_count = 0
        
        for doc in documents:
            event_data = {
                'event_type': 'discourse_topic',
                'source': doc['source'],
                'timestamp': doc['timestamp'],
                'data': doc
            }
            
            success = await self.koi_client.send_event(
                event_type='discourse_topic',
                data=event_data
            )
            
            if success:
                success_count += 1
        
        print(f"\n📤 Sent {success_count}/{len(documents)} documents to KOI Event Bridge")
        return success_count == len(documents)
    
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
            
            # Send to KOI
            await self.send_to_koi(all_documents)
        
        print("=" * 60)
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.client.aclose()


async def main():
    """Main entry point"""
    async with DiscourseSensor() as sensor:
        await sensor.run(limit_per_forum=20)


if __name__ == "__main__":
    asyncio.run(main())