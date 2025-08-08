#!/usr/bin/env python3
"""
Debug script to understand Medium page structure
"""

import asyncio
from playwright.async_api import async_playwright
from pathlib import Path
from loguru import logger


async def debug_medium_page():
    """Take screenshot and extract page info"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Try loading the page
        url = "https://medium.com/regen-network"
        logger.info(f"Loading: {url}")
        
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        
        # Take screenshot
        screenshot_path = Path("indexing/logs/medium_page.png")
        await page.screenshot(path=str(screenshot_path), full_page=False)
        logger.info(f"Screenshot saved to: {screenshot_path}")
        
        # Get page title
        title = await page.title()
        logger.info(f"Page title: {title}")
        
        # Try different selectors to find articles
        selectors_to_try = [
            'article',
            'div[data-testid="post-card"]',
            'div[class*="postArticle"]',
            'a[href*="/p/"]',
            'a[data-action="open-post"]',
            'h3',
            'h2',
            '[role="article"]'
        ]
        
        for selector in selectors_to_try:
            count = await page.evaluate(f"""
                () => document.querySelectorAll('{selector}').length
            """)
            if count > 0:
                logger.info(f"Found {count} elements with selector: {selector}")
                
                # Get first few hrefs if they're links
                if 'a[' in selector:
                    sample_hrefs = await page.evaluate(f"""
                        () => {{
                            const links = Array.from(document.querySelectorAll('{selector}')).slice(0, 3);
                            return links.map(l => l.href);
                        }}
                    """)
                    for href in sample_hrefs:
                        logger.info(f"  Sample href: {href}")
        
        # Get all links on the page
        all_links = await page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a'));
                return links.map(l => l.href).filter(href => href && href.includes('medium.com'));
            }
        """)
        
        logger.info(f"\nTotal links found: {len(all_links)}")
        
        # Filter for article-like links
        article_links = [l for l in all_links if '/p/' in l or '-' in l.split('/')[-1]]
        logger.info(f"Article-like links: {len(article_links)}")
        
        if article_links:
            logger.info("\nSample article links:")
            for link in article_links[:5]:
                logger.info(f"  - {link}")
        
        # Save page HTML for inspection
        html_path = Path("indexing/logs/medium_page.html")
        html_content = await page.content()
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logger.info(f"\nPage HTML saved to: {html_path}")
        
        await browser.close()


if __name__ == "__main__":
    import sys
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    
    asyncio.run(debug_medium_page())