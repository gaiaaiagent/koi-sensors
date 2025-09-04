#!/usr/bin/env python3
"""
Test All Target Websites from Server README + New Additions
Comprehensive test of all websites we want to collect data from
"""

import asyncio
import aiohttp
import yaml
import logging
import sys
from pathlib import Path
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

async def test_website(session, website_config):
    """Test crawling a single website"""
    name = website_config['name']
    url = website_config['url'] 
    priority = website_config.get('priority', 'medium')
    current_status = website_config.get('current_status', 'unknown')
    
    print(f"\n📄 Testing: {name}")
    print(f"   URL: {url}")
    print(f"   Priority: {priority} | Status: {current_status}")
    
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
            if response.status == 200:
                html = await response.text()
                
                # Parse content
                soup = BeautifulSoup(html, 'html.parser')
                
                # Remove unwanted elements
                for element in soup(['script', 'style', 'nav', 'footer', 'aside']):
                    element.decompose()
                
                # Extract title
                title = soup.find('title')
                title = title.get_text().strip() if title else "No title"
                
                # Extract content
                content = ' '.join(soup.get_text().split())
                
                # Generate RID
                parsed = urlparse(url)
                rid = WebPageRID(parsed.netloc, url)
                
                # Find internal links for potential expansion
                internal_links = 0
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    if parsed.netloc in href or href.startswith('/'):
                        internal_links += 1
                
                result = {
                    'name': name,
                    'url': url,
                    'status': 'SUCCESS',
                    'rid': rid.to_orn(),
                    'title': title[:60] + '...' if len(title) > 60 else title,
                    'content_length': len(content),
                    'internal_links': min(internal_links, 100),  # Cap at 100 for display
                    'priority': priority,
                    'current_status': current_status,
                    'response_time': response.headers.get('server', 'Unknown server')
                }
                
                print(f"   ✅ SUCCESS")
                print(f"   📄 Title: {result['title']}")
                print(f"   📏 Content: {len(content):,} characters")
                print(f"   🔗 Links found: {internal_links}")
                print(f"   🆔 RID: {rid.to_orn()}")
                
                return result
                
            else:
                print(f"   ❌ HTTP {response.status}")
                return {
                    'name': name,
                    'url': url, 
                    'status': f'HTTP_{response.status}',
                    'error': f'HTTP {response.status}'
                }
                
    except asyncio.TimeoutError:
        print(f"   ⏱️  TIMEOUT (>15s)")
        return {
            'name': name,
            'url': url,
            'status': 'TIMEOUT',
            'error': 'Request timeout'
        }
    except Exception as e:
        print(f"   ❌ ERROR: {str(e)[:60]}...")
        return {
            'name': name,
            'url': url,
            'status': 'ERROR',
            'error': str(e)[:100]
        }

async def test_all_websites():
    """Test all websites from configuration"""
    
    print("🌐 KOI Website Sensor - Complete Website Test")
    print("=" * 70)
    print("Testing ALL target websites from server README + new additions")
    print("=" * 70)
    
    # Load config
    try:
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
        print(f"✅ Configuration loaded: {len(config['websites'])} websites")
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        return
    
    # Show summary
    print(f"\n📋 Websites to test:")
    high_priority = [w for w in config['websites'] if w.get('priority') == 'high']
    medium_priority = [w for w in config['websites'] if w.get('priority') == 'medium'] 
    low_priority = [w for w in config['websites'] if w.get('priority') == 'low']
    
    print(f"   🔴 High Priority: {len(high_priority)} websites")
    print(f"   🟡 Medium Priority: {len(medium_priority)} websites") 
    print(f"   🟢 Low Priority: {len(low_priority)} websites")
    
    # Create session
    session = aiohttp.ClientSession(
        headers={
            'User-Agent': config['processing']['user_agent']
        },
        timeout=aiohttp.ClientTimeout(total=30)
    )
    
    results = []
    
    try:
        # Test all websites
        print(f"\n🚀 Starting comprehensive test...")
        
        for website in config['websites']:
            result = await test_website(session, website)
            results.append(result)
            
            # Small delay between requests to be respectful
            await asyncio.sleep(1)
            
    finally:
        await session.close()
    
    # Analysis
    successful = [r for r in results if r['status'] == 'SUCCESS']
    failed = [r for r in results if r['status'] != 'SUCCESS']
    
    print(f"\n" + "=" * 70)
    print(f"📊 COMPREHENSIVE TEST RESULTS")
    print(f"=" * 70)
    print(f"Total websites tested: {len(results)}")
    print(f"✅ Successful: {len(successful)} ({len(successful)/len(results)*100:.1f}%)")
    print(f"❌ Failed: {len(failed)} ({len(failed)/len(results)*100:.1f}%)")
    
    if successful:
        total_content = sum(r['content_length'] for r in successful)
        total_links = sum(r.get('internal_links', 0) for r in successful)
        
        print(f"\n📄 Content Analysis:")
        print(f"   Total content: {total_content:,} characters")
        print(f"   Average per site: {total_content//len(successful):,} characters")
        print(f"   Total links discovered: {total_links:,}")
        print(f"   Expansion potential: ~{total_links * 2:,} additional pages")
        
        print(f"\n🎯 High Priority Sites:")
        high_priority_success = [r for r in successful if r['priority'] == 'high']
        for result in high_priority_success:
            print(f"   ✅ {result['name']}: {result['content_length']:,} chars, {result.get('internal_links', 0)} links")
    
    if failed:
        print(f"\n❌ Failed Sites:")
        for result in failed:
            print(f"   {result['status']}: {result['name']} - {result.get('error', 'Unknown error')}")
    
    # Comparison with server status
    print(f"\n📈 Expansion Opportunities:")
    server_total = 64  # Current website docs from server README
    potential_expansion = sum(r.get('internal_links', 0) for r in successful) * 0.3  # Conservative estimate
    
    print(f"   Current server docs: ~{server_total} website documents")
    print(f"   Sensor potential: ~{int(potential_expansion):,} additional documents")
    print(f"   Total possible: ~{server_total + int(potential_expansion):,} website documents")
    
    print(f"\n✅ Ready for:")
    print(f"   🕷️  Real-time website monitoring")  
    print(f"   📊 Massive expansion of website document collection")
    print(f"   🎯 Progress toward 15,000 document target")
    print(f"   🔄 Integration with KOI coordinator when ready")

if __name__ == "__main__":
    asyncio.run(test_all_websites())