#!/usr/bin/env python3
"""
Discourse integration for main indexing pipeline
Bridges discourse module with main collectors
"""

import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from loguru import logger

# Add discourse module to path
sys.path.append(str(Path(__file__).parent.parent))

from discourse.discourse_loader import DiscourseDataLoader
from collectors.base_collector import Document


class DiscourseIntegration:
    """
    Integration class for discourse data in main pipeline
    """
    
    def __init__(self):
        """Initialize discourse integration"""
        self.loader = DiscourseDataLoader(
            storage_path=Path(__file__).parent.parent / "discourse" / "storage"
        )
    
    def get_documents(self) -> List[Document]:
        """
        Get discourse documents as Document objects
        
        Returns:
            List of Document objects from discourse forums
        """
        raw_docs = self.loader.load_documents(use_latest=True)
        
        documents = []
        for raw_doc in raw_docs:
            # Convert to Document object
            doc = Document(
                id=raw_doc.get('id', ''),
                source=raw_doc.get('source', 'forum.regen.network'),
                source_type='forum',
                url=raw_doc.get('url', ''),
                title=raw_doc.get('title', ''),
                content=raw_doc.get('content', ''),
                metadata=raw_doc.get('metadata', {}),
                author=raw_doc.get('author'),
                tags=raw_doc.get('tags', []),
                last_modified=None  # Can parse from metadata if needed
            )
            documents.append(doc)
        
        logger.info(f"Loaded {len(documents)} discourse documents for processing")
        return documents
    
    def get_raw_documents(self) -> List[Dict[str, Any]]:
        """
        Get raw discourse documents for direct processing
        
        Returns:
            List of document dictionaries
        """
        return self.loader.get_documents_for_embedding()
    
    def has_data(self) -> bool:
        """
        Check if discourse data is available
        
        Returns:
            True if data exists
        """
        latest = self.loader.get_latest_data_file()
        return latest is not None
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get discourse data statistics
        
        Returns:
            Statistics dictionary
        """
        return self.loader.get_statistics()


# Convenience function for main pipeline
def load_discourse_documents() -> List[Dict[str, Any]]:
    """
    Load all discourse documents for processing
    
    Returns:
        List of document dictionaries ready for embedding
    """
    integration = DiscourseIntegration()
    
    if not integration.has_data():
        logger.warning("No discourse data found. Run discourse indexing first:")
        logger.warning("  python indexing/discourse/scripts/index_all_forums.py")
        return []
    
    docs = integration.get_raw_documents()
    stats = integration.get_stats()
    
    logger.info(f"Loaded discourse data:")
    logger.info(f"  Topics: {stats.get('total_topics', 0)}")
    logger.info(f"  Posts: {stats.get('total_posts', 0)}")
    
    return docs


if __name__ == "__main__":
    # Test the integration
    logger.info("Testing Discourse Integration")
    logger.info("=" * 50)
    
    docs = load_discourse_documents()
    
    if docs:
        logger.success(f"✅ Successfully loaded {len(docs)} documents")
        logger.info(f"Sample: {docs[0].get('title', 'No title')}")
    else:
        logger.warning("❌ No documents loaded")