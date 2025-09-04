#!/usr/bin/env python3
"""
Human-like Medium collector that bypasses Cloudflare detection
Uses realistic browser behavior to collect all articles
"""

import asyncio
import sys
import random
import time
from pathlib import Path
from datetime import datetime
from loguru import logger
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from urllib.parse import urljoin
import re

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from indexing.collectors.medium_collector import MediumCollector


async def human_like_scroll(page):
    """Scroll like a human - variable speed, pauses, small movements"""
    viewport_height = await page.evaluate("window.innerHeight")
    total_height = await page.evaluate("document.body.scrollHeight")
    current_position = 0
    
    while current_position < total_height:
        # Variable scroll distance (like a human would)
        scroll_distance = random.randint(int(viewport_height * 0.5), int(viewport_height * 0.8))
        
        # Smooth scroll with easing
        await page.evaluate(f"""
            window.scrollTo({{
                top: {current_position + scroll_distance},
                behavior: 'smooth'
            }})
        """)
        
        current_position += scroll_distance
        
        # Random pause between scrolls (human reading behavior)
        await asyncio.sleep(random.uniform(1.5, 3.5))
        
        # Sometimes scroll back up a bit (like re-reading)
        if random.random() < 0.1:  # 10% chance
            small_scroll_up = random.randint(50, 200)
            await page.evaluate(f"""
                window.scrollBy({{
                    top: -{small_scroll_up},
                    behavior: 'smooth'
                }})
            """)
            await asyncio.sleep(random.uniform(0.5, 1.5))
        
        # Check new height (for infinite scroll)
        total_height = await page.evaluate("document.body.scrollHeight")


async def random_mouse_movement(page):
    """Move mouse randomly like a human"""
    viewport = page.viewport_size
    if viewport:
        for _ in range(random.randint(2, 5)):
            x = random.randint(100, viewport['width'] - 100)
            y = random.randint(100, viewport['height'] - 100)
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.1, 0.3))


