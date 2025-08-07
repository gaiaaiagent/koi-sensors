"""
Discourse forum collector for Regen Network forums
"""

import asyncio
import httpx
from typing import Dict, List, Optional, Any
from datetime import datetime
from loguru import logger
import json

from .base_collector import BaseCollector, Document

# Handle both relative and absolute imports
try:
    from ..utils.credential_manager import get_credential_manager
except ImportError:
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent.parent))
    from utils.credential_manager import get_credential_manager


class DiscourseCollector(BaseCollector):
    """
    Collector for Discourse forum posts and topics
    Works with or without API key (rate limits apply without key)
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Discourse collector
        
        Args:
            config: Forum configuration from sources.yaml
        """
        super().__init__(config)
        self.forums = config.get('forums', [])
        self.cred_manager = get_credential_manager()
        self.client = httpx.AsyncClient(timeout=30.0)
    
    def validate_config(self) -> bool:
        """
        Validate Discourse collector configuration
        """
        if not self.forums:
            logger.error("No forums configured")
            return False
        
        for forum in self.forums:
            if 'url' not in forum:
                logger.error(f"Forum missing URL: {forum}")
                return False
            if 'name' not in forum:
                logger.error(f"Forum missing name: {forum}")
                return False
        
        return True
    
    async def collect(self, limit: Optional[int] = None) -> List[Document]:
        """
        Collect documents from configured Discourse forums
        
        Args:
            limit: Maximum number of documents to collect
            
        Returns:
            List of collected documents
        """
        if not self.validate_config():
            return []
        
        all_documents = []
        doc_count = 0
        
        for forum_config in self.forums:
            if limit and doc_count >= limit:
                break
            
            try:
                forum_docs = await self.collect_forum(
                    forum_config,
                    limit - doc_count if limit else None
                )
                all_documents.extend(forum_docs)
                doc_count += len(forum_docs)
                
                # Save documents after each forum
                self.save_documents(forum_docs)
                
            except Exception as e:
                logger.error(f"Error collecting forum {forum_config['name']}: {e}")
                continue
        
        logger.info(f"Collected {len(all_documents)} documents from {len(self.forums)} forums")
        return all_documents
    
    async def collect_forum(self, forum_config: Dict[str, Any], limit: Optional[int] = None) -> List[Document]:
        """
        Collect documents from a single Discourse forum
        
        Args:
            forum_config: Forum configuration
            limit: Maximum number of documents to collect
            
        Returns:
            List of documents from the forum
        """
        forum_name = forum_config['name']
        forum_url = forum_config['url'].rstrip('/')
        categories = forum_config.get('categories', ['all'])
        
        logger.info(f"Collecting from {forum_name} ({forum_url})")
        
        # Get API key if configured
        api_key = None
        if 'api_key' in forum_config:
            api_key_var = forum_config['api_key'].strip('${}')
            api_key = self.cred_manager.get(api_key_var, source=forum_name)
            if api_key:
                logger.debug(f"Using API key for {forum_name}")
            else:
                logger.info(f"No API key for {forum_name}, using anonymous access (rate limits apply)")
        
        documents = []
        doc_count = 0
        
        # Get categories to process
        if 'all' in categories:
            # Fetch all categories
            category_list = await self.fetch_categories(forum_url, api_key)
        else:
            # Use specified categories
            category_list = categories
        
        # Collect topics from each category
        for category in category_list:
            if limit and doc_count >= limit:
                break
            
            # Get category slug/id
            category_slug = category if isinstance(category, str) else category.get('slug', str(category.get('id', '')))
            
            # Fetch topics in category
            topics = await self.fetch_topics(forum_url, category_slug, api_key)
            
            for topic in topics[:min(10, limit - doc_count) if limit else 10]:  # Limit topics per category
                if limit and doc_count >= limit:
                    break
                
                # Skip if already cached
                topic_url = f"{forum_url}/t/{topic.get('slug', '')}/{topic.get('id', '')}"
                if self.is_cached(topic_url):
                    logger.debug(f"Skipping cached topic: {topic.get('title', '')}")
                    continue
                
                # Fetch full topic with posts
                doc = await self.fetch_topic_content(forum_url, topic, forum_name, api_key)
                if doc:
                    documents.append(doc)
                    doc_count += 1
        
        logger.info(f"Collected {len(documents)} documents from {forum_name}")
        return documents
    
    async def fetch_categories(self, forum_url: str, api_key: Optional[str] = None) -> List[Dict]:
        """
        Fetch list of categories from forum
        
        Args:
            forum_url: Base forum URL
            api_key: Optional API key
            
        Returns:
            List of category objects
        """
        try:
            headers = self._get_headers(api_key)
            response = await self.client.get(f"{forum_url}/categories.json", headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                categories = data.get('category_list', {}).get('categories', [])
                logger.debug(f"Found {len(categories)} categories")
                return categories
            else:
                logger.warning(f"Failed to fetch categories: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error fetching categories: {e}")
            return []
    
    async def fetch_topics(self, forum_url: str, category: str, api_key: Optional[str] = None) -> List[Dict]:
        """
        Fetch topics from a category
        
        Args:
            forum_url: Base forum URL
            category: Category slug or 'latest' for all
            api_key: Optional API key
            
        Returns:
            List of topic objects
        """
        try:
            headers = self._get_headers(api_key)
            
            # Determine endpoint
            if category == 'all' or not category:
                endpoint = f"{forum_url}/latest.json"
            else:
                endpoint = f"{forum_url}/c/{category}.json"
            
            response = await self.client.get(endpoint, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                topics = data.get('topic_list', {}).get('topics', [])
                logger.debug(f"Found {len(topics)} topics in {category}")
                return topics
            else:
                logger.warning(f"Failed to fetch topics from {category}: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error fetching topics from {category}: {e}")
            return []
    
    async def fetch_topic_content(self, forum_url: str, topic: Dict, forum_name: str, 
                                 api_key: Optional[str] = None) -> Optional[Document]:
        """
        Fetch full topic content including posts
        
        Args:
            forum_url: Base forum URL
            topic: Topic object
            forum_name: Forum name for source tracking
            api_key: Optional API key
            
        Returns:
            Document object or None
        """
        try:
            topic_id = topic.get('id')
            topic_slug = topic.get('slug', '')
            topic_title = topic.get('title', 'Untitled')
            
            headers = self._get_headers(api_key)
            response = await self.client.get(f"{forum_url}/t/{topic_id}.json", headers=headers)
            
            if response.status_code != 200:
                logger.warning(f"Failed to fetch topic {topic_id}: {response.status_code}")
                return None
            
            data = response.json()
            
            # Extract posts
            posts = data.get('post_stream', {}).get('posts', [])
            if not posts:
                return None
            
            # Combine post content
            content_parts = [f"# {topic_title}\n"]
            
            for post in posts[:20]:  # Limit to first 20 posts
                username = post.get('username', 'anonymous')
                created = post.get('created_at', '')
                cooked = post.get('cooked', '')  # HTML content
                
                # Convert HTML to text (basic conversion)
                import re
                text = re.sub('<[^<]+?>', '', cooked)  # Strip HTML tags
                text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
                text = text.replace('&lt;', '<').replace('&gt;', '>')
                text = text.replace('&quot;', '"').replace('&#39;', "'")
                
                content_parts.append(f"\n## Post by {username} ({created})\n{text}\n")
            
            content = '\n'.join(content_parts)
            
            # Create document
            topic_url = f"{forum_url}/t/{topic_slug}/{topic_id}"
            
            # Parse dates
            created_at = None
            if topic.get('created_at'):
                try:
                    created_at = datetime.fromisoformat(topic['created_at'].replace('Z', '+00:00'))
                except:
                    pass
            
            doc = Document(
                id="",  # Auto-generated
                source=f"discourse:{forum_name}",
                source_type="discourse",
                url=topic_url,
                title=topic_title,
                content=content,
                metadata={
                    "forum": forum_name,
                    "topic_id": topic_id,
                    "category": topic.get('category_id'),
                    "posts_count": topic.get('posts_count', 1),
                    "views": topic.get('views', 0),
                    "like_count": topic.get('like_count', 0),
                    "reply_count": topic.get('reply_count', 0),
                    "pinned": topic.get('pinned', False),
                    "archived": topic.get('archived', False)
                },
                last_modified=created_at,
                author=posts[0].get('username') if posts else None,
                tags=self.extract_tags_from_topic(topic, content)
            )
            
            logger.debug(f"Processed topic: {topic_title} ({len(content)} bytes)")
            return doc
            
        except Exception as e:
            logger.error(f"Error fetching topic content: {e}")
            return None
    
    def _get_headers(self, api_key: Optional[str] = None) -> Dict[str, str]:
        """
        Get request headers with optional API key
        
        Args:
            api_key: Optional API key
            
        Returns:
            Headers dictionary
        """
        headers = {
            'User-Agent': 'Regen-Indexer/1.0',
            'Accept': 'application/json'
        }
        
        if api_key:
            headers['Api-Key'] = api_key
            headers['Api-Username'] = 'system'
        
        return headers
    
    def extract_tags_from_topic(self, topic: Dict, content: str) -> List[str]:
        """
        Extract relevant tags from topic metadata and content
        
        Args:
            topic: Topic metadata
            content: Topic content
            
        Returns:
            List of tags
        """
        tags = []
        
        # Add topic tags if present
        if topic.get('tags'):
            tags.extend(topic['tags'])
        
        # Add category as tag
        if topic.get('category_id'):
            tags.append(f"category-{topic['category_id']}")
        
        # Extract tags based on content
        content_lower = content.lower()
        
        keywords = {
            'governance': ['proposal', 'vote', 'voting', 'governance', 'dao'],
            'ecocredit': ['credit', 'carbon', 'offset', 'climate', 'batch'],
            'marketplace': ['marketplace', 'sell', 'buy', 'trade', 'listing'],
            'validator': ['validator', 'stake', 'delegation', 'commission'],
            'technical': ['bug', 'issue', 'feature', 'api', 'sdk'],
            'community': ['community', 'event', 'announcement', 'update']
        }
        
        for tag, terms in keywords.items():
            if any(term in content_lower for term in terms):
                tags.append(tag)
        
        return list(set(tags))  # Remove duplicates
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close HTTP client"""
        await self.client.aclose()