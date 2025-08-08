#!/usr/bin/env python3
"""
Index ALL Discourse forums (both Regen Network and RegenCommons)
Complete collection of all forum data
"""

import asyncio
from pathlib import Path
import sys
import json
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from discourse.scripts.crawl_forum_json import ForumJSONCrawler
from discourse.scripts.crawl_regencommons import RegenCommonsForumCrawler
from loguru import logger


async def index_all_discourse_forums():
    """Index all discourse forums"""
    
    logger.info("=" * 70)
    logger.info("COMPLETE DISCOURSE FORUM INDEXING")
    logger.info("=" * 70)
    
    logger.info("\n📋 This will index:")
    logger.info("  1. forum.regen.network (main forum)")
    logger.info("  2. regencommons.discourse.group (commons forum)")
    logger.info("\n⏱️  Estimated time: 2-3 minutes")
    
    all_documents = []
    stats = {
        'total_topics': 0,
        'total_posts': 0,
        'total_views': 0,
        'total_content_bytes': 0,
        'forums': {}
    }
    
    # 1. Index forum.regen.network
    logger.info("\n" + "=" * 50)
    logger.info("1️⃣ Indexing forum.regen.network...")
    logger.info("=" * 50)
    
    async with ForumJSONCrawler() as crawler:
        regen_docs = await crawler.crawl(limit=500, include_categories=True)
        
        if regen_docs:
            all_documents.extend(regen_docs)
            
            # Calculate stats
            posts = sum(doc.metadata.get('posts_count', 0) for doc in regen_docs)
            views = sum(doc.metadata.get('views', 0) for doc in regen_docs)
            content = sum(len(doc.content) for doc in regen_docs)
            
            stats['forums']['forum.regen.network'] = {
                'topics': len(regen_docs),
                'posts': posts,
                'views': views,
                'content_bytes': content
            }
            stats['total_topics'] += len(regen_docs)
            stats['total_posts'] += posts
            stats['total_views'] += views
            stats['total_content_bytes'] += content
            
            logger.success(f"✅ Indexed {len(regen_docs)} topics from forum.regen.network")
    
    # 2. Index regencommons.discourse.group
    logger.info("\n" + "=" * 50)
    logger.info("2️⃣ Indexing regencommons.discourse.group...")
    logger.info("=" * 50)
    
    async with RegenCommonsForumCrawler() as crawler:
        commons_docs = await crawler.crawl(limit=100)
        
        if commons_docs:
            all_documents.extend(commons_docs)
            
            # Calculate stats
            posts = sum(doc.metadata.get('posts_count', 0) for doc in commons_docs)
            views = sum(doc.metadata.get('views', 0) for doc in commons_docs)
            content = sum(len(doc.content) for doc in commons_docs)
            
            stats['forums']['regencommons.discourse.group'] = {
                'topics': len(commons_docs),
                'posts': posts,
                'views': views,
                'content_bytes': content
            }
            stats['total_topics'] += len(commons_docs)
            stats['total_posts'] += posts
            stats['total_views'] += views
            stats['total_content_bytes'] += content
            
            logger.success(f"✅ Indexed {len(commons_docs)} topics from regencommons.discourse.group")
    
    # Save combined summary
    logger.info("\n" + "=" * 70)
    logger.info("📊 FINAL STATISTICS")
    logger.info("=" * 70)
    
    logger.info(f"\n🎯 Total Results:")
    logger.info(f"  Forums indexed: {len(stats['forums'])}")
    logger.info(f"  Total topics: {stats['total_topics']}")
    logger.info(f"  Total posts: {stats['total_posts']:,}")
    logger.info(f"  Total views: {stats['total_views']:,}")
    logger.info(f"  Total content: {stats['total_content_bytes']:,} bytes ({stats['total_content_bytes']/1024/1024:.1f} MB)")
    
    logger.info(f"\n📁 By Forum:")
    for forum_name, forum_stats in stats['forums'].items():
        logger.info(f"\n  {forum_name}:")
        logger.info(f"    Topics: {forum_stats['topics']}")
        logger.info(f"    Posts: {forum_stats['posts']}")
        logger.info(f"    Views: {forum_stats['views']}")
        logger.info(f"    Content: {forum_stats['content_bytes']:,} bytes")
    
    # Categorize all documents
    governance_docs = [d for d in all_documents if 'governance' in d.title.lower() or 'proposal' in d.title.lower()]
    token_docs = [d for d in all_documents if 'token' in d.title.lower() or '$regen' in d.title.lower()]
    commons_docs = [d for d in all_documents if 'commons' in d.title.lower()]
    
    logger.info(f"\n🏷️ Content Categories:")
    logger.info(f"  Governance/Proposals: {len(governance_docs)}")
    logger.info(f"  Tokenomics: {len(token_docs)}")
    logger.info(f"  Commons Topics: {len(commons_docs)}")
    
    # Save combined summary
    summary_file = Path(__file__).parent.parent / "storage" / "combined_indexing_summary.json"
    summary = {
        'timestamp': datetime.now().isoformat(),
        'sources': list(stats['forums'].keys()),
        'statistics': stats,
        'document_count': len(all_documents),
        'categories': {
            'governance': len(governance_docs),
            'tokenomics': len(token_docs),
            'commons': len(commons_docs)
        },
        'sample_topics': [
            {
                'title': doc.title,
                'source': doc.source,
                'url': doc.url,
                'posts': doc.metadata.get('posts_count', 0)
            }
            for doc in all_documents[:10]
        ]
    }
    
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    logger.success(f"\n✅ INDEXING COMPLETE!")
    logger.info(f"📄 Summary saved to: {summary_file}")
    logger.info(f"📁 Data files in: discourse/storage/")
    
    logger.info("\n🚀 Next Steps:")
    logger.info("  1. Generate embeddings for all discourse data:")
    logger.info("     python indexing/scripts/generate_embeddings.py")
    logger.info("  2. Build knowledge graph:")
    logger.info("     python indexing/scripts/build_knowledge_graph.py")
    logger.info("  3. Run full pipeline:")
    logger.info("     python indexing/scripts/run_full_index.py")
    
    return all_documents


async def main():
    """Main entry point"""
    documents = await index_all_discourse_forums()
    
    if documents:
        logger.success(f"\n🎉 Successfully indexed {len(documents)} total forum topics across all forums!")
    else:
        logger.error("\n❌ Forum indexing failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())