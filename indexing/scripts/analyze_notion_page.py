#!/usr/bin/env python3
"""
Analyze Notion page structure to find transcript data.
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup
import json
import re

async def analyze_notion():
    """Analyze the Notion page structure."""
    
    url = "https://regennetwork.notion.site/PRP-Trascripts-3b97bc2cf21246e09e599b615e483b8d"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            html = await response.text()
            
    soup = BeautifulSoup(html, 'html.parser')
    
    # Look for script tags with JSON data
    scripts = soup.find_all('script')
    
    print(f"Found {len(scripts)} script tags")
    
    for i, script in enumerate(scripts):
        content = script.string or ''
        if 'pageId' in content or 'block' in content or 'collection' in content:
            print(f"\n=== Script {i} (potentially has data) ===")
            # Try to extract JSON
            json_pattern = re.search(r'\{.*\}', content, re.DOTALL)
            if json_pattern:
                try:
                    data = json.loads(json_pattern.group())
                    if 'block' in str(data) or 'collection' in str(data):
                        # Look for episode data
                        data_str = json.dumps(data, indent=2)
                        # Find episode references
                        episodes = re.findall(r'"title":\s*"([^"]*\d+:[^"]*)"', data_str)
                        if episodes:
                            print("Found episodes in JSON:")
                            for ep in episodes[:20]:
                                print(f"  - {ep}")
                except:
                    pass
                    
    # Check page title and meta tags
    title = soup.title.string if soup.title else "No title"
    print(f"\nPage title: {title}")
    
    # Look for any text containing episode patterns
    body_text = soup.get_text()
    
    # More flexible pattern
    episode_patterns = [
        r'Episode\s+(\d+)[:\s]+([^\n]+)',
        r'(\d{1,3}):\s+([^\n]+)',
        r'#(\d+)[:\s]+([^\n]+)',
    ]
    
    all_episodes = set()
    for pattern in episode_patterns:
        matches = re.findall(pattern, body_text, re.IGNORECASE)
        for match in matches:
            if len(match[0]) <= 3:  # Episode number should be 1-3 digits
                all_episodes.add((match[0], match[1][:50]))
                
    if all_episodes:
        print(f"\nFound {len(all_episodes)} unique episodes in text:")
        for num, title in sorted(all_episodes, key=lambda x: int(x[0]) if x[0].isdigit() else 999):
            print(f"  Episode {num}: {title}")
            
    # Check for Notion API data
    print("\n=== Checking for Notion-specific elements ===")
    notion_elements = soup.find_all(class_=re.compile('notion'))
    print(f"Found {len(notion_elements)} elements with 'notion' class")
    
    # Look for data attributes
    elements_with_data = soup.find_all(attrs={'data-block-id': True})
    print(f"Found {len(elements_with_data)} elements with data-block-id")
    
    return body_text

if __name__ == "__main__":
    text = asyncio.run(analyze_notion())