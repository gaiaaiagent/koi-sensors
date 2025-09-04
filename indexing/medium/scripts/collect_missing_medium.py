#!/usr/bin/env python3
"""
Collect the missing Medium articles from the user-provided list of 130
"""

import asyncio
import json
import sys
from pathlib import Path
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO")

sys.path.append(str(Path(__file__).parent.parent.parent))
from indexing.collectors.medium_collector import MediumCollector


async def main():
    """Collect missing Medium articles"""
    
    # Load the user-provided URLs
    with open("indexing/storage/user_provided_medium_urls.json") as f:
        all_urls = json.load(f)
    
    logger.info(f"User provided {len(all_urls)} Medium article URLs")
    
    # Check existing documents
    existing_docs = list(Path("indexing/storage/documents").glob("medium_*.json"))
    existing_urls = set()
    
    for doc_path in existing_docs:
        try:
            with open(doc_path) as f:
                doc = json.load(f)
                url = doc.get('url', '')
                # Normalize URL for comparison
                url = url.split('?')[0]  # Remove query params
                existing_urls.add(url)
        except Exception as e:
            logger.error(f"Error reading {doc_path}: {e}")
    
    logger.info(f"Found {len(existing_urls)} existing Medium articles")
    
    # Find missing URLs
    missing_urls = []
    for url in all_urls:
        normalized_url = url.split('?')[0]
        if normalized_url not in existing_urls:
            missing_urls.append(url)
    
    logger.info(f"Need to collect {len(missing_urls)} missing articles")
    
    if not missing_urls:
        logger.success("All 130 articles are already collected!")
        return
    
    # Show first few missing URLs
    logger.info("First few missing articles:")
    for url in missing_urls[:5]:
        logger.info(f"  - {url}")
    
    # Initialize collector
    config = {
        'medium': [{
            'name': 'regen-network-medium',
            'url': 'https://regen-network.medium.com',
            'strategy': 'scrape'
        }]
    }
    
    collector = MediumCollector(config)
    
    # Collect missing articles
    logger.info("\nStarting collection of missing articles...")
    collected = []
    failed = []
    
    for i, url in enumerate(missing_urls, 1):
        try:
            logger.info(f"[{i}/{len(missing_urls)}] Collecting: {url}")
            article = await collector.collect_article(url, 'regen-network-medium')
            
            if article:
                collected.append(article)
                # Save every 5 articles
                if len(collected) % 5 == 0:
                    collector.save_documents(collected[-5:])
                    logger.success(f"  Saved batch of 5 articles")
            else:
                logger.warning(f"  Failed to collect article")
                failed.append(url)
                
            # Small delay to be respectful
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.error(f"  Error collecting {url}: {e}")
            failed.append(url)
    
    # Save any remaining articles
    if collected and len(collected) % 5 != 0:
        remaining = len(collected) % 5
        collector.save_documents(collected[-remaining:])
        logger.success(f"Saved final batch of {remaining} articles")
    
    # Final report
    logger.info(f"\n{'='*60}")
    logger.success(f"Successfully collected {len(collected)} new articles")
    
    if failed:
        logger.warning(f"Failed to collect {len(failed)} articles:")
        for url in failed:
            logger.warning(f"  - {url}")
    
    # Check final count
    final_docs = list(Path("indexing/storage/documents").glob("medium_*.json"))
    logger.info(f"\nFINAL TOTAL: {len(final_docs)} Medium articles in storage")
    logger.info(f"Target: 130 articles")
    logger.info(f"Completion: {len(final_docs)/130*100:.1f}%")
    
    if len(final_docs) == 130:
        logger.success("🎉 ALL 130 MEDIUM ARTICLES SUCCESSFULLY COLLECTED! 🎉")


if __name__ == "__main__":
    asyncio.run(main())