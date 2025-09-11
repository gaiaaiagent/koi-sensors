#!/usr/bin/env python3
"""
Quick test for Research Retreat papers site
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import hashlib


async def test_research_retreat():
    """Test crawling Research Retreat papers"""
    
    print("🔬 Testing Research Retreat Papers Site")
    print("="*60)
    
    base_url = "https://www.researchretreat.org/papers"
    
    async with aiohttp.ClientSession() as session:
        try:
            print(f"📄 Fetching: {base_url}")
            async with session.get(base_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Get title
                    title = soup.find('title')
                    title_text = title.get_text().strip() if title else "No title"
                    print(f"✅ Page loaded: {title_text}")
                    
                    # Extract text content
                    for element in soup(['script', 'style', 'nav', 'footer']):
                        element.decompose()
                    
                    text_content = soup.get_text()
                    text_content = ' '.join(text_content.split())
                    
                    print(f"📏 Content length: {len(text_content):,} characters")
                    
                    # Find links (especially PDF links for papers)
                    pdf_links = []
                    other_links = []
                    
                    for link in soup.find_all('a', href=True):
                        href = link['href']
                        full_url = urljoin(base_url, href)
                        
                        if href.lower().endswith('.pdf'):
                            pdf_links.append((link.get_text().strip(), full_url))
                        elif 'researchretreat.org' in full_url:
                            other_links.append(full_url)
                    
                    print(f"\n📚 PDF Papers found: {len(pdf_links)}")
                    for i, (text, url) in enumerate(pdf_links[:5], 1):
                        print(f"   {i}. {text[:60]}...")
                        print(f"      URL: {url}")
                    
                    if len(pdf_links) > 5:
                        print(f"   ... and {len(pdf_links) - 5} more papers")
                    
                    print(f"\n🔗 Other internal links: {len(other_links)}")
                    
                    # Generate RID
                    domain = urlparse(base_url).netloc.replace('.', '_')
                    url_hash = hashlib.sha256(base_url.encode()).hexdigest()[:16]
                    rid = f"orn:web.page.{domain}.{url_hash}"
                    print(f"\n🆔 Generated RID: {rid}")
                    
                    # Extract some sample content
                    print(f"\n📝 Sample content (first 500 chars):")
                    print(text_content[:500] + "...")
                    
                    print(f"\n✅ Site Analysis Complete:")
                    print(f"   - Papers are accessible as PDFs")
                    print(f"   - Would need PDF extraction for full content")
                    print(f"   - Consider adding PDF support to sensor")
                    print(f"   - High-value academic content available")
                    
                else:
                    print(f"❌ HTTP {response.status}")
                    
        except Exception as e:
            print(f"❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_research_retreat())