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
from pathlib import Path
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

try:
    from playwright.async_api import async_playwright, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None
    Page = None


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

    # Playwright settings for JavaScript-heavy sites
    use_playwright: bool = False  # Enable Playwright for all sites
    playwright_domains: List[str] = ['regentokenomics.org']  # Domains that require Playwright
    playwright_wait_time: int = 3000  # ms to wait for content to load
    playwright_expand_toggles: bool = True  # Auto-expand Notion-style toggle blocks


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

        # Persistent state file for crawl queues (survives restarts)
        self.state_file = Path(__file__).parent / "website_sensor_state.json"

        # Website monitoring state
        self.monitored_pages: Dict[str, Dict[str, Any]] = {}
        self.page_hashes: Dict[str, str] = {}  # URL -> content hash
        self.crawl_queues: Dict[str, Set[str]] = {}  # domain -> URLs to crawl
        self.pages_crawled: Dict[str, int] = {}  # domain -> count of pages crawled
        # Video transcription is now inline during page event emission (no queue needed)

        # Load persistent state from previous runs
        self._load_state()

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

        # Playwright browser for JavaScript-heavy sites
        self.playwright = None
        self.browser = None
        self.browser_context = None

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

    def _load_state(self):
        """Load persistent crawl queue state from JSON file"""
        if not self.state_file.exists():
            self.logger.info("No previous state file found, starting fresh")
            return

        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)

            # Restore crawl queues (convert lists back to sets)
            for domain, urls in state.get('crawl_queues', {}).items():
                self.crawl_queues[domain] = set(urls)

            # Restore page counts
            self.pages_crawled = state.get('pages_crawled', {})

            # Restore page hashes
            self.page_hashes = state.get('page_hashes', {})

            self.logger.info(f"Loaded state: {len(self.crawl_queues)} domains, {sum(len(q) for q in self.crawl_queues.values())} queued URLs")

        except Exception as e:
            self.logger.error(f"Error loading state file: {e}")

    def _save_state(self):
        """Save persistent crawl queue state to JSON file"""
        try:
            state = {
                'crawl_queues': {domain: list(urls) for domain, urls in self.crawl_queues.items()},
                'pages_crawled': self.pages_crawled,
                'page_hashes': self.page_hashes,
                'last_saved': datetime.now(timezone.utc).isoformat()
            }

            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)

            self.logger.debug(f"Saved state: {len(self.crawl_queues)} domains, {sum(len(q) for q in self.crawl_queues.values())} queued URLs")

        except Exception as e:
            self.logger.error(f"Error saving state file: {e}")

    async def send_heartbeat_event(self, response_to: str = None):
        """Send a heartbeat event to register with coordinator"""
        try:
            # Only include enabled sites in the monitoring list
            enabled_sites = [
                site['name'] for site in self.config.websites
                if site.get('enabled', True) is not False
            ]
            heartbeat_data = {
                "type": "sensor_heartbeat",
                "sensor_id": "website-sensor",
                "sensor_type": "websites",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "active",
                "monitoring": enabled_sites,
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

    async def trigger_crawl(self, request):
        """HTTP endpoint to manually trigger crawl of specific URL(s)"""
        try:
            data = await request.json()
            url = data.get('url')
            domain = data.get('domain')

            if url:
                # Single URL crawl
                self.logger.info(f"🔄 Manual trigger: crawling {url}")
                parsed = urlparse(url)
                domain_key = parsed.netloc

                # Clear cached hash for this URL to force re-emission (important for manual re-scrapes)
                if url in self.page_hashes:
                    self.logger.info(f"Clearing cached hash for {url} to force event emission")
                    del self.page_hashes[url]

                # Add to front of queue for immediate processing
                if domain_key not in self.crawl_queues:
                    self.crawl_queues[domain_key] = set()
                self.crawl_queues[domain_key].add(url)

                # Process immediately with scrape strategy
                result = await self.process_page(url, depth=0, max_depth=1, strategy='scrape')

                return aiohttp.web.json_response({
                    'success': True,
                    'message': f'Crawled {url}',
                    'processed': result is not None,
                    'content_length': len(result.get('content', {}).get('text', '')) if result else 0
                })

            elif domain:
                # Full domain re-crawl
                self.logger.info(f"🔄 Manual trigger: re-crawling entire domain {domain}")

                # Find the website config for this domain
                for website in self.config.websites:
                    if domain in website['url']:
                        # Clear existing queue and start fresh
                        domain_key = urlparse(website['url']).netloc
                        self.crawl_queues[domain_key] = {website['url']}
                        self.pages_crawled[domain_key] = 0

                        # Trigger immediate crawl
                        await self.crawl_website(website)

                        return aiohttp.web.json_response({
                            'success': True,
                            'message': f'Re-crawled domain {domain}',
                            'pages_crawled': self.pages_crawled.get(domain_key, 0),
                            'queue_size': len(self.crawl_queues.get(domain_key, set()))
                        })

                return aiohttp.web.json_response({
                    'success': False,
                    'error': f'Domain {domain} not found in configuration'
                }, status=404)
            else:
                return aiohttp.web.json_response({
                    'success': False,
                    'error': 'Must provide either "url" or "domain" parameter'
                }, status=400)

        except Exception as e:
            self.logger.error(f"Error in trigger_crawl: {e}")
            return aiohttp.web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def start_http_api(self):
        """Start HTTP API server for manual triggers"""
        try:
            from aiohttp import web

            app = web.Application()
            app.router.add_post('/trigger', self.trigger_crawl)

            runner = web.AppRunner(app)
            await runner.setup()

            # Use port 8010 for website sensor API
            site = web.TCPSite(runner, 'localhost', 8010)
            await site.start()

            self.logger.info("🌐 HTTP API started on http://localhost:8010")
            self.logger.info("   POST /trigger with {'url': '...'} or {'domain': '...'}")
        except Exception as e:
            self.logger.error(f"Failed to start HTTP API: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

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

        # Start HTTP API for manual triggers
        asyncio.create_task(self.start_http_api())

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

        # Initialize Playwright browser if needed
        if PLAYWRIGHT_AVAILABLE and (self.config.use_playwright or self.config.playwright_domains):
            await self._initialize_playwright()

        # Initialize crawl queues for each website
        for website in self.config.websites:
            # Skip disabled websites
            if website.get('enabled', True) is False:
                self.logger.info(f"⏭️ Skipping disabled website: {website.get('name', website['url'])}")
                continue

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
            # Skip disabled websites
            if website.get('enabled', True) is False:
                continue
            task = asyncio.create_task(self.monitor_website(website))
            tasks.append(task)
        
        # Wait for all monitoring tasks
        await asyncio.gather(*tasks)
    
    # REMOVED: process_video_queue() and emit_video_transcript_event()
    # Videos are now transcribed inline during emit_page_event() and integrated into page content
    # This eliminates separate video transcript documents and ensures transcripts are part of the page from the start

    async def stop(self):
        """Stop website monitoring sensor"""
        self.logger.info("Stopping Website KOI Sensor")

        # Videos are now processed inline during page events (no queue to process)

        if self.session:
            await self.session.close()

        # Cleanup Playwright browser
        if self.browser_context:
            await self.browser_context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

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
                # Videos are now transcribed inline during page event emission
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
        
        # Process ALL URLs in queue (removed [:20] limit for deterministic full-site crawling)
        # Process in batches to respect max_pages limit while ensuring all URLs eventually get processed
        batch_size = min(max_pages - self.pages_crawled.get(domain, 0), len(urls_to_process))

        tasks = []
        for url in urls_to_process[:batch_size]:
            task = asyncio.create_task(process_url_safe(url, 0))
            tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Remove processed URLs from queue
        for url in urls_to_process[:batch_size]:
            self.crawl_queues[domain].discard(url)

        # Update crawl queue with new URLs for next cycle (removed 100 URL limit)
        # All discovered URLs are added to ensure complete site coverage
        if new_urls:
            self.crawl_queues[domain].update(new_urls)
            self.logger.info(f"Added {len(new_urls)} new URLs to queue for {domain}, queue now has {len(self.crawl_queues[domain])} URLs")

        self.logger.info(f"Crawled {domain}: {processed_count} pages processed, {len(new_urls)} new URLs discovered")

        # Save state after each crawl cycle for persistence across restarts
        self._save_state()
    
    def _check_for_transcript_on_page(self, content: str, soup: BeautifulSoup) -> bool:
        """
        Check if a transcript already exists on the page.
        Returns True if transcript is found, False otherwise.
        """
        content_lower = content.lower()

        # Check for common transcript indicators
        transcript_indicators = [
            'transcript',  # Direct mention
            'transcription',
            '00:00',  # Timestamp format common in transcripts
            '[00:',   # Alternative timestamp format
            'speaker:',  # Speaker labels
            'speaker 1:',
            'speaker 2:',
        ]

        # Count how many indicators are present
        indicator_count = sum(1 for indicator in transcript_indicators if indicator in content_lower)

        # If we find multiple indicators, it's likely a transcript
        if indicator_count >= 2:
            return True

        # Check for substantial transcript-like content (long paragraphs with timestamps)
        # Look for patterns like "00:00" or "[00:00]" followed by text
        import re
        timestamp_pattern = r'(\d{1,2}:\d{2}|\[\d{1,2}:\d{2}\])'
        timestamps = re.findall(timestamp_pattern, content)

        # If there are multiple timestamps (>5), it's likely a transcript
        if len(timestamps) > 5:
            return True

        # Check for very long content blocks (>5000 words suggests transcript)
        word_count = len(content.split())
        if word_count > 5000 and 'transcript' in content_lower:
            return True

        return False

    async def process_page(self, url: str, depth: int, max_depth: int, strategy: str) -> Optional[Dict[str, Any]]:
        """Process a single web page"""

        # Check if we've reached the page limit
        domain = urlparse(url).netloc
        if domain in self.pages_crawled and self.pages_crawled[domain] >= 1000:  # Hard limit at 1000 for now
            self.logger.debug(f"Reached page limit for {domain}, skipping {url}")
            return None
        
        if not self.session:
            return None

        # Decide whether to use Playwright or regular HTTP
        use_playwright = self._should_use_playwright(url)

        try:
            if use_playwright:
                # Fetch with Playwright for JavaScript-rendered content
                self.logger.info(f"📜 Using Playwright for {url}")
                html_content = await self._fetch_with_playwright(url)
                if not html_content:
                    self.logger.warning(f"Playwright fetch failed, falling back to HTTP")
                    use_playwright = False

            if not use_playwright:
                # Fetch page with regular HTTP
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
        self.logger.info(f"[DEBUG] Parsing HTML with BeautifulSoup...")
        soup = BeautifulSoup(html_content, 'html.parser')
        self.logger.info(f"[DEBUG] Parsed {len(html_content)} chars of HTML")

        # DEBUG: Check if transcript content is in raw HTML
        if 'regentokenomics.org' in url and 'nov-11' in url:
            if '8min' in html_content:
                self.logger.info(f"[DEBUG] ✓ Transcript '8min' found in raw HTML for {url}")
                # Save HTML to file for inspection
                with open('/tmp/regentokenomics_nov11.html', 'w') as f:
                    f.write(html_content)
                self.logger.info(f"[DEBUG] Saved HTML to /tmp/regentokenomics_nov11.html")
            else:
                self.logger.warning(f"[DEBUG] ✗ Transcript '8min' NOT in raw HTML for {url}")
        elif 'regentokenomics.org' in url and '8min' not in html_content:
            self.logger.warning(f"[DEBUG] ✗ Transcript '8min' NOT in raw HTML for {url}")

        # Extract clean text content
        self.logger.info(f"[DEBUG] Extracting clean content...")
        text_content = self.extract_clean_content(soup, url)
        self.logger.info(f"[DEBUG] Extracted {len(text_content)} chars of text")

        if len(text_content) < self.config.min_content_length:
            self.logger.info(f"[DEBUG] Content too short ({len(text_content)} < {self.config.min_content_length}), skipping")
            return None

        # Calculate content hash
        self.logger.info(f"[DEBUG] Calculating content hash...")
        content_hash = hashlib.sha256(text_content.encode('utf-8')).hexdigest()
        self.logger.info(f"[DEBUG] Content hash: {content_hash[:16]}...")
        
        # Check if content changed
        self.logger.info(f"[DEBUG] Checking if content changed...")
        previous_hash = self.page_hashes.get(url)
        content_changed = previous_hash != content_hash
        self.logger.info(f"[DEBUG] Previous hash: {previous_hash[:16] if previous_hash else 'None'}")
        self.logger.info(f"[DEBUG] Content changed: {content_changed}, Is new: {previous_hash is None}")

        if content_changed or previous_hash is None:
            # Content is new or changed
            event_type = "NEW" if previous_hash is None else "UPDATE"
            self.logger.info(f"[DEBUG] Calling emit_page_event with event_type={event_type}")
            await self.emit_page_event(url, text_content, soup, event_type)
            self.logger.info(f"[DEBUG] emit_page_event returned")

            # Update hash and increment page count
            self.page_hashes[url] = content_hash
            if domain in self.pages_crawled:
                self.pages_crawled[domain] += 1
        else:
            self.logger.info(f"[DEBUG] Content unchanged, skipping emit")

        # Always discover internal URLs (no depth limit)
        self.logger.info(f"[DEBUG] Extracting internal URLs...")
        discovered_urls = self.extract_internal_urls(soup, url)
        self.logger.info(f"[DEBUG] Found {len(discovered_urls)} internal URLs")

        # Video URLs are extracted and transcribed inline during emit_page_event
        # No longer using separate video queue - transcripts are integrated into page content

        return {
            "url": url,
            "content_length": len(text_content),
            "content_changed": content_changed,
            "discovered_urls": discovered_urls
        }

    async def _initialize_playwright(self):
        """Initialize Playwright browser for JavaScript-heavy sites"""
        try:
            self.logger.info("Initializing Playwright browser...")
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )

            # Use a realistic browser user agent for Playwright so that
            # dynamic frontends (like Super.so/Notion pages on regentokenomics.org)
            # fully hydrate their content. The generic KOI sensor UA is
            # still used for plain HTTP requests, but here we want to look
            # like a normal browser.
            playwright_ua = None
            if getattr(self.config, "user_agent", None):
                ua = self.config.user_agent
                # Avoid using explicit "KOI-Sensor" style identifiers for
                # Playwright, as some sites treat these as bots and skip
                # client-side rendering of rich content (e.g., transcripts).
                if "koi-sensor" not in ua.lower():
                    playwright_ua = ua

            context_args = {
                "viewport": {"width": 1920, "height": 1080},
            }
            if playwright_ua:
                context_args["user_agent"] = playwright_ua

            self.browser_context = await self.browser.new_context(**context_args)
            self.logger.info(
                "✅ Playwright browser initialized "
                f"(user agent={'default' if not playwright_ua else playwright_ua})"
            )
        except Exception as e:
            self.logger.error(f"Failed to initialize Playwright: {e}")
            self.logger.warning("Falling back to HTTP-only mode")

    async def _fetch_with_playwright(self, url: str) -> Optional[str]:
        """Fetch page content using Playwright for JavaScript rendering"""
        if not self.browser_context:
            self.logger.warning(f"Playwright not available, cannot fetch {url}")
            return None

        try:
            page = await self.browser_context.new_page()

            # Navigate to page
            await page.goto(url, wait_until='networkidle', timeout=30000)

            # Wait for content to load
            await asyncio.sleep(self.config.playwright_wait_time / 1000)

            # Auto-expand Notion-style toggle blocks if enabled
            if self.config.playwright_expand_toggles:
                self.logger.info(f"[EXPAND] Starting toggle expansion for {url}")

                # For Notion sites, scroll the page to trigger lazy loading, then expand toggles
                domain = urlparse(url).netloc
                if domain == 'regentokenomics.org':
                    try:
                        # Scroll to bottom to trigger lazy loading of all content
                        await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                        await asyncio.sleep(1)
                        # Scroll back to top
                        await page.evaluate("() => window.scrollTo(0, 0)")
                        await asyncio.sleep(1)

                        # Use JavaScript to expand all Notion toggles
                        await page.evaluate("""
                            () => {
                                // Make all notion-toggle__content visible
                                const hiddenContent = document.querySelectorAll('.notion-toggle__content');
                                hiddenContent.forEach(el => {
                                    el.style.display = 'block';
                                    el.style.visibility = 'visible';
                                });

                                // Remove 'closed' class from all toggles
                                const toggles = document.querySelectorAll('.notion-toggle.closed');
                                toggles.forEach(el => el.classList.remove('closed'));
                            }
                        """)
                        self.logger.info("[EXPAND] Scrolled page and used JavaScript to force-show all toggle content")
                        await asyncio.sleep(2)
                    except Exception as e:
                        self.logger.warning(f"[EXPAND] JavaScript expansion failed: {e}")

                await self._expand_notion_toggles(page)
                self.logger.info(f"[EXPAND] Toggle expansion completed for {url}")
                # Wait longer for dynamically loaded content to render
                # Notion sites need extra time for toggle content to fully load
                await asyncio.sleep(3)

            # Get the HTML after toggle expansion
            html_content = await page.content()
            self.logger.info(f"[EXPAND] Retrieved {len(html_content)} chars of HTML for {url}")

            # For Notion sites, extract ALL text from the HTML including hidden toggle content
            # Don't rely on innerText as it may miss content in collapsed/lazy-loaded sections
            domain = urlparse(url).netloc
            extracted_html = None
            if domain in self.config.playwright_domains and self.config.playwright_expand_toggles:
                try:
                    # For regentokenomics.org pages, wait for Otter.ai transcript to load
                    # The transcript appears AFTER toggle expansion but loads asynchronously
                    if 'regentokenomics.org' in url and 'weekly-meetups' in url:
                        self.logger.info("[EXPAND] Waiting for Otter.ai transcript to load...")
                        try:
                            # Wait for specific text that appears in transcripts (max 30 seconds)
                            await page.wait_for_function(
                                "() => document.body.textContent.includes('8min') || document.body.textContent.includes('Okay, cool')",
                                timeout=30000
                            )
                            self.logger.info("[EXPAND] Transcript detected in page!")
                            # Give widget extra time to fully render all content
                            await asyncio.sleep(2)
                        except Exception as e:
                            self.logger.warning(f"[EXPAND] Transcript did not load within 30s: {e}")
                    else:
                        # For other pages, wait standard time
                        await asyncio.sleep(5)

                    # Use JavaScript to extract ALL visible text content
                    all_text = await page.evaluate("""
                        () => {
                            const main = document.querySelector('main.super-content');
                            if (!main) return '';
                            return main.textContent;
                        }
                    """)

                    self.logger.info(f"[EXPAND] Extracted {len(all_text)} chars using recursive text extraction")

                    # Check if we got the transcript
                    if 'regentokenomics.org' in url:
                        has_transcript = '8min' in all_text
                        self.logger.info(f"[EXPAND] Transcript found in extracted text: {has_transcript}")
                        if has_transcript:
                            preview_idx = all_text.find('8min')
                            preview = all_text[max(0, preview_idx-50):preview_idx+200]
                            self.logger.info(f"[EXPAND] Transcript preview: ...{preview}...")

                    # Convert to HTML paragraphs
                    if len(all_text) > 200:
                        import html as html_module
                        paragraphs = []
                        # Split by multiple newlines or long spaces to get logical paragraphs
                        lines = all_text.split('\n')
                        current_para = []

                        for line in lines:
                            line = line.strip()
                            if line:
                                current_para.append(line)
                            elif current_para:
                                # End of paragraph
                                para_text = ' '.join(current_para)
                                if len(para_text) > 5:
                                    escaped = html_module.escape(para_text)
                                    paragraphs.append(f"<p>{escaped}</p>")
                                current_para = []

                        # Don't forget the last paragraph
                        if current_para:
                            para_text = ' '.join(current_para)
                            if len(para_text) > 5:
                                escaped = html_module.escape(para_text)
                                paragraphs.append(f"<p>{escaped}</p>")

                        html_paragraphs = '\n'.join(paragraphs)
                        extracted_html = f"""<html><body><main class="super-content">{html_paragraphs}</main></body></html>"""
                        self.logger.info(f"[EXPAND] Using extracted text content ({len(all_text)} chars, {len(paragraphs)} paragraphs) instead of HTML source")
                except Exception as e:
                    self.logger.warning(f"[EXPAND] Could not extract text recursively: {e}")

            # Use extracted HTML if we got it, otherwise use original HTML
            if extracted_html:
                html_content = extracted_html

            await page.close()
            return html_content

        except Exception as e:
            self.logger.error(f"Playwright fetch failed for {url}: {e}")
            return None

    async def _expand_notion_toggles(self, page: Page):
        """Expand all Notion-style toggle/collapsible blocks to reveal hidden content"""
        try:
            # Common selectors for toggle/collapsible blocks
            toggle_selectors = [
                'details:not([open])',  # HTML5 details/summary
                '[class*="toggle"]',     # Notion-style toggles
                '[class*="collaps"]',    # Generic collapsed elements
                '[aria-expanded="false"]',  # ARIA collapsed
                'button[class*="toggle"]',  # Toggle buttons
            ]

            for selector in toggle_selectors:
                try:
                    # Find all matching elements
                    elements = await page.query_selector_all(selector)
                    self.logger.info(f"Found {len(elements)} elements matching '{selector}'")

                    # Click/expand each one
                    for element in elements:
                        try:
                            await element.click(timeout=1000)
                            await asyncio.sleep(0.5)  # Wait longer for content to load
                        except Exception:
                            pass  # Element might not be clickable, that's okay

                except Exception as e:
                    # Some selectors might not match, that's fine
                    pass

            # Additional: Look for elements with "‣" symbol (common toggle indicator)
            # This handles regentokenomics.org and similar sites that use custom toggles
            try:
                # Use Playwright's built-in text selector to find and click toggles
                # This is more reliable than JavaScript clicks for Notion-based sites
                toggles_found = await page.locator('text=‣').count()
                self.logger.info(f"Found {toggles_found} ‣ toggle indicators")

                # Click each parent container (the actual clickable element)
                for i in range(toggles_found):
                    try:
                        # Get the toggle indicator
                        indicator = page.locator('text=‣').nth(i)
                        # Click the parent (which is the clickable container)
                        parent = indicator.locator('..')
                        await parent.click(timeout=1000, force=True)
                        self.logger.debug(f"Clicked toggle {i+1}/{toggles_found}")
                        await asyncio.sleep(0.3)
                    except Exception as e:
                        self.logger.debug(f"Could not click toggle {i+1}: {e}")

                self.logger.info(f"Clicked {toggles_found} ‣ toggle elements using Playwright locators")

                # Wait longer for content to expand and render
                # Notion-based sites need time for lazy-loaded content to fully render
                # Especially for embedded widgets like Otter.ai transcripts which can take 10+ seconds
                await asyncio.sleep(10)
            except Exception as e:
                self.logger.debug(f"Error expanding ‣ toggles: {e}")

            # Additional wait for any lazy-loaded content
            await asyncio.sleep(2)

            self.logger.info("✅ Expanded all toggle blocks")

        except Exception as e:
            self.logger.warning(f"Error expanding toggles: {e}")

    def _should_use_playwright(self, url: str) -> bool:
        """Determine if URL should be fetched with Playwright"""
        if not PLAYWRIGHT_AVAILABLE or not (self.browser_context):
            return False

        if self.config.use_playwright:
            return True

        # Check if domain is in playwright_domains list
        domain = urlparse(url).netloc
        return domain in self.config.playwright_domains

    def extract_clean_content(self, soup: BeautifulSoup, url: str) -> str:
        """Extract clean text content from HTML"""

        # Get page title first
        title = ""
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text().strip()

        # IMPROVED: For Notion-based sites (like regentokenomics.org), use main.super-content
        # This is the primary content container that holds the actual page content
        content_container = None

        # Try Notion/Super.so content containers first
        content_container = soup.find('main', class_=lambda x: x and 'super-content' in str(x))

        # Fallback to other common content containers
        if not content_container:
            content_container = soup.find('main')
        if not content_container:
            content_container = soup.find('article')
        if not content_container:
            content_container = soup.find(class_=lambda x: x and 'content' in str(x).lower())

        # If still no container found, use the whole soup
        if not content_container:
            content_container = soup
            self.logger.info(f"[CONTAINER] Using full soup as content container for {url}")
        else:
            container_name = content_container.name
            container_classes = content_container.get('class', [])
            # Get a preview of the text to verify we got the right container
            preview_text = content_container.get_text(separator=' ', strip=True)[:200]
            self.logger.info(f"[CONTAINER] Found <{container_name} class='{' '.join(container_classes)}'> with {len(content_container.get_text())} chars for {url}")
            self.logger.info(f"[CONTAINER] Preview: {preview_text}...")

        # Remove script and style elements from the content container
        removed_count = 0
        for script in content_container(["script", "style", "nav", "footer", "aside"]):
            script.decompose()
            removed_count += 1

        if 'regentokenomics.org' in url:
            text_after_removal = content_container.get_text(separator=' ', strip=True)
            self.logger.info(f"[CONTAINER] After removing {removed_count} elements, container has {len(text_after_removal)} chars")

        # Extract text properly without duplicates
        # Use a set to track seen text and preserve order
        seen_texts = set()
        paragraphs = []

        # Process only direct text-containing elements, not nested ones
        # Start with headers, paragraphs, and divs with meaningful content
        for element in content_container.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'article', 'section']):
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

        # Now get list items separately from the content container
        for element in content_container.find_all('li'):
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
            self.logger.info(f"[DEBUG] emit_page_event START for {url}")
            parsed_url = urlparse(url)
            domain = parsed_url.netloc
            self.logger.info(f"[DEBUG] Parsed URL: domain={domain}")

            # Create RID
            rid = WebPageRID(domain, url)
            self.logger.info(f"[DEBUG] Created RID: {rid.to_string()}")

            # Extract page metadata
            self.logger.info(f"[DEBUG] Extracting metadata...")
            metadata = self.extract_page_metadata(soup, url)
            self.logger.info(f"[DEBUG] Metadata extracted: {len(metadata)} fields")

            # Extract publication date with site-specific patterns
            self.logger.info(f"[DEBUG] Extracting publication date...")
            published_at, confidence = self.extract_publication_date(soup, url, domain)
            self.logger.info(f"[DEBUG] Publication date: {published_at}, confidence: {confidence}")

            # Fallback to last-modified if no publication date found
            if not published_at and metadata.get("last_modified"):
                try:
                    from dateutil import parser
                    published_at = parser.parse(metadata["last_modified"])
                    confidence = 0.6  # Lower confidence for modification date
                except Exception:
                    pass

            # INTEGRATE VIDEO TRANSCRIPTION: Check for existing transcript, only transcribe if missing
            # Extract and transcribe videos from this page
            self.logger.info(f"[DEBUG] Extracting video URLs...")
            video_urls = self.extract_video_urls(soup, url)
            self.logger.info(f"[DEBUG] Found {len(video_urls)} video URLs")
            video_transcripts = []

            if video_urls:
                self.logger.info(f"Found {len(video_urls)} videos on {url}")

                # Check if transcript already exists on the page
                self.logger.info(f"[DEBUG] Checking for existing transcript on page...")
                has_transcript_on_page = self._check_for_transcript_on_page(content, soup)
                self.logger.info(f"[DEBUG] Has transcript on page: {has_transcript_on_page}")

                if has_transcript_on_page:
                    self.logger.info(f"✅ Transcript already exists on page, skipping video transcription")
                elif self.video_transcriber:
                    self.logger.info(f"⚠️ No transcript found on page, transcribing {len(video_urls)} video(s)...")

                    for video_info in video_urls:
                        try:
                            result = await self.video_transcriber.process_video(video_info)
                            if result and result.get('transcript'):
                                video_transcripts.append({
                                    'url': video_info['url'],
                                    'type': video_info['type'],
                                    'title': video_info.get('title', 'Video'),
                                    'transcript': result['transcript']
                                })
                                self.logger.info(f"✅ Transcribed video: {video_info['url'][:60]}...")
                        except Exception as e:
                            self.logger.error(f"Error transcribing video {video_info['url']}: {e}")
                else:
                    self.logger.warning(f"⚠️ No transcript on page and video transcriber not available")

            # Append video transcripts to page content
            enhanced_content = content
            if video_transcripts:
                self.logger.info(f"Appending {len(video_transcripts)} video transcripts to page content")
                enhanced_content += "\n\n--- VIDEO TRANSCRIPTS ---\n"

                for i, vt in enumerate(video_transcripts, 1):
                    enhanced_content += f"\n## Video {i}: {vt['title']}\n"
                    enhanced_content += f"URL: {vt['url']}\n"
                    enhanced_content += f"Type: {vt['type']}\n\n"
                    enhanced_content += vt['transcript'] + "\n"

                # Store video info in metadata
                metadata['videos'] = [
                    {
                        'url': vt['url'],
                        'type': vt['type'],
                        'title': vt['title'],
                        'transcribed': True
                    }
                    for vt in video_transcripts
                ]

            # Create document in format compatible with existing system
            self.logger.info(f"[DEBUG] Creating document structure...")
            document = {
                "id": f"web_{rid.url_hash}",
                "source": f"web:{domain}",
                "source_type": "website",
                "url": url,  # CRITICAL: URL at root level for provenance
                "source_url": url,  # Additional field to ensure preservation
                "title": metadata.get("title", ""),
                "content": enhanced_content,  # Use enhanced content with video transcripts
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
            self.logger.info(f"[DEBUG] Converting document to bundle...")
            bundle = document_to_bundle(document, self.koi_node.node_id)
            self.logger.info(f"[DEBUG] Bundle created successfully")

            # Emit appropriate KOI event
            self.logger.info(f"[DEBUG] Emitting {event_type} event to coordinator...")
            if event_type == "NEW":
                await self.koi_node.emit_new_event(bundle)
            else:
                await self.koi_node.emit_update_event(bundle)

            self.logger.info(f"Emitted {event_type} event for {url} (RID: {rid.to_string()})")
            self.logger.info(f"[DEBUG] emit_page_event COMPLETED successfully")
        
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
