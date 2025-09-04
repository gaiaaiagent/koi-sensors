#!/usr/bin/env python3
"""
Crawl forum.regen.network using JSON API (no authentication required)
"""

import asyncio
import httpx
from typing import List, Dict, Optional
import json
from pathlib import Path
from loguru import logger
import sys
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from collectors.base_collector import Document


class ForumJSONCrawler:
    """Crawl forum.regen.network using public JSON API"""
    
    def __init__(self):
        self.base_url = "https://forum.regen.network"
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                'User-Agent': 'Regen-Indexer/1.0',
                'Accept': 'application/json'
            }
        )
        self.storage_dir = Path(__file__).parent.parent / "storage"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    async def fetch_json(self, endpoint: str) -> Optional[Dict]:
        """Fetch JSON from endpoint"""
        try:
            url = f"{self.base_url}{endpoint}" if endpoint.startswith('/') else endpoint
            response = await self.client.get(url)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Failed to fetch {url}: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching {endpoint}: {e}")
            return None
    
    async def get_categories(self) -> List[Dict]:
        """Get list of categories"""
        data = await self.fetch_json("/categories.json")
        if data and 'category_list' in data:
            categories = data['category_list'].get('categories', [])
            logger.info(f"Found {len(categories)} categories")
            return categories
        return []
    
    async def get_latest_topics(self, page: int = 0) -> List[Dict]:
        """Get latest topics from homepage"""
        data = await self.fetch_json(f"/latest.json?page={page}")
        if data and 'topic_list' in data:
            topics = data['topic_list'].get('topics', [])
            logger.info(f"Found {len(topics)} topics on page {page}")
            return topics
        return []
    
    async def get_category_topics(self, category_slug: str) -> List[Dict]:
        """Get topics from a specific category"""
        # Try different endpoint formats
        endpoints = [
            f"/c/{category_slug}.json",
            f"/c/{category_slug}/l/latest.json",
        ]
        
        for endpoint in endpoints:
            data = await self.fetch_json(endpoint)
            if data and 'topic_list' in data:
                topics = data['topic_list'].get('topics', [])
                if topics:
                    logger.info(f"Found {len(topics)} topics in category {category_slug}")
                    return topics
        
        return []
    
    async def get_topic_details(self, topic_id: int) -> Optional[Dict]:
        """Get full topic with posts"""
        data = await self.fetch_json(f"/t/{topic_id}.json")
        return data
    
    def process_topic_to_document(self, topic_data: Dict) -> Optional[Document]:
        """Convert topic JSON to Document"""
        try:
            # Extract basic info
            topic_id = topic_data.get('id')
            title = topic_data.get('title', 'Untitled')
            slug = topic_data.get('slug', '')
            
            # Extract posts
            post_stream = topic_data.get('post_stream', {})
            posts = post_stream.get('posts', [])
            
            if not posts:
                logger.warning(f"No posts in topic: {title}")
                return None
            
            # Build content from posts
            content_parts = [f"# {title}\n"]
            
            for i, post in enumerate(posts[:20], 1):  # Limit to 20 posts
                username = post.get('username', 'unknown')
                created = post.get('created_at', '')
                cooked = post.get('cooked', '')  # HTML content
                
                # Basic HTML stripping
                import re
                text = re.sub('<[^<]+?>', '', cooked)
                text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
                text = text.replace('&lt;', '<').replace('&gt;', '>')
                text = text.replace('&quot;', '"').replace('&#39;', "'")
                text = text.strip()
                
                if text:  # Only add non-empty posts
                    content_parts.append(f"\n## Post {i} by {username}")
                    if created:
                        content_parts.append(f"*{created}*")
                    content_parts.append(f"\n{text}\n")
            
            content = '\n'.join(content_parts)
            
            # Build URL
            url = f"{self.base_url}/t/{slug}/{topic_id}" if slug else f"{self.base_url}/t/{topic_id}"
            
            # Extract metadata
            category_id = topic_data.get('category_id')
            views = topic_data.get('views', 0)
            posts_count = topic_data.get('posts_count', len(posts))
            
            # Create document
            doc = Document(
                id=f"forum-regen-{topic_id}",
                source="forum.regen.network",
                source_type="forum",
                url=url,
                title=title,
                content=content,
                metadata={
                    'forum': 'regen-forum',
                    'topic_id': topic_id,
                    'category_id': category_id,
                    'posts_count': posts_count,
                    'views': views,
                    'pinned': topic_data.get('pinned', False),
                    'archived': topic_data.get('archived', False),
                    'crawled_at': datetime.now().isoformat()
                },
                author=posts[0].get('username') if posts else None,
                tags=topic_data.get('tags', [])
            )
            
            return doc
            
        except Exception as e:
            logger.error(f"Error processing topic: {e}")
            return None
    
    def save_documents(self, documents: List[Document]):
        """Save documents to JSON file"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = self.storage_dir / f"forum_crawl_{timestamp}.json"
        
        data = {
            'source': 'forum.regen.network',
            'timestamp': datetime.now().isoformat(),
            'document_count': len(documents),
            'documents': [
                {
                    'id': doc.id,
                    'source': doc.source,
                    'source_type': doc.source_type,
                    'url': doc.url,
                    'title': doc.title,
                    'content': doc.content,
                    'metadata': doc.metadata,
                    'author': doc.author,
                    'tags': doc.tags,
                    'last_modified': doc.last_modified.isoformat() if doc.last_modified else None
                }
                for doc in documents
            ]
        }
        
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.success(f"Saved {len(documents)} documents to {output_file}")
        return output_file
    
    async def crawl(self, limit: int = 50, include_categories: bool = True):
        """Main crawl function"""
        logger.info(f"Starting forum crawl (limit={limit})")
        
        all_topics = []
        
        # 1. Get latest topics
        logger.info("Fetching latest topics...")
        latest = await self.get_latest_topics()
        all_topics.extend(latest)
        
        # 2. Get topics from important categories
        if include_categories:
            important_categories = ['governance', 'regen-coin', 'regen-registry', 'regen-foundation']
            
            for cat_slug in important_categories:
                logger.info(f"Fetching topics from {cat_slug}...")
                cat_topics = await self.get_category_topics(cat_slug)
                all_topics.extend(cat_topics)
        
        # Remove duplicates
        seen_ids = set()
        unique_topics = []
        for topic in all_topics:
            topic_id = topic.get('id')
            if topic_id and topic_id not in seen_ids:
                seen_ids.add(topic_id)
                unique_topics.append(topic)
        
        logger.info(f"Found {len(unique_topics)} unique topics")
        
        # 3. Fetch full details for each topic
        documents = []
        for i, topic in enumerate(unique_topics[:limit]):
            topic_id = topic.get('id')
            title = topic.get('title', 'Unknown')
            
            logger.info(f"[{i+1}/{min(limit, len(unique_topics))}] Fetching: {title[:60]}...")
            
            # Get full topic data
            topic_data = await self.get_topic_details(topic_id)
            if topic_data:
                doc = self.process_topic_to_document(topic_data)
                if doc:
                    documents.append(doc)
                    logger.success(f"  ✅ Processed: {doc.title[:60]}...")
                else:
                    logger.warning(f"  ⚠️ Could not process topic")
            
            # Small delay to be respectful
            await asyncio.sleep(0.2)
        
        # 4. Save documents
        if documents:
            output_file = self.save_documents(documents)
            logger.success(f"\n✅ Successfully crawled {len(documents)} forum topics")
            
            # Show summary
            total_size = sum(len(d.content) for d in documents)
            logger.info(f"\nSummary:")
            logger.info(f"  Documents: {len(documents)}")
            logger.info(f"  Total content: {total_size:,} bytes")
            logger.info(f"  Output file: {output_file}")
            
            # Show sample documents
            logger.info(f"\nSample documents:")
            for doc in documents[:5]:
                logger.info(f"  - {doc.title[:70]}...")
                logger.info(f"    Posts: {doc.metadata.get('posts_count', 0)}, Views: {doc.metadata.get('views', 0)}")
        else:
            logger.warning("❌ No documents crawled")
        
        return documents
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        await self.client.aclose()


async def main():
    """Main function"""
    logger.info("=" * 60)
    logger.info("Forum.regen.network JSON Crawler (No Auth Required)")
    logger.info("=" * 60)
    
    async with ForumJSONCrawler() as crawler:
        # Start with a small test
        documents = await crawler.crawl(limit=20, include_categories=True)
        
        if documents:
            logger.success(f"\n✅ Crawl successful!")
            logger.info("\nTo crawl more documents, increase the limit:")
            logger.info("  await crawler.crawl(limit=100)")
            logger.info("\nTo integrate with main indexing system:")
            logger.info("  python indexing/scripts/run_collection.py")


if __name__ == "__main__":
    asyncio.run(main())