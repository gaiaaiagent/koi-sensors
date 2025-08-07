#!/usr/bin/env python3
"""
Test collection script - collect a small sample of documents to verify setup
"""

import sys
import asyncio
from pathlib import Path
import argparse
import yaml
from loguru import logger

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from collectors.git_collector import GitCollector
from utils.credential_manager import get_credential_manager


async def test_github_collection(limit: int = 5):
    """
    Test GitHub repository collection
    
    Args:
        limit: Number of documents to collect
    """
    logger.info(f"Testing GitHub collection (limit: {limit} documents)")
    
    # Create test configuration for just one small repo
    test_config = {
        'repos': [
            {
                'name': 'mcp',
                'url': 'https://github.com/regen-network/mcp.git',
                'branch': 'main',
                'paths': ['README.md', 'docs/']
            }
        ]
    }
    
    # Initialize collector
    collector = GitCollector(test_config)
    
    # Collect documents
    documents = await collector.collect(limit=limit)
    
    # Display results
    logger.success(f"Collected {len(documents)} documents")
    for doc in documents:
        logger.info(f"  - {doc.title} ({doc.source})")
        logger.debug(f"    URL: {doc.url}")
        logger.debug(f"    Size: {len(doc.content)} bytes")
        logger.debug(f"    Tags: {', '.join(doc.tags)}")
    
    # Show storage location
    storage_path = Path("/home/regenai/project/indexing/storage/documents")
    stored_files = list(storage_path.glob("github_*.json"))
    logger.info(f"Documents stored in: {storage_path}")
    logger.info(f"Total files in storage: {len(stored_files)}")
    
    return documents


async def test_full_collection(limit: int = 5):
    """
    Test collection from all configured sources
    
    Args:
        limit: Number of documents to collect
    """
    logger.info(f"Testing full collection (limit: {limit} documents)")
    
    # Load configuration
    config_path = Path(__file__).parent.parent / "config" / "sources.yaml"
    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        return []
    
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    all_documents = []
    
    # Test GitHub sources
    if 'github' in config['sources']:
        logger.info("Testing GitHub sources...")
        github_config = {'repos': config['sources']['github'][:2]}  # Test first 2 repos
        collector = GitCollector(github_config)
        docs = await collector.collect(limit=limit)
        all_documents.extend(docs)
    
    # Show summary
    logger.success(f"Total documents collected: {len(all_documents)}")
    
    # Group by source
    sources = {}
    for doc in all_documents:
        sources[doc.source] = sources.get(doc.source, 0) + 1
    
    logger.info("Documents by source:")
    for source, count in sources.items():
        logger.info(f"  - {source}: {count}")
    
    return all_documents


def verify_environment():
    """
    Verify the environment is properly set up
    """
    logger.info("Verifying environment setup...")
    
    # Check Python version
    import sys
    python_version = sys.version_info
    if python_version.major < 3 or python_version.minor < 11:
        logger.warning(f"Python {python_version.major}.{python_version.minor} detected. Python 3.11+ recommended")
    else:
        logger.success(f"✓ Python {python_version.major}.{python_version.minor} OK")
    
    # Check required directories
    dirs_to_check = [
        Path("/home/regenai/project/indexing/collectors"),
        Path("/home/regenai/project/indexing/processors"),
        Path("/home/regenai/project/indexing/storage/documents"),
        Path("/home/regenai/project/indexing/cache"),
        Path("/home/regenai/project/mcp-server")
    ]
    
    for dir_path in dirs_to_check:
        if dir_path.exists():
            logger.success(f"✓ {dir_path.name} directory exists")
        else:
            logger.error(f"✗ {dir_path} not found")
    
    # Check credentials
    logger.info("Checking credentials...")
    cred_manager = get_credential_manager()
    credentials = cred_manager.list_credentials()
    
    has_any_creds = False
    for key, available in credentials.items():
        if available:
            logger.success(f"✓ {key} configured")
            has_any_creds = True
        else:
            logger.debug(f"  {key} not configured (optional)")
    
    if not has_any_creds:
        logger.info("No API credentials configured - will use anonymous access")
    
    # Check MCP server
    import httpx
    try:
        response = httpx.get("http://localhost:3000/health", timeout=2)
        if response.status_code == 200:
            logger.success("✓ MCP server is running")
        else:
            logger.warning("MCP server responded but may not be healthy")
    except:
        logger.warning("MCP server not accessible (optional for testing)")
    
    # Check required Python packages
    required_packages = [
        'aiohttp', 'httpx', 'yaml', 'git', 'bs4', 
        'sentence_transformers', 'chromadb', 'loguru'
    ]
    
    missing_packages = []
    for package in required_packages:
        try:
            __import__(package)
            logger.success(f"✓ {package} installed")
        except ImportError:
            logger.error(f"✗ {package} not installed")
            missing_packages.append(package)
    
    if missing_packages:
        logger.error(f"Missing packages: {', '.join(missing_packages)}")
        logger.info("Run: pip install -r indexing/requirements.txt")
        return False
    
    logger.success("Environment verification complete!")
    return True


async def main():
    """
    Main test function
    """
    parser = argparse.ArgumentParser(description='Test document collection')
    parser.add_argument('--limit', type=int, default=5, help='Number of documents to collect')
    parser.add_argument('--source', choices=['github', 'all'], default='github', 
                      help='Which sources to test')
    parser.add_argument('--verify-only', action='store_true', 
                      help='Only verify environment, don\'t collect')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = "DEBUG" if args.verbose else "INFO"
    logger.remove()
    logger.add(sys.stderr, level=log_level, 
              format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")
    
    # Add file logging
    log_file = Path("/home/regenai/project/indexing/logs/test_collection.log")
    log_file.parent.mkdir(exist_ok=True)
    logger.add(log_file, rotation="10 MB", level="DEBUG")
    
    logger.info("=" * 60)
    logger.info("Regen Network Indexing System - Test Collection")
    logger.info("=" * 60)
    
    # Verify environment
    if not verify_environment():
        if not args.verify_only:
            logger.error("Environment verification failed. Fix issues before collecting.")
            return 1
    
    if args.verify_only:
        return 0
    
    # Run collection test
    try:
        if args.source == 'github':
            documents = await test_github_collection(limit=args.limit)
        else:
            documents = await test_full_collection(limit=args.limit)
        
        if documents:
            logger.success(f"\n✅ Test collection successful! Collected {len(documents)} documents")
            logger.info("You can now run full indexing with: python indexing/scripts/run_full_index.py")
        else:
            logger.warning("No documents collected. Check the logs for errors.")
            
    except Exception as e:
        logger.error(f"Test collection failed: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)