async def get_all_articles_human_like(base_url: str, max_articles: int = 200):
    """
    Collect Medium articles using human-like browsing behavior
    
    Args:
        base_url: The Medium publication URL
        max_articles: Maximum number of articles to collect
    
    Returns:
        List of unique article URLs
    """
    article_urls = set()
    
    async with async_playwright() as p:
        # Launch browser with anti-detection settings
        browser = await p.chromium.launch(
            headless=True,  # Must be headless on server
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ]
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            screen={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
            permissions=['geolocation'],
            ignore_https_errors=True
        )
        
        page = await context.new_page()
        
        # Apply stealth mode to bypass detection
        stealth_config = Stealth()
        await stealth_config.apply_stealth_async(page)
        
        # Remove signs of automation
        await page.evaluate("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            window.chrome = {
                runtime: {}
            };
            Object.defineProperty(navigator, 'permissions', {
                get: () => ({
                    query: () => Promise.resolve({ state: 'granted' })
                })
            });
        """)
        
        logger.info(f"Loading Medium page: {base_url}")
        
        # Navigate with realistic timing
        await page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
        
        # Wait for page to load and simulate human reading
        await asyncio.sleep(random.uniform(3, 5))
        
        # Move mouse around a bit
        await random_mouse_movement(page)
        
        # Check if we hit Cloudflare
        title = await page.title()
        if "Just a moment" in title or "Checking your browser" in title:
            logger.warning("Hit Cloudflare challenge, waiting for it to resolve...")
            # Wait for Cloudflare to resolve (usually takes 5-10 seconds)
            await asyncio.sleep(10)
            
            # Check again
            title = await page.title()
            if "Just a moment" in title:
                logger.error("Still blocked by Cloudflare after waiting")
                await browser.close()
                return []
        
        logger.info(f"Page loaded successfully: {title}")
        
        # Scroll down gradually to load articles
        previous_article_count = 0
        no_new_articles_count = 0
        scroll_attempts = 0
        max_scrolls = 100  # Increased to handle 130+ articles
        
        logger.info("Starting to scroll and collect articles...")
        
        while scroll_attempts < max_scrolls and len(article_urls) < max_articles:
            # Get current articles on page
            links = await page.evaluate("""
                () => {
                    const links = [];
                    // Look for all links on the page
                    document.querySelectorAll('a').forEach(link => {
                        const href = link.href;
                        if (href && href.includes('medium.com')) {
                            // Check if it's an article URL (various patterns Medium uses)
                            if (href.includes('/p/') || 
                                href.match(/-[a-f0-9]{8,}$/) ||
                                (href.includes('regen-network') && !href.includes('/tag/') && !href.includes('/about'))) {
                                const cleanUrl = href.split('?')[0].split('#')[0];
                                links.push(cleanUrl);
                            }
                        }
                    });
                    // Also check for article elements directly
                    document.querySelectorAll('article').forEach(article => {
                        const link = article.querySelector('a');
                        if (link && link.href) {
                            const cleanUrl = link.href.split('?')[0].split('#')[0];
                            if (cleanUrl.includes('medium.com')) {
                                links.push(cleanUrl);
                            }
                        }
                    });
                    return [...new Set(links)];
                }
            """)
            
            # Add new URLs
            for url in links:
                article_urls.add(url)
            
            current_count = len(article_urls)
            logger.info(f"Found {current_count} unique articles so far...")
            
            if current_count == previous_article_count:
                no_new_articles_count += 1
                if no_new_articles_count >= 5:  # Increased patience
                    logger.info(f"No new articles after {no_new_articles_count} scrolls, checking if we need to scroll more...")
                    
                    # Try scrolling to the very bottom
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(3)
                    
                    # Check one more time
                    new_links = await page.evaluate("""
                        () => {
                            const links = [];
                            document.querySelectorAll('a').forEach(link => {
                                const href = link.href;
                                if (href && href.includes('medium.com')) {
                                    if (href.includes('/p/') || 
                                        href.match(/-[a-f0-9]{8,}$/) ||
                                        (href.includes('regen-network') && !href.includes('/tag/') && !href.includes('/about'))) {
                                        const cleanUrl = href.split('?')[0].split('#')[0];
                                        links.push(cleanUrl);
                                    }
                                }
                            });
                            return [...new Set(links)];
                        }
                    """)
                    
                    for url in new_links:
                        article_urls.add(url)
                    
                    if len(article_urls) > current_count:
                        logger.info(f"Found more articles after aggressive scroll! Now have {len(article_urls)}")
                        no_new_articles_count = 0
                    elif no_new_articles_count >= 7:
                        logger.info("Really reached the end after multiple attempts")
                        break
            else:
                no_new_articles_count = 0
            
            previous_article_count = current_count
            
            # Scroll down like a human
            viewport_height = await page.evaluate("window.innerHeight")
            await page.evaluate(f"""
                window.scrollBy({{
                    top: {random.randint(int(viewport_height * 0.6), int(viewport_height * 0.9))},
                    behavior: 'smooth'
                }})
            """)
            
            # Random wait (simulating reading) - longer wait for infinite scroll to load
            await asyncio.sleep(random.uniform(3, 5))
            
            # Occasionally move mouse
            if random.random() < 0.3:
                await random_mouse_movement(page)
            
            scroll_attempts += 1
        
        # Take a screenshot for debugging
        screenshot_path = Path("indexing/logs/medium_success.png")
        await page.screenshot(path=str(screenshot_path))
        logger.info(f"Screenshot saved to: {screenshot_path}")
        
        await browser.close()
    
    # Filter URLs
    filtered_urls = []
    for url in article_urls:
        # Skip non-article pages
        if any(skip in url.lower() for skip in ['/policy/', '/about', '/tag/', '/archive', '/membership']):
            continue
        if '/p/' in url or re.search(r'-[a-f0-9]{8,}$', url):
            filtered_urls.append(url)
    
    return filtered_urls


async def main():
    """Main function to collect Medium articles with human-like behavior"""
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add("indexing/logs/medium_human_collection.log", rotation="10 MB", level="DEBUG")
    
    # Check command line arguments
    test_mode = False
    limit = None
    if len(sys.argv) > 1:
        if sys.argv[1] == '--test':
            test_mode = True
            limit = 5
            logger.info("Running in test mode - will collect only 5 articles")
        elif sys.argv[1] == '--limit' and len(sys.argv) > 2:
            limit = int(sys.argv[2])
            logger.info(f"Will collect up to {limit} articles")
    
    # Get article URLs using human-like browsing
    base_url = "https://medium.com/regen-network"
    logger.info("Starting human-like Medium collection...")
    
    try:
        max_to_fetch = limit if limit else 200
        article_urls = await get_all_articles_human_like(base_url, max_articles=max_to_fetch)
        logger.info(f"Successfully collected {len(article_urls)} article URLs")
    except Exception as e:
        logger.error(f"Error during collection: {e}")
        return
    
    if not article_urls:
        logger.error("No articles found! Cloudflare might still be blocking.")
        return
    
    # Sort URLs (newest first)
    article_urls = sorted(list(article_urls), reverse=True)
    
    # Apply limit if specified
    if limit:
        article_urls = article_urls[:limit]
    
    # Show sample URLs
    logger.info("\nSample article URLs:")
    for i, url in enumerate(article_urls[:5], 1):
        logger.info(f"{i}. {url}")
    if len(article_urls) > 5:
        logger.info(f"... and {len(article_urls) - 5} more articles")
    
    # Initialize collector
    config = {
        'medium': [
            {
                'name': 'regen-network-medium',
                'url': base_url,
                'strategy': 'scrape'
            }
        ]
    }
    
    collector = MediumCollector(config)
    
    # Collect article content
    logger.info("\nCollecting article content...")
    articles = []
    batch_size = 10
    failed_urls = []
    
    for i, url in enumerate(article_urls, 1):
        try:
            logger.info(f"Collecting article {i}/{len(article_urls)}: {url}")
            article = await collector.collect_article(url, 'regen-network-medium')
            
            if article:
                articles.append(article)
                
                # Save in batches
                if len(articles) % batch_size == 0:
                    collector.save_documents(articles[-batch_size:])
                    logger.info(f"Saved batch of {batch_size} articles")
            else:
                failed_urls.append(url)
            
            # Random delay between articles
            await asyncio.sleep(random.uniform(1, 2))
            
        except Exception as e:
            logger.error(f"Error collecting {url}: {e}")
            failed_urls.append(url)
    
    # Save remaining articles
    if articles and len(articles) % batch_size != 0:
        remaining = len(articles) % batch_size
        collector.save_documents(articles[-remaining:])
        logger.info(f"Saved final batch of {remaining} articles")
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"Collection Summary:")
    logger.info(f"{'='*60}")
    logger.info(f"Articles found: {len(article_urls)}")
    logger.info(f"Articles collected: {len(articles)}")
    logger.info(f"Failed: {len(failed_urls)}")
    
    if articles:
        logger.info("\nSample articles collected:")
        for i, doc in enumerate(articles[:5], 1):
            logger.info(f"{i}. {doc.title[:80]}")
            if doc.author:
                logger.info(f"   Author: {doc.author}")
    
    # Count total Medium docs
    storage_path = Path("indexing/storage/documents")
    medium_docs = list(storage_path.glob("medium_*.json"))
    logger.info(f"\nTotal Medium documents in storage: {len(medium_docs)}")
    
    logger.info(f"{'='*60}")
    logger.info("Collection complete!")


if __name__ == "__main__":
    asyncio.run(main())