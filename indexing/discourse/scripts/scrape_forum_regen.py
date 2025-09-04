#!/usr/bin/env python3
"""
Web scraping approach for forum.regen.network
Works without API key by using public HTML pages
"""

import asyncio
import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import json
from pathlib import Path
from loguru import logger
import sys
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from collectors.base_collector import Document


class ForumWebScraper:
    """Scrape forum.regen.network using HTML parsing"""
    
    def __init__(self):
        self.base_url = "https://forum.regen.network"
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,  # Important for handling 301s
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; RegenIndexer/1.0)'
            }
        )
        self.storage_dir = Path(__file__).parent.parent / "storage" / "forum_scrape"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    async def fetch_page(self, url: str) -> Optional[str]:
        """Fetch HTML content from URL"""
        try:
            response = await self.client.get(url)
            if response.status_code == 200:
                return response.text
            else:
                logger.warning(f"Failed to fetch {url}: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    async def scrape_homepage(self) -> List[Dict]:
        """Scrape homepage for latest topics"""
        logger.info("Scraping forum homepage for topics...")
        
        html = await self.fetch_page(self.base_url)
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        topics = []
        
        # Find topic list items
        topic_elements = soup.select('tr.topic-list-item')
        
        for elem in topic_elements[:30]:  # Limit to 30 topics
            try:
                # Extract topic link and title
                link_elem = elem.select_one('a.title')
                if not link_elem:
                    continue
                
                title = link_elem.get_text(strip=True)
                href = link_elem.get('href', '')
                
                # Build full URL
                if href.startswith('/'):
                    topic_url = self.base_url + href
                else:
                    topic_url = href
                
                # Extract metadata
                category_elem = elem.select_one('.category-name')
                category = category_elem.get_text(strip=True) if category_elem else 'uncategorized'
                
                # Extract post count and activity
                posts_elem = elem.select_one('.posts span.number')
                posts_count = posts_elem.get_text(strip=True) if posts_elem else '0'
                
                topics.append({
                    'title': title,
                    'url': topic_url,
                    'category': category,
                    'posts_count': posts_count
                })
                
            except Exception as e:
                logger.debug(f"Error parsing topic element: {e}")
                continue
        
        logger.info(f"Found {len(topics)} topics on homepage")
        return topics
    
    async def scrape_topic(self, topic_info: Dict) -> Optional[Document]:
        """Scrape individual topic page"""
        url = topic_info['url']
        logger.debug(f"Scraping topic: {topic_info['title']}")
        
        html = await self.fetch_page(url)
        if not html:
            return None
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract topic title from page
        title_elem = soup.select_one('h1.fancy-title')
        title = title_elem.get_text(strip=True) if title_elem else topic_info['title']
        
        # Extract posts
        posts = []
        post_elements = soup.select('div.post-stream article.onscreen-post')
        
        for post_elem in post_elements[:20]:  # Limit to 20 posts
            try:
                # Extract username
                username_elem = post_elem.select_one('.username a')
                username = username_elem.get_text(strip=True) if username_elem else 'anonymous'
                
                # Extract post content
                content_elem = post_elem.select_one('.cooked')
                if content_elem:
                    # Remove blockquotes to avoid duplication
                    for blockquote in content_elem.select('aside.quote'):
                        blockquote.decompose()
                    
                    content = content_elem.get_text(separator='\n', strip=True)
                else:
                    content = ''
                
                # Extract timestamp
                time_elem = post_elem.select_one('time')
                timestamp = time_elem.get('datetime', '') if time_elem else ''
                
                posts.append({
                    'username': username,
                    'content': content,
                    'timestamp': timestamp
                })
                
            except Exception as e:
                logger.debug(f"Error parsing post: {e}")
                continue
        
        if not posts:
            logger.warning(f"No posts found for topic: {title}")
            return None
        
        # Combine posts into document content
        content_parts = [f"# {title}\n"]
        
        for i, post in enumerate(posts, 1):
            content_parts.append(f"\n## Post {i} by {post['username']}")
            if post['timestamp']:
                content_parts.append(f"*{post['timestamp']}*")
            content_parts.append(f"\n{post['content']}\n")
        
        full_content = '\n'.join(content_parts)
        
        # Extract topic ID from URL
        topic_id = url.split('/')[-1] if '/' in url else 'unknown'
        
        # Create document
        doc = Document(
            id=f"forum-regen-{topic_id}",
            source="forum.regen.network",
            source_type="forum",
            url=url,
            title=title,
            content=full_content,
            metadata={
                'forum': 'regen-forum',
                'category': topic_info.get('category', 'uncategorized'),
                'posts_count': len(posts),
                'scraped_at': datetime.now().isoformat()
            },
            author=posts[0]['username'] if posts else None,
            tags=[topic_info.get('category', 'uncategorized')]
        )
        
        return doc
    
    async def scrape_categories(self) -> List[str]:
        """Discover available categories"""
        logger.info("Discovering categories...")
        
        html = await self.fetch_page(f"{self.base_url}/categories")
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        categories = []
        
        # Find category cards
        category_elements = soup.select('.category-list .category')
        
        for elem in category_elements:
            try:
                name_elem = elem.select_one('.category-name')
                if name_elem:
                    name = name_elem.get_text(strip=True)
                    categories.append(name)
            except Exception as e:
                logger.debug(f"Error parsing category: {e}")
                continue
        
        logger.info(f"Found {len(categories)} categories: {categories}")
        return categories
    
    async def scrape_category(self, category: str) -> List[Dict]:
        """Scrape topics from a specific category"""
        # Try different URL patterns
        urls_to_try = [
            f"{self.base_url}/c/{category.lower().replace(' ', '-')}",
            f"{self.base_url}/c/{category.lower().replace(' ', '-')}/l/latest",
            f"{self.base_url}/c/{category.lower()}"
        ]
        
        for url in urls_to_try:
            logger.debug(f"Trying category URL: {url}")
            html = await self.fetch_page(url)
            if html and 'topic-list' in html:
                # Parse topics from category page
                soup = BeautifulSoup(html, 'html.parser')
                topics = []
                
                topic_elements = soup.select('tr.topic-list-item')
                for elem in topic_elements[:10]:  # Limit per category
                    try:
                        link_elem = elem.select_one('a.title')
                        if link_elem:
                            title = link_elem.get_text(strip=True)
                            href = link_elem.get('href', '')
                            topic_url = self.base_url + href if href.startswith('/') else href
                            
                            topics.append({
                                'title': title,
                                'url': topic_url,
                                'category': category
                            })
                    except Exception as e:
                        logger.debug(f"Error parsing topic: {e}")
                        continue
                
                if topics:
                    logger.info(f"Found {len(topics)} topics in category: {category}")
                    return topics
        
        logger.warning(f"Could not scrape category: {category}")
        return []
    
    def save_documents(self, documents: List[Document]):
        """Save scraped documents to storage"""
        output_file = self.storage_dir / f"forum_scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        data = {
            'source': 'forum.regen.network',
            'timestamp': datetime.now().isoformat(),
            'document_count': len(documents),
            'documents': [doc.to_dict() for doc in documents]
        }
        
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.success(f"Saved {len(documents)} documents to {output_file}")
    
    async def run(self, limit: int = 20):
        """Run the scraper"""
        logger.info(f"Starting forum scraper (limit={limit})")
        
        # 1. Discover categories
        categories = await self.scrape_categories()
        
        # 2. Scrape homepage for latest topics
        topics = await self.scrape_homepage()
        
        # 3. Add topics from specific categories
        for category in ['Governance', 'Regen Registry', 'General']:
            if category in categories:
                cat_topics = await self.scrape_category(category)
                topics.extend(cat_topics)
        
        # Remove duplicates
        seen_urls = set()
        unique_topics = []
        for topic in topics:
            if topic['url'] not in seen_urls:
                seen_urls.add(topic['url'])
                unique_topics.append(topic)
        
        logger.info(f"Found {len(unique_topics)} unique topics to scrape")
        
        # 4. Scrape individual topics
        documents = []
        for topic in unique_topics[:limit]:
            doc = await self.scrape_topic(topic)
            if doc:
                documents.append(doc)
                logger.success(f"Scraped: {doc.title}")
            
            # Small delay to be respectful
            await asyncio.sleep(0.5)
        
        # 5. Save documents
        if documents:
            self.save_documents(documents)
            logger.success(f"✅ Successfully scraped {len(documents)} forum topics")
        else:
            logger.warning("❌ No documents scraped")
        
        return documents
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        await self.client.aclose()


async def main():
    """Main function"""
    logger.info("=" * 60)
    logger.info("Forum.regen.network Web Scraper")
    logger.info("=" * 60)
    
    async with ForumWebScraper() as scraper:
        documents = await scraper.run(limit=10)  # Start with 10 for testing
        
        if documents:
            logger.info("\nSummary:")
            logger.info(f"Total documents: {len(documents)}")
            logger.info(f"Total content size: {sum(len(d.content) for d in documents):,} bytes")
            logger.info("\nDocuments scraped:")
            for doc in documents[:5]:
                logger.info(f"  - {doc.title[:60]}...")
                logger.info(f"    {doc.url}")


if __name__ == "__main__":
    asyncio.run(main())