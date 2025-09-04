"""
KOI Protocol Integration - Collector Adapter
Adapts existing RegenAI collectors to KOI protocol compliance
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from abc import ABC, abstractmethod

from ..nodes.koi_node import KOIPartialNode
from ..core.rid_system import RID, document_to_rid, generate_rid_for_document
from ..core.bundle_system import Bundle, document_to_bundle, KOIEvent


class KOICollectorAdapter(ABC):
    """Base adapter to make existing collectors KOI-compliant"""
    
    def __init__(self, collector_name: str, coordinator_url: str = "http://localhost:8000"):
        self.collector_name = collector_name
        self.logger = logging.getLogger(f"koi.adapter.{collector_name}")
        
        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name=f"{collector_name}-sensor",
            coordinator_url=coordinator_url,
            poll_interval=30
        )
        
        # State tracking
        self.processed_documents: Set[str] = set()
        self.last_collection_time: Optional[datetime] = None
        self.metrics = {
            "documents_processed": 0,
            "events_emitted": 0,
            "errors_encountered": 0
        }
    
    @abstractmethod
    async def collect_documents(self) -> List[Dict[str, Any]]:
        """Collect documents using existing collector logic
        
        Returns:
            List of documents in existing Document format
        """
        pass
    
    @abstractmethod 
    def should_process_document(self, document: Dict[str, Any]) -> bool:
        """Determine if document should be processed
        
        Args:
            document: Document in existing format
            
        Returns:
            True if document should be processed
        """
        pass
    
    async def start_koi_collection(self):
        """Start KOI-compliant collection process"""
        self.logger.info(f"Starting KOI collection for {self.collector_name}")
        
        # Start KOI node
        await self.koi_node.start()
        
        # Start collection loop
        asyncio.create_task(self.collection_loop())
    
    async def stop_koi_collection(self):
        """Stop KOI collection process"""
        self.logger.info(f"Stopping KOI collection for {self.collector_name}")
        await self.koi_node.stop()
    
    async def collection_loop(self):
        """Main collection loop with KOI event emission"""
        while self.koi_node.running:
            try:
                start_time = datetime.now()
                
                # Use existing collector logic
                documents = await self.collect_documents()
                
                # Process each document
                for document in documents:
                    try:
                        await self.process_document_with_koi(document)
                    except Exception as e:
                        self.logger.error(f"Error processing document {document.get('id', 'unknown')}: {e}")
                        self.metrics["errors_encountered"] += 1
                
                self.last_collection_time = datetime.now()
                collection_time = (self.last_collection_time - start_time).total_seconds()
                
                self.logger.info(
                    f"Processed {len(documents)} documents in {collection_time:.2f}s"
                )
                
                # Wait before next collection (existing pattern - 6 hours)
                await asyncio.sleep(6 * 3600)  # 6 hours
                
            except Exception as e:
                self.logger.error(f"Error in collection loop: {e}")
                self.metrics["errors_encountered"] += 1
                await asyncio.sleep(300)  # Wait 5 minutes after errors
    
    async def process_document_with_koi(self, document: Dict[str, Any]):
        """Process document and emit KOI events"""
        
        # Apply filtering
        if not self.should_process_document(document):
            return
        
        # Generate RID
        try:
            rid = document_to_rid(document)
            if not rid:
                self.logger.warning(f"Could not generate RID for document: {document.get('id')}")
                return
        except Exception as e:
            self.logger.error(f"Error generating RID: {e}")
            return
        
        # Check if already processed
        document_id = document.get("id", "")
        if document_id in self.processed_documents:
            # Check if content changed (UPDATE event)
            cached_bundle = self.koi_node.get_cached_bundle(rid.to_string())
            if cached_bundle:
                # Generate new bundle and compare
                try:
                    new_bundle = document_to_bundle(document, self.koi_node.node_id)
                    if new_bundle.manifest.content_hash != cached_bundle.manifest.content_hash:
                        # Content changed - emit UPDATE event
                        await self.koi_node.emit_update_event(new_bundle)
                        self.metrics["events_emitted"] += 1
                        self.logger.debug(f"Emitted UPDATE event for {rid}")
                except Exception as e:
                    self.logger.error(f"Error processing UPDATE event: {e}")
            return
        
        # New document - create bundle and emit NEW event
        try:
            bundle = document_to_bundle(document, self.koi_node.node_id)
            await self.koi_node.emit_new_event(bundle)
            
            # Track as processed
            self.processed_documents.add(document_id)
            self.metrics["documents_processed"] += 1
            self.metrics["events_emitted"] += 1
            
            self.logger.debug(f"Emitted NEW event for {rid}")
            
        except Exception as e:
            self.logger.error(f"Error creating bundle for document {document_id}: {e}")
            return
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get collection metrics"""
        return {
            "collector_name": self.collector_name,
            "koi_node_id": self.koi_node.node_id,
            "last_collection_time": self.last_collection_time.isoformat() if self.last_collection_time else None,
            "processed_documents_count": len(self.processed_documents),
            "cached_bundles_count": len(self.koi_node.cache),
            "metrics": self.metrics.copy()
        }


