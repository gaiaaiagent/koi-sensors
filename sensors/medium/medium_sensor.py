"""
KOI Sensor Network - Medium Blog Monitoring Sensor
Monitors Regen Network Medium blog for new articles using RSS and web scraping
"""

import asyncio
import aiohttp
import hashlib
import feedparser
import re
from typing import Dict, List, Any, Optional, Set
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import html2text
import json

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import Bundle, document_to_bundle
from shared.config.base import BaseSensorConfig, APIConfig


class MediumMonitorConfig(BaseSensorConfig):
    """Medium monitoring sensor configuration"""
    
    # Medium sources to monitor
    medium_sources: List[Dict[str, Any]] = [
        {
            "name": "regen-network-medium",
            "url": "https://regen-network.medium.com",
            "rss_url": "https://medium.com/feed/@regen-network",  # RSS feed URL
            "check_interval": 21600,  # Check every 6 hours (blog posts don't change frequently)
            "importance": "high",
            "notes": "Main Regen Network blog on Medium"
        }
    ]
    
    # Collection behavior
    max_articles_per_check: int = 20  # Limit per check to avoid overwhelming
    use_rss: bool = True  # Primary method
    use_scraping: bool = True  # Fallback method
    historical_years: List[int] = [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]  # Years to check archives
    
    # Content filtering
    min_content_length: int = 500  # Minimum article length
    extract_images: bool = False  # Don't extract images to keep text-focused
    
    # HTTP settings
    request_delay: float = 1.0  # Seconds between requests
    user_agent: str = "KOI-Sensor/1.0 (Regen Network Knowledge Indexer; +https://regen.network)"
    timeout_seconds: int = 30


class MediumArticleRID(RID):
    """Medium article resource identifier: orn:medium.article.{article_id}"""
    
    def __init__(self, article_url: str):
        # Extract article ID from URL or create hash
        article_id = self._extract_article_id(article_url)
        super().__init__("orn", f"medium.article.{article_id}")
    
    def _extract_article_id(self, url: str) -> str:
        """Extract Medium article ID from URL"""
        # Medium URLs often end with -articleID (e.g., -a1b2c3d4e5f6)
        match = re.search(r'-([a-f0-9]{8,})$', url)
        if match:
            return match.group(1)
        
        # Fallback to hash of URL
        return hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]


