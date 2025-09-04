#!/usr/bin/env python3
"""
Scrape all podcast transcript links from Notion using Playwright.
"""

import asyncio
import json
import re
from pathlib import Path
from typing import List, Dict
from playwright.async_api import async_playwright
from loguru import logger
import aiohttp
from bs4 import BeautifulSoup


async def scrape_notion_links():
    """Use Playwright to scrape all transcript links from the Notion page."""
    
    url = "https://regennetwork.notion.site/PRP-Trascripts-3b97bc2cf21246e09e599b615e483b8d"
    transcript_links = []
    
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        logger.info(f"Loading Notion page: {url}")
        
        # Navigate to the page (with longer timeout and less strict wait)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        # Wait for content to load
        await page.wait_for_timeout(5000)  # Give it 5 seconds to load dynamic content
        
        # Get all links on the page
        links = await page.evaluate("""
            () => {
                const links = [];
                document.querySelectorAll('a').forEach(link => {
                    const text = link.innerText || '';
                    const href = link.href || '';
                    if (text && href) {
                        links.push({
                            text: text.trim(),
                            url: href
                        });
                    }
                });
                return links;
            }
        """)
        
        # Filter for episode links
        episode_pattern = re.compile(r'(\d+)[:\s]+(.+?)(?:\||$)')
        
        for link in links:
            text = link['text']
            url = link['url']
            
            # Check if this looks like an episode link
            match = episode_pattern.search(text)
            if match and 'notion.site' in url:
                episode_num = match.group(1)
                guest_name = match.group(2).strip()
                
                transcript_links.append({
                    'episode_num': int(episode_num),
                    'guest': guest_name,
                    'title': text,
                    'url': url
                })
                
        # Also get the page content to find any episodes without direct links
        content = await page.content()
        
        await browser.close()
        
    # Parse content with BeautifulSoup to find additional patterns
    soup = BeautifulSoup(content, 'html.parser')
    text_content = soup.get_text()
    
    # Find all episode mentions in text
    all_episodes = re.findall(r'(\d{1,3})[:\s]+([^\n]+)', text_content)
    
    # Add any missing episodes (without URLs for now)
    existing_nums = {link['episode_num'] for link in transcript_links}
    
    for num_str, title in all_episodes:
        num = int(num_str)
        if num not in existing_nums and num <= 100:  # Reasonable episode number
            title_clean = title.strip()
            if len(title_clean) > 3:  # Filter out noise
                transcript_links.append({
                    'episode_num': num,
                    'guest': title_clean.split('|')[0].strip(),
                    'title': f"{num}: {title_clean}",
                    'url': None  # Will need to construct URL
                })
    
    # Sort by episode number
    transcript_links.sort(key=lambda x: x['episode_num'])
    
    return transcript_links


async def fetch_transcript(url: str) -> Dict:
    """Fetch a single transcript from Notion."""
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        logger.info(f"Fetching transcript: {url}")
        
        await page.goto(url, wait_until="networkidle")
        await page.wait_for_timeout(2000)  # Let content load
        
        # Get the page content
        content = await page.content()
        title = await page.title()
        
        # Extract text content
        text_content = await page.evaluate("""
            () => {
                // Remove navigation and UI elements
                const elementsToRemove = document.querySelectorAll('nav, header, .notion-topbar');
                elementsToRemove.forEach(el => el.remove());
                
                // Get main content
                const mainContent = document.querySelector('main') || document.body;
                return mainContent.innerText || mainContent.textContent || '';
            }
        """)
        
        await browser.close()
        
        return {
            'url': url,
            'title': title,
            'content': text_content
        }


async def main():
    """Main scraping process."""
    
    logger.info("Starting Notion transcript scraping...")
    
    # Get all transcript links
    links = await scrape_notion_links()
    
    logger.info(f"Found {len(links)} episode references")
    
    # Save the links
    output_dir = Path("indexing/storage/notion_transcripts")
    output_dir.mkdir(exist_ok=True, parents=True)
    
    links_file = output_dir / "transcript_links.json"
    with open(links_file, 'w') as f:
        json.dump(links, f, indent=2)
        
    logger.info(f"Saved links to: {links_file}")
    
    # Display found episodes
    print("\n=== Episodes Found ===")
    for link in links:
        status = "✓" if link['url'] else "✗"
        print(f"{status} Episode {link['episode_num']:3}: {link['guest'][:50]}")
        if link['url']:
            print(f"   URL: {link['url'][:80]}")
            
    # Count statistics
    with_urls = sum(1 for l in links if l['url'])
    without_urls = len(links) - with_urls
    
    print(f"\n=== Summary ===")
    print(f"Total episodes found: {len(links)}")
    print(f"With URLs: {with_urls}")
    print(f"Without URLs: {without_urls}")
    
    # Optionally fetch a few transcripts as test
    if with_urls > 0:
        print("\n=== Testing Transcript Fetch ===")
        test_link = next(l for l in links if l['url'])
        
        transcript = await fetch_transcript(test_link['url'])
        
        if transcript and transcript['content']:
            print(f"Successfully fetched transcript for Episode {test_link['episode_num']}")
            print(f"Title: {transcript['title']}")
            print(f"Content length: {len(transcript['content'])} characters")
            print(f"Preview: {transcript['content'][:200]}...")
            
            # Save test transcript
            test_file = output_dir / f"episode_{test_link['episode_num']:03}_test.txt"
            with open(test_file, 'w') as f:
                f.write(transcript['content'])
            print(f"Saved to: {test_file}")
    
    return links


if __name__ == "__main__":
    asyncio.run(main())