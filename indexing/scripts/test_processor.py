#!/usr/bin/env python3
"""
Test document processor and embedder
"""

import sys
import json
from pathlib import Path
from loguru import logger

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from processors import DocumentProcessor, Embedder
from collectors import Document


def test_document_processor():
    """Test document processing and chunking"""
    logger.info("Testing DocumentProcessor...")
    
    # Create processor
    processor = DocumentProcessor(chunk_size=500, chunk_overlap=50)
    
    # Load a sample document from storage
    storage_path = Path("/home/regenai/project/indexing/storage/documents")
    doc_files = list(storage_path.glob("*.json"))
    
    if not doc_files:
        logger.error("No documents found in storage. Run collectors first.")
        return None
    
    # Load first document
    with open(doc_files[0], 'r') as f:
        doc_data = json.load(f)
    
    logger.info(f"Processing document: {doc_data.get('title', 'Unknown')}")
    
    # Process into chunks
    chunks = processor.process_document(doc_data)
    
    logger.success(f"Created {len(chunks)} chunks")
    
    # Show sample chunks
    for i, chunk in enumerate(chunks[:3]):
        logger.info(f"\nChunk {i+1}:")
        logger.info(f"  ID: {chunk.chunk_id}")
        logger.info(f"  Position: {chunk.position}")
        logger.info(f"  Tokens: ~{chunk.token_count}")
        logger.info(f"  Content preview: {chunk.content[:100]}...")
    
    return chunks


def test_embedder(chunks):
    """Test embedding generation"""
    logger.info("\nTesting Embedder...")
    
    if not chunks:
        logger.warning("No chunks to embed")
        return
    
    # Create embedder
    embedder = Embedder()
    
    # Process and store chunks
    logger.info(f"Processing {len(chunks)} chunks...")
    embedder.process_and_store(chunks[:5])  # Just process first 5 for testing
    
    # Get statistics
    stats = embedder.get_statistics()
    logger.info("\nEmbedder statistics:")
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")
    
    # Test search
    logger.info("\nTesting vector search...")
    query = "carbon credits climate"
    results = embedder.search(query, n_results=3)
    
    logger.info(f"Search results for '{query}':")
    for i, result in enumerate(results):
        logger.info(f"\n  Result {i+1}:")
        logger.info(f"    Chunk ID: {result['chunk_id']}")
        logger.info(f"    Distance: {result.get('distance', 'N/A')}")
        logger.info(f"    Content preview: {result['content'][:100]}...")
    
    return embedder


def test_full_pipeline():
    """Test complete processing pipeline"""
    logger.info("\nTesting full pipeline with multiple documents...")
    
    # Load multiple documents
    storage_path = Path("/home/regenai/project/indexing/storage/documents")
    doc_files = list(storage_path.glob("*.json"))[:5]  # Process first 5 documents
    
    if not doc_files:
        logger.error("No documents found")
        return
    
    processor = DocumentProcessor()
    embedder = Embedder()
    
    all_chunks = []
    
    for doc_file in doc_files:
        with open(doc_file, 'r') as f:
            doc_data = json.load(f)
        
        chunks = processor.process_document(doc_data)
        all_chunks.extend(chunks)
        logger.info(f"Processed {doc_data.get('title', 'Unknown')}: {len(chunks)} chunks")
    
    logger.info(f"\nTotal chunks: {len(all_chunks)}")
    
    # Generate embeddings and store
    embedder.process_and_store(all_chunks)
    
    # Final statistics
    stats = embedder.get_statistics()
    logger.success(f"\n✅ Pipeline complete!")
    logger.info(f"Chunks in vector database: {stats['chunks_in_chromadb']}")
    logger.info(f"Embeddings saved: {stats['embeddings_on_disk']}")


def main():
    """Main test function"""
    
    # Configure logging
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )
    
    logger.info("=" * 60)
    logger.info("Testing Document Processor and Embedder")
    logger.info("=" * 60)
    
    try:
        # Test document processor
        chunks = test_document_processor()
        
        if chunks:
            # Test embedder
            embedder = test_embedder(chunks)
            
            # Test full pipeline
            test_full_pipeline()
            
            logger.success("\n✅ All tests completed successfully!")
        else:
            logger.error("Document processing failed")
            return 1
            
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)