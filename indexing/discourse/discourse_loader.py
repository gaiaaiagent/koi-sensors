#!/usr/bin/env python3
"""
Discourse data loader for embedding and knowledge graph pipelines
Provides standardized interface for accessing discourse forum data
"""

import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime
from loguru import logger


class DiscourseDataLoader:
    """
    Loader for discourse forum data
    Handles manifest-based data discovery and parsing
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize discourse data loader
        
        Args:
            storage_path: Path to discourse storage directory
        """
        if storage_path is None:
            # Default path relative to this file
            self.storage_path = Path(__file__).parent / "storage"
        else:
            self.storage_path = Path(storage_path)
        
        self.manifest_file = self.storage_path / "manifest.json"
        self.manifest = None
        self._load_manifest()
    
    def _load_manifest(self):
        """Load manifest file"""
        if self.manifest_file.exists():
            with open(self.manifest_file, 'r') as f:
                self.manifest = json.load(f)
                logger.info(f"Loaded manifest with {len(self.manifest.get('data_files', []))} data files")
        else:
            logger.warning(f"No manifest found at {self.manifest_file}")
            self.manifest = None
    
    def get_latest_data_file(self) -> Optional[Path]:
        """
        Get the latest full data file
        
        Returns:
            Path to latest data file or None
        """
        if not self.manifest:
            # Fallback: find newest JSON file
            json_files = list(self.storage_path.glob("forum_crawl_*.json"))
            if json_files:
                # Sort by modification time
                latest = max(json_files, key=lambda f: f.stat().st_mtime)
                logger.info(f"Using latest file (no manifest): {latest.name}")
                return latest
            return None
        
        # Use manifest to find latest
        latest_file = self.manifest.get('latest_full_run')
        if latest_file:
            file_path = self.storage_path / latest_file
            if file_path.exists():
                logger.info(f"Using latest file from manifest: {latest_file}")
                return file_path
        
        # Fallback to finding file marked as latest
        for file_info in self.manifest.get('data_files', []):
            if file_info.get('is_latest'):
                file_path = self.storage_path / file_info['filename']
                if file_path.exists():
                    return file_path
        
        return None
    
    def load_documents(self, use_latest: bool = True, 
                       filename: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Load discourse documents
        
        Args:
            use_latest: Use latest full data file
            filename: Specific filename to load
            
        Returns:
            List of document dictionaries
        """
        # Determine which file to load
        if filename:
            file_path = self.storage_path / filename
        elif use_latest:
            file_path = self.get_latest_data_file()
            if not file_path:
                logger.error("No data files found")
                return []
        else:
            logger.error("Must specify filename or use_latest=True")
            return []
        
        # Load the data
        if not file_path.exists():
            logger.error(f"Data file not found: {file_path}")
            return []
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        documents = data.get('documents', [])
        logger.info(f"Loaded {len(documents)} documents from {file_path.name}")
        
        return documents
    
    def get_documents_for_embedding(self) -> List[Dict[str, Any]]:
        """
        Get documents formatted for embedding generation
        
        Returns:
            List of documents with required fields for embedding
        """
        documents = self.load_documents(use_latest=True)
        
        # Format for embedding pipeline
        formatted_docs = []
        for doc in documents:
            formatted_doc = {
                'id': doc.get('id', ''),
                'source': 'discourse:forum.regen.network',
                'source_type': 'forum',
                'url': doc.get('url', ''),
                'title': doc.get('title', ''),
                'content': doc.get('content', ''),
                'metadata': {
                    **doc.get('metadata', {}),
                    'original_source': doc.get('source', ''),
                    'author': doc.get('author'),
                    'tags': doc.get('tags', [])
                }
            }
            formatted_docs.append(formatted_doc)
        
        return formatted_docs
    
    def get_documents_for_knowledge_graph(self) -> List[Dict[str, Any]]:
        """
        Get documents formatted for knowledge graph extraction
        
        Returns:
            List of documents with entities and relationships to extract
        """
        documents = self.load_documents(use_latest=True)
        
        # Format for knowledge graph pipeline
        formatted_docs = []
        for doc in documents:
            # Prepare for entity extraction
            formatted_doc = {
                'id': doc.get('id', ''),
                'source': 'discourse',
                'title': doc.get('title', ''),
                'content': doc.get('content', ''),
                'url': doc.get('url', ''),
                'entities_to_extract': [
                    'governance_proposal',
                    'token_economics',
                    'credit_class',
                    'validator',
                    'dao',
                    'community_member'
                ],
                'metadata': doc.get('metadata', {})
            }
            
            # Add category-specific extraction hints
            if 'governance' in doc.get('title', '').lower():
                formatted_doc['entities_to_extract'].append('proposal_id')
            if 'token' in doc.get('title', '').lower() or 'regen' in doc.get('title', '').lower():
                formatted_doc['entities_to_extract'].append('token_metric')
            
            formatted_docs.append(formatted_doc)
        
        return formatted_docs
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about discourse data"""
        if self.manifest:
            return self.manifest.get('stats', {})
        
        # Calculate from data
        documents = self.load_documents(use_latest=True)
        return {
            'total_documents': len(documents),
            'sources': ['forum.regen.network']
        }
    
    def update_manifest(self, new_file_info: Dict[str, Any]):
        """
        Update manifest with new data file information
        
        Args:
            new_file_info: Information about new data file
        """
        if not self.manifest:
            self.manifest = {
                'source': 'discourse',
                'forums': [{'name': 'forum.regen.network', 'url': 'https://forum.regen.network'}],
                'data_files': []
            }
        
        # Mark previous files as not latest
        for file_info in self.manifest.get('data_files', []):
            file_info['is_latest'] = False
        
        # Add new file
        new_file_info['is_latest'] = True
        self.manifest['data_files'].append(new_file_info)
        
        # Update latest reference
        if new_file_info.get('type') == 'full_run':
            self.manifest['latest_full_run'] = new_file_info['filename']
        
        # Save manifest
        with open(self.manifest_file, 'w') as f:
            json.dump(self.manifest, f, indent=2)
        
        logger.info(f"Updated manifest with {new_file_info['filename']}")


# Integration functions for embedding and knowledge graph pipelines
def get_discourse_documents_for_processing() -> List[Dict[str, Any]]:
    """
    Main integration point for processing pipelines
    
    Returns:
        List of discourse documents ready for processing
    """
    loader = DiscourseDataLoader()
    return loader.get_documents_for_embedding()


def get_discourse_statistics() -> Dict[str, Any]:
    """
    Get statistics about indexed discourse data
    
    Returns:
        Statistics dictionary
    """
    loader = DiscourseDataLoader()
    return loader.get_statistics()


if __name__ == "__main__":
    # Test the loader
    loader = DiscourseDataLoader()
    
    logger.info("Testing Discourse Data Loader")
    logger.info("=" * 50)
    
    # Get latest file
    latest = loader.get_latest_data_file()
    if latest:
        logger.info(f"Latest data file: {latest.name}")
    
    # Load documents
    docs = loader.load_documents()
    logger.info(f"Loaded {len(docs)} documents")
    
    if docs:
        logger.info(f"Sample document: {docs[0].get('title', 'No title')}")
    
    # Get statistics
    stats = loader.get_statistics()
    logger.info(f"Statistics: {json.dumps(stats, indent=2)}")