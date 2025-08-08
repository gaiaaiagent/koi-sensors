#!/usr/bin/env python3
"""
Medium collector using Playwright to handle infinite scroll
Collects ALL articles from Regen Network's Medium blog
"""

import asyncio
import sys
import json
import re
from pathlib import Path
from datetime import datetime
from loguru import logger
from playwright.async_api import async_playwright
from urllib.parse import urljoin

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from indexing.collectors.medium_collector import MediumCollector


async def get_all_article_urls_with_scroll(base_url: str, max_scrolls: int = 50):
    """
    Use Playwright to scroll and collect all article URLs from Medium
    
    Args:
        base_url: The Medium publication URL
        max_scrolls: Maximum number of scroll attempts (safety limit)
    
    Returns:
        List of unique article URLs
    """
    article_urls = set()
    
    async with async_playwright() as p:
        # Launch browser in headless mode
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Set a reasonable viewport size
        await page.set_viewport_size({"width": 1280, "height": 800})
        
        logger.info(f"Loading Medium page: {base_url}")
        # Use longer timeout and different wait strategy
        await page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
        
        # Wait for initial content to load
        await page.wait_for_timeout(5000)
        
        previous_article_count = 0
        no_new_articles_count = 0
        scroll_count = 0
        
        while scroll_count < max_scrolls:
            # Get all article links currently on the page
            links = await page.evaluate("""
                () => {
                    const links = [];
                    // Look for all links that appear to be articles
                    document.querySelectorAll('a').forEach(link => {
                        const href = link.href;
                        // Check if it's an article URL (contains /p/ or ends with hex ID)
                        if (href && (href.includes('/p/') || href.match(/-[a-f0-9]{8,}$/))) {
                            // Remove query parameters and fragments
                            const cleanUrl = href.split('?')[0].split('#')[0];
                            if (cleanUrl.includes('medium.com')) {
                                links.push(cleanUrl);
                            }
                        }
                    });
                    return [...new Set(links)]; // Return unique URLs
                }
            """)
            
            # Add new URLs to our set
            for url in links:
                article_urls.add(url)
            
            current_article_count = len(article_urls)
            logger.info(f"Scroll {scroll_count + 1}: Found {current_article_count} unique articles")
            
            # Check if we got new articles
            if current_article_count == previous_article_count:
                no_new_articles_count += 1
                if no_new_articles_count >= 3:
                    logger.info("No new articles found after 3 scrolls, stopping")
                    break
            else:
                no_new_articles_count = 0
            
            previous_article_count = current_article_count
            
            # Scroll down to load more articles
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            # Wait for new content to potentially load
            await page.wait_for_timeout(2000)
            
            # Check if we've hit the end (look for "No more stories" or similar)
            end_of_content = await page.evaluate("""
                () => {
                    const text = document.body.innerText.toLowerCase();
                    return text.includes('no more stories') || 
                           text.includes(\"you've reached the end\") ||
                           text.includes('no more posts');
                }
            """)
            
            if end_of_content:
                logger.info("Reached end of content")
                break
            
            scroll_count += 1
        
        await browser.close()
    
    # Filter out non-article URLs
    filtered_urls = []
    publication_name = base_url.split('/')[-1]
    
    for url in article_urls:
        # Skip policy pages, about pages, etc.
        if any(skip in url.lower() for skip in ['/policy/', '/about', '/tag/', '/archive']):
            continue
        # Keep URLs that look like articles
        if '/p/' in url or re.search(r'-[a-f0-9]{8,}$', url):
            filtered_urls.append(url)
    
    return filtered_urls


async def main():
    """Main function to collect all Medium articles using scroll"""
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add("indexing/logs/medium_scroll_collection.log", rotation="10 MB", level="DEBUG")
    
    # Check command line arguments
    test_mode = False
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        test_mode = True
        logger.info("Running in test mode - will collect only 5 articles")
    
    # Get all article URLs using scroll
    # Try both URL formats that Medium uses
    urls_to_try = [
        "https://medium.com/regen-network",
        "https://regen-network.medium.com"
    ]
    
    article_urls = []
    logger.info("Starting Medium collection with scroll simulation...")
    
    for base_url in urls_to_try:
        try:
            logger.info(f"Trying URL: {base_url}")
            article_urls = await get_all_article_urls_with_scroll(base_url)
            if article_urls:
                logger.info(f"Found {len(article_urls)} unique article URLs")
                break
        except Exception as e:
            logger.error(f"Error with {base_url}: {e}")
            continue
    
    if not article_urls:
        logger.error("No articles found!")
        return
    
    # Sort URLs (newest first based on URL structure)
    article_urls = sorted(article_urls, reverse=True)
    
    # In test mode, limit to 5 articles
    if test_mode:
        article_urls = article_urls[:5]
        logger.info(f"Test mode: Processing only {len(article_urls)} articles")
    
    # Show sample URLs
    logger.info("\nSample article URLs found:")
    for i, url in enumerate(article_urls[:5], 1):
        logger.info(f"{i}. {url}")
    if len(article_urls) > 5:
        logger.info(f"... and {len(article_urls) - 5} more articles")
    
    # Initialize Medium collector
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
    
    # Collect articles
    logger.info("\nStarting article content collection...")
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
                    logger.info(f"Saved batch of {batch_size} articles (total: {len(articles)})")
            else:
                logger.warning(f"Failed to extract content from: {url}")
                failed_urls.append(url)
            
            # Small delay to be respectful
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Error collecting {url}: {e}")
            failed_urls.append(url)
            continue
    
    # Save remaining articles
    if articles and len(articles) % batch_size != 0:
        remaining = len(articles) % batch_size
        collector.save_documents(articles[-remaining:])
        logger.info(f"Saved final batch of {remaining} articles")
    
    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info(f"Collection Summary:")
    logger.info(f"{'='*60}")
    logger.info(f"Total URLs found: {len(article_urls)}")
    logger.info(f"Articles collected: {len(articles)}")
    logger.info(f"Failed collections: {len(failed_urls)}")
    
    if articles:
        # Show sample titles
        logger.info("\nSample articles collected:")
        for i, doc in enumerate(articles[:5], 1):
            title = doc.title
            author = doc.author or 'Unknown'
            date = doc.metadata.get('published_date', 'Unknown')
            logger.info(f"{i}. {title[:80]}")
            logger.info(f"   Author: {author}, Date: {date}")
        
        if len(articles) > 5:
            logger.info(f"... and {len(articles) - 5} more articles")
    
    if failed_urls:
        logger.warning(f"\nFailed to collect {len(failed_urls)} articles:")
        for url in failed_urls[:5]:
            logger.warning(f"  - {url}")
        if len(failed_urls) > 5:
            logger.warning(f"  ... and {len(failed_urls) - 5} more")
    
    # Count total Medium docs in storage
    storage_path = Path("indexing/storage/documents")
    medium_docs = list(storage_path.glob("medium_*.json"))
    logger.info(f"\nTotal Medium documents in storage: {len(medium_docs)}")
    
    # Save failed URLs for potential retry
    if failed_urls:
        failed_file = Path("indexing/logs/medium_failed_urls.txt")
        with open(failed_file, 'w') as f:
            for url in failed_urls:
                f.write(f"{url}\n")
        logger.info(f"Failed URLs saved to: {failed_file}")
    
    logger.info(f"{'='*60}")
    logger.info("Collection complete!")


if __name__ == "__main__":
    asyncio.run(main())