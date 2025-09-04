#!/usr/bin/env python3
"""
Final attempt to get ALL 130 Medium articles
Using the most thorough approach possible
"""

import asyncio
import sys
import json
from pathlib import Path
from loguru import logger
from playwright.async_api import async_playwright
import re

logger.remove()
logger.add(sys.stderr, level="INFO")

sys.path.append(str(Path(__file__).parent.parent.parent))
from indexing.collectors.medium_collector import MediumCollector


async def get_all_medium_urls():
    """Get ALL Medium article URLs using every method possible"""
    
    all_urls = set()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        # Strategy 1: Check the main page and look for the article count
        logger.info("Checking main publication page...")
        await page.goto("https://medium.com/regen-network", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        
        # Try to find article count on page
        article_count_text = await page.evaluate("""
            () => {
                const text = document.body.innerText;
                const match = text.match(/(\d+)\s*(stories?|articles?|posts?)/i);
                return match ? match[0] : null;
            }
        """)
        
        if article_count_text:
            logger.info(f"Page shows: {article_count_text}")
        
        # Get initial articles
        initial_articles = await page.evaluate("""
            () => {
                const articles = [];
                // Try multiple selectors
                document.querySelectorAll('a').forEach(link => {
                    const href = link.href;
                    if (href && href.includes('medium.com/regen-network/')) {
                        articles.push(href.split('?')[0]);
                    }
                });
                return [...new Set(articles)];
            }
        """)
        
        for url in initial_articles:
            if not any(skip in url for skip in ['/tag/', '/about', '/archive']):
                all_urls.add(url)
        
        logger.info(f"Found {len(all_urls)} articles on main page")
        
        # Strategy 2: Try archive pages by year AND month
        logger.info("\nChecking monthly archives...")
        
        for year in range(2018, 2025):
            for month in range(1, 13):
                try:
                    url = f"https://medium.com/regen-network/archive/{year}/{month:02d}"
                    logger.info(f"Checking {year}/{month:02d}...")
                    
                    await page.goto(url, wait_until="domcontentloaded", timeout=10000)
                    await asyncio.sleep(1)
                    
                    # Get all article links from this month
                    month_articles = await page.evaluate("""
                        () => {
                            const articles = [];
                            document.querySelectorAll('a').forEach(link => {
                                const href = link.href;
                                if (href && href.includes('medium.com/regen-network/')) {
                                    articles.push(href.split('?')[0]);
                                }
                            });
                            return [...new Set(articles)];
                        }
                    """)
                    
                    new_articles = 0
                    for url in month_articles:
                        if not any(skip in url for skip in ['/tag/', '/about', '/archive', '/tagged']):
                            if url not in all_urls:
                                new_articles += 1
                                all_urls.add(url)
                    
                    if new_articles > 0:
                        logger.info(f"  Found {new_articles} new articles in {year}/{month:02d}")
                    
                except Exception as e:
                    # No archive for this month
                    pass
        
        # Strategy 3: Try tagged pages (common way to list all articles)
        logger.info("\nChecking tagged pages...")
        
        tags = ['carbon', 'blockchain', 'regenerative', 'climate', 'biodiversity', 
                'cosmos', 'web3', 'defi', 'cryptocurrency', 'sustainability']
        
        for tag in tags:
            try:
                url = f"https://medium.com/regen-network/tagged/{tag}"
                await page.goto(url, wait_until="domcontentloaded", timeout=10000)
                await asyncio.sleep(1)
                
                tag_articles = await page.evaluate("""
                    () => {
                        const articles = [];
                        document.querySelectorAll('a').forEach(link => {
                            const href = link.href;
                            if (href && href.includes('medium.com/regen-network/')) {
                                articles.push(href.split('?')[0]);
                            }
                        });
                        return [...new Set(articles)];
                    }
                """)
                
                new_articles = 0
                for url in tag_articles:
                    if not any(skip in url for skip in ['/tag/', '/about', '/archive', '/tagged']):
                        if url not in all_urls:
                            new_articles += 1
                            all_urls.add(url)
                
                if new_articles > 0:
                    logger.info(f"  Tag '{tag}': {new_articles} new articles")
                    
            except Exception:
                pass
        
        # Strategy 4: Search for specific Regen Network terms
        logger.info("\nSearching for Regen Network articles...")
        
        search_terms = ['regen network', 'regen ledger', 'eco credits', 'carbon credits']
        for term in search_terms:
            try:
                search_url = f"https://medium.com/search?q={term.replace(' ', '%20')}"
                await page.goto(search_url, wait_until="domcontentloaded", timeout=10000)
                await asyncio.sleep(2)
                
                search_articles = await page.evaluate("""
                    () => {
                        const articles = [];
                        document.querySelectorAll('a').forEach(link => {
                            const href = link.href;
                            if (href && href.includes('medium.com/regen-network/')) {
                                articles.push(href.split('?')[0]);
                            }
                        });
                        return [...new Set(articles)];
                    }
                """)
                
                for url in search_articles:
                    if not any(skip in url for skip in ['/tag/', '/about', '/archive']):
                        all_urls.add(url)
                        
            except Exception:
                pass
        
        await browser.close()
    
    return list(all_urls)


async def main():
    """Main function to collect all Medium articles"""
    
    logger.info("Starting comprehensive Medium collection...")
    logger.info("Goal: Find all ~130 articles")
    logger.info("="*60)
    
    # Get all URLs
    all_urls = await get_all_medium_urls()
    
    logger.info(f"\n{'='*60}")
    logger.info(f"FOUND {len(all_urls)} UNIQUE ARTICLE URLs")
    logger.info(f"{'='*60}\n")
    
    # Save URL list for inspection
    url_file = Path("indexing/logs/all_medium_urls.txt")
    with open(url_file, 'w') as f:
        for url in sorted(all_urls):
            f.write(f"{url}\n")
    logger.info(f"Saved all URLs to: {url_file}")
    
    # Show sample
    logger.info("\nSample URLs:")
    for url in sorted(all_urls)[:10]:
        logger.info(f"  - {url}")
    
    # Now collect content for any we don't have
    existing_docs = list(Path("indexing/storage/documents").glob("medium_*.json"))
    existing_urls = set()
    
    for doc_path in existing_docs:
        try:
            with open(doc_path) as f:
                doc = json.load(f)
                existing_urls.add(doc.get('url', ''))
        except:
            pass
    
    new_urls = [url for url in all_urls if url not in existing_urls]
    
    logger.info(f"\nAlready have: {len(existing_urls)} articles")
    logger.info(f"New to collect: {len(new_urls)} articles")
    
    if new_urls:
        # Collect new articles
        config = {
            'medium': [{
                'name': 'regen-network-medium',
                'url': 'https://medium.com/regen-network',
                'strategy': 'scrape'
            }]
        }
        
        collector = MediumCollector(config)
        
        logger.info("\nCollecting new articles...")
        articles = []
        
        for i, url in enumerate(new_urls, 1):
            try:
                logger.info(f"Collecting {i}/{len(new_urls)}: {url}")
                article = await collector.collect_article(url, 'regen-network-medium')
                if article:
                    articles.append(article)
                    if len(articles) % 10 == 0:
                        collector.save_documents(articles[-10:])
                        logger.info(f"  Saved batch of 10")
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"  Error: {e}")
        
        # Save remaining
        if articles and len(articles) % 10 != 0:
            remaining = len(articles) % 10
            collector.save_documents(articles[-remaining:])
    
    # Final count
    final_docs = list(Path("indexing/storage/documents").glob("medium_*.json"))
    logger.info(f"\n{'='*60}")
    logger.info(f"FINAL TOTAL: {len(final_docs)} Medium articles in storage")
    logger.info(f"Target was ~130 articles")
    logger.info(f"Collection rate: {len(final_docs)/130*100:.1f}%")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())