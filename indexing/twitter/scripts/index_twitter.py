#!/usr/bin/env python3
"""
Full Twitter indexing script
Collects all tweets from configured accounts and integrates with main indexing system
"""

import asyncio
import sys
from pathlib import Path
import yaml
import json
from datetime import datetime
from loguru import logger
import argparse

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent.parent))

from twitter.collectors.twitter_collector import TwitterCollector
from processors.document_processor import DocumentProcessor
from processors.embedder import Embedder
from twitter.utils.auth_manager import TwitterAuthManager


def setup_logging():
    """Setup logging configuration"""
    log_dir = Path(__file__).parent.parent.parent / 'logs'
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / f"twitter_index_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logger.add(
        log_file,
        rotation="100 MB",
        retention="30 days",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
    )
    
    return log_file


def load_config():
    """Load Twitter configuration"""
    config_path = Path(__file__).parent.parent / 'config' / 'twitter_sources.yaml'
    
    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        return None
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    return config


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Index Twitter/X content')
    
    parser.add_argument(
        '--test',
        action='store_true',
        help='Run in test mode with limited tweets'
    )
    
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Maximum number of tweets to collect'
    )
    
    parser.add_argument(
        '--no-embeddings',
        action='store_true',
        help='Skip embedding generation'
    )
    
    parser.add_argument(
        '--incremental',
        action='store_true',
        help='Only collect new tweets since last run'
    )
    
    parser.add_argument(
        '--username',
        type=str,
        default=None,
        help='Specific username to collect (overrides config)'
    )
    
    return parser.parse_args()


async def collect_tweets(config, args):
    """Collect tweets from configured accounts"""
    print("\n" + "="*60)
    print("Phase 1: Tweet Collection")
    print("="*60)
    
    # Check authentication
    auth_manager = TwitterAuthManager()
    account = auth_manager.get_best_account()
    
    if not account:
        print("✗ No authentication configured")
        print("Run: python setup_twitter_auth.py")
        return []
    
    print(f"✓ Using account: @{account['username']}")
    
    # Override config if username specified
    if args.username:
        config['twitter']['accounts'] = [{
            'username': args.username,
            'include_replies': True,
            'include_retweets': True
        }]
        print(f"✓ Overriding to collect only @{args.username}")
    
    # Set limit based on arguments
    if args.test:
        limit = 50
        print("✓ Test mode: Limited to 50 tweets")
    elif args.limit:
        limit = args.limit
        print(f"✓ Limited to {limit} tweets")
    else:
        limit = None
        print("✓ Collecting all available tweets")
    
    # Create collector
    collector = TwitterCollector(config)
    
    # Collect tweets
    start_time = datetime.now()
    documents = await collector.collect(limit=limit)
    elapsed = (datetime.now() - start_time).total_seconds()
    
    print(f"\n✓ Collected {len(documents)} tweets in {elapsed:.1f} seconds")
    
    if documents:
        # Show statistics
        usernames = set(doc.metadata.get('username') for doc in documents)
        print(f"  Accounts: {', '.join('@' + u for u in usernames)}")
        
        # Date range
        dates = [doc.last_modified for doc in documents if doc.last_modified]
        if dates:
            print(f"  Date range: {min(dates).date()} to {max(dates).date()}")
        
        # Engagement stats
        total_likes = sum(doc.metadata.get('likes', 0) for doc in documents)
        total_retweets = sum(doc.metadata.get('retweets', 0) for doc in documents)
        print(f"  Total engagement: {total_likes:,} likes, {total_retweets:,} retweets")
    
    return documents


def process_documents(documents):
    """Process documents into chunks"""
    print("\n" + "="*60)
    print("Phase 2: Document Processing")
    print("="*60)
    
    if not documents:
        print("No documents to process")
        return []
    
    processor = DocumentProcessor()
    all_chunks = []
    
    print(f"Processing {len(documents)} documents...")
    
    for doc in documents:
        try:
            # Process document into chunks
            chunks = processor.process_document(doc)
            all_chunks.extend(chunks)
        except Exception as e:
            logger.error(f"Error processing document {doc.id}: {e}")
            continue
    
    print(f"✓ Created {len(all_chunks)} chunks from {len(documents)} documents")
    
    # Save chunks
    chunks_dir = Path(__file__).parent.parent.parent / 'storage' / 'chunks'
    chunks_dir.mkdir(parents=True, exist_ok=True)
    
    for chunk in all_chunks:
        chunk_file = chunks_dir / f"twitter_{chunk['id']}.json"
        with open(chunk_file, 'w') as f:
            json.dump(chunk, f, indent=2, default=str)
    
    print(f"✓ Saved chunks to {chunks_dir}")
    
    return all_chunks


