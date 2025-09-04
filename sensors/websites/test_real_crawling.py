#!/usr/bin/env python3
"""
Test Real Website Crawling in Standalone Mode
Actually crawls real websites and extracts content
"""

import asyncio
import aiohttp
import logging
from pathlib import Path
import sys
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import hashlib

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.core.rid_system import WebPageRID

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SimpleCrawler:
    """Simple web crawler for testing"""
    
    def __init__(self):
        self.session = None
        self.page_hashes = {}
        
    async def start(self):
        """Start HTTP session"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'User-Agent': 'KOI-Sensor-Test/1.0'}
        )
        
    async def stop(self):
        """Stop HTTP session"""
        if self.session:
            await self.session.close()
            
    async def crawl_page(self, url: str):
        """Crawl a single page and extract content"""
        logger.info(f"Crawling: {url}")
        
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"HTTP {response.status} for {url}")
                    return None
                    
                html = await response.text()
                logger.info(f"Downloaded {len(html)} characters")
                
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
            
        # Parse HTML
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'footer', 'aside']):
            element.decompose()
            
        # Extract title
        title = ""
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text().strip()
            
        # Extract main content
        content = soup.get_text()
        # Clean up whitespace
        content = ' '.join(content.split())
        
        # Generate content hash
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        
        # Generate RID
        parsed = urlparse(url)
        rid = WebPageRID(parsed.netloc, url)
        
        # Check for changes
        changed = False
        if url in self.page_hashes:
            changed = self.page_hashes[url] != content_hash
        else:
            changed = True  # First time seeing this page
            
        self.page_hashes[url] = content_hash
        
        return {
            'url': url,
            'rid': rid.to_orn(),
            'title': title,
            'content_length': len(content),
            'content_preview': content[:200] + '...' if len(content) > 200 else content,
            'content_hash': content_hash[:16],
            'changed': changed,
            'event_type': 'NEW' if url not in self.page_hashes or changed else 'NO_CHANGE'
        }

async def test_real_crawling():
    """Test crawling real Regen Network websites"""
    
    # Test URLs - starting with small, fast ones
    test_urls = [
        "https://www.regen.foundation",
        "https://docs.regen.network", 
        # "https://guides.regen.network",  # Comment out for faster testing
        # "https://registry.regen.network"  # Comment out for faster testing
    ]
    
    print("🕷️  KOI Website Sensor - Real Crawling Test")
    print("=" * 60)
    print("Testing actual web crawling and content extraction")
    print("=" * 60)
    
    crawler = SimpleCrawler()
    await crawler.start()
    
    try:
        for url in test_urls:
            print(f"\n📄 Testing: {url}")
            print("-" * 40)
            
            result = await crawler.crawl_page(url)
            
            if result:
                print(f"✅ Success!")
                print(f"   RID: {result['rid']}")
                print(f"   Title: {result['title']}")
                print(f"   Content: {result['content_length']} characters")
                print(f"   Hash: {result['content_hash']}")
                print(f"   Event: {result['event_type']}")
                print(f"   Preview: {result['content_preview']}")
            else:
                print(f"❌ Failed to crawl {url}")
                
        # Test change detection by crawling same URL again
        if test_urls:
            print(f"\n🔄 Testing Change Detection")
            print("-" * 40)
            print("Re-crawling first URL to test change detection...")
            
            result = await crawler.crawl_page(test_urls[0])
            if result:
                print(f"   Event: {result['event_type']} (should be NO_CHANGE)")
                
    finally:
        await crawler.stop()
        
    print("\n" + "=" * 60)
    print("✅ Real Crawling Test Complete!")
    print("\nKey observations:")
    print("1. RIDs are generated for each unique URL")
    print("2. Full content is extracted from HTML")
    print("3. Content hashes detect changes between visits") 
    print("4. This is REAL web scraping - not just references!")

if __name__ == "__main__":
    asyncio.run(test_real_crawling())