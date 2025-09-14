"""
KOI Sensor Network - Website Monitoring Sensor
Monitors Regen Network websites for content changes using proven server patterns
"""

import asyncio
import aiohttp
import hashlib
from typing import Dict, List, Any, Optional, Set
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import html2text
import re

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import Bundle, document_to_bundle
from shared.config.base import BaseSensorConfig, APIConfig


class WebsiteMonitorConfig(BaseSensorConfig):
    """Website monitoring sensor configuration"""
    
    # Website monitoring settings (excluding forums which are handled by Discourse sensor)
    websites: List[Dict[str, Any]] = [
        {
            "name": "regen-network",
            "url": "https://regen.network",
            "strategy": "scrape",
            "max_depth": 2,
            "check_interval": 3600,  # Check hourly
            "importance": "high",
            "notes": "Main Regen Network website"
        },
        {
            "name": "docs-regen-network",
            "url": "https://docs.regen.network",
            "strategy": "scrape",
            "max_depth": 3,
            "check_interval": 3600,  # Check hourly
            "importance": "high",
            "notes": "Technical documentation"
        },
        {
            "name": "guides-regen-network", 
            "url": "https://guides.regen.network",
            "strategy": "scrape",
            "max_depth": 3,
            "check_interval": 3600,
            "importance": "high",
            "notes": "User guides and tutorials"
        },
        {
            "name": "registry-regen-network",
            "url": "https://registry.regen.network",
            "strategy": "hybrid",
            "max_depth": 2,
            "check_interval": 1800,  # Check every 30 mins (more dynamic)
            "importance": "critical",
            "notes": "Credit classes, methodologies, projects"
        },
        {
            "name": "regen-foundation",
            "url": "https://www.regen.foundation",
            "strategy": "scrape",
            "max_depth": 2,
            "paths": ["/publications", "/initiatives", "/"],
            "check_interval": 7200,  # Check every 2 hours
            "importance": "medium",
            "notes": "Foundation updates, curated documents"
        },
        {
            "name": "research-retreat-papers",
            "url": "https://www.researchretreat.org/papers",
            "strategy": "scrape",
            "max_depth": 2,
            "check_interval": 21600,  # Check every 6 hours (academic papers change slowly)
            "importance": "high",
            "notes": "Academic research papers on regenerative topics - high value content"
        },
        {
            "name": "desci-com",
            "url": "https://desci.com",
            "strategy": "scrape",
            "max_depth": 2,
            "check_interval": 21600,  # Check every 6 hours
            "importance": "medium",
            "notes": "Decentralized science platform"
        },
        {
            "name": "regen-tokenomics",
            "url": "https://regentokenomics.org",
            "strategy": "scrape",
            "max_depth": 2,
            "check_interval": 7200,  # Check every 2 hours
            "importance": "high",
            "notes": "Tokenomics research and documentation"
        }
    ]
    
    # Scraping behavior
    max_concurrent: int = 3
    request_delay: float = 1.0  # Seconds between requests
    user_agent: str = "KOI-Sensor/1.0 (Regen Network Knowledge Indexer; +https://regen.network)"
    timeout_seconds: int = 30
    
    # Content filtering
    min_content_length: int = 200
    exclude_extensions: List[str] = ['.pdf', '.jpg', '.png', '.gif', '.zip', '.mp4', '.mp3']
    include_content_types: List[str] = ['text/html', 'application/xhtml+xml']


class WebPageRID(RID):
    """Web page resource identifier: orn:web.page.domain/path_hash"""
    
    def __init__(self, domain: str, url: str):
        self.domain = domain.replace('.', '_').replace(':', '_')  # Replace dots and colons
        self.full_url = url
        # Create hash of full URL for uniqueness while keeping it manageable
        self.url_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
        super().__init__("orn", f"web.page.{self.domain}.{self.url_hash}")


