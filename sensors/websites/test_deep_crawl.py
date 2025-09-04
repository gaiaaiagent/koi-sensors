#!/usr/bin/env python3
"""
Test Deep Crawling - Multiple Pages Discovery
Shows how sensor finds multiple pages on a site
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))
from koi_protocol.core.rid_system import WebPageRID

async def test_deep_crawl():
    """Test crawling multiple pages from a site"""
    
    print("🔍 KOI Website Sensor - Deep Crawling Test")
    print("=" * 60)
    print("Testing discovery and crawling of multiple pages")
    print("=" * 60)
    
    base_url = "https://guides.regen.network"
    max_pages = 5  # Limit for testing
    
    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30),
        headers={'User-Agent': 'KOI-Sensor-Test/1.0'}
    )
    
    discovered_urls = set([base_url])
    crawled_pages = []
    
    try:
        print(f"🌱 Starting from: {base_url}")
        
        # Crawl pages
        urls_to_crawl = list(discovered_urls)
        
        for i, url in enumerate(urls_to_crawl[:max_pages]):
            print(f"\n📄 Crawling page {i+1}: {url}")
            
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Extract content
                        title = soup.find('title')
                        title = title.get_text().strip() if title else "No title"
                        
                        # Clean content
                        for element in soup(['script', 'style', 'nav', 'footer']):
                            element.decompose()
                        content = ' '.join(soup.get_text().split())
                        
                        # Generate RID
                        parsed = urlparse(url)
                        rid = WebPageRID(parsed.netloc, url)
                        
                        page_info = {
                            'url': url,
                            'rid': rid.to_orn(),
                            'title': title,
                            'content_length': len(content),
                            'content_preview': content[:150] + '...' if len(content) > 150 else content
                        }
                        crawled_pages.append(page_info)
                        
                        print(f"   ✅ {title[:50]}")
                        print(f"   📏 {len(content):,} characters")
                        print(f"   🆔 {rid.to_orn()}")
                        
                        # Find more URLs on this page
                        new_urls = set()
                        for link in soup.find_all('a', href=True):
                            href = link['href']
                            
                            # Convert relative URLs to absolute
                            full_url = urljoin(url, href)
                            parsed_link = urlparse(full_url)
                            
                            # Only include URLs from same domain
                            if (parsed_link.netloc == parsed.netloc and 
                                full_url not in discovered_urls and
                                not full_url.endswith(('.pdf', '.jpg', '.png', '.gif')) and
                                '#' not in full_url):  # Skip anchors
                                new_urls.add(full_url)
                        
                        if new_urls:
                            print(f"   🔗 Found {len(new_urls)} new URLs")
                            discovered_urls.update(new_urls)
                            urls_to_crawl.extend(list(new_urls)[:3])  # Add some to crawl list
                        
                    else:
                        print(f"   ❌ HTTP {response.status}")
                        
            except Exception as e:
                print(f"   ❌ Error: {e}")
                
    finally:
        await session.close()
    
    # Summary
    print(f"\n📊 Deep Crawl Results:")
    print(f"   Pages crawled: {len(crawled_pages)}")
    print(f"   URLs discovered: {len(discovered_urls)}")
    print(f"   Total content: {sum(p['content_length'] for p in crawled_pages):,} characters")
    
    print(f"\n📄 All pages found:")
    for i, page in enumerate(crawled_pages, 1):
        print(f"   {i}. {page['title'][:40]}")
        print(f"      {page['url']}")
        print(f"      RID: {page['rid']}")
        print(f"      Content: {page['content_length']:,} chars")
        print()
    
    print(f"🎯 This demonstrates how sensors discover multiple documents:")
    print(f"   • Starting from 1 URL → Found {len(discovered_urls)} URLs") 
    print(f"   • Each page gets unique RID for identification")
    print(f"   • Full content extracted from each page")
    print(f"   • Ready to emit {len(crawled_pages)} NEW events")

if __name__ == "__main__":
    asyncio.run(test_deep_crawl())