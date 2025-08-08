#!/usr/bin/env python3
"""
Debug script to understand exactly how Medium loads articles
"""

import asyncio
from playwright.async_api import async_playwright
from loguru import logger
import sys

logger.remove()
logger.add(sys.stderr, level="INFO")


async def debug_medium_loading():
    """Debug how Medium loads articles when scrolling"""
    
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(
            headless=True,  # Must be headless on server
            args=['--disable-blink-features=AutomationControlled']
        )
        
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720}
        )
        
        page = await context.new_page()
        
        # Go to Medium page
        url = "https://medium.com/regen-network"
        logger.info(f"Loading {url}")
        await page.goto(url, wait_until="networkidle")
        
        # Wait for initial load
        await asyncio.sleep(5)
        
        all_articles = set()
        previous_count = 0
        no_new_count = 0
        
        logger.info("Starting to scroll and monitor article loading...")
        
        for i in range(50):  # Try many scrolls
            # Count current articles multiple ways
            
            # Method 1: Look for article elements
            article_count = await page.evaluate("""
                () => document.querySelectorAll('article').length
            """)
            
            # Method 2: Look for all links
            all_links = await page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a[href*="/regen-network/"]'));
                    return links.map(l => l.href).filter(href => 
                        !href.includes('/tag/') && 
                        !href.includes('/about') &&
                        !href.includes('/archive')
                    );
                }
            """)
            
            # Method 3: Look for h2/h3 headers (article titles)
            titles = await page.evaluate("""
                () => {
                    const headers = Array.from(document.querySelectorAll('h2, h3'));
                    return headers.map(h => h.innerText);
                }
            """)
            
            # Add unique articles
            for link in all_links:
                if '/regen-network/' in link:
                    all_articles.add(link.split('?')[0])
            
            current_count = len(all_articles)
            
            logger.info(f"Scroll {i+1}: Articles: {article_count}, Links: {len(all_links)}, Unique total: {current_count}, Titles: {len(titles)}")
            
            # Show some titles
            if titles and i % 5 == 0:
                logger.info(f"  Sample titles: {titles[:3]}")
            
            # Check if we're making progress
            if current_count == previous_count:
                no_new_count += 1
                if no_new_count >= 10:
                    logger.info("No new articles for 10 scrolls, stopping")
                    break
            else:
                no_new_count = 0
                previous_count = current_count
            
            # Scroll down
            await page.evaluate("""
                window.scrollTo({
                    top: document.body.scrollHeight,
                    behavior: 'smooth'
                })
            """)
            
            # Wait for potential lazy loading
            await asyncio.sleep(3)
            
            # Check if there's a "Show more" button and click it
            show_more_clicked = await page.evaluate("""
                () => {
                    const buttons = Array.from(document.querySelectorAll('button'));
                    for (const button of buttons) {
                        const text = button.innerText.toLowerCase();
                        if (text.includes('show more') || text.includes('load more')) {
                            button.click();
                            return true;
                        }
                    }
                    
                    // Also check for divs that might be clickable
                    const divs = Array.from(document.querySelectorAll('div'));
                    for (const div of divs) {
                        const text = div.innerText.toLowerCase();
                        if ((text === 'show more' || text === 'load more') && div.onclick) {
                            div.click();
                            return true;
                        }
                    }
                    
                    return false;
                }
            """)
            
            if show_more_clicked:
                logger.info("  *** Clicked a 'Show More' button! ***")
                await asyncio.sleep(3)
            
            # Also try to find infinite scroll triggers
            infinite_trigger = await page.evaluate("""
                () => {
                    // Look for sentinel elements often used for infinite scroll
                    const sentinels = document.querySelectorAll('[data-testid*="sentinel"], .sentinel, #sentinel');
                    return sentinels.length;
                }
            """)
            
            if infinite_trigger:
                logger.info(f"  Found {infinite_trigger} infinite scroll trigger elements")
        
        logger.info(f"\nFinal count: {len(all_articles)} unique articles")
        logger.info("\nSample URLs collected:")
        for url in list(all_articles)[:10]:
            logger.info(f"  - {url}")
        
        # Keep browser open for manual inspection
        logger.info("\nBrowser will stay open for 30 seconds for manual inspection...")
        await asyncio.sleep(30)
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(debug_medium_loading())