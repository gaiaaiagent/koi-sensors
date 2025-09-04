#!/usr/bin/env python3
"""
Script to collect all articles from Regen Network's Medium blog
"""

import asyncio
import sys
from pathlib import Path
from loguru import logger

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from indexing.collectors.medium_collector import MediumCollector


async def main():
    """
    Main function to run Medium collection
    """
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add("indexing/logs/medium_collection.log", rotation="10 MB", level="DEBUG")
    
    # Configuration for Regen Network Medium
    config = {
        'medium': [
            {
                'name': 'regen-network-medium',
                'url': 'https://medium.com/regen-network',
                'strategy': 'scrape'
            }
        ]
    }
    
    # Check for command line arguments
    limit = None
    if len(sys.argv) > 1:
        if sys.argv[1] == '--test':
            limit = 5
            logger.info("Running in test mode - collecting only 5 articles")
        elif sys.argv[1] == '--limit':
            if len(sys.argv) > 2:
                limit = int(sys.argv[2])
                logger.info(f"Collecting up to {limit} articles")
        elif sys.argv[1] == '--help':
            print("Usage: python collect_medium.py [options]")
            print("Options:")
            print("  --test        Collect only 5 articles for testing")
            print("  --limit N     Collect up to N articles")
            print("  --help        Show this help message")
            print("  (no options)  Collect all available articles")
            return
    
    # Initialize collector
    collector = MediumCollector(config)
    
    # Collect articles
    logger.info("Starting Medium blog collection...")
    documents = await collector.collect(limit=limit)
    
    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info(f"Collection Summary:")
    logger.info(f"{'='*60}")
    logger.info(f"Total articles collected: {len(documents)}")
    
    if documents:
        # Show some sample titles
        logger.info("\nSample articles collected:")
        for i, doc in enumerate(documents[:10], 1):
            title = doc.metadata.get('title', 'Untitled')
            author = doc.metadata.get('author', 'Unknown')
            date = doc.metadata.get('published_date', 'Unknown date')
            logger.info(f"{i}. {title[:80]}")
            logger.info(f"   Author: {author}, Date: {date}")
        
        if len(documents) > 10:
            logger.info(f"... and {len(documents) - 10} more articles")
        
        # Show storage location
        storage_path = Path("indexing/storage/documents")
        logger.info(f"\nDocuments saved to: {storage_path.absolute()}")
        
        # Count Medium documents in storage
        medium_docs = list(storage_path.glob("medium_*.json"))
        logger.info(f"Total Medium documents in storage: {len(medium_docs)}")
    else:
        logger.warning("No articles were collected. This might indicate an issue with the scraping.")
        logger.info("Troubleshooting tips:")
        logger.info("1. Check if the Medium URL is accessible")
        logger.info("2. Medium might be blocking automated requests")
        logger.info("3. The page structure might have changed")
        logger.info("4. Try running with --test flag first")
    
    logger.info(f"{'='*60}")
    logger.info("Collection complete!")


if __name__ == "__main__":
    asyncio.run(main())