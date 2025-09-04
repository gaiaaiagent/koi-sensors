#!/usr/bin/env python3
"""
Show Extracted Data from Website Tests
Display the actual content we scraped from each site
"""

import asyncio
import aiohttp
import yaml
import sys
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import json

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.core.rid_system import WebPageRID

async def extract_and_show_data():
    """Extract and display data from all configured websites"""
    
    print("📄 KOI Website Sensor - Extracted Data Viewer")
    print("=" * 60)
    print("Showing actual content extracted from each website")
    print("=" * 60)
    
    # Load config
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    
    session = aiohttp.ClientSession(
        headers={'User-Agent': config['processing']['user_agent']},
        timeout=aiohttp.ClientTimeout(total=30)
    )
    
    extracted_data = []
    
    try:
        for website in config['websites']:
            print(f"\n🌐 EXTRACTING: {website['name']}")
            print(f"URL: {website['url']}")
            print("-" * 50)
            
            try:
                async with session.get(website['url']) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Remove unwanted elements
                        for element in soup(['script', 'style', 'nav', 'footer', 'aside']):
                            element.decompose()
                        
                        # Extract metadata
                        title = soup.find('title')
                        title = title.get_text().strip() if title else "No title"
                        
                        description = soup.find('meta', attrs={'name': 'description'})
                        description = description.get('content', '') if description else ''
                        
                        # Extract main content
                        content = ' '.join(soup.get_text().split())
                        
                        # Generate RID
                        parsed = urlparse(website['url'])
                        rid = WebPageRID(parsed.netloc, website['url'])
                        
                        # Create document
                        document = {
                            'name': website['name'],
                            'url': website['url'],
                            'rid': rid.to_orn(),
                            'title': title,
                            'description': description,
                            'content': content,
                            'content_length': len(content),
                            'priority': website.get('priority', 'medium'),
                            'status': website.get('current_status', 'unknown')
                        }
                        
                        extracted_data.append(document)
                        
                        # Show preview
                        print(f"✅ SUCCESS")
                        print(f"RID: {document['rid']}")
                        print(f"Title: {title}")
                        print(f"Description: {description[:100]}..." if description else "No description")
                        print(f"Content Length: {len(content):,} characters")
                        print(f"Content Preview:")
                        print(f"  {content[:300]}...")
                        print()
                        
                    else:
                        print(f"❌ HTTP {response.status}")
                        
            except Exception as e:
                print(f"❌ Error: {e}")
                
    finally:
        await session.close()
    
    # Save extracted data
    output_file = 'extracted_website_data.json'
    with open(output_file, 'w') as f:
        json.dump(extracted_data, f, indent=2, ensure_ascii=False)
    
    # Summary
    total_content = sum(doc['content_length'] for doc in extracted_data)
    
    print("=" * 60)
    print("📊 EXTRACTION SUMMARY")
    print("=" * 60)
    print(f"Websites processed: {len(extracted_data)}")
    print(f"Total content extracted: {total_content:,} characters")
    print(f"Average per site: {total_content // len(extracted_data):,} characters")
    print(f"Data saved to: {output_file}")
    
    print(f"\n📄 Content by Priority:")
    high_priority = [d for d in extracted_data if d['priority'] == 'high']
    medium_priority = [d for d in extracted_data if d['priority'] == 'medium'] 
    low_priority = [d for d in extracted_data if d['priority'] == 'low']
    
    if high_priority:
        high_content = sum(d['content_length'] for d in high_priority)
        print(f"  🔴 High Priority: {len(high_priority)} sites, {high_content:,} characters")
        
    if medium_priority:
        medium_content = sum(d['content_length'] for d in medium_priority)
        print(f"  🟡 Medium Priority: {len(medium_priority)} sites, {medium_content:,} characters")
        
    if low_priority:
        low_content = sum(d['content_length'] for d in low_priority)
        print(f"  🟢 Low Priority: {len(low_priority)} sites, {low_content:,} characters")
    
    print(f"\n📋 Individual Site Breakdown:")
    for doc in sorted(extracted_data, key=lambda x: x['content_length'], reverse=True):
        print(f"  {doc['content_length']:>6,} chars - {doc['name']} ({doc['priority']})")
    
    return extracted_data

if __name__ == "__main__":
    asyncio.run(extract_and_show_data())