"""
Base collector classes for Regen Network indexing system
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
import hashlib
import json
from loguru import logger


@dataclass
class Document:
    """
    Represents a collected document with metadata
    """
    id: str  # Unique identifier (hash of content)
    source: str  # e.g., "github:regen-ledger", "discourse:regen-forum"
    source_type: str  # e.g., "github", "discourse", "website"
    url: str  # Original URL or path
    title: str
    content: str  # Raw text content
    metadata: Dict[str, Any] = field(default_factory=dict)
    collected_at: datetime = field(default_factory=datetime.now)
    last_modified: Optional[datetime] = None
    author: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    koi_rid: Optional[str] = None  # Knowledge Object Identifier
    
    def __post_init__(self):
        """Generate ID if not provided"""
        if not self.id:
            self.id = self.generate_id()
    
    def generate_id(self) -> str:
        """Generate unique ID from content hash"""
        content_hash = hashlib.sha256(
            f"{self.source}:{self.url}:{self.content}".encode()
        ).hexdigest()
        return content_hash[:16]
    
    def to_json(self) -> str:
        """Convert to JSON string"""
        data = {
            "id": self.id,
            "source": self.source,
            "source_type": self.source_type,
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "metadata": self.metadata,
            "collected_at": self.collected_at.isoformat(),
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
            "author": self.author,
            "tags": self.tags,
            "koi_rid": self.koi_rid
        }
        return json.dumps(data, indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Document':
        """Create Document from JSON string"""
        data = json.loads(json_str)
        data['collected_at'] = datetime.fromisoformat(data['collected_at'])
        if data.get('last_modified'):
            data['last_modified'] = datetime.fromisoformat(data['last_modified'])
        return cls(**data)


class BaseCollector(ABC):
    """
    Abstract base class for all content collectors
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize collector with configuration
        
        Args:
            config: Configuration dictionary from sources.yaml
        """
        self.config = config
        self.storage_path = Path("/home/regenai/project/indexing/storage/documents")
        self.cache_path = Path("/home/regenai/project/indexing/cache")
        self.documents_collected = 0
        
        # Ensure directories exist
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.cache_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Initialized {self.__class__.__name__} collector")
    
    @abstractmethod
    async def collect(self, limit: Optional[int] = None) -> List[Document]:
        """
        Collect documents from the source
        
        Args:
            limit: Maximum number of documents to collect (for testing)
            
        Returns:
            List of collected Document objects
        """
        pass
    
    @abstractmethod
    def validate_config(self) -> bool:
        """
        Validate collector configuration
        
        Returns:
            True if configuration is valid
        """
        pass
    
    def save_document(self, doc: Document) -> Path:
        """
        Save document to storage
        
        Args:
            doc: Document to save
            
        Returns:
            Path to saved document
        """
        doc_path = self.storage_path / f"{doc.source_type}_{doc.id}.json"
        with open(doc_path, 'w') as f:
            f.write(doc.to_json())
        logger.debug(f"Saved document {doc.id} to {doc_path}")
        return doc_path
    
    def save_documents(self, documents: List[Document]) -> List[Path]:
        """
        Save multiple documents to storage
        
        Args:
            documents: List of documents to save
            
        Returns:
            List of paths to saved documents
        """
        paths = []
        for doc in documents:
            paths.append(self.save_document(doc))
        
        self.documents_collected += len(documents)
        logger.info(f"Saved {len(documents)} documents (total: {self.documents_collected})")
        return paths
    
    def load_cached_document(self, doc_id: str) -> Optional[Document]:
        """
        Load a cached document if it exists
        
        Args:
            doc_id: Document ID
            
        Returns:
            Document if found in cache, None otherwise
        """
        pattern = f"*_{doc_id}.json"
        matching_files = list(self.storage_path.glob(pattern))
        
        if matching_files:
            with open(matching_files[0], 'r') as f:
                return Document.from_json(f.read())
        return None
    
    def is_cached(self, url: str, max_age_hours: int = 24) -> bool:
        """
        Check if a document is already cached and fresh
        
        Args:
            url: Document URL
            max_age_hours: Maximum age in hours before re-collection
            
        Returns:
            True if document is cached and fresh
        """
        # Generate expected ID for this URL
        test_id = hashlib.sha256(f"{url}".encode()).hexdigest()[:16]
        
        # Check all cached documents
        for doc_path in self.storage_path.glob("*.json"):
            with open(doc_path, 'r') as f:
                doc = Document.from_json(f.read())
                if doc.url == url:
                    age = datetime.now() - doc.collected_at
                    if age.total_seconds() < max_age_hours * 3600:
                        logger.debug(f"Using cached version of {url}")
                        return True
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get collection statistics
        
        Returns:
            Dictionary with collection stats
        """
        return {
            "collector": self.__class__.__name__,
            "documents_collected": self.documents_collected,
            "storage_path": str(self.storage_path),
            "cache_path": str(self.cache_path)
        }


class BatchCollector(BaseCollector):
    """
    Base class for collectors that process documents in batches
    """
    
    def __init__(self, config: Dict[str, Any], batch_size: int = 32):
        """
        Initialize batch collector
        
        Args:
            config: Configuration dictionary
            batch_size: Number of documents to process at once
        """
        super().__init__(config)
        self.batch_size = batch_size
    
    async def collect_batch(self, items: List[Any]) -> List[Document]:
        """
        Collect a batch of items
        
        Args:
            items: List of items to collect
            
        Returns:
            List of Document objects
        """
        documents = []
        for item in items:
            try:
                doc = await self.process_item(item)
                if doc:
                    documents.append(doc)
            except Exception as e:
                logger.error(f"Error processing item: {e}")
                continue
        return documents
    
    @abstractmethod
    async def process_item(self, item: Any) -> Optional[Document]:
        """
        Process a single item into a Document
        
        Args:
            item: Item to process
            
        Returns:
            Document object or None if processing fails
        """
        pass