"""
Web scraper for collecting content from websites
"""

import asyncio
import httpx
from typing import Dict, List, Optional, Any, Set
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse
from pathlib import Path
from loguru import logger
from bs4 import BeautifulSoup
import html2text
import re

from .base_collector import BaseCollector, Document


class WebScraper(BaseCollector):
    """
    Collector for website content
    Handles various website types including documentation sites, blogs, and general pages
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize web scraper
        
        Args:
            config: Website configuration from sources.yaml
        """
        super().__init__(config)
        self.websites = config.get('websites', [])
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={'User-Agent': 'Regen-Indexer/1.0 (compatible; bot)'}
        )
        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
        self.html_converter.ignore_images = True
        self.html_converter.body_width = 0  # Don't wrap lines
        self.visited_urls: Set[str] = set()
    
    def validate_config(self) -> bool:
        """
        Validate web scraper configuration
        """
        if not self.websites:
            logger.error("No websites configured")
            return False
        
        for site in self.websites:
            if 'url' not in site:
                logger.error(f"Website missing URL: {site}")
                return False
            if 'name' not in site:
                logger.error(f"Website missing name: {site}")
                return False
        
        return True
    
    async def collect(self, limit: Optional[int] = None) -> List[Document]:
        """
        Collect documents from configured websites
        
        Args:
            limit: Maximum number of documents to collect
            
        Returns:
            List of collected documents
        """
        if not self.validate_config():
            return []
        
        all_documents = []
        doc_count = 0
        
        for site_config in self.websites:
            if limit and doc_count >= limit:
                break
            
            try:
                site_docs = await self.collect_website(
                    site_config,
                    limit - doc_count if limit else None
                )
                all_documents.extend(site_docs)
                doc_count += len(site_docs)
                
                # Save documents after each website
                self.save_documents(site_docs)
                
            except Exception as e:
                logger.error(f"Error collecting website {site_config['name']}: {e}")
                continue
        
        logger.info(f"Collected {len(all_documents)} documents from {len(self.websites)} websites")
        return all_documents
    
    async def collect_website(self, site_config: Dict[str, Any], limit: Optional[int] = None) -> List[Document]:
        """
        Collect documents from a single website
        
        Args:
            site_config: Website configuration
            limit: Maximum number of documents to collect
            
        Returns:
            List of documents from the website
        """
        site_name = site_config['name']
        base_url = site_config['url'].rstrip('/')
        max_depth = site_config.get('max_depth', 2)
        paths = site_config.get('paths', ['/'])
        strategy = site_config.get('strategy', 'crawl')
        
        logger.info(f"Collecting from {site_name} ({base_url})")
        
        documents = []
        doc_count = 0
        self.visited_urls.clear()
        
        # Handle different scraping strategies
        if strategy == 'sitemap':
            # Try to fetch sitemap first
            sitemap_docs = await self.collect_from_sitemap(base_url, site_name, limit)
            documents.extend(sitemap_docs)
            doc_count += len(sitemap_docs)
        
        # Crawl specified paths
        for path in paths:
            if limit and doc_count >= limit:
                break
            
            start_url = urljoin(base_url, path)
            
            # Crawl from this starting point
            path_docs = await self.crawl_recursive(
                start_url, 
                base_url,
                site_name,
                current_depth=0,
                max_depth=max_depth,
                limit=limit - doc_count if limit else None
            )
            
            documents.extend(path_docs)
            doc_count += len(path_docs)
        
        logger.info(f"Collected {len(documents)} documents from {site_name}")
        return documents
    
    async def crawl_recursive(self, url: str, base_url: str, site_name: str, 
                             current_depth: int, max_depth: int, 
                             limit: Optional[int] = None) -> List[Document]:
        """
        Recursively crawl website pages
        
        Args:
            url: Current URL to crawl
            base_url: Base URL of the website
            site_name: Name of the website
            current_depth: Current crawl depth
            max_depth: Maximum crawl depth
            limit: Maximum number of documents
            
        Returns:
            List of documents found
        """
        documents = []
        
        # Check limits
        if current_depth > max_depth:
            return documents
        
        if limit and len(documents) >= limit:
            return documents
        
        # Normalize URL
        url = self.normalize_url(url)
        
        # Skip if already visited or cached
        if url in self.visited_urls:
            return documents
        
        self.visited_urls.add(url)
        
        if self.is_cached(url):
            logger.debug(f"Skipping cached URL: {url}")
            return documents
        
        # Fetch and process page
        doc = await self.fetch_page(url, site_name, base_url)
        if doc:
            documents.append(doc)
        
        # If we haven't reached max depth, find and crawl links
        if current_depth < max_depth and (not limit or len(documents) < limit):
            links = await self.extract_links(url, base_url)
            
            for link in links[:20]:  # Limit links per page
                if limit and len(documents) >= limit:
                    break
                
                if link not in self.visited_urls:
                    sub_docs = await self.crawl_recursive(
                        link,
                        base_url,
                        site_name,
                        current_depth + 1,
                        max_depth,
                        limit - len(documents) if limit else None
                    )
                    documents.extend(sub_docs)
        
        return documents
    
    async def fetch_page(self, url: str, site_name: str, base_url: str) -> Optional[Document]:
        """
        Fetch and process a single web page
        
        Args:
            url: URL to fetch
            site_name: Name of the website
            base_url: Base URL for the site
            
        Returns:
            Document object or None
        """
        try:
            response = await self.client.get(url)
            
            if response.status_code != 200:
                logger.warning(f"Failed to fetch {url}: {response.status_code}")
                return None
            
            # Check content type
            content_type = response.headers.get('content-type', '').lower()
            if 'text/html' not in content_type:
                logger.debug(f"Skipping non-HTML content: {url}")
                return None
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract title
            title = self.extract_title(soup, url)
            
            # Remove script and style elements
            for script in soup(["script", "style", "nav", "header", "footer"]):
                script.decompose()
            
            # Convert to markdown
            content = self.html_converter.handle(str(soup))
            
            # Clean up content
            content = self.clean_content(content)
            
            # Skip if content is too small
            if len(content.strip()) < 100:
                logger.debug(f"Skipping page with minimal content: {url}")
                return None
            
            # Extract metadata
            meta_description = ""
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc:
                meta_description = meta_desc.get('content', '')
            
            # Parse last modified
            last_modified = None
            if 'last-modified' in response.headers:
                try:
                    last_modified = datetime.strptime(
                        response.headers['last-modified'],
                        '%a, %d %b %Y %H:%M:%S %Z'
                    )
                except:
                    pass
            
            # Determine page type
            page_type = self.determine_page_type(url, soup, content)
            
            # Create document
            doc = Document(
                id="",  # Auto-generated
                source=f"website:{site_name}",
                source_type="website",
                url=url,
                title=title,
                content=content,
                metadata={
                    "site": site_name,
                    "base_url": base_url,
                    "page_type": page_type,
                    "description": meta_description,
                    "content_length": len(content)
                },
                last_modified=last_modified,
                tags=self.extract_tags_from_content(content, site_name, page_type)
            )
            
            logger.debug(f"Processed: {title} ({len(content)} bytes)")
            return doc
            
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    async def extract_links(self, url: str, base_url: str) -> List[str]:
        """
        Extract links from a page for crawling
        
        Args:
            url: Page URL
            base_url: Base URL of the site
            
        Returns:
            List of absolute URLs to crawl
        """
        try:
            response = await self.client.get(url)
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.text, 'html.parser')
            links = []
            
            for link in soup.find_all('a', href=True):
                href = link['href']
                
                # Skip anchors, javascript, mailto, etc.
                if href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                    continue
                
                # Convert to absolute URL
                absolute_url = urljoin(url, href)
                
                # Only include URLs from the same domain
                if urlparse(absolute_url).netloc == urlparse(base_url).netloc:
                    normalized = self.normalize_url(absolute_url)
                    if normalized not in self.visited_urls:
                        links.append(normalized)
            
            return list(set(links))  # Remove duplicates
            
        except Exception as e:
            logger.error(f"Error extracting links from {url}: {e}")
            return []
    
    async def collect_from_sitemap(self, base_url: str, site_name: str, 
                                  limit: Optional[int] = None) -> List[Document]:
        """
        Collect documents from sitemap.xml if available
        
        Args:
            base_url: Base URL of the website
            site_name: Name of the website
            limit: Maximum number of documents
            
        Returns:
            List of documents from sitemap
        """
        documents = []
        sitemap_urls = [
            f"{base_url}/sitemap.xml",
            f"{base_url}/sitemap_index.xml",
            f"{base_url}/sitemap"
        ]
        
        for sitemap_url in sitemap_urls:
            try:
                response = await self.client.get(sitemap_url)
                if response.status_code == 200:
                    # Parse sitemap
                    soup = BeautifulSoup(response.text, 'xml')
                    
                    # Find all URLs
                    for loc in soup.find_all('loc'):
                        if limit and len(documents) >= limit:
                            break
                        
                        url = loc.text.strip()
                        if url not in self.visited_urls and not self.is_cached(url):
                            doc = await self.fetch_page(url, site_name, base_url)
                            if doc:
                                documents.append(doc)
                    
                    logger.info(f"Found {len(documents)} pages in sitemap")
                    break
                    
            except Exception as e:
                logger.debug(f"No sitemap at {sitemap_url}: {e}")
                continue
        
        return documents
    
    def normalize_url(self, url: str) -> str:
        """
        Normalize URL for consistency
        
        Args:
            url: URL to normalize
            
        Returns:
            Normalized URL
        """
        parsed = urlparse(url.lower())
        
        # Remove fragment
        parsed = parsed._replace(fragment='')
        
        # Remove trailing slash from path
        if parsed.path.endswith('/') and parsed.path != '/':
            parsed = parsed._replace(path=parsed.path[:-1])
        
        # Remove common tracking parameters
        if parsed.query:
            params = dict(p.split('=') for p in parsed.query.split('&') if '=' in p)
            tracking_params = ['utm_source', 'utm_medium', 'utm_campaign', 'ref', 'fbclid']
            params = {k: v for k, v in params.items() if k not in tracking_params}
            query = '&'.join(f"{k}={v}" for k, v in sorted(params.items()))
            parsed = parsed._replace(query=query)
        
        return urlunparse(parsed)
    
    def extract_title(self, soup: BeautifulSoup, url: str) -> str:
        """
        Extract page title
        
        Args:
            soup: BeautifulSoup object
            url: Page URL (fallback)
            
        Returns:
            Page title
        """
        # Try various title sources
        title = None
        
        # Try <title> tag
        if soup.title:
            title = soup.title.string
        
        # Try <h1> tag
        if not title:
            h1 = soup.find('h1')
            if h1:
                title = h1.get_text()
        
        # Try meta og:title
        if not title:
            og_title = soup.find('meta', property='og:title')
            if og_title:
                title = og_title.get('content')
        
        # Fallback to URL path
        if not title:
            path = urlparse(url).path.strip('/')
            title = path.split('/')[-1].replace('-', ' ').replace('_', ' ').title()
        
        return (title or 'Untitled').strip()
    
    def clean_content(self, content: str) -> str:
        """
        Clean up converted markdown content
        
        Args:
            content: Raw markdown content
            
        Returns:
            Cleaned content
        """
        # Remove excessive whitespace
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        # Remove navigation breadcrumbs
        content = re.sub(r'^Home\s*[>»/]\s*.*?\n', '', content, flags=re.MULTILINE)
        
        # Remove common footer patterns
        content = re.sub(r'(Copyright|©).*?(\n|$)', '', content, flags=re.IGNORECASE)
        content = re.sub(r'All rights reserved.*?(\n|$)', '', content, flags=re.IGNORECASE)
        
        return content.strip()
    
    def determine_page_type(self, url: str, soup: BeautifulSoup, content: str) -> str:
        """
        Determine the type of page
        
        Args:
            url: Page URL
            soup: BeautifulSoup object
            content: Page content
            
        Returns:
            Page type string
        """
        url_lower = url.lower()
        
        # Check URL patterns
        if '/docs/' in url_lower or '/documentation/' in url_lower:
            return 'documentation'
        elif '/blog/' in url_lower or '/news/' in url_lower or '/article/' in url_lower:
            return 'blog'
        elif '/api/' in url_lower:
            return 'api'
        elif '/guide/' in url_lower or '/tutorial/' in url_lower:
            return 'guide'
        elif '/about' in url_lower:
            return 'about'
        
        # Check content patterns
        if 'class=' in content and 'function' in content:
            return 'api'
        elif re.search(r'step \d+|how to|tutorial', content, re.IGNORECASE):
            return 'guide'
        
        return 'general'
    
    def extract_tags_from_content(self, content: str, site_name: str, page_type: str) -> List[str]:
        """
        Extract relevant tags from page content
        
        Args:
            content: Page content
            site_name: Website name
            page_type: Type of page
            
        Returns:
            List of tags
        """
        tags = [site_name, page_type]
        
        content_lower = content.lower()
        
        # Topic-based tags
        keywords = {
            'ecocredit': ['carbon', 'credit', 'offset', 'climate', 'batch'],
            'marketplace': ['marketplace', 'buy', 'sell', 'trade'],
            'governance': ['proposal', 'vote', 'governance', 'dao'],
            'validator': ['validator', 'stake', 'delegation'],
            'developer': ['api', 'sdk', 'contract', 'module'],
            'guide': ['tutorial', 'guide', 'how-to', 'setup']
        }
        
        for tag, terms in keywords.items():
            if any(term in content_lower for term in terms):
                tags.append(tag)
        
        return list(set(tags))
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close HTTP client"""
        await self.client.aclose()