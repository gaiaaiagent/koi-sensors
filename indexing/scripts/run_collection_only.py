#!/usr/bin/env python3
"""
Collection-only indexing script for Regen Network content
Phase 1: Collect and cache documents with metadata
Target: 15,000+ documents
"""

import sys
import asyncio
from pathlib import Path
import yaml
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from loguru import logger
import argparse

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from collectors import GitCollector, DiscourseCollector, WebScraper
from processors import DocumentProcessor


class CollectionIndexer:
    """
    Phase 1 indexer that only collects and caches documents with metadata
    Does NOT generate embeddings or knowledge graph
    """
    
    def __init__(self, config_path: Path):
        """
        Initialize collection-only indexer
        
        Args:
            config_path: Path to sources.yaml configuration
        """
        self.config_path = config_path
        self.load_config()
        
        # Initialize document processor for chunking only
        self.document_processor = DocumentProcessor(
            chunk_size=self.config.get('indexing', {}).get('chunk_size', 1000),
            chunk_overlap=self.config.get('indexing', {}).get('chunk_overlap', 200)
        )
        
        # Statistics
        self.stats = {
            'start_time': datetime.now(),
            'documents_collected': 0,
            'chunks_created': 0,
            'documents_cached': 0,
            'metadata_generated': 0,
            'errors': [],
            'by_source': {}
        }
    
    def load_config(self):
        """Load configuration from sources.yaml"""
        with open(self.config_path) as f:
            self.config = yaml.safe_load(f)
        logger.info(f"Loaded configuration from {self.config_path}")
    
    async def collect_github(self, limit: Optional[int] = None) -> List[Dict]:
        """Collect documents from GitHub repositories"""
        logger.info("📦 Collecting from GitHub repositories...")
        
        if 'github' not in self.config['sources']:
            logger.warning("No GitHub sources configured")
            return []
        
        all_docs = []
        repos = self.config['sources']['github']
        
        # Use test paths if in test mode
        if self.config.get('indexing', {}).get('test_mode', False):
            for repo in repos:
                if 'test_paths' in repo:
                    repo['paths'] = repo['test_paths']
        
        collector = GitCollector({'repos': repos})
        docs = await collector.collect(limit=limit)
        
        # Convert to dictionaries
        for doc in docs:
            doc_dict = json.loads(doc.to_json())
            all_docs.append(doc_dict)
        
        self.stats['by_source']['github'] = len(all_docs)
        logger.success(f"Collected {len(all_docs)} GitHub documents")
        return all_docs
    
    async def collect_discourse(self, limit: Optional[int] = None) -> List[Dict]:
        """Collect documents from Discourse forums"""
        logger.info("💬 Collecting from Discourse forums...")
        
        if 'discourse' not in self.config['sources']:
            logger.warning("No Discourse sources configured")
            return []
        
        all_docs = []
        forums = self.config['sources']['discourse']
        
        async with DiscourseCollector({'forums': forums}) as collector:
            docs = await collector.collect(limit=limit)
            
            # Convert to dictionaries
            for doc in docs:
                doc_dict = json.loads(doc.to_json())
                all_docs.append(doc_dict)
        
        self.stats['by_source']['discourse'] = len(all_docs)
        logger.success(f"Collected {len(all_docs)} Discourse documents")
        return all_docs
    
    async def collect_websites(self, limit: Optional[int] = None) -> List[Dict]:
        """Collect documents from websites"""
        logger.info("🌐 Collecting from websites...")
        
        if 'websites' not in self.config['sources']:
            logger.warning("No websites configured")
            return []
        
        all_docs = []
        websites = self.config['sources']['websites']
        
        # Apply test limits if configured
        if self.config.get('indexing', {}).get('test_mode', False):
            for site in websites:
                site['max_depth'] = site.get('test_limit', 2)
        
        async with WebScraper({'websites': websites}) as scraper:
            docs = await scraper.collect(limit=limit)
            
            # Convert to dictionaries
            for doc in docs:
                doc_dict = json.loads(doc.to_json())
                all_docs.append(doc_dict)
        
        self.stats['by_source']['websites'] = len(all_docs)
        logger.success(f"Collected {len(all_docs)} website documents")
        return all_docs
    
    async def collect_all(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Collect documents from all configured sources
        
        Args:
            limit: Optional limit on total documents
            
        Returns:
            List of all collected documents
        """
        all_documents = []
        
        # Calculate per-source limits if total limit is set
        if limit:
            sources_count = sum([
                1 for s in ['github', 'discourse', 'websites'] 
                if s in self.config['sources']
            ])
            per_source_limit = max(limit // sources_count, 10)
        else:
            per_source_limit = None
        
        # Collect from each source
        github_docs = await self.collect_github(per_source_limit)
        all_documents.extend(github_docs)
        
        if not limit or len(all_documents) < limit:
            remaining = limit - len(all_documents) if limit else None
            discourse_docs = await self.collect_discourse(remaining)
            all_documents.extend(discourse_docs)
        
        if not limit or len(all_documents) < limit:
            remaining = limit - len(all_documents) if limit else None
            website_docs = await self.collect_websites(remaining)
            all_documents.extend(website_docs)
        
        self.stats['documents_collected'] = len(all_documents)
        
        logger.info(f"\n📊 Collection Summary:")
        logger.info(f"  Total documents: {len(all_documents)}")
        for source, count in self.stats['by_source'].items():
            logger.info(f"  {source}: {count}")
        
        return all_documents
    
    def save_documents_and_metadata(self, documents: List[Dict]) -> int:
        """
        Save documents and their metadata without generating embeddings
        
        Args:
            documents: List of document dictionaries
            
        Returns:
            Number of documents saved
        """
        logger.info(f"💾 Saving {len(documents)} documents and metadata...")
        
        # Create storage directories
        docs_dir = Path("/home/regenai/project/indexing/storage/documents")
        metadata_dir = Path("/home/regenai/project/indexing/storage/metadata")
        docs_dir.mkdir(parents=True, exist_ok=True)
        metadata_dir.mkdir(parents=True, exist_ok=True)
        
        saved_count = 0
        batch_size = 100
        
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            
            for doc in batch:
                try:
                    # Save full document
                    doc_id = doc.get('koi_rid', doc.get('id', f"doc_{saved_count}"))
                    doc_path = docs_dir / f"{doc_id}.json"
                    
                    with open(doc_path, 'w', encoding='utf-8') as f:
                        json.dump(doc, f, indent=2, ensure_ascii=False)
                    
                    # Create and save metadata
                    metadata = {
                        'id': doc_id,
                        'koi_rid': doc.get('koi_rid'),
                        'title': doc.get('title', 'Untitled'),
                        'source': doc.get('source'),
                        'source_type': doc.get('source_type'),
                        'url': doc.get('url'),
                        'created_at': doc.get('created_at'),
                        'updated_at': doc.get('updated_at'),
                        'author': doc.get('author'),
                        'tags': doc.get('tags', []),
                        'content_length': len(doc.get('content', '')),
                        'indexed_at': datetime.now().isoformat(),
                        'requires_embedding': True,  # Flag for phase 2
                        'chunks_created': False  # Will be updated when chunks are created
                    }
                    
                    metadata_path = metadata_dir / f"{doc_id}_metadata.json"
                    with open(metadata_path, 'w', encoding='utf-8') as f:
                        json.dump(metadata, f, indent=2, ensure_ascii=False)
                    
                    saved_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to save document {doc_id}: {e}")
                    self.stats['errors'].append(f"Save error for {doc_id}: {str(e)}")
            
            logger.debug(f"Saved batch {i//batch_size + 1}: {len(batch)} documents")
        
        self.stats['documents_cached'] = saved_count
        self.stats['metadata_generated'] = saved_count
        logger.success(f"Saved {saved_count} documents with metadata")
        
        return saved_count
    
    def create_and_save_chunks(self, documents: List[Dict]) -> int:
        """
        Create chunks and save them separately (without embeddings)
        
        Args:
            documents: List of document dictionaries
            
        Returns:
            Number of chunks created
        """
        logger.info(f"📝 Creating chunks for {len(documents)} documents...")
        
        chunks_dir = Path("/home/regenai/project/indexing/storage/chunks")
        chunks_dir.mkdir(parents=True, exist_ok=True)
        
        total_chunks = 0
        batch_size = 100
        
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            chunks = self.document_processor.process_batch(batch)
            
            # Save chunks without embeddings
            for chunk in chunks:
                chunk_data = {
                    'chunk_id': chunk.chunk_id,
                    'document_id': chunk.document_id,
                    'koi_rid': chunk.koi_rid,
                    'content': chunk.content,
                    'chunk_index': chunk.chunk_index,
                    'total_chunks': chunk.total_chunks,
                    'metadata': chunk.metadata,
                    'requires_embedding': True  # Flag for phase 2
                }
                
                chunk_path = chunks_dir / f"{chunk.chunk_id}.json"
                with open(chunk_path, 'w', encoding='utf-8') as f:
                    json.dump(chunk_data, f, indent=2, ensure_ascii=False)
            
            total_chunks += len(chunks)
            logger.debug(f"Created batch {i//batch_size + 1}: {len(chunks)} chunks")
            
            # Update metadata to indicate chunks were created
            metadata_dir = Path("/home/regenai/project/indexing/storage/metadata")
            for doc in batch:
                doc_id = doc.get('koi_rid', doc.get('id'))
                metadata_path = metadata_dir / f"{doc_id}_metadata.json"
                if metadata_path.exists():
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)
                    metadata['chunks_created'] = True
                    metadata['chunk_count'] = len([c for c in chunks if c.document_id == doc_id])
                    with open(metadata_path, 'w') as f:
                        json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        self.stats['chunks_created'] = total_chunks
        logger.success(f"Created and saved {total_chunks} chunks")
        
        return total_chunks
    
    def create_index_manifest(self):
        """Create a manifest file for the indexed content"""
        manifest_path = Path("/home/regenai/project/indexing/storage/index_manifest.json")
        
        manifest = {
            'created_at': self.stats['start_time'].isoformat(),
            'completed_at': datetime.now().isoformat(),
            'statistics': {
                'documents_collected': self.stats['documents_collected'],
                'documents_cached': self.stats['documents_cached'],
                'metadata_generated': self.stats['metadata_generated'],
                'chunks_created': self.stats['chunks_created'],
                'by_source': self.stats['by_source']
            },
            'phase': 'collection',
            'requires_embedding': True,
            'requires_knowledge_graph': True,
            'errors_count': len(self.stats['errors'])
        }
        
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        logger.info(f"📋 Created index manifest at {manifest_path}")
    
    async def run(self, limit: Optional[int] = None):
        """
        Run collection-only indexing pipeline
        
        Args:
            limit: Optional limit on documents to process
        """
        logger.info("🚀 Starting Regen Network content collection (Phase 1)...")
        logger.info(f"📊 Target: {'Test mode - ' + str(limit) + ' documents' if limit else '15,000+ documents'}")
        logger.info("ℹ️  This phase will collect and cache documents WITHOUT generating embeddings")
        
        try:
            # Phase 1: Collection
            logger.info("\n=== Phase 1: Document Collection ===")
            documents = await self.collect_all(limit)
            
            if not documents:
                logger.error("No documents collected!")
                return
            
            # Phase 1.5: Save documents and metadata
            logger.info("\n=== Phase 1.5: Saving Documents and Metadata ===")
            self.save_documents_and_metadata(documents)
            
            # Phase 1.6: Create chunks (without embeddings)
            logger.info("\n=== Phase 1.6: Creating Document Chunks ===")
            self.create_and_save_chunks(documents)
            
            # Create manifest for next phase
            self.create_index_manifest()
            
            # Final statistics
            self.print_final_stats()
            
        except Exception as e:
            logger.error(f"Collection failed: {e}")
            self.stats['errors'].append(str(e))
            import traceback
            logger.debug(traceback.format_exc())
    
    def print_final_stats(self):
        """Print final collection statistics"""
        duration = datetime.now() - self.stats['start_time']
        
        logger.info("\n" + "=" * 60)
        logger.success("✅ Collection Phase Complete!")
        logger.info("=" * 60)
        
        logger.info(f"📄 Total documents collected: {self.stats['documents_collected']}")
        logger.info(f"💾 Total documents cached: {self.stats['documents_cached']}")
        logger.info(f"📋 Total metadata files created: {self.stats['metadata_generated']}")
        logger.info(f"📦 Total chunks created: {self.stats['chunks_created']}")
        logger.info(f"⏱️  Time taken: {duration}")
        
        logger.info("\n📊 Documents by source:")
        for source, count in self.stats['by_source'].items():
            logger.info(f"  {source}: {count}")
        
        # Check requirements
        logger.info("\n📋 Requirements Check:")
        if self.stats['documents_collected'] >= 15000:
            logger.success("✅ Milestone 1.1 collection phase complete: 15,000+ documents collected")
        else:
            remaining = 15000 - self.stats['documents_collected']
            logger.warning(f"⚠️  Need {remaining} more documents to meet 15,000 requirement")
        
        logger.info("\n📌 Next Steps:")
        logger.info("  1. Run 'python indexing/scripts/generate_embeddings.py' to create embeddings")
        logger.info("  2. Run 'python indexing/scripts/build_knowledge_graph.py' to build knowledge graph")
        
        if self.stats['errors']:
            logger.warning(f"\n⚠️  Errors encountered: {len(self.stats['errors'])}")
            for error in self.stats['errors'][:5]:
                logger.warning(f"  - {error}")


async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Run collection-only indexing for Regen Network content')
    parser.add_argument('--limit', type=int, help='Limit number of documents (for testing)')
    parser.add_argument('--test', action='store_true', help='Run in test mode with minimal documents')
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
    log_file = Path("/home/regenai/project/indexing/logs/collection.log")
    log_file.parent.mkdir(exist_ok=True)
    logger.add(log_file, rotation="100 MB", level="DEBUG")
    
    # Load configuration
    config_path = Path(__file__).parent.parent / "config" / "sources.yaml"
    
    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        return 1
    
    # Create indexer
    indexer = CollectionIndexer(config_path)
    
    # Set test mode if requested
    if args.test:
        indexer.config['indexing'] = indexer.config.get('indexing', {})
        indexer.config['indexing']['test_mode'] = True
        args.limit = args.limit or 100
    
    # Run collection
    await indexer.run(limit=args.limit)
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)