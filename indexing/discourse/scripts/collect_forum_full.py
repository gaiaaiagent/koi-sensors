#!/usr/bin/env python3
"""
Full forum.regen.network collector
Crawls all available topics without authentication
"""

import asyncio
from pathlib import Path
import sys

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from discourse.scripts.crawl_forum_json import ForumJSONCrawler
from loguru import logger


async def main():
    """Crawl forum.regen.network comprehensively"""
    
    logger.info("=" * 60)
    logger.info("Full Forum.regen.network Collection")
    logger.info("=" * 60)
    logger.info("\nThis will crawl forum.regen.network without authentication")
    logger.info("Using the public JSON API endpoints")
    
    # Ask for confirmation for full crawl
    response = input("\nHow many topics to crawl? (20/50/100/all): ").strip().lower()
    
    if response == 'all':
        limit = 500  # Practical limit
    elif response.isdigit():
        limit = int(response)
    else:
        limit = 50  # Default
    
    logger.info(f"\nCrawling {limit} topics...")
    
    async with ForumJSONCrawler() as crawler:
        documents = await crawler.crawl(limit=limit, include_categories=True)
        
        if documents:
            logger.success(f"\n✅ Successfully crawled {len(documents)} topics!")
            
            # Calculate statistics
            total_posts = sum(doc.metadata.get('posts_count', 0) for doc in documents)
            total_views = sum(doc.metadata.get('views', 0) for doc in documents)
            
            logger.info("\n📊 Statistics:")
            logger.info(f"  Topics crawled: {len(documents)}")
            logger.info(f"  Total posts: {total_posts}")
            logger.info(f"  Total views: {total_views}")
            logger.info(f"  Average posts/topic: {total_posts/len(documents):.1f}")
            
            # Show governance topics
            governance_docs = [d for d in documents if 'governance' in str(d.metadata.get('category_id', '')).lower() or 'governance' in d.title.lower()]
            if governance_docs:
                logger.info(f"\n🏛️ Governance topics found: {len(governance_docs)}")
                for doc in governance_docs[:5]:
                    logger.info(f"  - {doc.title[:70]}...")
            
            # Show tokenomics topics
            token_docs = [d for d in documents if 'token' in d.title.lower() or 'regen' in d.title.lower()]
            if token_docs:
                logger.info(f"\n💰 Tokenomics topics found: {len(token_docs)}")
                for doc in token_docs[:5]:
                    logger.info(f"  - {doc.title[:70]}...")
            
            logger.info("\n✅ Data saved to: indexing/storage/forum_json/")
            logger.info("Next steps:")
            logger.info("  1. Process documents with embeddings:")
            logger.info("     python indexing/scripts/generate_embeddings.py")
            logger.info("  2. Or run full indexing pipeline:")
            logger.info("     python indexing/scripts/run_full_index.py")
        else:
            logger.error("❌ No documents were crawled")


if __name__ == "__main__":
    asyncio.run(main())