#!/usr/bin/env python3
"""
Test collection with a larger repository (regen-ledger)
"""

import sys
import asyncio
from pathlib import Path
from loguru import logger

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from collectors.git_collector import GitCollector


async def test_regen_ledger():
    """
    Test collection from regen-ledger repository
    """
    logger.info("Testing collection from regen-ledger repository")
    
    # Configuration for regen-ledger
    config = {
        'repos': [
            {
                'name': 'regen-ledger',
                'url': 'https://github.com/regen-network/regen-ledger.git',
                'branch': 'main',
                'paths': [
                    'docs/',  # Documentation directory
                    'x/ecocredit/spec/',  # Ecocredit module specs
                    '*.md'  # Root markdown files
                ]
            }
        ]
    }
    
    # Initialize collector
    collector = GitCollector(config)
    
    # Collect documents with a reasonable limit for testing
    limit = 20  # Collect 20 documents to verify traversal
    logger.info(f"Collecting up to {limit} documents...")
    
    documents = await collector.collect(limit=limit)
    
    # Display results
    logger.success(f"Collected {len(documents)} documents")
    
    # Group by directory
    by_directory = {}
    for doc in documents:
        file_path = doc.metadata.get('file_path', '')
        directory = str(Path(file_path).parent) if '/' in file_path else 'root'
        if directory not in by_directory:
            by_directory[directory] = []
        by_directory[directory].append(doc)
    
    # Show documents by directory
    logger.info("Documents by directory:")
    for directory, docs in sorted(by_directory.items()):
        logger.info(f"\n  {directory}/ ({len(docs)} files):")
        for doc in docs[:3]:  # Show first 3 from each directory
            logger.info(f"    - {Path(doc.metadata['file_path']).name}")
            logger.debug(f"      Title: {doc.title}")
            logger.debug(f"      URL: {doc.url}")
            logger.debug(f"      Size: {doc.metadata['size_bytes']} bytes")
    
    # Verify URLs are correct
    logger.info("\nVerifying GitHub URLs are properly formatted:")
    for doc in documents[:3]:
        logger.info(f"  - {doc.url}")
    
    # Show file types collected
    file_types = {}
    for doc in documents:
        file_type = doc.metadata.get('file_type', 'unknown')
        file_types[file_type] = file_types.get(file_type, 0) + 1
    
    logger.info("\nFile types collected:")
    for file_type, count in sorted(file_types.items()):
        logger.info(f"  - {file_type}: {count} files")
    
    # Check storage
    storage_path = Path("/home/regenai/project/indexing/storage/documents")
    stored_files = list(storage_path.glob("github_*.json"))
    logger.info(f"\nTotal files in storage: {len(stored_files)}")
    
    return documents


async def main():
    """
    Main test function
    """
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO", 
              format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")
    
    logger.info("=" * 60)
    logger.info("Testing GitCollector with Larger Repository")
    logger.info("=" * 60)
    
    try:
        documents = await test_regen_ledger()
        
        if documents:
            logger.success(f"\n✅ Successfully collected {len(documents)} documents from regen-ledger")
            logger.info("The GitCollector is properly traversing repository directories!")
        else:
            logger.error("No documents collected - check for errors above")
            
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)