class MediumKOISensor:
    """Medium blog monitoring sensor using RSS and web scraping"""
    
    def __init__(self, config: MediumMonitorConfig):
        self.config = config
        self.logger = self._setup_logging()
        
        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name="medium-sensor",
            coordinator_url=getattr(config.koi_net, 'coordinator_url', 'http://localhost:8005'),
            poll_interval=30
        )
        
        # Article tracking
        self.article_hashes: Dict[str, str] = {}  # URL -> content hash
        self.collected_articles: Set[str] = set()  # Track collected article URLs
        
        # HTTP session
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Content converter
        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
        self.html_converter.ignore_images = self.config.extract_images == False
        self.html_converter.body_width = 0  # No wrapping
    
    def _setup_logging(self):
        """Setup logging for Medium sensor"""
        import logging
        logger = logging.getLogger("koi.sensor.medium")
        logger.setLevel(getattr(logging, self.config.monitoring.log_level))
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        return logger
    
    async def start(self):
        """Start Medium monitoring sensor"""
        self.logger.info("Starting Medium KOI Sensor")
        
        # Start KOI node
        await self.koi_node.start()
        
        # Initialize HTTP session
        connector = aiohttp.TCPConnector(limit=10, limit_per_host=3)
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        headers = {"User-Agent": self.config.user_agent}
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=headers
        )
        
        # Start monitoring loops for each Medium source
        tasks = []
        for source in self.config.medium_sources:
            task = asyncio.create_task(self.monitor_medium_source(source))
            tasks.append(task)
        
        # Wait for all monitoring tasks
        await asyncio.gather(*tasks)
    
    async def stop(self):
        """Stop Medium monitoring sensor"""
        self.logger.info("Stopping Medium KOI Sensor")
        
        if self.session:
            await self.session.close()
        
        await self.koi_node.stop()
    
    async def monitor_medium_source(self, source_config: Dict[str, Any]):
        """Monitor a single Medium publication for new articles"""
        check_interval = source_config.get("check_interval", 21600)
        
        self.logger.info(f"Starting monitoring for {source_config['name']} (interval: {check_interval}s)")
        
        # Do initial collection of historical articles
        await self.collect_historical_articles(source_config)
        
        # Then monitor for new articles
        while self.koi_node.running:
            try:
                # Collect recent articles
                await self.collect_recent_articles(source_config)
                
                self.logger.debug(f"Completed check cycle for {source_config['name']}")
                
                # Wait for next check
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                self.logger.error(f"Error monitoring {source_config['name']}: {e}")
                await asyncio.sleep(60)  # Wait longer after errors
    
    async def collect_historical_articles(self, source_config: Dict[str, Any]):
        """Collect historical articles on first run"""
        self.logger.info(f"Collecting historical articles from {source_config['name']}")
        
        article_urls = set()
        
        # Try RSS feed first
        if self.config.use_rss and "rss_url" in source_config:
            rss_urls = await self.collect_from_rss(source_config["rss_url"])
            article_urls.update(rss_urls)
            self.logger.info(f"Found {len(rss_urls)} articles from RSS feed")
        
        # Try archive scraping for historical articles
        if self.config.use_scraping:
            base_url = source_config["url"]
            
            # Check archive pages by year/month
            for year in self.config.historical_years:
                for month in range(1, 13):
                    archive_url = f"{base_url}/archive/{year}/{month:02d}"
                    
                    try:
                        archive_articles = await self.scrape_archive_page(archive_url)
                        if archive_articles:
                            article_urls.update(archive_articles)
                            self.logger.info(f"Found {len(archive_articles)} articles from {year}/{month:02d}")
                        
                        # Rate limiting
                        await asyncio.sleep(self.config.request_delay)
                        
                    except Exception as e:
                        self.logger.debug(f"No archive for {year}/{month:02d}: {e}")
        
        # Also try the main archive page
        if self.config.use_scraping:
            main_archive_url = f"{source_config['url']}/archive"
            try:
                main_articles = await self.scrape_archive_page(main_archive_url)
                if main_articles:
                    article_urls.update(main_articles)
                    self.logger.info(f"Found {len(main_articles)} articles from main archive")
            except Exception as e:
                self.logger.warning(f"Error scraping main archive: {e}")
        
        # Process collected article URLs
        self.logger.info(f"Total historical articles found: {len(article_urls)}")
        
        # Limit initial collection
        article_urls = list(article_urls)[:100]  # Process first 100 historical articles
        
        for i, url in enumerate(article_urls, 1):
            if url not in self.collected_articles:
                try:
                    self.logger.info(f"Processing historical article {i}/{len(article_urls)}: {url}")
                    await self.process_article(url, source_config["name"])
                    self.collected_articles.add(url)
                    
                    # Rate limiting
                    await asyncio.sleep(self.config.request_delay)
                    
                except Exception as e:
                    self.logger.error(f"Error processing article {url}: {e}")
    
    async def collect_recent_articles(self, source_config: Dict[str, Any]):
        """Collect recent articles (for periodic checks)"""
        article_urls = set()
        
        # Try RSS feed first (most recent articles)
        if self.config.use_rss and "rss_url" in source_config:
            rss_urls = await self.collect_from_rss(source_config["rss_url"])
            article_urls.update(rss_urls)
        
        # Also check the main page for very recent articles
        if self.config.use_scraping:
            main_page_url = source_config["url"]
            try:
                main_articles = await self.scrape_page_for_articles(main_page_url)
                if main_articles:
                    article_urls.update(main_articles)
            except Exception as e:
                self.logger.warning(f"Error scraping main page: {e}")
        
        # Process new articles only
        new_articles = [url for url in article_urls if url not in self.collected_articles]
        
        if new_articles:
            self.logger.info(f"Found {len(new_articles)} new articles")
            
            for url in new_articles[:self.config.max_articles_per_check]:
                try:
                    await self.process_article(url, source_config["name"])
                    self.collected_articles.add(url)
                    
                    # Rate limiting
                    await asyncio.sleep(self.config.request_delay)
                    
                except Exception as e:
                    self.logger.error(f"Error processing article {url}: {e}")
    
    async def collect_from_rss(self, rss_url: str) -> Set[str]:
        """Collect article URLs from RSS feed"""
        article_urls = set()
        
        try:
            if not self.session:
                return article_urls
            
            # Fetch RSS feed
            async with self.session.get(rss_url) as response:
                if response.status == 200:
                    rss_content = await response.text()
                    
                    # Parse RSS feed
                    feed = feedparser.parse(rss_content)
                    
                    for entry in feed.entries:
                        if hasattr(entry, 'link'):
                            # Clean up Medium redirect URLs
                            url = entry.link
                            if '?source=rss' in url:
                                url = url.split('?source=rss')[0]
                            article_urls.add(url)
                    
                    self.logger.debug(f"Found {len(article_urls)} articles from RSS")
        
        except Exception as e:
            self.logger.error(f"Error fetching RSS feed: {e}")
        
        return article_urls
    
    async def scrape_archive_page(self, archive_url: str) -> Set[str]:
        """Scrape an archive page for article URLs"""
        article_urls = set()
        
        try:
            if not self.session:
                return article_urls
            
            async with self.session.get(archive_url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Extract article URLs from various patterns
                    article_urls.update(self._extract_article_urls_from_page(soup, archive_url))
                    
                    # Also try to extract from JavaScript data
                    article_urls.update(self._extract_urls_from_javascript(html))
        
        except Exception as e:
            self.logger.debug(f"Error scraping archive page {archive_url}: {e}")
        
        return article_urls
    
    async def scrape_page_for_articles(self, page_url: str) -> Set[str]:
        """Scrape a page for article URLs"""
        article_urls = set()
        
        try:
            if not self.session:
                return article_urls
            
            async with self.session.get(page_url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Extract article URLs
                    article_urls.update(self._extract_article_urls_from_page(soup, page_url))
                    
                    # Extract from JavaScript
                    article_urls.update(self._extract_urls_from_javascript(html))
        
        except Exception as e:
            self.logger.error(f"Error scraping page {page_url}: {e}")
        
        return article_urls
    
    def _extract_article_urls_from_page(self, soup: BeautifulSoup, base_url: str) -> Set[str]:
        """Extract article URLs from a BeautifulSoup parsed page"""
        article_urls = set()
        
        # Look for article links with various patterns
        patterns = [
            # Links ending with Medium article ID
            soup.find_all('a', href=re.compile(r'-[a-f0-9]{8,}$')),
            # Links containing /p/ (Medium's article pattern)
            soup.find_all('a', href=re.compile(r'/p/')),
            # H2/H3 titles with links
            [a for h in soup.find_all(['h2', 'h3']) for a in h.find_all('a', href=True)],
        ]
        
        for pattern in patterns:
            for link in pattern:
                href = link.get('href', '')
                if href:
                    full_url = urljoin(base_url, href)
                    if self._is_article_url(full_url):
                        article_urls.add(full_url)
        
        # Look for article elements
        for article in soup.find_all('article'):
            links = article.find_all('a', href=True)
            for link in links:
                href = link.get('href', '')
                if href and ('/p/' in href or re.search(r'-[a-f0-9]{8,}$', href)):
                    full_url = urljoin(base_url, href)
                    if self._is_article_url(full_url):
                        article_urls.add(full_url)
        
        return article_urls
    
    def _extract_urls_from_javascript(self, html: str) -> Set[str]:
        """Extract article URLs from JavaScript data in page"""
        article_urls = set()
        
        # Look for Medium's post IDs in JavaScript
        post_id_matches = re.findall(r'"postId":"([a-f0-9]+)"', html)
        for post_id in post_id_matches:
            # Medium URLs often use the pattern /p/{postId}
            article_urls.add(f"https://medium.com/p/{post_id}")
        
        # Look for full URLs in JavaScript
        url_matches = re.findall(r'"url":"(https?://[^"]+)"', html)
        for url in url_matches:
            if self._is_article_url(url):
                article_urls.add(url)
        
        return article_urls
    
    def _is_article_url(self, url: str) -> bool:
        """Check if URL is likely a Medium article URL"""
        # Exclude common non-article paths
        excluded_paths = [
            '/about', '/archive', '/tag/', '/tags/', '/latest', '/trending',
            '/membership', '/subscribe', '/signin', '/signup', '/feed', '/sitemap'
        ]
        
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        # Check exclusions
        for excluded in excluded_paths:
            if excluded in path:
                return False
        
        # Check if it looks like an article
        if re.search(r'-[a-f0-9]{8,}$', path):  # Medium article ID
            return True
        if '/p/' in path:  # Medium's /p/ pattern for articles
            return True
        if 'medium.com' in url and len(path.split('/')) > 2:  # Has enough path segments
            return True
        
        return False
    
    async def process_article(self, article_url: str, source_name: str):
        """Process a single article"""
        try:
            if not self.session:
                return
            
            # Fetch article content
            async with self.session.get(article_url) as response:
                if response.status != 200:
                    self.logger.warning(f"HTTP {response.status} for {article_url}")
                    return
                
                html_content = await response.text()
            
            # Parse content
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract article content and metadata
            article_data = self.extract_article_data(soup, article_url)
            
            if not article_data or len(article_data.get("content", "")) < self.config.min_content_length:
                self.logger.warning(f"Article too short or empty: {article_url}")
                return
            
            # Calculate content hash
            content_hash = hashlib.sha256(article_data["content"].encode('utf-8')).hexdigest()
            
            # Check if content changed
            previous_hash = self.article_hashes.get(article_url)
            content_changed = previous_hash != content_hash
            
            if content_changed or previous_hash is None:
                # Emit KOI event
                await self.emit_article_event(
                    article_url,
                    article_data,
                    source_name,
                    "NEW" if previous_hash is None else "UPDATE"
                )
                
                # Update hash
                self.article_hashes[article_url] = content_hash
                
                self.logger.info(f"Processed article: {article_data.get('title', 'Untitled')}")
        
        except Exception as e:
            self.logger.error(f"Error processing article {article_url}: {e}")
    
    def extract_article_data(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract article content and metadata from HTML"""
        article_data = {
            "url": url,
            "title": "",
            "author": "",
            "content": "",
            "published_date": None,
            "tags": [],
            "read_time": "",
            "description": ""
        }
        
        # Extract title
        title_tag = soup.find('h1') or soup.find('title')
        if title_tag:
            article_data["title"] = title_tag.get_text().strip()
        
        # Extract author
        author_meta = soup.find('meta', {'name': 'author'}) or soup.find('meta', {'property': 'article:author'})
        if author_meta:
            article_data["author"] = author_meta.get('content', '')
        else:
            # Try to find author in page structure
            author_elem = soup.find('a', {'rel': 'author'}) or soup.find('span', class_=re.compile('author'))
            if author_elem:
                article_data["author"] = author_elem.get_text().strip()
        
        # Extract published date
        time_elem = soup.find('time')
        if time_elem:
            article_data["published_date"] = time_elem.get('datetime', '')
        
        # Extract description
        desc_meta = soup.find('meta', {'name': 'description'}) or soup.find('meta', {'property': 'og:description'})
        if desc_meta:
            article_data["description"] = desc_meta.get('content', '')
        
        # Extract tags
        for tag_elem in soup.find_all('a', href=re.compile('/tag/')):
            tag_text = tag_elem.get_text().strip()
            if tag_text and tag_text not in article_data["tags"]:
                article_data["tags"].append(tag_text)
        
        # Extract main content
        # Medium articles are often in <article> or main content divs
        article_elem = soup.find('article') or soup.find('main') or soup.find('div', class_=re.compile('article'))
        
        if article_elem:
            # Remove navigation, headers, footers
            for elem in article_elem.find_all(['nav', 'header', 'footer', 'aside']):
                elem.decompose()
            
            # Convert to text
            html_content = str(article_elem)
            text_content = self.html_converter.handle(html_content)
            
            # Clean up
            text_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', text_content)
            text_content = text_content.strip()
            
            article_data["content"] = text_content
        else:
            # Fallback: get all text
            for script in soup(["script", "style", "nav", "footer", "aside"]):
                script.decompose()
            
            text_content = self.html_converter.handle(str(soup))
            text_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', text_content)
            article_data["content"] = text_content.strip()
        
        # Extract read time if available
        read_time_elem = soup.find(text=re.compile(r'\d+\s*min\s*read'))
        if read_time_elem:
            article_data["read_time"] = read_time_elem.strip()
        
        return article_data
    
    async def emit_article_event(self, url: str, article_data: Dict[str, Any], source_name: str, event_type: str):
        """Emit KOI event for article"""
        try:
            # Create RID
            rid = MediumArticleRID(url)
            
            # Auto-generate tags based on content
            auto_tags = self.generate_auto_tags(article_data["content"])
            all_tags = list(set(article_data.get("tags", []) + auto_tags))
            
            # Create document in KOI format
            document = {
                "id": f"medium_{rid.to_string().split('.')[-1]}",
                "source": f"medium:{source_name}",
                "source_type": "blog",
                "url": url,
                "title": article_data.get("title", "Untitled"),
                "content": article_data["content"],
                "metadata": {
                    "author": article_data.get("author", ""),
                    "published_date": article_data.get("published_date"),
                    "read_time": article_data.get("read_time", ""),
                    "description": article_data.get("description", ""),
                    "tags": all_tags,
                    "word_count": len(article_data["content"].split()),
                    "collection_method": "medium_sensor",
                    "koi_sensor": "medium-monitor"
                },
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "last_modified": article_data.get("published_date"),
                "author": article_data.get("author"),
                "tags": all_tags
            }
            
            # Create KOI Bundle
            bundle = document_to_bundle(document, self.koi_node.node_id)
            
            # Emit appropriate KOI event
            if event_type == "NEW":
                await self.koi_node.emit_new_event(bundle)
            else:
                await self.koi_node.emit_update_event(bundle)
            
            self.logger.info(f"Emitted {event_type} event for article: {article_data.get('title', 'Untitled')} (RID: {rid.to_string()})")
        
        except Exception as e:
            self.logger.error(f"Error emitting event for {url}: {e}")
    
    def generate_auto_tags(self, content: str) -> List[str]:
        """Generate automatic tags based on content"""
        tags = []
        content_lower = content.lower()
        
        # Check for common Regen Network topics
        topic_keywords = {
            "governance": ["governance", "proposal", "voting", "dao"],
            "ecocredits": ["ecocredit", "credit", "carbon", "biodiversity", "nature-based"],
            "marketplace": ["marketplace", "trading", "buying", "selling", "registry"],
            "methodology": ["methodology", "protocol", "standard", "verification"],
            "development": ["development", "technical", "blockchain", "cosmos", "sdk"],
            "community": ["community", "commons", "regenerative", "ecosystem"],
            "climate": ["climate", "climate change", "emissions", "sustainability"],
            "agriculture": ["agriculture", "farming", "soil", "regenerative agriculture"],
            "finance": ["finance", "refi", "investment", "funding", "tokenomics"]
        }
        
        for tag, keywords in topic_keywords.items():
            if any(keyword in content_lower for keyword in keywords):
                tags.append(tag)
        
        return tags


# Example usage and configuration
async def main():
    """Example usage of MediumKOISensor"""
    
    from shared.config.base import KoiNetConfig, MonitoringConfig
    
    # Configuration
    config = MediumMonitorConfig(
        sensor_name="medium-monitor",
        platform="medium",
        api=APIConfig(),  # No API needed for RSS/scraping
        koi_net=KoiNetConfig(
            node_name="medium-monitor-sensor",
            coordinator_url="http://localhost:8005"
        ),
        monitoring=MonitoringConfig(
            log_level="INFO"
        ),
        medium_sources=[
            {
                "name": "regen-network-medium",
                "url": "https://regen-network.medium.com",
                "rss_url": "https://medium.com/feed/@regen-network",
                "check_interval": 21600,  # 6 hours
                "importance": "high"
            }
        ]
    )
    
    sensor = MediumKOISensor(config)
    
    try:
        await sensor.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await sensor.stop()


if __name__ == "__main__":
    asyncio.run(main())