def generate_embeddings(chunks):
    """Generate embeddings for chunks"""
    print("\n" + "="*60)
    print("Phase 3: Embedding Generation")
    print("="*60)
    
    if not chunks:
        print("No chunks to embed")
        return
    
    embedder = Embedder()
    
    print(f"Generating embeddings for {len(chunks)} chunks...")
    
    # Generate embeddings in batches
    batch_size = 32
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i+batch_size]
        batch_texts = [chunk['content'] for chunk in batch]
        
        try:
            embeddings = embedder.embed_batch(batch_texts)
            
            # Save embeddings
            for chunk, embedding in zip(batch, embeddings):
                embedder.save_embedding(chunk['id'], embedding)
            
            print(f"  Processed batch {i//batch_size + 1}/{(len(chunks) + batch_size - 1)//batch_size}")
            
        except Exception as e:
            logger.error(f"Error generating embeddings for batch: {e}")
            continue
    
    print(f"✓ Generated embeddings for {len(chunks)} chunks")


def update_manifest(documents, chunks):
    """Update the index manifest with Twitter data"""
    print("\n" + "="*60)
    print("Updating Index Manifest")
    print("="*60)
    
    manifest_path = Path(__file__).parent.parent.parent / 'storage' / 'twitter_manifest.json'
    
    # Load existing manifest or create new
    if manifest_path.exists():
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
    else:
        manifest = {
            'created_at': datetime.now().isoformat(),
            'sources': {},
            'statistics': {}
        }
    
    # Update Twitter source info
    manifest['sources']['twitter'] = {
        'last_indexed': datetime.now().isoformat(),
        'document_count': len(documents),
        'chunk_count': len(chunks),
        'accounts': list(set(doc.metadata.get('username') for doc in documents))
    }
    
    # Update statistics
    manifest['statistics']['twitter'] = {
        'total_tweets': len(documents),
        'total_chunks': len(chunks),
        'total_likes': sum(doc.metadata.get('likes', 0) for doc in documents),
        'total_retweets': sum(doc.metadata.get('retweets', 0) for doc in documents),
        'date_range': {
            'start': min(doc.last_modified for doc in documents if doc.last_modified).isoformat() if documents else None,
            'end': max(doc.last_modified for doc in documents if doc.last_modified).isoformat() if documents else None
        }
    }
    
    # Save manifest
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    
    print(f"✓ Updated manifest: {manifest_path}")


async def main():
    """Main indexing pipeline"""
    args = parse_arguments()
    
    # Setup logging
    log_file = setup_logging()
    
    print("\n" + "="*60)
    print("Twitter/X Indexing Pipeline")
    print("="*60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Log file: {log_file}")
    
    # Load configuration
    config = load_config()
    if not config:
        print("✗ Failed to load configuration")
        return 1
    
    try:
        # Phase 1: Collect tweets
        documents = await collect_tweets(config, args)
        
        if not documents:
            print("\n⚠️  No tweets collected. Check authentication and configuration.")
            return 1
        
        # Phase 2: Process documents
        chunks = process_documents(documents)
        
        # Phase 3: Generate embeddings (unless skipped)
        if not args.no_embeddings:
            generate_embeddings(chunks)
        else:
            print("\n⚠️  Skipping embedding generation (--no-embeddings flag)")
        
        # Update manifest
        update_manifest(documents, chunks)
        
        # Final summary
        print("\n" + "="*60)
        print("Indexing Complete")
        print("="*60)
        print(f"✓ Indexed {len(documents)} tweets")
        print(f"✓ Created {len(chunks)} searchable chunks")
        print(f"✓ Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Indexing failed: {e}", exc_info=True)
        print(f"\n✗ Indexing failed: {e}")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nIndexing interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"\n✗ Fatal error: {e}")
        sys.exit(1)