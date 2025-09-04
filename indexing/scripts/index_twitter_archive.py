#!/usr/bin/env python3
"""
Index Twitter Archive into Regen Network Knowledge Base
Processes the full Twitter archive and generates embeddings
"""

import asyncio
import json
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from indexing.collectors.twitter_collector import TwitterCollector
from indexing.processors.document_processor import DocumentProcessor
from indexing.processors.embedder import Embedder
from loguru import logger
import time


async def main():
    """Index full Twitter archive"""
    
    # Configuration
    archive_path = "/home/regenai/project/indexing/storage/TwitterData"
    output_dir = Path("indexing/storage/documents/twitter")
    embeddings_dir = Path("indexing/storage/embeddings/twitter")
    
    # Create output directories
    output_dir.mkdir(parents=True, exist_ok=True)
    embeddings_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("Starting Twitter archive indexing...")
    start_time = time.time()
    
    # Initialize components
    collector = TwitterCollector(archive_path)
    processor = DocumentProcessor(chunk_size=1000, chunk_overlap=200)
    embedder = Embedder()
    
    # Get statistics first
    stats = collector.get_stats()
    logger.info(f"Archive contains {stats['total_tweets']:,} total tweets")
    logger.info(f"Will index all {stats['total_tweets']:,} tweets (including retweets)")
    
    # Collect all tweets INCLUDING retweets
    logger.info("Collecting tweets from archive...")
    documents = await collector.collect(
        include_replies=True,
        include_retweets=True  # Now including retweets for comprehensive coverage
    )
    
    logger.info(f"Collected {len(documents):,} tweets for indexing")
    
    # Save raw documents
    docs_file = output_dir / "twitter_documents.json"
    with open(docs_file, 'w') as f:
        json.dump(documents, f, indent=2)
    logger.info(f"Saved raw documents to {docs_file}")
    
    # Process documents into chunks
    logger.info("Processing documents into chunks...")
    all_chunks = []
    
    for i, doc in enumerate(documents):
        # Create a combined text for chunking
        text = doc['content']
        
        # Add metadata as context
        if doc['metadata'].get('hashtags'):
            text += f"\n\nHashtags: {', '.join(doc['metadata']['hashtags'])}"
        if doc['metadata'].get('urls'):
            text += f"\n\nLinks: {', '.join(doc['metadata']['urls'][:3])}"
        
        # Process into chunks
        chunks = processor.chunk_text(
            text=text,
            doc_id=doc['id'],
            metadata={
                'source': 'twitter',
                'tweet_id': doc['source_id'],
                'date': doc['created_at'],
                'type': doc['metadata']['type'],
                'author': doc['author'],
                'url': doc['url'],
                'koi_rid': doc['koi_rid']
            }
        )
        
        all_chunks.extend(chunks)
        
        if (i + 1) % 1000 == 0:
            logger.info(f"Processed {i + 1:,}/{len(documents):,} tweets into {len(all_chunks):,} chunks")
    
    logger.info(f"Created {len(all_chunks):,} chunks from {len(documents):,} tweets")
    
    # Save chunks
    chunks_file = output_dir / "twitter_chunks.json"
    with open(chunks_file, 'w') as f:
        json.dump(all_chunks, f, indent=2)
    logger.info(f"Saved chunks to {chunks_file}")
    
    # Generate embeddings
    logger.info("Generating embeddings for chunks...")
    chunk_texts = [chunk['text'] for chunk in all_chunks]
    
    # Process in batches to avoid memory issues
    batch_size = 100
    all_embeddings = []
    
    for i in range(0, len(chunk_texts), batch_size):
        batch = chunk_texts[i:i + batch_size]
        batch_embeddings = embedder.embed_batch(batch)
        all_embeddings.extend(batch_embeddings)
        
        if (i + batch_size) % 1000 == 0:
            logger.info(f"Generated embeddings for {min(i + batch_size, len(chunk_texts)):,}/{len(chunk_texts):,} chunks")
    
    # Save embeddings
    embeddings_file = embeddings_dir / "twitter_embeddings.npy"
    embedder.save_embeddings(all_embeddings, embeddings_file)
    logger.info(f"Saved embeddings to {embeddings_file}")
    
    # Create metadata index
    metadata = {
        'total_documents': len(documents),
        'total_chunks': len(all_chunks),
        'date_range': {
            'start': stats['date_range']['start'],
            'end': stats['date_range']['end']
        },
        'document_types': {
            'original_tweets': stats['original_tweets'],
            'replies': stats['replies']
        },
        'embedding_model': embedder.model_name,
        'chunk_size': processor.chunk_size,
        'chunk_overlap': processor.chunk_overlap,
        'indexed_at': time.strftime('%Y-%m-%d %H:%M:%S')
    }
    
    metadata_file = output_dir / "twitter_metadata.json"
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    # Report completion
    elapsed = time.time() - start_time
    logger.info(f"\n{'='*50}")
    logger.info(f"Twitter Archive Indexing Complete!")
    logger.info(f"{'='*50}")
    logger.info(f"Documents indexed: {len(documents):,}")
    logger.info(f"Chunks created: {len(all_chunks):,}")
    logger.info(f"Embeddings generated: {len(all_embeddings):,}")
    logger.info(f"Time elapsed: {elapsed:.1f} seconds")
    logger.info(f"Processing rate: {len(documents) / elapsed:.1f} tweets/second")
    logger.info(f"\nOutput files:")
    logger.info(f"  - Documents: {docs_file}")
    logger.info(f"  - Chunks: {chunks_file}")
    logger.info(f"  - Embeddings: {embeddings_file}")
    logger.info(f"  - Metadata: {metadata_file}")


if __name__ == "__main__":
    asyncio.run(main())