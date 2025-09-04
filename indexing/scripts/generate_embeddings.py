#!/usr/bin/env python3
"""
Phase 2: Embedding generation for previously collected documents
Processes chunks created by run_collection_only.py
"""

import sys
import asyncio
from pathlib import Path
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from loguru import logger
import argparse
from tqdm import tqdm

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from processors import Embedder, DocumentChunk


class EmbeddingGenerator:
    """
    Phase 2: Generate embeddings for previously collected and chunked documents
    """
    
    def __init__(self):
        """Initialize embedding generator"""
        # Check for manifest from collection phase
        self.manifest_path = Path("/home/regenai/project/indexing/storage/index_manifest.json")
        self.chunks_dir = Path("/home/regenai/project/indexing/storage/chunks")
        self.metadata_dir = Path("/home/regenai/project/indexing/storage/metadata")
        
        if not self.manifest_path.exists():
            raise FileNotFoundError(
                "No index manifest found. Please run 'run_collection_only.py' first."
            )
        
        with open(self.manifest_path) as f:
            self.manifest = json.load(f)
        
        # Initialize embedder
        self.embedder = Embedder(
            model_name='sentence-transformers/all-MiniLM-L6-v2'
        )
        
        # Statistics
        self.stats = {
            'start_time': datetime.now(),
            'chunks_processed': 0,
            'embeddings_generated': 0,
            'errors': [],
            'skipped': 0
        }
    
    def load_chunks(self, limit: Optional[int] = None) -> List[DocumentChunk]:
        """
        Load chunks that need embeddings
        
        Args:
            limit: Optional limit on chunks to process
            
        Returns:
            List of DocumentChunk objects
        """
        logger.info("📦 Loading chunks that need embeddings...")
        
        chunks = []
        chunk_files = list(self.chunks_dir.glob("*.json"))
        
        if limit:
            chunk_files = chunk_files[:limit]
        
        for chunk_file in tqdm(chunk_files, desc="Loading chunks"):
            try:
                with open(chunk_file) as f:
                    chunk_data = json.load(f)
                
                # Only process if embedding is needed
                if chunk_data.get('requires_embedding', True):
                    # Recreate DocumentChunk object
                    chunk = DocumentChunk(
                        document_id=chunk_data['document_id'],
                        chunk_id=chunk_data['chunk_id'],
                        content=chunk_data['content'],
                        chunk_index=chunk_data['chunk_index'],
                        total_chunks=chunk_data['total_chunks'],
                        metadata=chunk_data.get('metadata', {}),
                        koi_rid=chunk_data.get('koi_rid')
                    )
                    chunks.append(chunk)
                else:
                    self.stats['skipped'] += 1
                    
            except Exception as e:
                logger.error(f"Failed to load chunk {chunk_file}: {e}")
                self.stats['errors'].append(f"Load error: {chunk_file.name}")
        
        logger.success(f"Loaded {len(chunks)} chunks for embedding generation")
        if self.stats['skipped'] > 0:
            logger.info(f"Skipped {self.stats['skipped']} chunks (already have embeddings)")
        
        return chunks
    
    def generate_embeddings(self, chunks: List[DocumentChunk], batch_size: int = 32):
        """
        Generate embeddings for chunks
        
        Args:
            chunks: List of DocumentChunk objects
            batch_size: Batch size for embedding generation
        """
        logger.info(f"🔢 Generating embeddings for {len(chunks)} chunks...")
        
        # Process and store embeddings
        self.embedder.process_and_store(chunks, batch_size=batch_size)
        
        # Update chunk files to mark embeddings as generated
        for chunk in tqdm(chunks, desc="Updating chunk metadata"):
            chunk_file = self.chunks_dir / f"{chunk.chunk_id}.json"
            if chunk_file.exists():
                with open(chunk_file) as f:
                    chunk_data = json.load(f)
                chunk_data['requires_embedding'] = False
                chunk_data['embedding_generated_at'] = datetime.now().isoformat()
                with open(chunk_file, 'w') as f:
                    json.dump(chunk_data, f, indent=2, ensure_ascii=False)
        
        self.stats['chunks_processed'] = len(chunks)
        self.stats['embeddings_generated'] = len(chunks)
        
        logger.success(f"Generated and stored {len(chunks)} embeddings")
    
    def update_manifest(self):
        """Update the index manifest with embedding generation info"""
        self.manifest['embedding_phase'] = {
            'completed_at': datetime.now().isoformat(),
            'chunks_processed': self.stats['chunks_processed'],
            'embeddings_generated': self.stats['embeddings_generated'],
            'errors_count': len(self.stats['errors'])
        }
        self.manifest['requires_embedding'] = False
        
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest, f, indent=2)
        
        logger.info("📋 Updated index manifest with embedding info")
    
    def verify_embeddings(self):
        """Verify that embeddings were created successfully"""
        logger.info("🔍 Verifying embeddings...")
        
        # Get statistics from embedder
        embedder_stats = self.embedder.get_statistics()
        
        logger.info(f"💾 Storage Statistics:")
        logger.info(f"  Chunks in ChromaDB: {embedder_stats['chunks_in_chromadb']}")
        logger.info(f"  Embeddings on disk: {embedder_stats['embeddings_on_disk']}")
        
        # Check if all chunks have embeddings
        total_chunks = self.manifest['statistics']['chunks_created']
        if embedder_stats['chunks_in_chromadb'] >= total_chunks:
            logger.success(f"✅ All {total_chunks} chunks have embeddings")
        else:
            missing = total_chunks - embedder_stats['chunks_in_chromadb']
            logger.warning(f"⚠️  Missing embeddings for {missing} chunks")
    
    def run(self, limit: Optional[int] = None, batch_size: int = 32):
        """
        Run embedding generation pipeline
        
        Args:
            limit: Optional limit on chunks to process
            batch_size: Batch size for embedding generation
        """
        logger.info("🚀 Starting Embedding Generation (Phase 2)...")
        logger.info(f"📊 Processing chunks from: {self.chunks_dir}")
        
        try:
            # Load chunks
            chunks = self.load_chunks(limit=limit)
            
            if not chunks:
                logger.warning("No chunks need embedding generation")
                return
            
            # Generate embeddings
            self.generate_embeddings(chunks, batch_size=batch_size)
            
            # Update manifest
            self.update_manifest()
            
            # Verify embeddings
            self.verify_embeddings()
            
            # Print statistics
            self.print_stats()
            
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            self.stats['errors'].append(str(e))
            import traceback
            logger.debug(traceback.format_exc())
    
    def print_stats(self):
        """Print embedding generation statistics"""
        duration = datetime.now() - self.stats['start_time']
        
        logger.info("\n" + "=" * 60)
        logger.success("✅ Embedding Generation Complete!")
        logger.info("=" * 60)
        
        logger.info(f"📦 Chunks processed: {self.stats['chunks_processed']}")
        logger.info(f"🔢 Embeddings generated: {self.stats['embeddings_generated']}")
        if self.stats['skipped'] > 0:
            logger.info(f"⏭️  Chunks skipped (already had embeddings): {self.stats['skipped']}")
        logger.info(f"⏱️  Time taken: {duration}")
        
        # Calculate embedding rate
        if self.stats['chunks_processed'] > 0:
            rate = self.stats['chunks_processed'] / duration.total_seconds()
            logger.info(f"⚡ Processing rate: {rate:.1f} chunks/second")
        
        logger.info("\n📌 Next Steps:")
        logger.info("  Run 'python indexing/scripts/build_knowledge_graph.py' to build knowledge graph")
        
        if self.stats['errors']:
            logger.warning(f"\n⚠️  Errors encountered: {len(self.stats['errors'])}")
            for error in self.stats['errors'][:5]:
                logger.warning(f"  - {error}")


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Generate embeddings for collected documents')
    parser.add_argument('--limit', type=int, help='Limit number of chunks to process')
    parser.add_argument('--batch-size', type=int, default=32, help='Batch size for embedding generation')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = "DEBUG" if args.verbose else "INFO"
    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )
    
    # Add file logging
    log_file = Path("/home/regenai/project/indexing/logs/embeddings.log")
    log_file.parent.mkdir(exist_ok=True)
    logger.add(log_file, rotation="100 MB", level="DEBUG")
    
    try:
        # Create generator
        generator = EmbeddingGenerator()
        
        # Run embedding generation
        generator.run(limit=args.limit, batch_size=args.batch_size)
        
        return 0
        
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())