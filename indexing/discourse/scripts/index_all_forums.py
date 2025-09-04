#!/usr/bin/env python3
"""
Index ALL forum.regen.network topics
Full collection and processing pipeline
"""

import asyncio
from pathlib import Path
import sys
import json
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from discourse.scripts.crawl_forum_json import ForumJSONCrawler
from loguru import logger


async def crawl_all_forums():
    """Crawl all forum topics"""
    
    logger.info("=" * 70)
    logger.info("FULL FORUM.REGEN.NETWORK INDEXING")
    logger.info("=" * 70)
    
    logger.info("\n📋 This will:")
    logger.info("  1. Crawl ALL available topics from forum.regen.network")
    logger.info("  2. Include all categories (governance, tokenomics, registry, etc.)")
    logger.info("  3. Save to discourse/storage/ for processing")
    logger.info("\n⚠️  This may take 10-20 minutes depending on forum size")
    
    # Set high limit to get all topics
    TOPIC_LIMIT = 500  # Practical limit for all topics
    
    logger.info(f"\n🎯 Target: Up to {TOPIC_LIMIT} topics")
    
    async with ForumJSONCrawler() as crawler:
        # Get all topics
        documents = await crawler.crawl(limit=TOPIC_LIMIT, include_categories=True)
        
        if documents:
            # Calculate statistics
            total_posts = sum(doc.metadata.get('posts_count', 0) for doc in documents)
            total_views = sum(doc.metadata.get('views', 0) for doc in documents)
            total_content = sum(len(doc.content) for doc in documents)
            
            logger.success(f"\n✅ Successfully indexed {len(documents)} forum topics!")
            
            logger.info("\n📊 Final Statistics:")
            logger.info(f"  Topics indexed: {len(documents)}")
            logger.info(f"  Total posts: {total_posts:,}")
            logger.info(f"  Total views: {total_views:,}")
            logger.info(f"  Total content: {total_content:,} bytes ({total_content/1024/1024:.1f} MB)")
            logger.info(f"  Average posts/topic: {total_posts/len(documents):.1f}")
            logger.info(f"  Average content/topic: {total_content/len(documents):,.0f} bytes")
            
            # Categorize topics
            categories = {}
            for doc in documents:
                cat_id = doc.metadata.get('category_id', 'uncategorized')
                if cat_id not in categories:
                    categories[cat_id] = []
                categories[cat_id].append(doc)
            
            logger.info(f"\n📁 Topics by Category:")
            for cat_id, cat_docs in sorted(categories.items(), key=lambda x: len(x[1]), reverse=True):
                logger.info(f"  Category {cat_id}: {len(cat_docs)} topics")
            
            # Identify important topics
            governance_docs = [d for d in documents if 'governance' in d.title.lower() or 'proposal' in d.title.lower()]
            token_docs = [d for d in documents if 'token' in d.title.lower() or '$regen' in d.title.lower()]
            registry_docs = [d for d in documents if 'registry' in d.title.lower() or 'credit' in d.title.lower()]
            
            logger.info("\n🎯 Key Topics Found:")
            logger.info(f"  Governance/Proposals: {len(governance_docs)}")
            logger.info(f"  Tokenomics: {len(token_docs)}")
            logger.info(f"  Registry/Credits: {len(registry_docs)}")
            
            if governance_docs:
                logger.info("\n🏛️ Sample Governance Topics:")
                for doc in governance_docs[:5]:
                    logger.info(f"  - {doc.title[:80]}...")
            
            # Save summary
            summary_file = Path(__file__).parent.parent / "storage" / "indexing_summary.json"
            summary = {
                'timestamp': datetime.now().isoformat(),
                'source': 'forum.regen.network',
                'total_topics': len(documents),
                'total_posts': total_posts,
                'total_views': total_views,
                'total_content_bytes': total_content,
                'categories': {cat: len(docs) for cat, docs in categories.items()},
                'governance_topics': len(governance_docs),
                'token_topics': len(token_docs),
                'registry_topics': len(registry_docs),
                'sample_topics': [
                    {
                        'title': doc.title,
                        'url': doc.url,
                        'posts': doc.metadata.get('posts_count', 0),
                        'views': doc.metadata.get('views', 0)
                    }
                    for doc in documents[:10]
                ]
            }
            
            with open(summary_file, 'w') as f:
                json.dump(summary, f, indent=2)
            
            logger.success(f"\n✅ Indexing complete!")
            logger.info(f"📄 Summary saved to: {summary_file}")
            logger.info(f"📁 Full data in: discourse/storage/")
            
            logger.info("\n🚀 Next Steps:")
            logger.info("  1. Generate embeddings:")
            logger.info("     python indexing/scripts/generate_embeddings.py")
            logger.info("  2. Build knowledge graph:")
            logger.info("     python indexing/scripts/build_knowledge_graph.py")
            logger.info("  3. Or run full pipeline:")
            logger.info("     python indexing/scripts/run_full_index.py")
            
            return documents
        else:
            logger.error("❌ No documents were indexed")
            return []


async def main():
    """Main entry point"""
    documents = await crawl_all_forums()
    
    if documents:
        logger.success(f"\n🎉 Successfully indexed {len(documents)} forum topics!")
        logger.info("Forum indexing complete. Ready for embedding generation.")
    else:
        logger.error("\n❌ Forum indexing failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())