"""
Integration bridge between existing indexing system and KOI node
Enables the document processor to generate and register RIDs
"""

import sys
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import httpx
from loguru import logger

# Add indexing path to system path
sys.path.append('/home/regenai/project')

from indexing.processors.document_processor import DocumentChunk
from indexing.collectors.base_collector import Document

class KOIIntegrationBridge:
    """
    Bridge between the existing indexing system and KOI node
    """
    
    def __init__(self, koi_node_url: str = "http://localhost:8000"):
        """
        Initialize the integration bridge
        
        Args:
            koi_node_url: URL of the KOI node server
        """
        self.koi_node_url = koi_node_url
        self.client = httpx.Client()
        
        # Version tracking for subjects
        self.version_tracker = {}
        
        logger.info(f"Initialized KOI Integration Bridge connecting to {koi_node_url}")
        
    def generate_rid_for_document(self, document: Dict[str, Any]) -> str:
        """
        Generate a RID for a document following Regen's naming convention
        
        Args:
            document: Document dictionary from the indexing system
            
        Returns:
            Generated RID string
        """
        # Determine relevance based on source
        source = document.get('source', '').lower()
        if 'credit' in source or 'registry' in source:
            relevance = 'core'
        elif 'governance' in source or 'proposal' in source:
            relevance = 'relevant'
        else:
            relevance = 'background'
            
        # Determine object type
        doc_type = document.get('type', 'document').lower()
        if 'analysis' in doc_type:
            object_type = 'analysis'
        elif 'memo' in doc_type or 'strategic' in doc_type:
            object_type = 'memo'
        elif 'readme' in doc_type or 'documentation' in doc_type:
            object_type = 'readme'
        else:
            object_type = 'notes'
            
        # Create subject from title or source
        title = document.get('title', document.get('source', 'untitled'))
        subject = title.lower().replace(' ', '-').replace('_', '-')[:50]  # Limit subject length
        
        # Get or increment version
        version = self._get_next_version(subject)
        
        # Generate content hash
        content = document.get('content', '')
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:8]
        
        # Format RID
        rid = f"{relevance}.{object_type}.{subject}.v{version[0]}.{version[1]}.{version[2]}.{content_hash}"
        
        return rid
        
    def generate_rid_for_chunk(self, chunk: DocumentChunk) -> str:
        """
        Generate a RID for a document chunk
        
        Args:
            chunk: DocumentChunk object
            
        Returns:
            Generated RID string
        """
        # Use document metadata to determine RID components
        metadata = chunk.metadata
        
        # Determine relevance
        source = metadata.get('document_source', '').lower()
        if 'credit' in source or 'registry' in source:
            relevance = 'core'
        else:
            relevance = 'relevant'
            
        # Object type for chunks
        object_type = 'notes'  # Chunks are typically notes/fragments
        
        # Subject from document title
        title = metadata.get('document_title', 'chunk')
        subject = f"{title}-chunk{chunk.chunk_index}".lower().replace(' ', '-')[:50]
        
        # Generate hash from chunk content
        content_hash = hashlib.sha256(chunk.content.encode()).hexdigest()[:8]
        
        # Simple versioning for chunks
        rid = f"{relevance}.{object_type}.{subject}.v1.0.0.{content_hash}"
        
        return rid
        
    def register_document_with_koi(self, document: Dict[str, Any]) -> Optional[str]:
        """
        Register a document with the KOI node and get a RID
        
        Args:
            document: Document to register
            
        Returns:
            Generated RID or None if failed
        """
        try:
            # Generate RID using KOI node endpoint
            response = self.client.post(
                f"{self.koi_node_url}/regen/generate-rid",
                json={
                    "content": document.get('content', ''),
                    "object_type": self._determine_object_type(document),
                    "subject": document.get('title', 'untitled').lower().replace(' ', '-'),
                    "relevance": self._determine_relevance(document)
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                rid = result['rid']
                
                # Store the RID in the document
                document['koi_rid'] = rid
                
                logger.info(f"Registered document with RID: {rid}")
                return rid
            else:
                logger.error(f"Failed to generate RID: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error registering document with KOI: {e}")
            return None
            
    def sync_existing_documents(self, documents_path: Path) -> int:
        """
        Sync existing documents from the indexing system with KOI
        
        Args:
            documents_path: Path to documents storage
            
        Returns:
            Number of documents synced
        """
        synced_count = 0
        documents_path = Path(documents_path)
        
        if not documents_path.exists():
            logger.warning(f"Documents path does not exist: {documents_path}")
            return 0
            
        # Process all JSON documents
        for doc_file in documents_path.glob("*.json"):
            try:
                with open(doc_file, 'r') as f:
                    document = json.load(f)
                    
                # Skip if already has RID
                if 'koi_rid' in document:
                    continue
                    
                # Generate and register RID
                rid = self.generate_rid_for_document(document)
                document['koi_rid'] = rid
                
                # Save updated document
                with open(doc_file, 'w') as f:
                    json.dump(document, f, indent=2)
                    
                synced_count += 1
                
                if synced_count % 100 == 0:
                    logger.info(f"Synced {synced_count} documents with KOI")
                    
            except Exception as e:
                logger.error(f"Error processing {doc_file}: {e}")
                
        logger.success(f"Completed sync: {synced_count} documents registered with KOI")
        return synced_count
        
    def check_health(self) -> bool:
        """
        Check if KOI node is healthy
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            response = self.client.get(f"{self.koi_node_url}/regen/health")
            if response.status_code == 200:
                health = response.json()
                logger.info(f"KOI node health: {health['status']}")
                return health['status'] == 'healthy'
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            
        return False
        
    def get_statistics(self) -> Optional[Dict[str, Any]]:
        """
        Get statistics from KOI node
        
        Returns:
            Statistics dictionary or None if failed
        """
        try:
            response = self.client.get(f"{self.koi_node_url}/regen/stats")
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            
        return None
        
    def _determine_relevance(self, document: Dict[str, Any]) -> str:
        """Determine relevance level for a document"""
        source = document.get('source', '').lower()
        doc_type = document.get('type', '').lower()
        
        # Core relevance
        if any(term in source for term in ['credit', 'registry', 'methodology']):
            return 'core'
        if any(term in doc_type for term in ['whitepaper', 'specification', 'protocol']):
            return 'core'
            
        # Relevant
        if any(term in source for term in ['governance', 'proposal', 'blog', 'announcement']):
            return 'relevant'
            
        # Background
        return 'background'
        
    def _determine_object_type(self, document: Dict[str, Any]) -> str:
        """Determine object type for a document"""
        doc_type = document.get('type', '').lower()
        title = document.get('title', '').lower()
        
        if 'analysis' in doc_type or 'report' in doc_type:
            return 'analysis'
        elif 'memo' in doc_type or 'strategic' in title:
            return 'memo'
        elif 'readme' in doc_type or 'documentation' in doc_type:
            return 'readme'
        else:
            return 'notes'
            
    def _get_next_version(self, subject: str) -> tuple:
        """Get next version for a subject"""
        if subject not in self.version_tracker:
            self.version_tracker[subject] = (1, 0, 0)
        else:
            current = self.version_tracker[subject]
            self.version_tracker[subject] = (current[0], current[1], current[2] + 1)
            
        return self.version_tracker[subject]


# Example usage
def main():
    """Example usage of the integration bridge"""
    bridge = KOIIntegrationBridge()
    
    # Check health
    if bridge.check_health():
        print("KOI node is healthy")
        
        # Get statistics
        stats = bridge.get_statistics()
        if stats:
            print(f"Current statistics: {json.dumps(stats, indent=2)}")
            
        # Example: Register a document
        test_document = {
            "id": "test-doc-1",
            "title": "Carbon Credit Methodology Overview",
            "content": "This document describes the methodology for carbon credit verification...",
            "source": "registry",
            "type": "analysis"
        }
        
        rid = bridge.register_document_with_koi(test_document)
        if rid:
            print(f"Document registered with RID: {rid}")
            
        # Sync existing documents (if path exists)
        docs_path = Path("/home/regenai/project/indexing/storage/documents")
        if docs_path.exists():
            synced = bridge.sync_existing_documents(docs_path)
            print(f"Synced {synced} existing documents")
    else:
        print("KOI node is not healthy")


if __name__ == "__main__":
    main()