class TwitterKOIAdapter(KOICollectorAdapter):
    """KOI adapter for Twitter collector"""
    
    def __init__(self, coordinator_url: str = "http://localhost:8000"):
        super().__init__("twitter", coordinator_url)
        
        # Twitter-specific configuration
        self.keywords_include = [
            "regenerative agriculture", "carbon credits", "regen network",
            "climate solutions", "regenag", "carboncredits"
        ]
        self.min_engagement = 1  # Minimum likes/retweets
    
    async def collect_documents(self) -> List[Dict[str, Any]]:
        """Use existing Twitter collector logic"""
        # This would call your existing Twitter collector
        # For now, return empty list - integrate with actual collector
        
        self.logger.info("Collecting Twitter documents (using existing collector)")
        
        # TODO: Import and call existing TwitterCollector
        # from indexing.twitter.collectors.twitter_collector import TwitterCollector
        # collector = TwitterCollector()
        # documents = await collector.collect_documents()
        # return documents
        
        return []  # Placeholder
    
    def should_process_document(self, document: Dict[str, Any]) -> bool:
        """Twitter-specific filtering"""
        
        # Basic validation
        if not document.get("content") or not document.get("id"):
            return False
        
        # Check for regenerative keywords
        content_lower = document.get("content", "").lower()
        if not any(keyword.lower() in content_lower for keyword in self.keywords_include):
            return False
        
        # Check engagement metrics
        metadata = document.get("metadata", {})
        public_metrics = metadata.get("public_metrics", {})
        
        like_count = public_metrics.get("like_count", 0)
        retweet_count = public_metrics.get("retweet_count", 0)
        
        if (like_count + retweet_count) < self.min_engagement:
            return False
        
        return True


class DiscourseKOIAdapter(KOICollectorAdapter):
    """KOI adapter for Discourse forum collector"""
    
    def __init__(self, coordinator_url: str = "http://localhost:8000"):
        super().__init__("discourse", coordinator_url)
    
    async def collect_documents(self) -> List[Dict[str, Any]]:
        """Use existing Discourse collector logic"""
        self.logger.info("Collecting Discourse documents (using existing collector)")
        
        # TODO: Import and call existing DiscourseCollector
        # from indexing.discourse.collectors.discourse_collector import DiscourseCollector
        # collector = DiscourseCollector()
        # documents = await collector.collect_documents()
        # return documents
        
        return []  # Placeholder
    
    def should_process_document(self, document: Dict[str, Any]) -> bool:
        """Discourse-specific filtering"""
        
        # Basic validation
        if not document.get("content") or not document.get("id"):
            return False
        
        # Filter very short posts
        if len(document.get("content", "")) < 50:
            return False
        
        # Include all valid discourse posts
        return True


class NotionKOIAdapter(KOICollectorAdapter):
    """KOI adapter for Notion collector"""
    
    def __init__(self, coordinator_url: str = "http://localhost:8000"):
        super().__init__("notion", coordinator_url)
    
    async def collect_documents(self) -> List[Dict[str, Any]]:
        """Use existing Notion collector logic"""
        self.logger.info("Collecting Notion documents (using existing collector)")
        
        # TODO: Import and call existing NotionCollector
        # from indexing.notion.crawler import NotionCrawler
        # crawler = NotionCrawler()
        # documents = await crawler.collect_documents()
        # return documents
        
        return []  # Placeholder
    
    def should_process_document(self, document: Dict[str, Any]) -> bool:
        """Notion-specific filtering"""
        
        # Basic validation
        if not document.get("content") or not document.get("id"):
            return False
        
        # Filter empty pages
        content = document.get("content", "").strip()
        if len(content) < 20:
            return False
        
        return True


class WebScraperKOIAdapter(KOICollectorAdapter):
    """KOI adapter for web scraping collector"""
    
    def __init__(self, coordinator_url: str = "http://localhost:8000"):
        super().__init__("web-scraper", coordinator_url)
    
    async def collect_documents(self) -> List[Dict[str, Any]]:
        """Use existing web scraper logic"""
        self.logger.info("Collecting web documents (using existing scraper)")
        
        # TODO: Import and call existing WebScraper
        # from indexing.collectors.web_scraper import WebScraper
        # scraper = WebScraper()
        # documents = await scraper.collect_documents()
        # return documents
        
        return []  # Placeholder
    
    def should_process_document(self, document: Dict[str, Any]) -> bool:
        """Web scraper filtering"""
        
        # Basic validation
        if not document.get("content") or not document.get("url"):
            return False
        
        # Filter very short content
        if len(document.get("content", "")) < 100:
            return False
        
        return True


# Factory function to create adapters
def create_koi_adapter(collector_type: str, coordinator_url: str = "http://localhost:8000") -> Optional[KOICollectorAdapter]:
    """Create KOI adapter for specified collector type"""
    
    adapters = {
        "twitter": TwitterKOIAdapter,
        "discourse": DiscourseKOIAdapter,
        "notion": NotionKOIAdapter,
        "web": WebScraperKOIAdapter
    }
    
    adapter_class = adapters.get(collector_type)
    if adapter_class:
        return adapter_class(coordinator_url)
    
    return None