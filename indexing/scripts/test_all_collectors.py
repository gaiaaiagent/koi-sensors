#!/usr/bin/env python3
"""
Test all collectors together with sample data from each source
"""

import sys
import asyncio
from pathlib import Path
from loguru import logger
import yaml

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from collectors import GitCollector, DiscourseCollector, WebScraper


async def test_github():
    """Test GitHub collection"""
    logger.info("Testing GitHub collector...")
    
    config = {
        'repos': [
            {
                'name': 'mcp',
                'url': 'https://github.com/regen-network/mcp.git',
                'branch': 'main',
                'paths': ['README.md', 'docs/']
            }
        ]
    }
    
    collector = GitCollector(config)
    docs = await collector.collect(limit=3)
    logger.success(f"GitHub: Collected {len(docs)} documents")
    
    for doc in docs:
        logger.info(f"  - {doc.title[:60]}...")
    
    return docs


async def test_discourse():
    """Test Discourse forum collection"""
    logger.info("Testing Discourse collector...")
    
    config = {
        'forums': [
            {
                'name': 'regen-forum',
                'url': 'https://forum.regen.network',
                'categories': ['all']  # Will use anonymous access
            }
        ]
    }
    
    async with DiscourseCollector(config) as collector:
        docs = await collector.collect(limit=3)
        logger.success(f"Discourse: Collected {len(docs)} documents")
        
        for doc in docs:
            logger.info(f"  - {doc.title[:60]}...")
        
        return docs


async def test_web_scraper():
    """Test web scraper collection"""
    logger.info("Testing Web scraper...")
    
    config = {
        'websites': [
            {
                'name': 'docs-regen',
                'url': 'https://docs.regen.network',
                'max_depth': 1,  # Shallow crawl for testing
                'paths': ['/']
            }
        ]
    }
    
    async with WebScraper(config) as scraper:
        docs = await scraper.collect(limit=3)
        logger.success(f"Web: Collected {len(docs)} documents")
        
        for doc in docs:
            logger.info(f"  - {doc.title[:60]}...")
        
        return docs


async def test_all_sources():
    """Test collection from all configured sources in sources.yaml"""
    logger.info("Testing collection from sources.yaml configuration...")
    
    # Load configuration
    config_path = Path(__file__).parent.parent / "config" / "sources.yaml"
    
    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        return []
    
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    all_documents = []
    
    # Test GitHub
    if 'github' in config['sources']:
        logger.info("\n📦 Testing GitHub sources...")
        github_repos = config['sources']['github'][:1]  # Just test first repo
        github_config = {'repos': github_repos}
        
        collector = GitCollector(github_config)
        docs = await collector.collect(limit=2)
        all_documents.extend(docs)
        logger.info(f"  Collected {len(docs)} GitHub documents")
    
    # Test Discourse
    if 'discourse' in config['sources']:
        logger.info("\n💬 Testing Discourse forums...")
        forums = config['sources']['discourse'][:1]  # Just test first forum
        discourse_config = {'forums': forums}
        
        async with DiscourseCollector(discourse_config) as collector:
            docs = await collector.collect(limit=2)
            all_documents.extend(docs)
            logger.info(f"  Collected {len(docs)} forum posts")
    
    # Test Websites
    if 'websites' in config['sources']:
        logger.info("\n🌐 Testing website scraping...")
        websites = config['sources']['websites'][:1]  # Just test first website
        web_config = {'websites': websites}
        
        async with WebScraper(web_config) as scraper:
            docs = await scraper.collect(limit=2)
            all_documents.extend(docs)
            logger.info(f"  Collected {len(docs)} web pages")
    
    return all_documents


async def main():
    """Main test function"""
    
    # Configure logging
    logger.remove()
    logger.add(
        sys.stderr, 
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )
    
    logger.info("=" * 60)
    logger.info("Testing All Collectors")
    logger.info("=" * 60)
    
    all_docs = []
    
    try:
        # Test individual collectors
        logger.info("\n🧪 Testing individual collectors...")
        
        github_docs = await test_github()
        all_docs.extend(github_docs)
        
        discourse_docs = await test_discourse()
        all_docs.extend(discourse_docs)
        
        web_docs = await test_web_scraper()
        all_docs.extend(web_docs)
        
        # Test with actual configuration
        logger.info("\n📋 Testing with sources.yaml configuration...")
        config_docs = await test_all_sources()
        all_docs.extend(config_docs)
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.success(f"✅ All collectors tested successfully!")
        logger.info(f"Total documents collected: {len(all_docs)}")
        
        # Group by source type
        by_source = {}
        for doc in all_docs:
            source_type = doc.source_type
            by_source[source_type] = by_source.get(source_type, 0) + 1
        
        logger.info("\nDocuments by source type:")
        for source_type, count in by_source.items():
            logger.info(f"  - {source_type}: {count}")
        
        # Check storage
        storage_path = Path("/home/regenai/project/indexing/storage/documents")
        stored_files = list(storage_path.glob("*.json"))
        logger.info(f"\nTotal files in storage: {len(stored_files)}")
        
        # Show sample URLs
        logger.info("\nSample document URLs:")
        for doc in all_docs[:5]:
            logger.info(f"  - {doc.url}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)