class WebsiteKOISensor:
    """Website monitoring sensor using proven server patterns"""
    
    def __init__(self, config: WebsiteMonitorConfig):
        self.config = config
        self.logger = self._setup_logging()
        
        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name=f"website-sensor",
            coordinator_url=getattr(config.koi_net, 'coordinator_url', 'http://localhost:8005'),
            poll_interval=30
        )
        
        # Website monitoring state
        self.monitored_pages: Dict[str, Dict[str, Any]] = {}
        self.page_hashes: Dict[str, str] = {}  # URL -> content hash
        self.crawl_queues: Dict[str, Set[str]] = {}  # domain -> URLs to crawl
        
        # HTTP session
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Content converter
        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
        self.html_converter.ignore_images = True
        self.html_converter.body_width = 0  # No wrapping
    
    def _setup_logging(self):
        """Setup logging for website sensor"""
        import logging
        logger = logging.getLogger(f"koi.sensor.website")
        logger.setLevel(getattr(logging, self.config.monitoring.log_level))
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        return logger
    
    async def start(self):
        """Start website monitoring sensor"""
        self.logger.info("Starting Website KOI Sensor")
        
        # Configure KOI node logging to match sensor logging
        import logging
        koi_logger = logging.getLogger(f"koi.node.website-sensor")
        koi_logger.setLevel(logging.INFO)
        koi_logger.handlers = self.logger.handlers  # Use same handlers as sensor
        
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
        
        # Initialize crawl queues for each website
        for website in self.config.websites:
            domain = urlparse(website["url"]).netloc
            self.crawl_queues[domain] = set()
            
            # Add initial URLs to queue
            if "paths" in website:
                for path in website["paths"]:
                    full_url = urljoin(website["url"], path)
                    self.crawl_queues[domain].add(full_url)
            else:
                self.crawl_queues[domain].add(website["url"])
        
        # Start monitoring loops for each website
        tasks = []
        for website in self.config.websites:
            task = asyncio.create_task(self.monitor_website(website))
            tasks.append(task)
        
        # Wait for all monitoring tasks
        await asyncio.gather(*tasks)
    
    async def stop(self):
        """Stop website monitoring sensor"""
        self.logger.info("Stopping Website KOI Sensor")
        
        if self.session:
            await self.session.close()
        
        await self.koi_node.stop()
    
    async def monitor_website(self, website_config: Dict[str, Any]):
        """Monitor a single website for changes"""
        domain = urlparse(website_config["url"]).netloc
        check_interval = website_config.get("check_interval", 3600)
        
        self.logger.info(f"Starting monitoring for {domain} (interval: {check_interval}s)")
        
        while self.koi_node.running:
            try:
                # Crawl and check for changes
                await self.crawl_website(website_config)
                
                self.logger.debug(f"Completed crawl cycle for {domain}")
                
                # Wait for next check
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                self.logger.error(f"Error monitoring {domain}: {e}")
                await asyncio.sleep(60)  # Wait longer after errors
    
    async def crawl_website(self, website_config: Dict[str, Any]):
        """Crawl a website and detect changes"""
        domain = urlparse(website_config["url"]).netloc
        max_depth = website_config.get("max_depth", 2)
        strategy = website_config.get("strategy", "scrape")
        
        # Get URLs to process
        urls_to_process = list(self.crawl_queues[domain])
        if not urls_to_process:
            urls_to_process = [website_config["url"]]
        
        processed_count = 0
        new_urls = set()
        
        # Process URLs with concurrency limit
        semaphore = asyncio.Semaphore(self.config.max_concurrent)
        
        async def process_url_safe(url: str, depth: int):
            nonlocal processed_count, new_urls
            
            async with semaphore:
                try:
                    result = await self.process_page(url, depth, max_depth, strategy)
                    if result:
                        processed_count += 1
                        # Add discovered URLs
                        if result.get("discovered_urls"):
                            new_urls.update(result["discovered_urls"])
                    
                    # Rate limiting
                    if self.config.request_delay > 0:
                        await asyncio.sleep(self.config.request_delay)
                        
                except Exception as e:
                    self.logger.error(f"Error processing {url}: {e}")
        
        # Process initial URLs
        tasks = []
        for url in urls_to_process[:20]:  # Limit initial crawl
            task = asyncio.create_task(process_url_safe(url, 0))
            tasks.append(task)
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # Update crawl queue with new URLs for next cycle
        if new_urls and len(self.crawl_queues[domain]) < 100:  # Limit queue size
            self.crawl_queues[domain].update(new_urls)
        
        self.logger.info(f"Crawled {domain}: {processed_count} pages processed, {len(new_urls)} new URLs discovered")
    
    async def process_page(self, url: str, depth: int, max_depth: int, strategy: str) -> Optional[Dict[str, Any]]:
        """Process a single web page"""
        
        if depth > max_depth:
            return None
        
        if not self.session:
            return None
        
        try:
            # Fetch page
            async with self.session.get(url) as response:
                if response.status != 200:
                    self.logger.warning(f"HTTP {response.status} for {url}")
                    return None
                
                content_type = response.headers.get('content-type', '').lower()
                if not any(ct in content_type for ct in self.config.include_content_types):
                    return None
                
                html_content = await response.text()
        
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return None
        
        # Parse content
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extract clean text content
        text_content = self.extract_clean_content(soup, url)
        
        if len(text_content) < self.config.min_content_length:
            return None
        
        # Calculate content hash
        content_hash = hashlib.sha256(text_content.encode('utf-8')).hexdigest()
        
        # Check if content changed
        previous_hash = self.page_hashes.get(url)
        content_changed = previous_hash != content_hash
        
        if content_changed or previous_hash is None:
            # Content is new or changed
            await self.emit_page_event(url, text_content, soup, 
                                     "NEW" if previous_hash is None else "UPDATE")
            
            # Update hash
            self.page_hashes[url] = content_hash
        
        # Discover new URLs if within depth limit
        discovered_urls = set()
        if depth < max_depth:
            discovered_urls = self.extract_internal_urls(soup, url)
        
        return {
            "url": url,
            "content_length": len(text_content),
            "content_changed": content_changed,
            "discovered_urls": discovered_urls
        }
    
    def extract_clean_content(self, soup: BeautifulSoup, url: str) -> str:
        """Extract clean text content from HTML"""
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "aside"]):
            script.decompose()
        
        # Get page title
        title = ""
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text().strip()
        
        # Convert HTML to markdown-style text
        html_content = str(soup)
        text_content = self.html_converter.handle(html_content)
        
        # Clean up text
        text_content = re.sub(r'\\n\\s*\\n\\s*\\n+', '\\n\\n', text_content)  # Remove excessive newlines
        text_content = re.sub(r'[\\r\\n]+', '\\n', text_content)  # Normalize line endings
        text_content = text_content.strip()
        
        # Combine title and content
        if title and title not in text_content[:200]:
            text_content = f"# {title}\\n\\n{text_content}"
        
        return text_content
    
    def extract_internal_urls(self, soup: BeautifulSoup, base_url: str) -> Set[str]:
        """Extract internal URLs from page"""
        
        base_domain = urlparse(base_url).netloc
        discovered_urls = set()
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            
            # Convert relative URLs to absolute
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            
            # Only include same-domain URLs
            if parsed.netloc == base_domain:
                # Filter out unwanted extensions
                if not any(full_url.lower().endswith(ext) for ext in self.config.exclude_extensions):
                    # Remove fragment and query parameters for cleaner URLs
                    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    discovered_urls.add(clean_url)
        
        return discovered_urls
    
    async def emit_page_event(self, url: str, content: str, soup: BeautifulSoup, event_type: str):
        """Emit KOI event for web page"""
        
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc
            
            # Create RID
            rid = WebPageRID(domain, url)
            
            # Extract page metadata
            metadata = self.extract_page_metadata(soup, url)
            
            # Extract publication date for Daily Curator
            import sys
            sys.path.append('/Users/darrenzal/projects/RegenAI/koi-processor')
            try:
                from utils.date_extractor import extract_publication_date
                published_at, confidence = extract_publication_date(str(soup), 'website')
            except:
                published_at, confidence = None, 0.0
            
            # Fallback to last-modified if no publication date found
            if not published_at and metadata.get("last_modified"):
                try:
                    from dateutil import parser
                    published_at = parser.parse(metadata["last_modified"])
                    confidence = 0.6  # Lower confidence for modification date
                except:
                    pass
            
            # Create document in format compatible with existing system
            document = {
                "id": f"web_{rid.url_hash}",
                "source": f"web:{domain}",
                "source_type": "website",
                "url": url,
                "title": metadata.get("title", ""),
                "content": content,
                "metadata": {
                    # Publication date metadata for Daily Curator
                    "published_at": published_at.isoformat() if published_at else None,
                    "published_confidence": confidence,
                    "extracted_from": "meta_tags" if confidence > 0.8 else "last_modified" if confidence > 0.5 else "unknown",
                    
                    # Original metadata
                    "domain": domain,
                    "path": parsed_url.path,
                    "description": metadata.get("description", ""),
                    "keywords": metadata.get("keywords", []),
                    "language": metadata.get("language", "en"),
                    "last_modified": metadata.get("last_modified"),
                    "content_type": "text/html",
                    "word_count": len(content.split()),
                    "collection_method": "web_scraping",
                    "koi_sensor": "website-monitor"
                },
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "last_modified": metadata.get("last_modified"),
                "author": metadata.get("author"),
                "tags": metadata.get("keywords", [])
            }
            
            # Create KOI Bundle
            bundle = document_to_bundle(document, self.koi_node.node_id)
            
            # Emit appropriate KOI event
            if event_type == "NEW":
                await self.koi_node.emit_new_event(bundle)
            else:
                await self.koi_node.emit_update_event(bundle)
            
            self.logger.info(f"Emitted {event_type} event for {url} (RID: {rid.to_string()})")
        
        except Exception as e:
            self.logger.error(f"Error emitting event for {url}: {e}")
    
    def extract_page_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract metadata from HTML page"""
        
        metadata = {}
        
        # Title
        title_tag = soup.find('title')
        if title_tag:
            metadata["title"] = title_tag.get_text().strip()
        
        # Meta tags
        meta_tags = soup.find_all('meta')
        for meta in meta_tags:
            name = meta.get('name', '').lower()
            property_attr = meta.get('property', '').lower()
            content = meta.get('content', '')
            
            if name == 'description' or property_attr == 'og:description':
                metadata["description"] = content
            elif name == 'keywords':
                metadata["keywords"] = [k.strip() for k in content.split(',') if k.strip()]
            elif name == 'author':
                metadata["author"] = content
            elif name == 'language' or property_attr == 'og:locale':
                metadata["language"] = content.split('-')[0] if '-' in content else content
            elif name == 'last-modified' or name == 'date':
                metadata["last_modified"] = content
        
        return metadata


# Example usage and configuration
async def main():
    """Example usage of WebsiteKOISensor"""
    
    from shared.config.base import KoiNetConfig, MonitoringConfig
    
    # Configuration matching server patterns
    config = WebsiteMonitorConfig(
        sensor_name="website-monitor",
        platform="websites", 
        api=APIConfig(),  # No API needed for web scraping
        koi_net=KoiNetConfig(
            node_name="website-monitor-sensor",
            coordinator_url="http://localhost:8005"
        ),
        monitoring=MonitoringConfig(
            log_level="INFO"
        ),
        websites=[
            {
                "name": "docs-regen-network",
                "url": "https://docs.regen.network", 
                "strategy": "scrape",
                "max_depth": 3,
                "check_interval": 3600,
                "importance": "high"
            },
            {
                "name": "guides-regen-network",
                "url": "https://guides.regen.network",
                "strategy": "scrape", 
                "max_depth": 3,
                "check_interval": 3600,
                "importance": "high"
            },
            {
                "name": "registry-regen-network",
                "url": "https://registry.regen.network",
                "strategy": "hybrid",
                "max_depth": 2,
                "check_interval": 1800,  # More frequent for dynamic content
                "importance": "critical"
            }
        ]
    )
    
    sensor = WebsiteKOISensor(config)
    
    try:
        await sensor.start()
    except KeyboardInterrupt:
        print("\\nShutting down...")
        await sensor.stop()


if __name__ == "__main__":
    asyncio.run(main())