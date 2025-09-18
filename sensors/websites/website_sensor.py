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
import json

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import Bundle, document_to_bundle
from shared.config.base import BaseSensorConfig, APIConfig
from sites import SITE_HANDLERS

try:
    from video_transcriber import VideoTranscriber
except ImportError:
    # Video transcriber is optional
    VideoTranscriber = None


class WebsiteMonitorConfig(BaseSensorConfig):
    """Website monitoring sensor configuration"""

    # Website monitoring settings (excluding forums which are handled by Discourse sensor)
    websites: List[Dict[str, Any]] = []  # Will be loaded from config.yaml or passed in __init__
    
    # Scraping behavior
    max_concurrent: int = 3
    request_delay: float = 1.0  # Seconds between requests
    user_agent: str = "KOI-Sensor/1.0 (Regen Network Knowledge Indexer; +https://regen.network)"
    timeout_seconds: int = 30
    
    # Content filtering
    min_content_length: int = 200
    exclude_extensions: List[str] = ['.pdf', '.jpg', '.png', '.gif', '.zip', '.mp3']  # Removed .mp4 for video processing
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
        self.pages_crawled: Dict[str, int] = {}  # domain -> count of pages crawled
        self.video_queue: List[Dict[str, Any]] = []  # Queue for videos to transcribe

        # Initialize video transcriber if available
        self.video_transcriber = None
        if VideoTranscriber:
            try:
                self.video_transcriber = VideoTranscriber()
                self.logger.info("Video transcription enabled")
            except Exception as e:
                self.logger.warning(f"Could not initialize video transcriber: {e}")
        
        # HTTP session
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Content converter - DEPRECATED: html2text was causing word-breaking issues
        # Now using BeautifulSoup's get_text() method for cleaner extraction
        # self.html_converter = html2text.HTML2Text()
        # self.html_converter.ignore_links = False
        # self.html_converter.ignore_images = True
        # self.html_converter.body_width = 0  # No wrapping
    
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
    
    async def send_heartbeat_event(self, response_to: str = None):
        """Send a heartbeat event to register with coordinator"""
        try:
            heartbeat_data = {
                "type": "sensor_heartbeat",
                "sensor_id": "website-sensor",
                "sensor_type": "websites",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "active",
                "monitoring": [site['name'] for site in self.config.websites],
                "pages_tracked": len(self.page_hashes)
            }

            if response_to:
                heartbeat_data["response_to"] = response_to

            # Create document for heartbeat
            heartbeat_document = {
                'id': f"websites_heartbeat_{int(datetime.now().timestamp())}",
                'title': 'Websites Sensor Heartbeat',
                'url': '',
                'type': 'heartbeat',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'content': json.dumps(heartbeat_data),
                'metadata': {
                    'sensor_type': 'websites',
                    'sensor_id': self.config.koi_net.node_name,
                    'event_type': 'HEARTBEAT'
                }
            }

            # Convert to bundle and emit
            bundle = document_to_bundle(heartbeat_document)
            await self.koi_node.emit_new_event(bundle)

            if not response_to:
                self.logger.info("Sent heartbeat event to coordinator")
            else:
                self.logger.info(f"Responded to ping request {response_to}")

        except Exception as e:
            self.logger.error(f"Error sending heartbeat: {e}")

    async def send_periodic_heartbeats(self):
        """Send periodic heartbeats every 30 minutes"""
        while self.koi_node.running:
            await asyncio.sleep(1800)  # 30 minutes
            await self.send_heartbeat_event()

    async def handle_coordinator_events(self):
        """Listen for ping requests from coordinator"""
        try:
            # Subscribe to coordinator events
            async for event in self.koi_node.event_stream():
                if event.get('type') == 'PING_REQUEST':
                    # Check if this ping is for us
                    target = event.get('target')
                    if target == 'website-sensor' or target == 'websites-sensor' or target == 'all':
                        self.logger.info(f"Received ping request, responding...")
                        await self.send_heartbeat_event(response_to=event.get('id'))
        except Exception as e:
            self.logger.error(f"Error handling coordinator events: {e}")

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

        # Send initial heartbeat to register
        await self.send_heartbeat_event()

        # Start background tasks
        asyncio.create_task(self.send_periodic_heartbeats())
        asyncio.create_task(self.handle_coordinator_events())
        
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
            self.pages_crawled[domain] = 0
            
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
    
    async def process_video_queue(self):
        """Process videos in the queue"""
        if not self.video_transcriber or not self.video_queue:
            return

        while self.video_queue:
            video_info = self.video_queue.pop(0)
            try:
                self.logger.info(f"Processing video from {video_info['source_page']}")
                result = await self.video_transcriber.process_video(video_info)

                if result and result.get('transcript'):
                    # Create a document for the transcript
                    doc = {
                        'id': f"video_transcript_{hashlib.sha256(video_info['url'].encode()).hexdigest()[:16]}",
                        'source': video_info['source_page'],
                        'source_type': 'video_transcript',
                        'url': video_info['url'],
                        'title': f"Video Transcript: {video_info.get('title', 'Video')}",
                        'content': result['transcript'],
                        'author': 'Video Transcription',
                        'tags': ['video', 'transcript', urlparse(video_info['source_page']).netloc],
                        'collected_at': datetime.now(timezone.utc).isoformat(),
                        'last_modified': datetime.now(timezone.utc).isoformat(),
                        'metadata': {
                            'video_type': video_info['type'],
                            'source_page': video_info['source_page'],
                            'transcribed_at': result.get('transcribed_at')
                        }
                    }

                    # Emit as KOI event
                    await self.emit_video_transcript_event(doc)

            except Exception as e:
                self.logger.error(f"Error processing video {video_info.get('url')}: {e}")

    async def emit_video_transcript_event(self, doc: Dict[str, Any]):
        """Emit KOI event for video transcript"""
        try:
            # Create bundle
            bundle = document_to_bundle(doc)

            # Emit event
            await self.emit_new_event(bundle)
            self.logger.info(f"Emitted video transcript event for {doc['url']}")

        except Exception as e:
            self.logger.error(f"Error emitting video transcript event: {e}")

    async def stop(self):
        """Stop website monitoring sensor"""
        self.logger.info("Stopping Website KOI Sensor")

        # Process remaining videos
        if self.video_queue:
            self.logger.info(f"Processing {len(self.video_queue)} remaining videos...")
            await self.process_video_queue()

        if self.session:
            await self.session.close()

        # Cleanup video transcriber
        if self.video_transcriber:
            self.video_transcriber.cleanup()
        
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

                # Process any queued videos after crawling
                if self.video_queue and self.video_transcriber:
                    self.logger.info(f"Processing {len(self.video_queue)} videos from {domain}")
                    await self.process_video_queue()

                self.logger.debug(f"Completed crawl cycle for {domain}")
                
                # Wait for next check
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                self.logger.error(f"Error monitoring {domain}: {e}")
                await asyncio.sleep(60)  # Wait longer after errors
    
    async def crawl_website(self, website_config: Dict[str, Any]):
        """Crawl a website and detect changes"""
        domain = urlparse(website_config["url"]).netloc
        max_depth = website_config.get("max_depth", 2)  # Still passed but not used for limiting
        max_pages = website_config.get("max_pages", 1000)  # Default to 1000 pages
        strategy = website_config.get("strategy", "scrape")

        # Get URLs to process
        urls_to_process = list(self.crawl_queues[domain])
        if not urls_to_process:
            urls_to_process = [website_config["url"]]
            self.logger.info(f"No URLs in queue for {domain}, using initial URL: {website_config['url']}")
        else:
            self.logger.info(f"Processing {len(urls_to_process)} URLs from queue for {domain}")
        
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
                            self.logger.debug(f"Discovered {len(result['discovered_urls'])} URLs from {url}")
                    else:
                        self.logger.warning(f"No result from processing {url}")

                    # Rate limiting
                    if self.config.request_delay > 0:
                        await asyncio.sleep(self.config.request_delay)
                        
                except Exception as e:
                    self.logger.error(f"Error processing {url}: {e}", exc_info=True)
        
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
            self.logger.info(f"Added {len(new_urls)} new URLs to queue for {domain}, queue now has {len(self.crawl_queues[domain])} URLs")

        self.logger.info(f"Crawled {domain}: {processed_count} pages processed, {len(new_urls)} new URLs discovered")
    
    async def process_page(self, url: str, depth: int, max_depth: int, strategy: str) -> Optional[Dict[str, Any]]:
        """Process a single web page"""

        # Check if we've reached the page limit
        domain = urlparse(url).netloc
        if domain in self.pages_crawled and self.pages_crawled[domain] >= 1000:  # Hard limit at 1000 for now
            self.logger.debug(f"Reached page limit for {domain}, skipping {url}")
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
            
            # Update hash and increment page count
            self.page_hashes[url] = content_hash
            if domain in self.pages_crawled:
                self.pages_crawled[domain] += 1
        
        # Always discover internal URLs (no depth limit)
        discovered_urls = self.extract_internal_urls(soup, url)

        # Extract video URLs if enabled for this site
        video_urls = []
        if strategy != 'discourse_api':  # Don't extract videos from discourse API
            video_urls = self.extract_video_urls(soup, url)
            if video_urls:
                self.logger.info(f"Found {len(video_urls)} videos on {url}")
                # Add to video queue for processing
                self.video_queue.extend(video_urls)

        return {
            "url": url,
            "content_length": len(text_content),
            "content_changed": content_changed,
            "discovered_urls": discovered_urls,
            "video_urls": video_urls
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

        # Extract text properly without duplicates
        # Use a set to track seen text and preserve order
        seen_texts = set()
        paragraphs = []

        # Process only direct text-containing elements, not nested ones
        # Start with headers, paragraphs, and divs with meaningful content
        for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'article', 'section', 'main']):
            text = element.get_text(separator=' ', strip=True)
            if text and len(text) > 5:  # Keep most content, skip only tiny fragments
                # Clean up the text
                text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
                text = text.strip()

                # Check if we've seen this exact text or a subset
                if text not in seen_texts:
                    # Also check if this text is not a subset of something we've seen
                    is_subset = False
                    for seen in seen_texts:
                        if text in seen:
                            is_subset = True
                            break

                    if not is_subset:
                        paragraphs.append(text)
                        seen_texts.add(text)

        # Now get list items separately
        for element in soup.find_all('li'):
            # Only get direct text, not nested list items
            text = ''.join([str(s) for s in element.stripped_strings])
            if text and len(text) > 10:
                text = re.sub(r'\s+', ' ', text).strip()
                if text not in seen_texts:
                    paragraphs.append(f"• {text}")
                    seen_texts.add(text)

        # Join paragraphs with single newlines for cleaner output
        text_content = '\n'.join(paragraphs)

        # Final cleanup - remove excessive blank lines
        lines = text_content.split('\n')
        cleaned_lines = []
        prev_blank = False

        for line in lines:
            is_blank = not line.strip()
            if is_blank and prev_blank:
                continue  # Skip multiple blank lines
            cleaned_lines.append(line)
            prev_blank = is_blank

        text_content = '\n'.join(cleaned_lines).strip()

        # Add title if not already present
        if title and title not in text_content[:200]:
            text_content = f"# {title}\n\n{text_content}"

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

    def extract_video_urls(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Extract video URLs from page including YouTube/Vimeo embeds and direct mp4 links"""
        videos = []

        # Look for direct video links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.lower().endswith('.mp4'):
                full_url = urljoin(base_url, href)
                videos.append({
                    'type': 'direct',
                    'url': full_url,
                    'source_page': base_url,
                    'title': link.get_text(strip=True) or 'Video'
                })

        # Look for video tags
        for video in soup.find_all('video'):
            src = video.get('src')
            if src:
                full_url = urljoin(base_url, src)
                videos.append({
                    'type': 'embedded',
                    'url': full_url,
                    'source_page': base_url,
                    'title': 'Embedded Video'
                })
            # Check source tags within video
            for source in video.find_all('source'):
                src = source.get('src')
                if src and src.lower().endswith('.mp4'):
                    full_url = urljoin(base_url, src)
                    videos.append({
                        'type': 'embedded',
                        'url': full_url,
                        'source_page': base_url,
                        'title': 'Embedded Video'
                    })

        # Look for YouTube iframes
        for iframe in soup.find_all('iframe'):
            src = iframe.get('src', '')
            if 'youtube.com' in src or 'youtu.be' in src:
                videos.append({
                    'type': 'youtube',
                    'url': src,
                    'source_page': base_url,
                    'title': iframe.get('title', 'YouTube Video')
                })
            elif 'vimeo.com' in src:
                videos.append({
                    'type': 'vimeo',
                    'url': src,
                    'source_page': base_url,
                    'title': iframe.get('title', 'Vimeo Video')
                })

        return videos
    
    async def emit_page_event(self, url: str, content: str, soup: BeautifulSoup, event_type: str):
        """Emit KOI event for web page"""

        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc

            # Create RID
            rid = WebPageRID(domain, url)

            # Extract page metadata
            metadata = self.extract_page_metadata(soup, url)

            # Extract publication date with site-specific patterns
            published_at, confidence = self.extract_publication_date(soup, url, domain)

            # Fallback to last-modified if no publication date found
            if not published_at and metadata.get("last_modified"):
                try:
                    from dateutil import parser
                    published_at = parser.parse(metadata["last_modified"])
                    confidence = 0.6  # Lower confidence for modification date
                except Exception:
                    pass
            
            # Create document in format compatible with existing system
            document = {
                "id": f"web_{rid.url_hash}",
                "source": f"web:{domain}",
                "source_type": "website",
                "url": url,  # CRITICAL: URL at root level for provenance
                "source_url": url,  # Additional field to ensure preservation
                "title": metadata.get("title", ""),
                "content": content,
                "metadata": {
                    # Core metadata fields for provenance
                    "title": metadata.get("title", ""),
                    "url": url,  # Also in metadata for redundancy
                    "source_url": url,  # Extra safeguard
                    "author": metadata.get("author", ""),
                    "source_name": domain,
                    "source_type": "website",

                    # Publication date metadata for Daily Curator
                    "published_at": published_at.isoformat() if published_at else None,
                    "published_date": published_at.strftime('%Y-%m-%d') if published_at else None,  # Date-only format for compatibility
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
    
    def extract_publication_date(self, soup: BeautifulSoup, url: str, domain: str):
        """Extract publication date using site-specific patterns"""
        from datetime import datetime
        import re

        published_at = None
        confidence = 0.0

        try:
            # Check if we have a site-specific handler
            site_handler_class = SITE_HANDLERS.get(domain)
            if site_handler_class:
                # Use site-specific handler
                site_handler = site_handler_class(domain, self.logger)
                published_at, confidence = site_handler.extract_publication_date(soup, url)
                if published_at:
                    self.logger.info(f"Used site-specific handler for {domain}: {published_at} (confidence: {confidence})")
                    return published_at, confidence
                else:
                    self.logger.debug(f"Site-specific handler for {domain} returned no date")

            # Fallback to generic extraction if no handler or no date found
            # Site-specific extraction patterns
            if 'regentokenomics.org' in domain:
                # Look for dates in list items like "September 16, 2025"
                date_pattern = r'((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})'
                text = str(soup)
                match = re.search(date_pattern, text)
                if match:
                    date_str = match.group(1)
                    try:
                        published_at = datetime.strptime(date_str, '%B %d, %Y')
                        confidence = 0.8
                        self.logger.debug(f"Found date on regentokenomics.org: {date_str}")
                    except Exception as e:
                        self.logger.debug(f"Failed to parse date {date_str}: {e}")

            elif 'regen.foundation' in domain and '/publications' in url:
                # Look for "Published May 22, 2025" format
                date_pattern = r'Published\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}'
                text = str(soup)
                match = re.search(date_pattern, text)
                if match:
                    date_str = match.group(0).replace('Published ', '')
                    try:
                        published_at = datetime.strptime(date_str, '%B %d, %Y')
                        confidence = 0.9
                        self.logger.debug(f"Found publication date on regen.foundation: {date_str}")
                    except:
                        pass

            elif 'forum.regen.network' in domain or 'discourse' in domain:
                # Enhanced Discourse forum date extraction
                # Priority 1: Look for time elements with datetime attributes
                time_elements = soup.find_all(['time', 'relative-time'])
                for elem in time_elements:
                    datetime_attr = elem.get('datetime')
                    if datetime_attr:
                        try:
                            from dateutil import parser
                            published_at = parser.parse(datetime_attr)
                            confidence = 0.95
                            self.logger.debug(f"Found Discourse datetime attribute: {datetime_attr}")
                            break
                        except:
                            pass

                # Priority 2: Look for date in specific class patterns
                if not published_at:
                    date_elements = soup.find_all(['span', 'div', 'time'], attrs={'class': re.compile(r'date|time|post-time|relative-time|cooked-date')})
                    for elem in date_elements:
                        date_str = elem.get_text(strip=True)
                        if date_str:
                            try:
                                from dateutil import parser
                                published_at = parser.parse(date_str, fuzzy=True)
                                confidence = 0.85
                                self.logger.debug(f"Found Discourse date text: {date_str}")
                                break
                            except:
                                pass

                # Priority 3: Look for relative date patterns
                if not published_at:
                    relative_patterns = [
                        (r'(\d+)\s*min(?:ute)?s?\s+ago', 'minutes'),
                        (r'(\d+)\s*h(?:ou)?rs?\s+ago', 'hours'),
                        (r'(\d+)\s*d(?:ay)?s?\s+ago', 'days'),
                        (r'yesterday', 'yesterday'),
                        (r'(\d+)\s*w(?:ee)?ks?\s+ago', 'weeks')
                    ]
                    page_text = soup.get_text()[:5000]
                    for pattern, unit in relative_patterns:
                        match = re.search(pattern, page_text, re.IGNORECASE)
                        if match:
                            from datetime import timedelta
                            if unit == 'yesterday':
                                published_at = datetime.now() - timedelta(days=1)
                            else:
                                amount = int(match.group(1))
                                if unit == 'minutes':
                                    published_at = datetime.now() - timedelta(minutes=amount)
                                elif unit == 'hours':
                                    published_at = datetime.now() - timedelta(hours=amount)
                                elif unit == 'days':
                                    published_at = datetime.now() - timedelta(days=amount)
                                elif unit == 'weeks':
                                    published_at = datetime.now() - timedelta(weeks=amount)
                            confidence = 0.75
                            self.logger.debug(f"Found relative date: {match.group(0) if unit != 'yesterday' else 'yesterday'}")
                            break

            elif 'guides.regen.network' in domain or 'docs.regen.network' in domain:
                # Documentation sites might have "Last updated" dates
                # Look for relative dates like "Last updated 1 year ago"
                text = str(soup)
                if 'Last updated' in text:
                    # For now, use current date with low confidence for relative dates
                    published_at = datetime.now()
                    confidence = 0.3
                    self.logger.debug(f"Found relative date on {domain}, using current date with low confidence")

            # Skip generic ISO date extraction - it causes too many false positives
            # Only use structured data and meta tags for generic extraction

            # Try meta tags as last resort
            if not published_at:
                for meta in soup.find_all('meta'):
                    prop = meta.get('property', '').lower()
                    name = meta.get('name', '').lower()
                    content = meta.get('content', '')

                    if any(x in prop or x in name for x in ['article:published_time', 'datePublished', 'date', 'DC.date']):
                        try:
                            from dateutil import parser
                            published_at = parser.parse(content)
                            confidence = 0.8
                            self.logger.debug(f"Found date in meta tag: {content}")
                            break
                        except:
                            pass

            if published_at:
                self.logger.info(f"Extracted date for {domain}: {published_at.isoformat()} (confidence: {confidence})")

        except Exception as e:
            self.logger.error(f"Error extracting date for {url}: {e}")

        return published_at, confidence

    def extract_page_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract metadata from HTML page"""
        from urllib.parse import urlparse

        metadata = {}
        parsed_url = urlparse(url)
        domain = parsed_url.netloc

        # Check if we have a site-specific handler for enhanced metadata
        site_handler_class = SITE_HANDLERS.get(domain)
        if site_handler_class:
            # Use site-specific handler for metadata
            site_handler = site_handler_class(domain, self.logger)
            site_metadata = site_handler.extract_metadata(soup, url)
            metadata.update(site_metadata)
            self.logger.debug(f"Extracted site-specific metadata for {domain}: {list(site_metadata.keys())}")

        # Always extract basic metadata regardless
        # Title
        title_tag = soup.find('title')
        if title_tag and 'title' not in metadata:
            metadata["title"] = title_tag.get_text().strip()

        # Meta tags
        meta_tags = soup.find_all('meta')
        for meta in meta_tags:
            name = meta.get('name', '').lower()
            property_attr = meta.get('property', '').lower()
            content = meta.get('content', '')

            if (name == 'description' or property_attr == 'og:description') and 'description' not in metadata:
                metadata["description"] = content
            elif name == 'keywords' and 'keywords' not in metadata:
                metadata["keywords"] = [k.strip() for k in content.split(',') if k.strip()]
            elif name == 'author' and 'author' not in metadata:
                metadata["author"] = content
            elif (name == 'language' or property_attr == 'og:locale') and 'language' not in metadata:
                metadata["language"] = content.split('-')[0] if '-' in content else content
            elif (name == 'last-modified' or name == 'date') and 'last_modified' not in metadata:
                metadata["last_modified"] = content

        return metadata


# Example usage and configuration
async def main():
    """Example usage of WebsiteKOISensor with continuous polling"""
    import os
    from dotenv import load_dotenv

    # Load environment variables
    load_dotenv()

    # Get polling interval from environment (default 30 minutes)
    poll_interval = int(os.getenv('WEBSITE_POLL_INTERVAL', 1800))

    from shared.config.base import KoiNetConfig, MonitoringConfig
    from pathlib import Path
    import yaml

    # Load configuration from YAML file
    config_path = Path(__file__).parent / "config.yaml"
    websites_config = []

    if config_path.exists():
        print(f"Loading websites from config.yaml at {config_path}")
        with open(config_path, 'r') as f:
            yaml_config = yaml.safe_load(f)
            websites_config = yaml_config.get('websites', [])
            print(f"Loaded {len(websites_config)} websites from config.yaml")
            # Convert to expected format
            for site in websites_config:
                site['check_interval'] = site.get('check_interval', poll_interval)
                print(f"  - {site.get('name', 'unknown')}: {site.get('url', 'no-url')}")
    else:
        print(f"WARNING: Config file not found at {config_path}, using fallback")
        # Fallback to hardcoded config
        websites_config = [
            {
                "name": "docs-regen-network",
                "url": "https://docs.regen.network",
                "strategy": "scrape",
                "max_depth": 3,
                "check_interval": poll_interval,
                "importance": "high"
            },
            {
                "name": "guides-regen-network",
                "url": "https://guides.regen.network",
                "strategy": "scrape",
                "max_depth": 3,
                "check_interval": poll_interval,
                "importance": "high"
            },
            {
                "name": "registry-regen-network",
                "url": "https://registry.regen.network",
                "strategy": "hybrid",
                "max_depth": 2,
                "check_interval": poll_interval,
                "importance": "critical"
            }
        ]

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
        websites=websites_config
    )

    sensor = WebsiteKOISensor(config)

    print(f"Starting Website sensor with {poll_interval} second polling interval ({poll_interval/60:.1f} minutes)")

    try:
        await sensor.start()
    except KeyboardInterrupt:
        print("\\nShutting down...")
        await sensor.stop()


if __name__ == "__main__":
    asyncio.run(main())