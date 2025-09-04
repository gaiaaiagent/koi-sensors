#!/usr/bin/env python3
"""
Aggressive Medium collector that tries multiple methods to get all 130 articles
"""

import asyncio
import sys
import random
from pathlib import Path
from datetime import datetime
from loguru import logger
from playwright.async_api import async_playwright
from urllib.parse import urljoin
import re

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from indexing.collectors.medium_collector import MediumCollector


async def collect_all_medium_articles():
    """
    Aggressively collect all Medium articles using multiple strategies
    """
    all_article_urls = set()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
            ]
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        
        page = await context.new_page()
        
        # Strategy 1: Try the main publication page with aggressive scrolling
        logger.info("Strategy 1: Main publication page with aggressive scrolling")
        await page.goto("https://medium.com/regen-network", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)
        
        # Scroll aggressively
        for i in range(50):  # Many scroll attempts
            # Get current articles
            links = await page.evaluate("""
                () => {
                    const links = [];
                    document.querySelectorAll('a').forEach(link => {
                        const href = link.href;
                        if (href && href.includes('medium.com') && 
                            (href.includes('/p/') || href.match(/-[a-f0-9]{8,}$/))) {
                            links.push(href.split('?')[0]);
                        }
                    });
                    return [...new Set(links)];
                }
            """)
            
            for url in links:
                if 'regen-network' in url or '/p/' in url:
                    all_article_urls.add(url)
            
            logger.info(f"Scroll {i+1}: Found {len(all_article_urls)} total articles")
            
            # Scroll to bottom
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            
            # Check for "Show More" or "Load More" button
            show_more = await page.evaluate("""
                () => {
                    const buttons = Array.from(document.querySelectorAll('button'));
                    const showMore = buttons.find(b => 
                        b.innerText.toLowerCase().includes('show more') ||
                        b.innerText.toLowerCase().includes('load more') ||
                        b.innerText.toLowerCase().includes('older')
                    );
                    if (showMore) {
                        showMore.click();
                        return true;
                    }
                    return false;
                }
            """)
            
            if show_more:
                logger.info("Clicked 'Show More' button!")
                await asyncio.sleep(3)
        
        # Strategy 2: Try the archive pages
        logger.info("\nStrategy 2: Checking archive pages...")
        
        # Try yearly archives
        for year in range(2018, 2025):
            archive_url = f"https://medium.com/regen-network/archive/{year}"
            logger.info(f"Checking archive: {archive_url}")
            
            try:
                await page.goto(archive_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
                
                # Get all links from archive page
                links = await page.evaluate("""
                    () => {
                        const links = [];
                        document.querySelectorAll('a').forEach(link => {
                            const href = link.href;
                            if (href && href.includes('medium.com')) {
                                links.push(href.split('?')[0]);
                            }
                        });
                        return [...new Set(links)];
                    }
                """)
                
                for url in links:
                    if 'regen-network' in url and ('/p/' in url or re.match(r'.*-[a-f0-9]{8,}$', url)):
                        all_article_urls.add(url)
                
                logger.info(f"Archive {year}: Total articles now: {len(all_article_urls)}")
                
            except Exception as e:
                logger.debug(f"Archive {year} error: {e}")
        
        # Strategy 3: Try the latest posts page
        logger.info("\nStrategy 3: Checking latest posts...")
        await page.goto("https://medium.com/regen-network/latest", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        # Scroll on latest page
        for i in range(20):
            links = await page.evaluate("""
                () => {
                    const links = [];
                    document.querySelectorAll('a').forEach(link => {
                        const href = link.href;
                        if (href && href.includes('medium.com')) {
                            links.push(href.split('?')[0]);
                        }
                    });
                    return [...new Set(links)];
                }
            """)
            
            for url in links:
                if 'regen-network' in url and ('/p/' in url or re.match(r'.*-[a-f0-9]{8,}$', url)):
                    all_article_urls.add(url)
            
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
        
        logger.info(f"After latest page: Total articles: {len(all_article_urls)}")
        
        await browser.close()
    
    # Filter out non-article URLs
    filtered_urls = []
    for url in all_article_urls:
        if any(skip in url.lower() for skip in ['/policy/', '/about', '/tag/', '/membership']):
            continue
        if '/p/' in url or re.search(r'-[a-f0-9]{8,}$', url):
            filtered_urls.append(url)
    
    return filtered_urls


async def main():
    """Main function"""
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    
    logger.info("Starting aggressive Medium collection to get all 130 articles...")
    
    # Get all article URLs
    article_urls = await collect_all_medium_articles()
    logger.info(f"\n{'='*60}")
    logger.info(f"Found {len(article_urls)} unique article URLs!")
    logger.info(f"{'='*60}\n")
    
    if not article_urls:
        logger.error("No articles found!")
        return
    
    # Show sample URLs
    logger.info("Sample article URLs:")
    for i, url in enumerate(sorted(article_urls)[:10], 1):
        logger.info(f"{i}. {url}")
    if len(article_urls) > 10:
        logger.info(f"... and {len(article_urls) - 10} more articles\n")
    
    # Now collect the content
    config = {
        'medium': [{
            'name': 'regen-network-medium',
            'url': 'https://medium.com/regen-network',
            'strategy': 'scrape'
        }]
    }
    
    collector = MediumCollector(config)
    
    logger.info("Collecting article content...")
    articles = []
    failed_urls = []
    
    for i, url in enumerate(article_urls, 1):
        try:
            logger.info(f"Collecting article {i}/{len(article_urls)}: {url}")
            article = await collector.collect_article(url, 'regen-network-medium')
            
            if article:
                articles.append(article)
                
                # Save every 10 articles
                if len(articles) % 10 == 0:
                    collector.save_documents(articles[-10:])
                    logger.info(f"Saved batch of 10 articles")
            else:
                failed_urls.append(url)
            
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
        except Exception as e:
            logger.error(f"Error: {e}")
            failed_urls.append(url)
    
    # Save remaining
    if articles and len(articles) % 10 != 0:
        remaining = len(articles) % 10
        collector.save_documents(articles[-remaining:])
        logger.info(f"Saved final batch of {remaining} articles")
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"FINAL SUMMARY:")
    logger.info(f"{'='*60}")
    logger.info(f"Total URLs found: {len(article_urls)}")
    logger.info(f"Articles collected: {len(articles)}")
    logger.info(f"Failed: {len(failed_urls)}")
    
    # Count total in storage
    storage_path = Path("indexing/storage/documents")
    medium_docs = list(storage_path.glob("medium_*.json"))
    logger.info(f"Total Medium documents in storage: {len(medium_docs)}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())