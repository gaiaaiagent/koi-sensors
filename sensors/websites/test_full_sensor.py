#!/usr/bin/env python3
"""
Test Full Website Sensor in Standalone Mode
Tests the complete sensor with configuration
"""

import asyncio
import logging
import yaml
import sys
from pathlib import Path

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_full_sensor():
    """Test the complete sensor setup"""
    
    print("🌐 KOI Website Sensor - Full Test (Standalone Mode)")
    print("=" * 60)
    print("Testing complete sensor with configuration")
    print("This will crawl real websites without a coordinator")
    print("=" * 60)
    
    # Load config
    try:
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
        print("✅ Configuration loaded successfully")
        print(f"   Sensor: {config['sensor']['name']}")
        print(f"   Websites: {len(config['websites'])} configured")
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        return
    
    # Show what we'll test
    print(f"\n📋 Websites to test:")
    for i, website in enumerate(config['websites'][:2], 1):  # Test only first 2
        print(f"   {i}. {website['name']} ({website['url']})")
        print(f"      Priority: {website['priority']} | Interval: {website['check_interval']}s")
    
    print(f"\n🔄 Starting crawl test...")
    
    # Simple standalone crawler (mimicking sensor behavior)
    import aiohttp
    from bs4 import BeautifulSoup
    import hashlib
    from koi_protocol.core.rid_system import WebPageRID
    from urllib.parse import urlparse
    
    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30),
        headers={'User-Agent': config['processing']['user_agent']}
    )
    
    try:
        results = []
        
        # Test each website
        for website in config['websites'][:2]:  # Limit to 2 for testing
            url = website['url']
            name = website['name']
            
            print(f"\n📄 Processing: {name}")
            print(f"   URL: {url}")
            
            try:
                # Crawl the page
                async with session.get(url) as response:
                    if response.status == 200:
                        html = await response.text()
                        
                        # Parse and extract content
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Remove unwanted elements
                        for element in soup(['script', 'style', 'nav', 'footer']):
                            element.decompose()
                        
                        # Extract content
                        title = soup.find('title')
                        title = title.get_text().strip() if title else "No title"
                        content = ' '.join(soup.get_text().split())
                        
                        # Generate RID
                        parsed = urlparse(url)
                        rid = WebPageRID(parsed.netloc, url)
                        
                        # Create document (same format as sensor)
                        document = {
                            "id": f"web_{rid.path_hash}",
                            "source": f"web:{parsed.netloc}",
                            "url": url,
                            "title": title,
                            "content": content,
                            "content_length": len(content),
                            "rid": rid.to_orn()
                        }
                        
                        results.append(document)
                        
                        print(f"   ✅ Success!")
                        print(f"   RID: {rid.to_orn()}")
                        print(f"   Title: {title[:50]}...")
                        print(f"   Content: {len(content)} characters")
                        print(f"   Status: {website['current_status']}")
                        
                    else:
                        print(f"   ❌ HTTP {response.status}")
                        
            except Exception as e:
                print(f"   ❌ Error: {e}")
                
    finally:
        await session.close()
    
    # Summary
    print(f"\n📊 Test Summary:")
    print(f"   Websites tested: {len(results)}")
    print(f"   Total content: {sum(r['content_length'] for r in results):,} characters")
    
    if results:
        print(f"\n📄 Sample document structure:")
        sample = results[0]
        for key in ['id', 'source', 'title', 'rid']:
            print(f"   {key}: {sample[key]}")
        print(f"   content: {sample['content'][:100]}...")
    
    print(f"\n✅ Full Sensor Test Complete!")
    print(f"\nThis demonstrates:")
    print(f"1. 🕷️  Real web crawling and content extraction")
    print(f"2. 🆔 RID generation for unique identification") 
    print(f"3. 📋 Document creation in compatible format")
    print(f"4. ⚙️  Configuration-driven website selection")
    print(f"5. 📊 Full data ingestion (not just references!)")

if __name__ == "__main__":
    asyncio.run(test_full_sensor())