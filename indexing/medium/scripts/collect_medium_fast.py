#!/usr/bin/env python3
"""
Fast Medium collector - gets recent articles without scanning all archives
"""

import asyncio
import sys
import httpx
from pathlib import Path
from loguru import logger
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from indexing.collectors.medium_collector import MediumCollector


async def get_recent_articles(base_url: str, max_pages: int = 5):
    """Get recent articles by following 'Show More' pattern"""
    client = httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    )
    
    article_urls = set()
    
    # Get main archive page
    logger.info(f"Fetching main archive from {base_url}/archive")
    response = await client.get(f"{base_url}/archive")
    
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all links that look like articles
        links = soup.find_all('a', href=True)
        for link in links:
            href = link.get('href', '')
            if href:
                full_url = urljoin(base_url, href)
                # Check if it looks like an article URL
                if ('/p/' in href or re.search(r'-[a-f0-9]{8,}$', href)) and 'medium.com' in full_url:
                    article_urls.add(full_url.split('?')[0])  # Remove query params
        
        logger.info(f"Found {len(article_urls)} articles from main archive")
    
    # Also try recent years
    import datetime
    current_year = datetime.datetime.now().year
    
    for year in [current_year, current_year - 1, current_year - 2]:
        for month in range(1, 13):
            if len(article_urls) >= 100:  # Stop if we have enough
                break
                
            archive_url = f"{base_url}/archive/{year}/{month:02d}"
            logger.info(f"Checking {archive_url}")
            
            try:
                response = await client.get(archive_url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    links = soup.find_all('a', href=True)
                    for link in links:
                        href = link.get('href', '')
                        if href:
                            full_url = urljoin(base_url, href)
                            if ('/p/' in href or re.search(r'-[a-f0-9]{8,}$', href)) and 'medium.com' in full_url:
                                article_urls.add(full_url.split('?')[0])
                    
                    logger.info(f"Total articles found: {len(article_urls)}")
                    
            except Exception as e:
                logger.debug(f"Error fetching {archive_url}: {e}")
                continue
            
            await asyncio.sleep(0.5)  # Be respectful
    
    await client.aclose()
    return list(article_urls)


async def main():
    """Main function to run fast Medium collection"""
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add("indexing/logs/medium_fast_collection.log", rotation="10 MB", level="DEBUG")
    
    # Get article URLs first
    base_url = "https://medium.com/regen-network"
    logger.info("Fetching article URLs from Medium...")
    article_urls = await get_recent_articles(base_url)
    
    logger.info(f"Found {len(article_urls)} unique articles")
    
    if not article_urls:
        logger.error("No articles found!")
        return
    
    # Configuration for Medium collector
    config = {
        'medium': [
            {
                'name': 'regen-network-medium',
                'url': base_url,
                'strategy': 'scrape'
            }
        ]
    }
    
    # Initialize collector
    collector = MediumCollector(config)
    
    # Collect articles directly
    logger.info("Collecting article content...")
    articles = []
    batch_size = 10
    
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
            
            await asyncio.sleep(0.5)  # Be respectful
            
        except Exception as e:
            logger.error(f"Error collecting {url}: {e}")
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
    logger.info(f"Total articles collected: {len(articles)}")
    
    if articles:
        # Show sample titles
        logger.info("\nSample articles:")
        for i, doc in enumerate(articles[:5], 1):
            title = doc.title
            author = doc.author or 'Unknown'
            logger.info(f"{i}. {title[:80]}")
            logger.info(f"   Author: {author}")
        
        if len(articles) > 5:
            logger.info(f"... and {len(articles) - 5} more articles")
    
    # Count total Medium docs in storage
    storage_path = Path("indexing/storage/documents")
    medium_docs = list(storage_path.glob("medium_*.json"))
    logger.info(f"\nTotal Medium documents in storage: {len(medium_docs)}")
    
    logger.info(f"{'='*60}")
    logger.info("Collection complete!")


if __name__ == "__main__":
    asyncio.run(main())