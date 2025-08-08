"""
Medium blog collector for Regen Network
Specialized collector for scraping all articles from Medium publications
"""

import asyncio
import httpx
import json
import re
from typing import Dict, List, Optional, Any
from datetime import datetime
from urllib.parse import urljoin, urlparse
from pathlib import Path
from loguru import logger
from bs4 import BeautifulSoup
import html2text

from .base_collector import BaseCollector, Document


class MediumCollector(BaseCollector):
    """
    Specialized collector for Medium blog posts
    Handles Medium's specific structure and pagination
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Medium collector
        
        Args:
            config: Medium configuration from sources.yaml
        """
        super().__init__(config)
        self.medium_config = config.get('medium', [])
        self.client = httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=True,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
        )
        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
        self.html_converter.ignore_images = True
        self.html_converter.body_width = 0
        
    def validate_config(self) -> bool:
        """Validate Medium configuration"""
        if not self.medium_config:
            logger.error("No Medium sources configured")
            return False
        
        for source in self.medium_config:
            if 'url' not in source:
                logger.error(f"Medium source missing URL: {source}")
                return False
            if 'name' not in source:
                logger.error(f"Medium source missing name: {source}")
                return False
        
        return True
    
    async def collect(self, limit: Optional[int] = None) -> List[Document]:
        """
        Collect all articles from configured Medium publications
        
        Args:
            limit: Maximum number of articles to collect (None for all)
            
        Returns:
            List of collected documents
        """
        if not self.validate_config():
            return []
        
        all_documents = []
        
        for source in self.medium_config:
            try:
                logger.info(f"Collecting from Medium: {source['name']}")
                articles = await self.collect_medium_articles(source, limit)
                all_documents.extend(articles)
                
                # Save documents after each source
                self.save_documents(articles)
                
                logger.info(f"Collected {len(articles)} articles from {source['name']}")
                
            except Exception as e:
                logger.error(f"Error collecting from {source['name']}: {e}")
                continue
        
        logger.info(f"Total collected: {len(all_documents)} Medium articles")
        return all_documents
    
    async def collect_medium_articles(self, source: Dict[str, Any], limit: Optional[int] = None) -> List[Document]:
        """
        Collect articles from a Medium publication
        
        Args:
            source: Medium source configuration
            limit: Maximum number of articles to collect
            
        Returns:
            List of Document objects
        """
        base_url = source['url'].rstrip('/')
        publication_name = base_url.split('/')[-1]
        
        # Try multiple strategies to get article list
        articles = []
        article_urls = set()
        
        # Strategy 1: Try to get all archive pages (Medium archives by year/month)
        import datetime
        current_year = datetime.datetime.now().year
        
        # Try archive pages for different years and months
        for year in range(2018, current_year + 1):  # Regen Network started around 2018
            for month in range(1, 13):
                archive_url = f"{base_url}/archive/{year}/{month:02d}"
                try:
                    logger.info(f"Checking archive: {archive_url}")
                    response = await self.client.get(archive_url)
                    
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, 'html.parser')
                        
                        # Look for article links
                        links = soup.find_all('a', href=True)
                        for link in links:
                            href = link.get('href', '')
                            if href:
                                full_url = urljoin(base_url, href)
                                if self._is_article_url(full_url, publication_name):
                                    article_urls.add(full_url)
                        
                        # Extract from JavaScript data
                        article_urls.update(self._extract_urls_from_js(response.text, base_url))
                        
                        if len(article_urls) > 0:
                            logger.info(f"Found {len(article_urls)} total articles so far")
                    
                    # Small delay to be respectful
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logger.debug(f"No archive for {year}/{month:02d}: {e}")
                    continue
        
        # Strategy 2: Also try the main archive page
        archive_urls = [
            f"{base_url}/archive",
            f"{base_url}/latest",
            base_url  # Main page as fallback
        ]
        
        for url in archive_urls:
            try:
                logger.info(f"Trying to fetch article list from: {url}")
                response = await self.client.get(url)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Look for article links - Medium uses various patterns
                    link_patterns = [
                        # Direct article links
                        soup.find_all('a', href=re.compile(f'/{publication_name}/[^/]+$')),
                        # Links with article IDs
                        soup.find_all('a', href=re.compile(r'-[a-f0-9]{8,}$')),
                        # H2/H3 titles with links
                        [a for h in soup.find_all(['h2', 'h3']) for a in h.find_all('a', href=True)],
                        # Article cards
                        soup.find_all('article'),
                    ]
                    
                    for pattern in link_patterns:
                        for element in pattern:
                            if element.name == 'article':
                                # Find link within article element
                                links = element.find_all('a', href=True)
                                for link in links:
                                    href = link.get('href', '')
                                    if href and ('/p/' in href or re.search(r'-[a-f0-9]{8,}$', href)):
                                        article_urls.add(urljoin(base_url, href))
                            else:
                                href = element.get('href', '')
                                if href:
                                    full_url = urljoin(base_url, href)
                                    # Filter out non-article links
                                    if self._is_article_url(full_url, publication_name):
                                        article_urls.add(full_url)
                    
                    # Also try to extract from JavaScript data
                    article_urls.update(self._extract_urls_from_js(response.text, base_url))
                    
                    if article_urls:
                        logger.info(f"Found {len(article_urls)} total article URLs")
                        
            except Exception as e:
                logger.warning(f"Error fetching {url}: {e}")
                continue
        
        # If we couldn't find articles through archive, try RSS feed
        if not article_urls:
            rss_url = f"{base_url}/feed"
            try:
                logger.info(f"Trying RSS feed: {rss_url}")
                response = await self.client.get(rss_url)
                if response.status_code == 200:
                    # Parse RSS
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(response.text)
                    for item in root.findall('.//item'):
                        link = item.find('link')
                        if link is not None and link.text:
                            article_urls.add(link.text)
                    logger.info(f"Found {len(article_urls)} articles from RSS feed")
            except Exception as e:
                logger.warning(f"Error fetching RSS: {e}")
        
        # Convert URLs to list and apply limit
        article_urls = list(article_urls)
        if limit:
            article_urls = article_urls[:limit]
        
        logger.info(f"Processing {len(article_urls)} articles...")
        
        # Collect each article and save in batches
        batch_size = 10
        for i, url in enumerate(article_urls, 1):
            try:
                logger.info(f"Collecting article {i}/{len(article_urls)}: {url}")
                article = await self.collect_article(url, source['name'])
                if article:
                    articles.append(article)
                    
                    # Save batch every 10 articles
                    if len(articles) % batch_size == 0:
                        self.save_documents(articles[-batch_size:])
                        logger.info(f"Saved batch of {batch_size} articles (total saved: {len(articles)})")
                
                # Small delay to be respectful
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Error collecting article {url}: {e}")
                continue
        
        # Save any remaining articles
        if len(articles) % batch_size != 0:
            remaining = len(articles) % batch_size
            self.save_documents(articles[-remaining:])
            logger.info(f"Saved final batch of {remaining} articles")
        
        return articles
    
    def _is_article_url(self, url: str, publication_name: str) -> bool:
        """Check if URL is likely an article URL"""
        # Exclude common non-article paths
        excluded_paths = ['/about', '/archive', '/tag/', '/tags/', '/latest', '/trending', 
                         '/membership', '/subscribe', '/signin', '/signup', '/feed', '/sitemap']
        
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        # Check exclusions
        for excluded in excluded_paths:
            if excluded in path:
                return False
        
        # Check if it looks like an article (has slug or ID)
        if re.search(r'-[a-f0-9]{8,}$', path):  # Medium article ID
            return True
        if f'/{publication_name}/' in url and len(path.split('/')) > 2:  # Publication article
            return True
        if '/p/' in path:  # Medium's /p/ pattern for articles
            return True
            
        return False
    
    def _extract_urls_from_js(self, html: str, base_url: str) -> set:
        """Extract article URLs from JavaScript data in page"""
        urls = set()
        
        # Look for JSON data in script tags
        soup = BeautifulSoup(html, 'html.parser')
        for script in soup.find_all('script'):
            if script.string:
                # Look for Medium's data patterns
                matches = re.findall(r'"postId":"([a-f0-9]+)"', script.string)
                for post_id in matches:
                    # Medium uses /p/{postId} pattern
                    urls.add(f"{base_url}/p/{post_id}")
                
                # Also look for direct URLs
                url_matches = re.findall(r'"url":"([^"]+)"', script.string)
                for url in url_matches:
                    if self._is_article_url(url, base_url.split('/')[-1]):
                        urls.add(url)
        
        return urls
    
    async def collect_article(self, url: str, source_name: str) -> Optional[Document]:
        """
        Collect a single Medium article
        
        Args:
            url: Article URL
            source_name: Name of the Medium source
            
        Returns:
            Document object or None if failed
        """
        try:
            response = await self.client.get(url)
            if response.status_code != 200:
                logger.warning(f"Failed to fetch article: {url} (status: {response.status_code})")
                return None
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract title
            title = None
            title_selectors = ['h1', 'meta[property="og:title"]', 'title']
            for selector in title_selectors:
                element = soup.find(selector)
                if element:
                    title = element.get('content') if element.name == 'meta' else element.get_text()
                    if title:
                        break
            
            if not title:
                title = url.split('/')[-1][:50]  # Use URL slug as fallback
            
            # Extract author
            author = None
            author_selectors = [
                'meta[name="author"]',
                'a[rel="author"]',
                'span[data-testid="authorName"]'
            ]
            for selector in author_selectors:
                element = soup.select_one(selector)
                if element:
                    author = element.get('content') if element.name == 'meta' else element.get_text()
                    if author:
                        break
            
            # Extract publish date
            published_date = None
            date_selectors = [
                'meta[property="article:published_time"]',
                'time[datetime]',
                'span[data-testid="storyPublishDate"]'
            ]
            for selector in date_selectors:
                element = soup.select_one(selector)
                if element:
                    if element.name == 'meta':
                        published_date = element.get('content')
                    elif element.name == 'time':
                        published_date = element.get('datetime')
                    else:
                        published_date = element.get_text()
                    if published_date:
                        break
            
            # Extract article content
            # Medium articles are usually in <article> or main content area
            content = None
            content_selectors = [
                'article',
                'div[class*="postArticle"]',
                'div[class*="story-content"]',
                'main'
            ]
            
            for selector in content_selectors:
                element = soup.select_one(selector)
                if element:
                    # Remove script and style tags
                    for tag in element.find_all(['script', 'style', 'nav', 'footer']):
                        tag.decompose()
                    
                    # Convert to markdown
                    content = self.html_converter.handle(str(element))
                    if content and len(content.strip()) > 100:  # Ensure we got real content
                        break
            
            if not content:
                # Fallback: get all paragraphs
                paragraphs = soup.find_all('p')
                if paragraphs:
                    content = '\n\n'.join([p.get_text() for p in paragraphs if p.get_text().strip()])
            
            if not content or len(content.strip()) < 100:
                logger.warning(f"Insufficient content extracted from {url}")
                return None
            
            # Extract tags/categories
            tags = []
            tag_selectors = [
                'a[href*="/tag/"]',
                'a[href*="/tagged/"]',
                'meta[property="article:tag"]'
            ]
            for selector in tag_selectors:
                elements = soup.select(selector)
                for element in elements:
                    if element.name == 'meta':
                        tag = element.get('content')
                    else:
                        tag = element.get_text()
                    if tag and tag not in tags:
                        tags.append(tag.strip())
            
            # Create document
            doc = Document(
                id='',  # Will be auto-generated
                source=f'medium:{source_name}',
                source_type='medium',
                url=url,
                title=title.strip() if title else 'Untitled',
                content=content,
                author=author.strip() if author else None,
                tags=tags,
                metadata={
                    'published_date': published_date,
                    'collected_at': datetime.now().isoformat()
                }
            )
            
            return doc
            
        except Exception as e:
            logger.error(f"Error collecting article {url}: {e}")
            return None