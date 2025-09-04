#!/usr/bin/env python3
"""
Main indexing script for Regen Network content
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
from processors import DocumentProcessor, Embedder


class FullIndexer:
    """
    Main indexer that coordinates collection, processing, and embedding
    """
    
    def __init__(self, config_path: Path):
        """
        Initialize full indexer
        
        Args:
            config_path: Path to sources.yaml configuration
        """
        self.config_path = config_path
        self.load_config()
        
        # Initialize processors
        self.document_processor = DocumentProcessor(
            chunk_size=self.config.get('indexing', {}).get('chunk_size', 1000),
            chunk_overlap=self.config.get('indexing', {}).get('chunk_overlap', 200)
        )
        
        self.embedder = Embedder(
            model_name=self.config.get('indexing', {}).get('embedding_model', 'sentence-transformers/all-MiniLM-L6-v2')
        )
        
        # Statistics
        self.stats = {
            'start_time': datetime.now(),
            'documents_collected': 0,
            'chunks_created': 0,
            'embeddings_generated': 0,
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
    
    def process_documents(self, documents: List[Dict]) -> List[Any]:
        """
        Process documents into chunks
        
        Args:
            documents: List of document dictionaries
            
        Returns:
            List of DocumentChunk objects
        """
        logger.info(f"📝 Processing {len(documents)} documents into chunks...")
        
        all_chunks = []
        batch_size = 100
        
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            chunks = self.document_processor.process_batch(batch)
            all_chunks.extend(chunks)
            logger.debug(f"Processed batch {i//batch_size + 1}: {len(chunks)} chunks")
        
        self.stats['chunks_created'] = len(all_chunks)
        logger.success(f"Created {len(all_chunks)} chunks from {len(documents)} documents")
        
        return all_chunks
    
    def generate_embeddings(self, chunks: List[Any]):
        """
        Generate embeddings for all chunks
        
        Args:
            chunks: List of DocumentChunk objects
        """
        logger.info(f"🔢 Generating embeddings for {len(chunks)} chunks...")
        
        batch_size = self.config.get('indexing', {}).get('batch_size', 32)
        self.embedder.process_and_store(chunks, batch_size=batch_size)
        
        self.stats['embeddings_generated'] = len(chunks)
        logger.success(f"Generated and stored {len(chunks)} embeddings")
    
    async def run(self, limit: Optional[int] = None):
        """
        Run full indexing pipeline
        
        Args:
            limit: Optional limit on documents to process
        """
        logger.info("🚀 Starting Regen Network content indexing...")
        logger.info(f"📊 Target: {'Test mode - ' + str(limit) + ' documents' if limit else '15,000+ documents'}")
        
        try:
            # Phase 1: Collection
            logger.info("\n=== Phase 1: Document Collection ===")
            documents = await self.collect_all(limit)
            
            if not documents:
                logger.error("No documents collected!")
                return
            
            # Phase 2: Processing
            logger.info("\n=== Phase 2: Document Processing ===")
            chunks = self.process_documents(documents)
            
            if not chunks:
                logger.error("No chunks created!")
                return
            
            # Phase 3: Embedding Generation
            logger.info("\n=== Phase 3: Embedding Generation ===")
            self.generate_embeddings(chunks)
            
            # Final statistics
            self.print_final_stats()
            
        except Exception as e:
            logger.error(f"Indexing failed: {e}")
            self.stats['errors'].append(str(e))
            import traceback
            logger.debug(traceback.format_exc())
    
    def print_final_stats(self):
        """Print final indexing statistics"""
        duration = datetime.now() - self.stats['start_time']
        
        logger.info("\n" + "=" * 60)
        logger.success("✅ Indexing Complete!")
        logger.info("=" * 60)
        
        logger.info(f"📄 Total documents indexed: {self.stats['documents_collected']}")
        logger.info(f"📦 Total chunks created: {self.stats['chunks_created']}")
        logger.info(f"🔢 Total embeddings generated: {self.stats['embeddings_generated']}")
        logger.info(f"⏱️  Time taken: {duration}")
        
        logger.info("\n📊 Documents by source:")
        for source, count in self.stats['by_source'].items():
            logger.info(f"  {source}: {count}")
        
        # Check requirements
        logger.info("\n📋 Requirements Check:")
        if self.stats['documents_collected'] >= 15000:
            logger.success("✅ Milestone 1.1 requirement met: 15,000+ documents indexed")
        else:
            remaining = 15000 - self.stats['documents_collected']
            logger.warning(f"⚠️  Need {remaining} more documents to meet 15,000 requirement")
        
        # Get embedder stats
        embedder_stats = self.embedder.get_statistics()
        logger.info(f"\n💾 Storage Statistics:")
        logger.info(f"  Chunks in ChromaDB: {embedder_stats['chunks_in_chromadb']}")
        logger.info(f"  Embeddings on disk: {embedder_stats['embeddings_on_disk']}")
        
        if self.stats['errors']:
            logger.warning(f"\n⚠️  Errors encountered: {len(self.stats['errors'])}")
            for error in self.stats['errors'][:5]:
                logger.warning(f"  - {error}")


async def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Run full Regen Network content indexing')
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
    log_file = Path("/home/regenai/project/indexing/logs/full_index.log")
    log_file.parent.mkdir(exist_ok=True)
    logger.add(log_file, rotation="100 MB", level="DEBUG")
    
    # Load configuration
    config_path = Path(__file__).parent.parent / "config" / "sources.yaml"
    
    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        return 1
    
    # Create indexer
    indexer = FullIndexer(config_path)
    
    # Set test mode if requested
    if args.test:
        indexer.config['indexing'] = indexer.config.get('indexing', {})
        indexer.config['indexing']['test_mode'] = True
        args.limit = args.limit or 100
    
    # Run indexing
    await indexer.run(limit=args.limit)
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)