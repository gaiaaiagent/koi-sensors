#!/usr/bin/env python3
"""
Crawl regencommons.discourse.group forum
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


class RegenCommonsForumCrawler:
    """Crawl regencommons.discourse.group using public JSON API"""
    
    def __init__(self):
        self.base_url = "https://regencommons.discourse.group"
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
    
    async def test_connection(self) -> bool:
        """Test if we can connect to the forum"""
        try:
            response = await self.client.get(f"{self.base_url}/categories.json")
            if response.status_code == 200:
                data = response.json()
                categories = data.get('category_list', {}).get('categories', [])
                logger.success(f"✅ Connected! Found {len(categories)} categories")
                for cat in categories[:5]:
                    logger.info(f"  - {cat.get('name')} (id: {cat.get('id')})")
                return True
            else:
                logger.error(f"❌ Failed to connect: HTTP {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            return False
    
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
    
    async def get_latest_topics(self) -> List[Dict]:
        """Get latest topics"""
        data = await self.fetch_json("/latest.json")
        if data and 'topic_list' in data:
            topics = data['topic_list'].get('topics', [])
            logger.info(f"Found {len(topics)} latest topics")
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
            
            # Create document
            doc = Document(
                id=f"forum-regencommons-{topic_id}",
                source="regencommons.discourse.group",
                source_type="forum",
                url=url,
                title=title,
                content=content,
                metadata={
                    'forum': 'regencommons-forum',
                    'topic_id': topic_id,
                    'category_id': topic_data.get('category_id'),
                    'posts_count': topic_data.get('posts_count', len(posts)),
                    'views': topic_data.get('views', 0),
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
    
    async def crawl(self, limit: int = 50):
        """Main crawl function"""
        logger.info(f"Starting RegenCommons forum crawl (limit={limit})")
        
        # Test connection first
        if not await self.test_connection():
            logger.error("Cannot connect to forum")
            return []
        
        # Get latest topics
        topics = await self.get_latest_topics()
        
        if not topics:
            logger.warning("No topics found")
            return []
        
        logger.info(f"Processing up to {min(limit, len(topics))} topics...")
        
        # Fetch full details for each topic
        documents = []
        for i, topic in enumerate(topics[:limit]):
            topic_id = topic.get('id')
            title = topic.get('title', 'Unknown')
            
            logger.info(f"[{i+1}/{min(limit, len(topics))}] Fetching: {title[:60]}...")
            
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
        
        # Save documents
        if documents:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = self.storage_dir / f"regencommons_crawl_{timestamp}.json"
            
            data = {
                'source': 'regencommons.discourse.group',
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
            
            # Update manifest
            await self.update_manifest(output_file, len(documents), len(topics))
            
            # Show summary
            total_size = sum(len(d.content) for d in documents)
            logger.info(f"\nSummary:")
            logger.info(f"  Documents: {len(documents)}")
            logger.info(f"  Total content: {total_size:,} bytes ({total_size/1024/1024:.1f} MB)")
            
            # Show sample documents
            logger.info(f"\nSample documents:")
            for doc in documents[:5]:
                logger.info(f"  - {doc.title[:70]}...")
                logger.info(f"    Posts: {doc.metadata.get('posts_count', 0)}, Views: {doc.metadata.get('views', 0)}")
        else:
            logger.warning("❌ No documents crawled")
        
        return documents
    
    async def update_manifest(self, output_file: Path, doc_count: int, total_available: int):
        """Update manifest with RegenCommons data"""
        manifest_file = self.storage_dir / "manifest.json"
        
        # Load existing manifest
        if manifest_file.exists():
            with open(manifest_file, 'r') as f:
                manifest = json.load(f)
        else:
            manifest = {
                'source': 'discourse',
                'forums': []
            }
        
        # Add RegenCommons if not present
        if not any(f['url'] == self.base_url for f in manifest.get('forums', [])):
            manifest['forums'].append({
                'name': 'regencommons.discourse.group',
                'url': self.base_url
            })
        
        # Update data files
        if 'data_files' not in manifest:
            manifest['data_files'] = []
        
        # Add new file info
        file_info = {
            'filename': output_file.name,
            'forum': 'regencommons',
            'type': 'full_run' if doc_count >= total_available * 0.8 else 'partial_run',
            'timestamp': datetime.now().isoformat(),
            'topics_count': doc_count,
            'size_bytes': output_file.stat().st_size,
            'description': f'RegenCommons forum crawl - {doc_count} topics'
        }
        
        manifest['data_files'].append(file_info)
        
        # Update stats
        if 'stats' not in manifest:
            manifest['stats'] = {}
        
        manifest['stats']['regencommons'] = {
            'total_topics': doc_count,
            'last_updated': datetime.now().isoformat()
        }
        
        # Save manifest
        with open(manifest_file, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        logger.info(f"Updated manifest with RegenCommons data")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        await self.client.aclose()


async def main():
    """Main function"""
    logger.info("=" * 60)
    logger.info("RegenCommons Forum Crawler")
    logger.info("=" * 60)
    
    async with RegenCommonsForumCrawler() as crawler:
        # Start with all available topics
        documents = await crawler.crawl(limit=100)  # Get up to 100 topics
        
        if documents:
            logger.success(f"\n✅ Successfully crawled {len(documents)} RegenCommons topics!")
        else:
            logger.error("\n❌ Failed to crawl RegenCommons forum")


if __name__ == "__main__":
    asyncio.run(main())